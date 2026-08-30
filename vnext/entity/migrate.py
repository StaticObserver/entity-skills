from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .errors import EntityError
from .objects import GIT_COMMIT_RE
from .paths import Workspace, init_project
from .records import load_json, now_utc, require_id, write_json


def _load_legacy(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise EntityError(f"legacy input not found: {path}", code="not_found") from exc
        except json.JSONDecodeError as exc:
            raise EntityError(
                f"invalid legacy JSON {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}",
                code="invalid_json",
            ) from exc
        if not isinstance(value, dict):
            raise EntityError("legacy export root must be an object", code="invalid_json")
        return value
    if not path.is_file():
        raise EntityError(f"legacy input not found: {path}", code="not_found")
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise EntityError(f"cannot open legacy SQLite database {path}: {exc}", code="invalid_legacy") from exc
    connection.row_factory = sqlite3.Row
    try:
        projects = [dict(row) for row in connection.execute("SELECT * FROM projects")]
        cases: list[dict[str, Any]] = []
        for row in connection.execute("SELECT * FROM cases"):
            case = dict(row)
            for key in ("source_json", "current_json", "legacy_json"):
                if key in case:
                    case[key.removesuffix("_json")] = json.loads(case.pop(key) or "{}")
            identities: dict[str, dict[str, Any]] = {}
            for item in connection.execute(
                "SELECT dimension, payload_json, is_current FROM identities WHERE case_uid=?",
                (case["case_uid"],),
            ):
                group = identities.setdefault(item["dimension"], {"items": []})
                payload = json.loads(item["payload_json"])
                group["items"].append(payload)
                if item["is_current"]:
                    group["current_id"] = payload.get(f"{item['dimension']}_id", "")
            case["identities"] = identities
            cases.append(case)
        return {"schema_version": 3, "projects": projects, "cases": cases, "sites": []}
    except (sqlite3.Error, json.JSONDecodeError, KeyError) as exc:
        raise EntityError(f"invalid legacy SQLite database {path}: {exc}", code="invalid_legacy") from exc
    finally:
        connection.close()


def _safe_id(value: str, fallback: str) -> str:
    candidate = value.strip().replace(" ", "-")
    try:
        return require_id(candidate or fallback)
    except EntityError:
        return fallback


def migrate_legacy(source: Path, destination: Path) -> dict[str, Any]:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise EntityError(f"migration destination must be empty: {destination}", code="destination_not_empty")
    legacy = _load_legacy(source)
    for field in ("projects", "cases"):
        if not isinstance(legacy.get(field) or [], list):
            raise EntityError(f"legacy {field} must be a JSON array", code="invalid_legacy")
    workspace = Workspace.init(destination, destination.name)
    report: dict[str, Any] = {
        "schema_version": 1,
        "source": str(source),
        "destination": str(destination),
        "created_at": now_utc(),
        "imported": {"projects": 0, "sources": 0, "pgens": 0, "builds": 0, "runs": 0},
        "conflicts": [],
    }
    project_names: dict[str, str] = {}
    for index, project in enumerate(legacy.get("projects") or [], 1):
        if not isinstance(project, dict):
            raise EntityError(f"legacy project {index} must be a JSON object", code="invalid_legacy")
        raw = str(project.get("slug") or Path(str(project.get("project_root") or "")).name or f"project-{index}")
        project_id = _safe_id(raw, f"project-{index}")
        if not workspace.project_dir(project_id).exists():
            init_project(workspace, project_id)
            report["imported"]["projects"] += 1
        project_names[str(project.get("project_uid") or project_id)] = project_id
    for case_index, case in enumerate(legacy.get("cases") or [], 1):
        if not isinstance(case, dict):
            raise EntityError(f"legacy case {case_index} must be a JSON object", code="invalid_legacy")
        project_id = project_names.get(str(case.get("project_uid") or ""))
        if not project_id:
            project_id = _safe_id(Path(str(case.get("project_root") or "project")).name, f"project-{case_index}")
            if not workspace.project_dir(project_id).exists():
                init_project(workspace, project_id)
                report["imported"]["projects"] += 1
        identities = case.get("identities") or {}
        if not isinstance(identities, dict):
            raise EntityError(
                f"legacy case {case_index} identities must be a JSON object",
                code="invalid_legacy",
            )
        for dimension in ("source", "pgen", "build", "run"):
            group = identities.get(dimension) or {}
            if not isinstance(group, dict):
                raise EntityError(
                    f"legacy {dimension} identities must be a JSON object",
                    code="invalid_legacy",
                )
            items = group.get("items") or []
            if not isinstance(items, list):
                raise EntityError(
                    f"legacy {dimension} identity items must be a JSON array",
                    code="invalid_legacy",
                )
            for item_index, item in enumerate(items, 1):
                if not isinstance(item, dict):
                    report["conflicts"].append({
                        "kind": dimension,
                        "id": f"legacy-{dimension}-{case_index}-{item_index}",
                        "reason": "legacy identity must be a JSON object",
                        "legacy": item,
                    })
                    continue
                raw_id = str(item.get(f"{dimension}_id") or item.get("identity_id") or f"legacy-{dimension}-{case_index}-{item_index}")
                object_id = _safe_id(raw_id, f"legacy-{dimension}-{case_index}-{item_index}")
                if dimension == "source":
                    commit = str(item.get("git_commit") or item.get("commit") or "")
                    repository = str(item.get("repository") or item.get("repo") or "")
                    if not commit or not repository or not GIT_COMMIT_RE.fullmatch(commit):
                        report["conflicts"].append({"kind": "source", "id": object_id, "reason": "missing repository or fixed Git commit", "legacy": item})
                        continue
                    commit = commit.lower()
                    root = workspace.source_dir(project_id, object_id)
                    source_path = root / "source.json"
                    candidate = {
                        "schema_version": 1,
                        "id": object_id,
                        "repository": repository,
                        "git_commit": commit,
                        "checkout": "checkout",
                        "legacy": item,
                    }
                    if source_path.is_file():
                        existing = load_json(source_path)
                        same_source = (
                            existing.get("repository") == repository
                            and existing.get("git_commit") == commit
                        )
                        if not same_source:
                            report["conflicts"].append({
                                "kind": "source",
                                "id": object_id,
                                "reason": "duplicate Source ID has different repository or Git commit",
                                "existing": existing,
                                "legacy": item,
                            })
                        continue
                    root.mkdir(parents=True, exist_ok=False)
                    write_json(source_path, candidate, replace=False)
                elif dimension == "pgen":
                    report["conflicts"].append({"kind": "pgen", "id": object_id, "reason": "PGen files require manual import", "legacy": item})
                    continue
                elif dimension == "build":
                    report["conflicts"].append({"kind": "build", "id": object_id, "reason": "Build requires mapped Source, PGen, Site and deps", "legacy": item})
                    continue
                else:
                    report["conflicts"].append({"kind": "run", "id": object_id, "reason": "Run requires mapped Build and original TOML", "legacy": item})
                    continue
                report["imported"][f"{dimension}s"] += 1
        if case.get("case_id") or case.get("case_uid"):
            report["conflicts"].append({
                "kind": "case",
                "id": case.get("case_id") or case.get("case_uid"),
                "reason": "Case is not part of the new model; retained only in this report",
            })
    write_json(workspace.root / "migration-report.json", report)
    return report
