from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .errors import EntityError
from .paths import Workspace, init_project
from .records import now_utc, require_id, write_json


def _load_legacy(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise EntityError("legacy export root must be an object", code="invalid_json")
        return value
    connection = sqlite3.connect(path)
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
        raw = str(project.get("slug") or Path(str(project.get("project_root") or "")).name or f"project-{index}")
        project_id = _safe_id(raw, f"project-{index}")
        if not workspace.project_dir(project_id).exists():
            init_project(workspace, project_id)
            report["imported"]["projects"] += 1
        project_names[str(project.get("project_uid") or project_id)] = project_id
    for case_index, case in enumerate(legacy.get("cases") or [], 1):
        project_id = project_names.get(str(case.get("project_uid") or ""))
        if not project_id:
            project_id = _safe_id(Path(str(case.get("project_root") or "project")).name, f"project-{case_index}")
            if not workspace.project_dir(project_id).exists():
                init_project(workspace, project_id)
                report["imported"]["projects"] += 1
        identities = case.get("identities") or {}
        mapped: dict[str, dict[str, str]] = {"source": {}, "pgen": {}, "build": {}}
        for dimension in ("source", "pgen", "build", "run"):
            items = (identities.get(dimension) or {}).get("items") or []
            for item_index, item in enumerate(items, 1):
                raw_id = str(item.get(f"{dimension}_id") or item.get("identity_id") or f"legacy-{dimension}-{case_index}-{item_index}")
                object_id = _safe_id(raw_id, f"legacy-{dimension}-{case_index}-{item_index}")
                if dimension == "source":
                    commit = str(item.get("git_commit") or item.get("commit") or "")
                    repository = str(item.get("repository") or item.get("repo") or "")
                    if not commit or not repository:
                        report["conflicts"].append({"kind": "source", "id": object_id, "reason": "missing repository or Git commit", "legacy": item})
                        continue
                    root = workspace.source_dir(project_id, object_id)
                    root.mkdir(parents=True, exist_ok=True)
                    write_json(root / "source.json", {"schema_version": 1, "id": object_id, "repository": repository, "git_commit": commit, "checkout": "checkout", "legacy": item})
                elif dimension == "pgen":
                    report["conflicts"].append({"kind": "pgen", "id": object_id, "reason": "PGen files require manual import", "legacy": item})
                    continue
                elif dimension == "build":
                    report["conflicts"].append({"kind": "build", "id": object_id, "reason": "Build requires mapped Source, PGen, Site and deps", "legacy": item})
                    continue
                else:
                    report["conflicts"].append({"kind": "run", "id": object_id, "reason": "Run requires mapped Build and original TOML", "legacy": item})
                    continue
                mapped[dimension][raw_id] = object_id
                report["imported"][f"{dimension}s"] += 1
        if case.get("case_id") or case.get("case_uid"):
            report["conflicts"].append({
                "kind": "case",
                "id": case.get("case_id") or case.get("case_uid"),
                "reason": "Case is not part of the new model; retained only in this report",
            })
    write_json(workspace.root / "migration-report.json", report)
    return report
