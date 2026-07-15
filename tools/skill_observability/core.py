"""Collector, redaction, hashing, command tracing, and run validation."""

from __future__ import annotations

import fcntl
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .contracts import (
    ContractError,
    SCHEMA_VERSION,
    validate_artifact,
    validate_event,
    validate_manifest,
    validate_result,
)


TERMINAL_EVENTS = {"run.finished", "run.failed"}
SECRET_KEY_RE = re.compile(
    r"(?:^|[_-])(?:token|password|passwd|secret|credential|private[_-]?key|cookie|authorization)(?:$|[_-])",
    re.IGNORECASE,
)
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
URI_CREDENTIAL_RE = re.compile(r"(://[^\s:/@]+:)[^\s@]+(@)")
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
    re.DOTALL,
)
JSON_SECRET_RE = re.compile(
    r'(?i)("(?:token|password|passwd|secret|credential|private[_-]?key|cookie|authorization)"\s*:\s*)"[^"]*"'
)
ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(token|password|passwd|secret|credential|private[_-]?key|cookie|authorization)\s*=\s*([^\s&]+)"
)
FLAG_SECRET_RE = re.compile(
    r"(?i)(--(?:token|password|passwd|secret|credential|private[_-]?key|cookie|authorization)\s+)(\S+)"
)
SINGLE_QUOTED_SECRET_RE = re.compile(
    r"(?i)('(?:token|password|passwd|secret|credential|private[_-]?key|cookie|authorization)'\s*:\s*)'[^']*'"
)
COLON_SECRET_RE = re.compile(
    r"(?i)\b(token|password|passwd|secret|credential|private[_-]?key|cookie|authorization)\s*:\s*([^\s,}]+)"
)
SKIP_TREE_PARTS = {".git", "__pycache__", ".pytest_cache", ".DS_Store"}
JSON_CAPTURE_LIMIT = 1024 * 1024
TAIL_LIMIT = 4096


class TraceError(RuntimeError):
    """Raised for an invalid or unsafe trace operation."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> Tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_roots(values: Iterable[Path | str]) -> List[str]:
    roots = []
    seen = set()
    for value in values:
        root = str(Path(value).expanduser().resolve())
        if root not in seen:
            roots.append(root)
            seen.add(root)
    return roots


def _assert_write_root_safe(path: Path, protected_roots: Sequence[str]) -> None:
    resolved = path.expanduser().resolve()
    for raw in protected_roots:
        root = Path(raw).expanduser().resolve()
        if _path_within(resolved, root):
            raise TraceError(f"trace path is inside protected root: {resolved} within {root}")


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as handle:
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(str(temporary), str(path))


def load_json(path: Path, label: str = "JSON") -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise TraceError(f"cannot read {label} at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TraceError(f"{label} at {path} must contain an object")
    return value


def read_jsonl(path: Path, label: str) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    values = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    raise TraceError(f"{label} contains a blank line at {number}")
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise TraceError(f"{label} line {number} is invalid JSON: {exc}") from exc
                if not isinstance(value, dict):
                    raise TraceError(f"{label} line {number} must be an object")
                values.append(value)
    except OSError as exc:
        raise TraceError(f"cannot read {label} at {path}: {exc}") from exc
    return values


def redact_string(value: str) -> str:
    value = PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", value)
    value = BEARER_RE.sub("Bearer [REDACTED]", value)
    value = URI_CREDENTIAL_RE.sub(r"\1[REDACTED]\2", value)
    value = JSON_SECRET_RE.sub(r'\1"[REDACTED]"', value)
    value = SINGLE_QUOTED_SECRET_RE.sub(r"\1'[REDACTED]'", value)
    value = ASSIGNMENT_SECRET_RE.sub(r"\1=[REDACTED]", value)
    value = FLAG_SECRET_RE.sub(r"\1[REDACTED]", value)
    value = COLON_SECRET_RE.sub(r"\1: [REDACTED]", value)
    return value


def redact_value(value: Any, key_hint: str = "") -> Any:
    if key_hint and SECRET_KEY_RE.search(key_hint):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(key): redact_value(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_string(str(value))


def redact_argv(argv: Sequence[str]) -> List[str]:
    result = []
    redact_next = False
    for item in argv:
        if redact_next:
            result.append("[REDACTED]")
            redact_next = False
            continue
        if "=" in item:
            key, _ = item.split("=", 1)
            if SECRET_KEY_RE.search(key):
                result.append(key + "=[REDACTED]")
                continue
        if item.startswith("-") and SECRET_KEY_RE.search(item):
            result.append(item)
            redact_next = True
            continue
        result.append(redact_string(item))
    return result


def tree_identity(path: Path) -> Tuple[str, int]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise TraceError(f"identity path does not exist: {resolved}")
    if resolved.is_file():
        return sha256_file(resolved)
    if not resolved.is_dir():
        raise TraceError(f"identity path is not a regular file or directory: {resolved}")

    digest = hashlib.sha256()
    total = 0
    for item in sorted(resolved.rglob("*"), key=lambda value: value.as_posix()):
        relative = item.relative_to(resolved)
        if any(part in SKIP_TREE_PARTS for part in relative.parts):
            continue
        relative_bytes = relative.as_posix().encode("utf-8")
        if item.is_symlink():
            target = os.readlink(str(item)).encode("utf-8")
            digest.update(b"L\0" + relative_bytes + b"\0" + target + b"\0")
            total += len(target)
        elif item.is_file():
            file_hash, size = sha256_file(item)
            digest.update(b"F\0" + relative_bytes + b"\0" + file_hash.encode("ascii") + b"\0")
            total += size
        elif item.is_dir():
            digest.update(b"D\0" + relative_bytes + b"\0")
    return digest.hexdigest(), total


def _git_output(cwd: Path, args: Sequence[str]) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def git_identity(path: Path) -> Tuple[Optional[str], Optional[bool]]:
    cwd = path if path.is_dir() else path.parent
    root_text = _git_output(cwd, ["rev-parse", "--show-toplevel"])
    revision = _git_output(cwd, ["rev-parse", "HEAD"])
    if not root_text or not revision:
        return None, None
    root = Path(root_text).resolve()
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        return revision, None
    status = _git_output(root, ["status", "--porcelain", "--untracked-files=all", "--", str(relative)])
    if status is None:
        return revision, None
    return revision, bool(status)


def _skill_name(path: Path) -> str:
    root = path if path.is_dir() else path.parent
    skill_file = root / "SKILL.md"
    if skill_file.is_file():
        try:
            for line in skill_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("name:"):
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return value
        except OSError:
            pass
    return root.name


def skill_identity(path: Path, exposure: str = "injected") -> Dict[str, Any]:
    root = path.expanduser().resolve()
    if root.is_file() and root.name == "SKILL.md":
        root = root.parent
    digest, _ = tree_identity(root)
    revision, dirty = git_identity(root)
    return {
        "name": _skill_name(root),
        "source": str(root),
        "package_revision": revision,
        "content_sha256": digest,
        "dirty": dirty,
        "exposure": exposure,
    }


def default_trace_home() -> Path:
    configured = os.environ.get("ENTITY_SKILL_TRACE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".entity-skills" / "observability").resolve()


def run_paths(run_dir: Path) -> Dict[str, Path]:
    root = run_dir.expanduser().resolve()
    return {
        "root": root,
        "manifest": root / "manifest.json",
        "events": root / "events.jsonl",
        "artifacts": root / "artifacts.jsonl",
        "result": root / "result.json",
    }


def load_manifest(run_dir: Path) -> Dict[str, Any]:
    paths = run_paths(run_dir)
    manifest = load_json(paths["manifest"], "run manifest")
    try:
        validate_manifest(manifest)
    except ContractError as exc:
        raise TraceError(str(exc)) from exc
    _assert_write_root_safe(paths["root"], manifest["capture"]["protected_roots"])
    return manifest


def start_run(
    *,
    task_id: str,
    input_ref: str,
    input_sha256: str,
    variant: str,
    agent_provider: str,
    agent_model: str,
    agent_configuration: str,
    tool_profile: str,
    tool_configuration: str,
    skill_paths: Sequence[Path],
    trace_home: Optional[Path] = None,
    run_id: Optional[str] = None,
    protected_roots: Sequence[Path] = (),
    decision_records: bool = True,
) -> Tuple[Path, Dict[str, Any]]:
    run_id = run_id or str(uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise TraceError("run_id may contain only letters, digits, dot, underscore, and hyphen")
    skills = [skill_identity(path) for path in skill_paths]
    if len({item["name"] for item in skills}) != len(skills):
        raise TraceError("skill names must be unique within one run")

    roots = _normalize_roots([*protected_roots, *(Path(item["source"]) for item in skills)])
    home = (trace_home or default_trace_home()).expanduser().resolve()
    date = datetime.now(timezone.utc).date().isoformat()
    run_dir = home / "runs" / date / run_id
    _assert_write_root_safe(run_dir, roots)
    if run_dir.exists():
        raise TraceError(f"run directory already exists: {run_dir}")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "task": {
            "case_id": task_id,
            "input_ref": input_ref,
            "input_sha256": input_sha256,
        },
        "variant": variant,
        "agent": {
            "provider": agent_provider,
            "model": agent_model,
            "configuration": agent_configuration,
        },
        "tools": {
            "profile": tool_profile,
            "configuration": tool_configuration,
        },
        "skills": skills,
        "capture": {
            "raw_input": False,
            "raw_tool_output": False,
            "decision_records": bool(decision_records),
            "protected_roots": roots,
        },
        "started_at": now_utc(),
    }
    try:
        validate_manifest(manifest)
    except ContractError as exc:
        raise TraceError(str(exc)) from exc
    run_dir.mkdir(parents=True)
    paths = run_paths(run_dir)
    atomic_write_json(paths["manifest"], manifest)
    paths["events"].touch(exist_ok=False)
    paths["artifacts"].touch(exist_ok=False)

    started = append_event(
        run_dir,
        event_type="run.started",
        source_kind="collector",
        source_id="skill-observer",
        evidence_level="observed",
        phase="orient",
        payload={"task_id": task_id, "variant": variant},
    )
    for skill in skills:
        append_event(
            run_dir,
            event_type="skill.exposed",
            source_kind="collector",
            source_id="skill-observer",
            evidence_level="observed",
            phase="orient",
            parent_span_id=started["span_id"],
            payload={
                "name": skill["name"],
                "content_sha256": skill["content_sha256"],
                "exposure": skill["exposure"],
            },
        )
    return run_dir, manifest


def _locked_jsonl(path: Path):
    handle = path.open("a+", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _read_locked_jsonl(handle: Any, label: str) -> List[Dict[str, Any]]:
    handle.seek(0)
    values = []
    for number, line in enumerate(handle, 1):
        if not line.strip():
            raise TraceError(f"{label} contains a blank line at {number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceError(f"{label} line {number} is invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise TraceError(f"{label} line {number} must be an object")
        values.append(value)
    return values


def append_event(
    run_dir: Path,
    *,
    event_type: str,
    source_kind: str,
    source_id: str,
    evidence_level: str,
    phase: str,
    payload: Mapping[str, Any],
    span_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    manifest = load_manifest(run_dir)
    if event_type == "decision.recorded" and not manifest["capture"]["decision_records"]:
        raise TraceError("decision records are disabled for this run")
    if event_type in {"run.started", "run.finished", "run.failed"}:
        if source_kind != "collector" or source_id != "skill-observer":
            raise TraceError("run lifecycle events are collector-owned")
    paths = run_paths(run_dir)
    handle = _locked_jsonl(paths["events"])
    try:
        events = _read_locked_jsonl(handle, "events.jsonl")
        for index, existing in enumerate(events, 1):
            try:
                validate_event(existing)
            except ContractError as exc:
                raise TraceError(f"existing event {index} is invalid: {exc}") from exc
            if existing["seq"] != index:
                raise TraceError(f"existing event sequence is not contiguous at {index}")
        if events and events[-1]["type"] in TERMINAL_EVENTS:
            raise TraceError("cannot append an event after the terminal event")
        if event_type == "run.started" and events:
            raise TraceError("run.started must be the first and only initial event")
        if event_type != "run.started" and not events:
            raise TraceError("the first event must be run.started")
        known_spans = {item["span_id"] for item in events}
        if parent_span_id is not None and parent_span_id not in known_spans:
            raise TraceError(f"parent span is not present in this run: {parent_span_id}")
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(uuid.uuid4()),
            "run_id": manifest["run_id"],
            "seq": len(events) + 1,
            "time": now_utc(),
            "type": event_type,
            "source": {"kind": source_kind, "id": source_id},
            "evidence_level": evidence_level,
            "phase": phase,
            "span_id": span_id or str(uuid.uuid4()),
            "parent_span_id": parent_span_id,
            "payload": redact_value(dict(payload)),
        }
        try:
            validate_event(event)
        except ContractError as exc:
            raise TraceError(str(exc)) from exc
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        return event
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _event_by_id(events: Sequence[Mapping[str, Any]], event_id: str) -> Mapping[str, Any]:
    for event in events:
        if event.get("event_id") == event_id:
            return event
    raise TraceError(f"producing event is not present in this run: {event_id}")


def register_artifact(
    run_dir: Path,
    *,
    path: Path,
    role: str,
    authority: str,
    produced_by: str,
    site_id: str = "local",
    media_type: Optional[str] = None,
    phase: str = "verify",
) -> Dict[str, Any]:
    manifest = load_manifest(run_dir)
    paths = run_paths(run_dir)
    events = read_jsonl(paths["events"], "events.jsonl")
    if events and events[-1].get("type") in TERMINAL_EVENTS:
        raise TraceError("cannot register an artifact after the terminal event")
    producing_event = _event_by_id(events, produced_by)
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise TraceError(f"artifact is not a regular file: {resolved}")
    digest, size = sha256_file(resolved)
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()),
        "run_id": manifest["run_id"],
        "role": role,
        "locator": {"site_id": site_id, "path": str(resolved)},
        "media_type": media_type or mimetypes.guess_type(str(resolved))[0] or "application/octet-stream",
        "sha256": digest,
        "size_bytes": size,
        "produced_by": produced_by,
        "authority": authority,
    }
    try:
        validate_artifact(artifact)
    except ContractError as exc:
        raise TraceError(str(exc)) from exc

    handle = _locked_jsonl(paths["artifacts"])
    try:
        artifacts = _read_locked_jsonl(handle, "artifacts.jsonl")
        for index, existing in enumerate(artifacts, 1):
            try:
                validate_artifact(existing)
            except ContractError as exc:
                raise TraceError(f"existing artifact {index} is invalid: {exc}") from exc
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(artifact, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

    append_event(
        run_dir,
        event_type="artifact.observed",
        source_kind="collector",
        source_id="skill-observer",
        evidence_level="observed",
        phase=phase,
        parent_span_id=producing_event["span_id"],
        payload={
            "artifact_id": artifact["artifact_id"],
            "role": role,
            "authority": authority,
            "locator": artifact["locator"],
            "sha256": digest,
        },
    )
    return artifact


def _parse_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def derive_result(
    manifest: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    terminal = events[-1] if events and events[-1].get("type") in TERMINAL_EVENTS else None
    terminal_status = "incomplete"
    if terminal:
        terminal_status = "completed" if terminal["type"] == "run.finished" else "failed"
    tool_finished = [event for event in events if event.get("type") == "tool.finished"]
    tool_failed = 0
    for event in tool_finished:
        payload = event.get("payload", {})
        if payload.get("status") not in {"ok", "pass", "completed"} or payload.get("exit_code") not in {0, None}:
            tool_failed += 1
    validation_counts = {"pass": 0, "fail": 0, "unknown": 0}
    for event in events:
        if event.get("type") != "validation.finished":
            continue
        status = event.get("payload", {}).get("status", "unknown")
        if status not in validation_counts:
            status = "unknown"
        validation_counts[status] += 1

    wall_time = None
    input_tokens = None
    output_tokens = None
    if terminal:
        terminal_payload = terminal.get("payload", {})
        wall_time = terminal_payload.get("wall_time_ms")
        input_tokens = terminal_payload.get("input_tokens")
        output_tokens = terminal_payload.get("output_tokens")
    if wall_time is None and events:
        elapsed = _parse_time(events[-1]["time"]) - _parse_time(events[0]["time"])
        wall_time = max(0, int(elapsed.total_seconds() * 1000))

    result = {
        "schema_version": SCHEMA_VERSION,
        "run_id": manifest["run_id"],
        "terminal_status": terminal_status,
        "last_seq": events[-1]["seq"] if events else 0,
        "decisions": sum(event.get("type") == "decision.recorded" for event in events),
        "tool_calls": {"total": len(tool_finished), "failed": tool_failed},
        "artifacts": len(artifacts),
        "validations": validation_counts,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "wall_time_ms": wall_time,
        },
        "terminal_event_id": terminal["event_id"] if terminal else None,
    }
    validate_result(result)
    return result


def finish_run(
    run_dir: Path,
    *,
    status: str,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    wall_time_ms: Optional[int] = None,
) -> Dict[str, Any]:
    if status not in {"completed", "failed"}:
        raise TraceError("finish status must be completed or failed")
    paths = run_paths(run_dir)
    manifest = load_manifest(run_dir)
    existing_events = read_jsonl(paths["events"], "events.jsonl")
    if existing_events and existing_events[-1].get("type") in TERMINAL_EVENTS:
        expected_type = "run.finished" if status == "completed" else "run.failed"
        if existing_events[-1]["type"] != expected_type:
            raise TraceError("existing terminal event does not match requested finish status")
        artifacts = read_jsonl(paths["artifacts"], "artifacts.jsonl")
        result = derive_result(manifest, existing_events, artifacts)
        if paths["result"].exists():
            stored = load_json(paths["result"], "result.json")
            try:
                validate_result(stored)
            except ContractError as exc:
                raise TraceError(str(exc)) from exc
            if stored != result:
                raise TraceError("existing result.json does not match the terminal trace")
            return stored
        atomic_write_json(paths["result"], result)
        return result
    event = append_event(
        run_dir,
        event_type="run.finished" if status == "completed" else "run.failed",
        source_kind="collector",
        source_id="skill-observer",
        evidence_level="observed",
        phase="finish",
        payload={
            "status": status,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "wall_time_ms": wall_time_ms,
        },
    )
    events = read_jsonl(paths["events"], "events.jsonl")
    artifacts = read_jsonl(paths["artifacts"], "artifacts.jsonl")
    result = derive_result(manifest, events, artifacts)
    result["terminal_event_id"] = event["event_id"]
    validate_result(result)
    atomic_write_json(paths["result"], result)
    return result


def _validate_schema_documents() -> List[str]:
    errors = []
    schema_root = Path(__file__).resolve().parent / "schemas"
    for name in ("manifest.schema.json", "event.schema.json", "artifact.schema.json", "result.schema.json"):
        path = schema_root / name
        try:
            value = load_json(path, name)
        except TraceError as exc:
            errors.append(str(exc))
            continue
        if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{name} does not declare JSON Schema draft 2020-12")
    return errors


def validate_run(run_dir: Path, verify_artifact_content: bool = True) -> Dict[str, Any]:
    errors = _validate_schema_documents()
    warnings: List[str] = []
    paths = run_paths(run_dir)
    try:
        manifest = load_manifest(run_dir)
    except (TraceError, ContractError) as exc:
        return {"valid": False, "terminal_status": "unknown", "errors": [*errors, str(exc)], "warnings": []}

    try:
        events = read_jsonl(paths["events"], "events.jsonl")
    except TraceError as exc:
        events = []
        errors.append(str(exc))
    try:
        artifacts = read_jsonl(paths["artifacts"], "artifacts.jsonl")
    except TraceError as exc:
        artifacts = []
        errors.append(str(exc))

    event_ids = set()
    seen_spans = set()
    tool_starts: Dict[str, Mapping[str, Any]] = {}
    tool_finishes = set()
    terminal_events = []
    started_events = []
    for index, event in enumerate(events, 1):
        try:
            validate_event(event)
        except ContractError as exc:
            errors.append(f"event {index}: {exc}")
            continue
        if event["run_id"] != manifest["run_id"]:
            errors.append(f"event {index} run_id does not match manifest")
        if event["seq"] != index:
            errors.append(f"event {index} has seq={event['seq']} instead of {index}")
        if event["event_id"] in event_ids:
            errors.append(f"duplicate event_id: {event['event_id']}")
        event_ids.add(event["event_id"])
        parent = event["parent_span_id"]
        if parent is not None and parent not in seen_spans:
            errors.append(f"event {index} references unseen parent span: {parent}")
        if event["type"] == "tool.started":
            if event["span_id"] in tool_starts:
                errors.append(f"tool span started more than once: {event['span_id']}")
            tool_starts[event["span_id"]] = event
        elif event["type"] == "tool.finished":
            if event["span_id"] not in tool_starts:
                errors.append(f"tool.finished has no tool.started: {event['span_id']}")
            if event["span_id"] in tool_finishes:
                errors.append(f"tool span finished more than once: {event['span_id']}")
            tool_finishes.add(event["span_id"])
        if event["type"] in TERMINAL_EVENTS:
            terminal_events.append(event)
        if event["type"] == "run.started":
            started_events.append(event)
        seen_spans.add(event["span_id"])

    if not events:
        errors.append("events.jsonl is empty")
    elif events[0].get("type") != "run.started":
        errors.append("the first event must be run.started")
    if len(started_events) != 1:
        errors.append(f"run must contain exactly one run.started event, found {len(started_events)}")
    if len(terminal_events) > 1:
        errors.append("run contains more than one terminal event")
    if terminal_events and events[-1].get("event_id") != terminal_events[-1].get("event_id"):
        errors.append("terminal event must be the final event")
    open_tools = sorted(set(tool_starts) - tool_finishes)
    if open_tools:
        message = f"unfinished tool spans: {', '.join(open_tools)}"
        if terminal_events:
            errors.append(message)
        else:
            warnings.append(message)

    artifact_ids = set()
    for index, artifact in enumerate(artifacts, 1):
        try:
            validate_artifact(artifact)
        except ContractError as exc:
            errors.append(f"artifact {index}: {exc}")
            continue
        if artifact["run_id"] != manifest["run_id"]:
            errors.append(f"artifact {index} run_id does not match manifest")
        if artifact["artifact_id"] in artifact_ids:
            errors.append(f"duplicate artifact_id: {artifact['artifact_id']}")
        artifact_ids.add(artifact["artifact_id"])
        if artifact["produced_by"] not in event_ids:
            errors.append(f"artifact {index} references missing producing event")
        if verify_artifact_content:
            path = Path(artifact["locator"]["path"])
            if not path.is_file():
                errors.append(f"artifact {index} no longer exists: {path}")
            else:
                digest, size = sha256_file(path)
                if digest != artifact["sha256"] or size != artifact["size_bytes"]:
                    errors.append(f"artifact {index} content fingerprint drifted: {path}")

    observed_artifacts = {
        event.get("payload", {}).get("artifact_id")
        for event in events if event.get("type") == "artifact.observed"
    }
    missing_events = sorted(artifact_ids - observed_artifacts)
    unknown_events = sorted(item for item in observed_artifacts - artifact_ids if item)
    if missing_events:
        message = f"artifacts lack artifact.observed events: {', '.join(missing_events)}"
        if terminal_events:
            errors.append(message)
        else:
            warnings.append(message)
    if unknown_events:
        errors.append(f"artifact.observed references missing artifacts: {', '.join(unknown_events)}")

    derived = None
    if events:
        try:
            derived = derive_result(manifest, events, artifacts)
        except (ContractError, ValueError, TypeError) as exc:
            errors.append(f"cannot derive result: {exc}")
    if terminal_events:
        if not paths["result"].is_file():
            errors.append("terminal run is missing result.json")
        else:
            try:
                stored = load_json(paths["result"], "result.json")
                validate_result(stored)
                if derived is not None and stored != derived:
                    errors.append("result.json does not match the result derived from events and artifacts")
            except (TraceError, ContractError) as exc:
                errors.append(str(exc))
    elif paths["result"].exists():
        errors.append("incomplete run must not have result.json")

    return {
        "valid": not errors,
        "run_id": manifest["run_id"],
        "terminal_status": derived["terminal_status"] if derived else "incomplete",
        "events": len(events),
        "artifacts": len(artifacts),
        "errors": errors,
        "warnings": warnings,
        "derived_result": derived,
    }


class _PipeRecorder:
    def __init__(self, target: Any, capture: bool) -> None:
        self.binary_target = hasattr(target, "buffer")
        self.target = getattr(target, "buffer", target)
        self.capture_enabled = capture
        self.digest = hashlib.sha256()
        self.size = 0
        self.tail = bytearray()
        self.capture = bytearray()
        self.capture_truncated = False

    def consume(self, pipe: Any) -> None:
        while True:
            block = pipe.read(8192)
            if not block:
                break
            if isinstance(block, str):
                block = block.encode("utf-8", errors="replace")
            self.digest.update(block)
            self.size += len(block)
            self.tail.extend(block)
            if len(self.tail) > TAIL_LIMIT:
                del self.tail[:-TAIL_LIMIT]
            if self.capture_enabled:
                remaining = JSON_CAPTURE_LIMIT - len(self.capture)
                if remaining > 0:
                    self.capture.extend(block[:remaining])
                if len(block) > remaining:
                    self.capture_truncated = True
            if self.binary_target:
                self.target.write(block)
            else:
                self.target.write(block.decode("utf-8", errors="replace"))
            self.target.flush()

    def summary(self) -> Dict[str, Any]:
        return {
            "sha256": self.digest.hexdigest(),
            "bytes": self.size,
            "tail": redact_string(self.tail.decode("utf-8", errors="replace")),
        }


def run_tool(
    run_dir: Path,
    *,
    name: str,
    command: Sequence[str],
    phase: str = "execute",
    parent_span_id: Optional[str] = None,
    capture_json: bool = False,
    capture_authority: str = "tool-json-output",
    capture_json_name: Optional[str] = None,
    cwd: Optional[Path] = None,
) -> int:
    if not command:
        raise TraceError("tool command is empty")
    load_manifest(run_dir)
    working_directory = (cwd or Path.cwd()).expanduser().resolve()
    if not working_directory.is_dir():
        raise TraceError(f"tool working directory is not a directory: {working_directory}")
    arguments_hash = sha256_bytes(canonical_json_bytes(list(command)))
    started = append_event(
        run_dir,
        event_type="tool.started",
        source_kind="tool",
        source_id=name,
        evidence_level="observed",
        phase=phase,
        parent_span_id=parent_span_id,
        payload={
            "name": name,
            "executable": command[0],
            "arguments": redact_argv(list(command[1:])),
            "arguments_sha256": arguments_hash,
            "cwd": str(working_directory),
        },
    )
    started_at = time.monotonic()
    stdout_recorder = _PipeRecorder(sys.stdout, capture_json)
    stderr_recorder = _PipeRecorder(sys.stderr, False)
    try:
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=None,
            cwd=str(working_directory),
        )
    except OSError as exc:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        finished = append_event(
            run_dir,
            event_type="tool.finished",
            source_kind="tool",
            source_id=name,
            evidence_level="observed",
            phase=phase,
            span_id=started["span_id"],
            parent_span_id=parent_span_id,
            payload={
                "name": name,
                "status": "error",
                "exit_code": 127,
                "elapsed_ms": elapsed_ms,
                "stdout": stdout_recorder.summary(),
                "stderr": {"sha256": sha256_bytes(b""), "bytes": 0, "tail": redact_string(str(exc))},
            },
        )
        append_event(
            run_dir,
            event_type="error.observed",
            source_kind="collector",
            source_id="skill-observer",
            evidence_level="observed",
            phase=phase,
            parent_span_id=finished["span_id"],
            payload={"kind": "tool-launch", "message": str(exc)},
        )
        return 127

    assert process.stdout is not None
    assert process.stderr is not None
    threads = [
        threading.Thread(target=stdout_recorder.consume, args=(process.stdout,), daemon=True),
        threading.Thread(target=stderr_recorder.consume, args=(process.stderr,), daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        exit_code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        exit_code = process.wait()
    for thread in threads:
        thread.join()
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    finished = append_event(
        run_dir,
        event_type="tool.finished",
        source_kind="tool",
        source_id=name,
        evidence_level="observed",
        phase=phase,
        span_id=started["span_id"],
        parent_span_id=parent_span_id,
        payload={
            "name": name,
            "status": "ok" if exit_code == 0 else "error",
            "exit_code": exit_code,
            "elapsed_ms": elapsed_ms,
            "stdout": stdout_recorder.summary(),
            "stderr": stderr_recorder.summary(),
        },
    )

    if capture_json:
        if stdout_recorder.capture_truncated:
            append_event(
                run_dir,
                event_type="error.observed",
                source_kind="collector",
                source_id="skill-observer",
                evidence_level="observed",
                phase="verify",
                parent_span_id=finished["span_id"],
                payload={"kind": "json-capture", "message": "stdout exceeded 1 MiB capture limit"},
            )
        else:
            try:
                decoded = stdout_recorder.capture.decode("utf-8")
                parsed = json.loads(decoded)
                safe_value = redact_value(parsed)
                evidence_dir = run_paths(run_dir)["root"] / "evidence"
                name = capture_json_name or started["span_id"]
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
                    raise TraceError("capture JSON name contains unsafe characters")
                evidence_path = evidence_dir / f"{name}.json"
                if evidence_path.exists():
                    raise TraceError(f"captured JSON evidence already exists: {evidence_path}")
                if not isinstance(safe_value, dict):
                    safe_value = {"value": safe_value}
                atomic_write_json(evidence_path, safe_value)
                register_artifact(
                    run_dir,
                    path=evidence_path,
                    role="tool-json-output",
                    authority=capture_authority,
                    produced_by=finished["event_id"],
                    site_id="collector",
                    media_type="application/json",
                )
            except (UnicodeDecodeError, json.JSONDecodeError, TraceError) as exc:
                append_event(
                    run_dir,
                    event_type="error.observed",
                    source_kind="collector",
                    source_id="skill-observer",
                    evidence_level="observed",
                    phase="verify",
                    parent_span_id=finished["span_id"],
                    payload={"kind": "json-capture", "message": str(exc)},
                )
    return exit_code
