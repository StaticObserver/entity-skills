"""Shared JSON I/O helpers for entity-env-build scripts.

Import this instead of duplicating load_json / write_json_atomic in every script.
Also provides: unified --json protocol output, harness runtime logging,
and path derivation.
"""

import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Harness home directory
# ---------------------------------------------------------------------------

_HARNESS_HOME = Path.home() / ".entity-env-build"
_OLD_HARNESS_HOME = Path.home() / ".entity"

_HARNESS_README = """\
# Entity Build Environment — Harness State Directory

This directory is managed by the `entity-env-build` AI agent skill.
It persists across builds and sessions. Do not delete it unless you
want to reset the harness's machine-level knowledge.

## Files

| Path | Purpose | Format | Lifecycle |
|------|---------|--------|-----------|
| `run.log` | Audit trail of every script invocation and build step | JSON-lines, append-only | Append forever; trim manually if needed |
| `site-notes/<hostname>.md` | Machine-specific dependency knowledge, known-good combinations, and discovered issues | Markdown | Updated after builds; grows with experience |

## Notes

- `run.log` is the source of truth for "what happened when". If a build
  fails, check this file first.
- `site-notes/` is read at the start of every Phase 2 environment probe.
  It helps the agent avoid repeating known mistakes.
- Compatibility results are recorded in `entity-deps.local.json.compatibility`
  and saved to `compat/<run_id>.json` by the agent workflow.
"""


def _migrate_old_harness_home() -> None:
    """If ~/.entity/ exists and ~/.entity-env-build/ does not, migrate contents."""
    if _HARNESS_HOME.exists():
        return
    if not _OLD_HARNESS_HOME.exists():
        return
    old_site_notes = _OLD_HARNESS_HOME / "site-notes"
    if not old_site_notes.is_dir():
        return
    _HARNESS_HOME.mkdir(parents=True, exist_ok=True)
    target = _HARNESS_HOME / "site-notes"
    if not target.exists():
        shutil.copytree(str(old_site_notes), str(target))
    # Write README so the directory is self-documenting
    (_HARNESS_HOME / "README.md").write_text(_HARNESS_README, encoding="utf-8")


def ensure_harness_home() -> Path:
    """Create ~/.entity-env-build/ and its README if missing. Return the path."""
    _migrate_old_harness_home()
    _HARNESS_HOME.mkdir(parents=True, exist_ok=True)
    readme = _HARNESS_HOME / "README.md"
    if not readme.exists():
        readme.write_text(_HARNESS_README, encoding="utf-8")
    return _HARNESS_HOME


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def load_json(path: Path) -> Dict[str, Any]:
    """Read and parse a JSON object file. Exits on error."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return data


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Write *data* to *path* atomically (temp file + rename)."""
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as f:
        f.write(text)
        tmp = Path(f.name)
    tmp.replace(path)


def get_dotted(obj: Dict[str, Any], dotted: str) -> Any:
    """Drill into *obj* using dotted path. Returns None when any key is missing."""
    cur: Any = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


# ---------------------------------------------------------------------------
# Protocol output
# ---------------------------------------------------------------------------


def protocol_ok(action: str, **extra: Any) -> None:
    """Print JSON success line to stdout and exit 0."""
    payload: Dict[str, Any] = {
        "status": "ok",
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    print(json.dumps(payload, sort_keys=True))
    sys.exit(0)


def protocol_error(action: str, message: str, **extra: Any) -> None:
    """Print JSON error line to stderr and exit 1."""
    payload: Dict[str, Any] = {
        "status": "error",
        "action": action,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)
    sys.exit(1)


def add_json_flag(parser: Any) -> None:
    """Add --json to an argparse parser for opt-in protocol mode."""
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output a single JSON protocol line to stdout on success, stderr on error.",
    )


# ---------------------------------------------------------------------------
# Runtime event log
# ---------------------------------------------------------------------------


def log_event(
    run_id: str,
    session_id: str,
    action: str,
    status: str,
    script: str = "",
    artifacts: Optional[List[str]] = None,
    exit_code: Optional[int] = None,
    elapsed_ms: Optional[int] = None,
) -> None:
    """Append one JSON line to ~/.entity-env-build/run.log."""
    ensure_harness_home()
    entry: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run": run_id,
        "session": session_id,
        "action": action,
        "status": status,
    }
    if script:
        entry["script"] = script
    if artifacts:
        entry["artifacts"] = artifacts
    if exit_code is not None:
        entry["exit_code"] = exit_code
    if elapsed_ms is not None:
        entry["elapsed_ms"] = elapsed_ms

    log_path = _HARNESS_HOME / "run.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def save_compat_report(run_id: str, report: Dict[str, Any]) -> Path:
    """Save compat check report to ~/.entity-env-build/compat/<run_id>.json."""
    ensure_harness_home()
    compat_dir = _HARNESS_HOME / "compat"
    compat_dir.mkdir(parents=True, exist_ok=True)
    path = compat_dir / f"{run_id}.json"
    write_json_atomic(path, report)
    return path


# ---------------------------------------------------------------------------
# Path derivation (from checkpoint selected entries)
# ---------------------------------------------------------------------------


def derive_paths(selected: Dict[str, Any]) -> Dict[str, Any]:
    """Derive PATH / CMAKE_PREFIX_PATH / LD_LIBRARY_PATH from selected entries."""
    path_entries: List[str] = []
    cmake_entries: List[str] = []
    ld_entries: List[str] = []

    for entry in selected.values():
        if not isinstance(entry, dict):
            continue
        prefix = entry.get("prefix", "")

        bin_path = entry.get("bin", "")
        if bin_path:
            path_entries.append(str(bin_path))
        if prefix:
            bin_dir = str(Path(prefix) / "bin")
            if bin_dir not in path_entries:
                path_entries.append(bin_dir)

        if prefix and prefix not in cmake_entries:
            cmake_entries.append(str(prefix))

        lib_path = entry.get("lib", "")
        if lib_path:
            ld_entries.append(str(lib_path))
        if prefix:
            for sub in ("lib64", "lib"):
                lib_dir = str(Path(prefix) / sub)
                if lib_dir not in ld_entries:
                    ld_entries.append(lib_dir)

    if "/usr/bin" not in path_entries:
        path_entries.append("/usr/bin")

    return {
        "PATH": path_entries,
        "CMAKE_PREFIX_PATH": cmake_entries,
        "LD_LIBRARY_PATH": ld_entries,
        "DYLD_LIBRARY_PATH": [],
    }


# ---------------------------------------------------------------------------
# Site notes — runtime artifacts in harness home (agent-managed)
# ---------------------------------------------------------------------------


def site_notes_base() -> Path:
    """Return ~/.entity-env-build/site-notes/, creating it if needed."""
    ensure_harness_home()
    base = _HARNESS_HOME / "site-notes"
    base.mkdir(parents=True, exist_ok=True)
    return base


