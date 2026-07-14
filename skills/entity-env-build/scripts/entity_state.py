"""Minimal build-run state tracking for entity-env-build.

The state file lives beside the build artifacts. It records the main artifact
chain only; site notes, remote state, and orchestration are intentionally out of
scope.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from _json_io import load_json, write_json_atomic


STATE_FILE = ".entity-session.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(artifacts_dir: Path) -> Dict[str, Any]:
    path = artifacts_dir / STATE_FILE
    if path.exists():
        return load_json(path)
    now = _now()
    return {
        "schema_version": 1,
        "session_id": uuid.uuid4().hex[:8],
        "started_at": now,
        "updated_at": now,
        "steps": {},
        "last_step": "",
        "last_status": "",
    }


def record_step(
    artifacts_dir: Path,
    step: str,
    status: str,
    inputs: Optional[Dict[str, str]] = None,
    outputs: Optional[Dict[str, str]] = None,
    run_id: str = "",
    message: str = "",
) -> Dict[str, Any]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(artifacts_dir)
    now = _now()
    steps = state.setdefault("steps", {})
    if not isinstance(steps, dict):
        steps = {}
        state["steps"] = steps
    entry: Dict[str, Any] = {"status": status, "updated_at": now}
    if inputs:
        entry["inputs"] = inputs
    if outputs:
        entry["outputs"] = outputs
    if run_id:
        entry["run_id"] = run_id
    if message:
        entry["message"] = message
    steps[step] = entry
    state["updated_at"] = now
    state["last_step"] = step
    state["last_status"] = status
    write_json_atomic(artifacts_dir / STATE_FILE, state)
    return state
