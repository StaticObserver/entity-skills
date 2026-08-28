from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import EntityError
from .objects import load_run
from .paths import Workspace
from .records import now_utc, require_id, write_json


def record_analysis(
    workspace: Workspace,
    project_id: str,
    analysis_id: str,
    run_ids: list[str],
    script: str,
    parameters: dict[str, Any] | None,
    output: str,
) -> dict[str, Any]:
    analysis_id = require_id(analysis_id, "analysis id")
    if not run_ids:
        raise EntityError("analysis requires at least one run", code="invalid_record")
    project = workspace.require_project(project_id)
    script_path = (project / script).resolve() if not Path(script).is_absolute() else Path(script).resolve()
    scripts_root = (project / "scripts").resolve()
    try:
        script_relative = script_path.relative_to(project)
        script_path.relative_to(scripts_root)
    except ValueError as exc:
        raise EntityError(
            f"analysis script must be inside {scripts_root}",
            code="invalid_record",
        ) from exc
    if not script_path.is_file():
        raise EntityError(f"analysis script not found: {script_path}", code="not_found")
    resolved: list[dict[str, str]] = []
    for run_id in run_ids:
        build_id, run_root, _ = load_run(workspace, project_id, run_id)
        resolved.append({"run": run_id, "build": build_id, "record": str(run_root / "run.json")})
    if len(resolved) == 1:
        root = Path(resolved[0]["record"]).parent / "analysis" / analysis_id
    else:
        root = project / "analysis" / analysis_id
    if root.exists():
        raise EntityError(f"analysis already exists: {analysis_id}", code="already_exists")
    root.mkdir(parents=True)
    record = {
        "schema_version": 1,
        "id": analysis_id,
        "runs": [item["run"] for item in resolved],
        "script": str(script_relative),
        "parameters": parameters or {},
        "output": output,
        "created_at": now_utc(),
    }
    write_json(root / "analysis.json", record, replace=False)
    return record
