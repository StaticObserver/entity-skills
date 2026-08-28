from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .errors import EntityError
from .paths import Workspace
from .records import load_json
from .site import SiteOps


def _issue(issues: list[dict[str, str]], code: str, path: Path | str, message: str, severity: str = "error") -> None:
    issues.append({"severity": severity, "code": code, "path": str(path), "message": message})


def _read(path: Path, issues: list[dict[str, str]]) -> dict[str, Any] | None:
    try:
        return load_json(path)
    except EntityError as exc:
        _issue(issues, exc.code, path, str(exc))
        return None


def _git_head(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def check_workspace(workspace: Workspace) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    _read(workspace.root / "workspace.json", issues)
    sites: dict[str, dict[str, Any]] = {}
    for path in sorted((workspace.root / "sites").glob("*.json")):
        record = _read(path, issues)
        if not record:
            continue
        site_id = str(record.get("id") or "")
        if site_id != path.stem:
            _issue(issues, "id_path_mismatch", path, f"site id {site_id!r} differs from filename")
        sites[site_id] = record
        try:
            site = SiteOps(record)
            site_record_path = site.path("site.json")
            if site.is_file(site_record_path):
                site_record = site.read_json(site_record_path)
                for field in ("id", "root", "transport", "scheduler"):
                    if site_record.get(field) != record.get(field):
                        _issue(
                            issues,
                            "site_config_conflict",
                            site_record_path,
                            f"Site {field} differs from Workspace sites/{path.name}",
                        )
        except EntityError as exc:
            _issue(issues, "site_unreachable", path, str(exc), "warning")
    projects_root = workspace.root / "projects"
    for project in sorted(path for path in projects_root.iterdir() if path.is_dir()) if projects_root.exists() else []:
        project_record = _read(project / "project.json", issues)
        if not project_record:
            continue
        project_id = str(project_record.get("id") or project.name)
        sources: dict[str, dict[str, Any]] = {}
        for source_file in sorted((project / "sources").glob("*/source.json")):
            source = _read(source_file, issues)
            if not source:
                continue
            source_id = str(source.get("id") or "")
            sources[source_id] = source
            checkout = source_file.parent / str(source.get("checkout") or "checkout")
            if checkout.exists():
                head = _git_head(checkout)
                if head is None:
                    _issue(issues, "not_git_checkout", checkout, "Source checkout is not a Git repository")
                elif head != str(source.get("git_commit") or ""):
                    _issue(
                        issues,
                        "source_commit_mismatch",
                        checkout,
                        f"HEAD is {head}, recorded commit is {source.get('git_commit')}",
                    )
        pgens: dict[str, dict[str, Any]] = {}
        for pgen_file in sorted((project / "pgens").glob("*/pgen.json")):
            pgen = _read(pgen_file, issues)
            if not pgen:
                continue
            pgen_id = str(pgen.get("id") or "")
            pgens[pgen_id] = pgen
            entry = pgen_file.parent / str(pgen.get("entry") or "")
            if not entry.is_file():
                _issue(issues, "pgen_entry_missing", entry, "PGen entry file does not exist")
        builds_root = project / "builds"
        run_ids: set[str] = set()
        for build_file in sorted(builds_root.glob("*/build.json")) if builds_root.exists() else []:
            build = _read(build_file, issues)
            if not build:
                continue
            build_id = str(build.get("id") or build_file.parent.name)
            source_id = str(build.get("source") or "")
            pgen_id = str(build.get("pgen") or "")
            site_id = str(build.get("site") or "")
            if source_id not in sources:
                _issue(issues, "dangling_source", build_file, f"Source does not exist: {source_id}")
            if pgen_id not in pgens:
                _issue(issues, "dangling_pgen", build_file, f"PGen does not exist: {pgen_id}")
            if site_id not in sites:
                _issue(issues, "dangling_site", build_file, f"Site does not exist: {site_id}")
                site = None
            else:
                try:
                    site = SiteOps(sites[site_id])
                    deps_file = site.path("deps", str(build.get("deps") or ""), "deps.json")
                    if not site.is_file(deps_file):
                        _issue(issues, "deps_missing", deps_file, "Build deps record does not exist")
                    result_file = site.path("projects", project_id, "builds", build_id, "build-result.json")
                    if site.is_file(result_file):
                        result = site.read_json(result_file)
                        if result.get("build") != build_id:
                            _issue(issues, "build_result_conflict", result_file, "result references another Build")
                except EntityError as exc:
                    _issue(issues, "site_unreachable", workspace.site_file(site_id), str(exc), "warning")
                    site = None
            for run_file in sorted((build_file.parent / "runs").glob("*/run.json")):
                run = _read(run_file, issues)
                if not run:
                    continue
                run_ids.add(str(run.get("id") or run_file.parent.name))
                if run.get("build") != build_id:
                    _issue(issues, "run_build_conflict", run_file, f"Run must reference {build_id}")
                toml = run_file.parent / str(run.get("toml") or "")
                if not toml.is_file():
                    _issue(issues, "toml_missing", toml, "Run TOML does not exist")
                runtime = build.get("runtime") or {}
                if runtime.get("mpi") and site_id in sites:
                    template = (sites[site_id].get("mpi") or {}).get("template")
                    if not isinstance(template, list) or not template:
                        _issue(issues, "mpi_launcher_missing", workspace.site_file(site_id), "MPI Build needs site.mpi.template")
        analysis_files = list(project.glob("analysis/*/analysis.json"))
        analysis_files.extend(project.glob("builds/*/runs/*/analysis/*/analysis.json"))
        for analysis_file in sorted(analysis_files):
            analysis = _read(analysis_file, issues)
            if not analysis:
                continue
            for run_id in analysis.get("runs") or []:
                if str(run_id) not in run_ids:
                    _issue(issues, "dangling_analysis_run", analysis_file, f"Run does not exist: {run_id}")
            script = project / str(analysis.get("script") or "")
            if not script.is_file():
                _issue(issues, "analysis_script_missing", script, "Analysis script does not exist")
    return {
        "ok": not any(item["severity"] == "error" for item in issues),
        "workspace": str(workspace.root),
        "issues": issues,
        "errors": sum(item["severity"] == "error" for item in issues),
        "warnings": sum(item["severity"] == "warning" for item in issues),
    }
