"""Import observable tool calls from a Codex rollout JSONL.

This adapter deliberately ignores messages, reasoning items, encrypted
reasoning, and agent_reasoning events. It imports only custom tool call and
custom tool call output records, retaining hashes and byte counts rather than
raw input/output content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..core import (
    TraceError,
    append_event,
    canonical_json_bytes,
    load_manifest,
    read_jsonl,
    run_paths,
    sha256_bytes,
    sha256_text,
)


def _serialized(value: Any) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")
    return canonical_json_bytes(value)


def _is_observer_call(call_input: Any) -> bool:
    if not isinstance(call_input, str):
        return False
    normalized = call_input.replace("\\", "/")
    return "tools/skill_observability/skill_observer.py" in normalized


def _resource_matches(
    manifest: Mapping[str, Any], call_input: Any, session_cwd: Optional[str]
) -> List[Dict[str, str]]:
    if not isinstance(call_input, str):
        return []
    matches = []
    seen = set()
    for skill in manifest.get("skills", []):
        source = Path(str(skill.get("source") or "")).resolve()
        candidates = [str(source)]
        for base in [Path(session_cwd).resolve() if session_cwd else None, Path.cwd().resolve()]:
            if base is None:
                continue
            try:
                candidates.append(str(source.relative_to(base)))
            except ValueError:
                pass
        matched = next((candidate for candidate in candidates if candidate and candidate in call_input), None)
        if matched and skill.get("name") not in seen:
            matches.append({
                "name": str(skill.get("name") or ""),
                "resource_ref": matched,
                "content_sha256": str(skill.get("content_sha256") or ""),
            })
            seen.add(skill.get("name"))
    return matches


def _load_rollout(path: Path) -> Dict[str, Any]:
    calls: List[Dict[str, Any]] = []
    outputs: Dict[str, Any] = {}
    session_meta = 0
    session_cwd: Optional[str] = None
    skipped_reasoning = 0
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TraceError(f"cannot read Codex rollout at {path}: {exc}") from exc
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceError(f"Codex rollout line {number} is invalid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise TraceError(f"Codex rollout line {number} must be an object")
        record_type = record.get("type")
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if record_type == "session_meta":
            session_meta += 1
            if payload.get("cwd"):
                session_cwd = str(payload["cwd"])
            continue
        if payload.get("type") in {"reasoning", "agent_reasoning"}:
            skipped_reasoning += 1
            continue
        if record_type != "response_item":
            continue
        if payload.get("type") == "custom_tool_call":
            call_id = str(payload.get("call_id") or payload.get("id") or "")
            if not call_id:
                raise TraceError(f"Codex tool call on line {number} has no call_id")
            calls.append({
                "call_id": call_id,
                "name": str(payload.get("name") or "unknown-tool"),
                "status": str(payload.get("status") or "unknown"),
                "input": payload.get("input"),
                "line": number,
            })
        elif payload.get("type") == "custom_tool_call_output":
            call_id = str(payload.get("call_id") or "")
            if call_id:
                outputs[call_id] = payload.get("output")
    if session_meta == 0:
        raise TraceError("input does not contain a Codex session_meta record")
    return {
        "calls": calls,
        "outputs": outputs,
        "session_meta": session_meta,
        "session_cwd": session_cwd,
        "skipped_reasoning": skipped_reasoning,
        "rollout_sha256": sha256_bytes(raw),
    }


def import_codex_rollout(
    run_dir: Path,
    *,
    rollout_path: Path,
    parent_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    manifest = load_manifest(run_dir)
    paths = run_paths(run_dir)
    rollout_path = rollout_path.expanduser().resolve()
    parsed = _load_rollout(rollout_path)
    events = read_jsonl(paths["events"], "events.jsonl")
    if not events:
        raise TraceError("run has no run.started event")
    root_span = parent_span_id or events[0]["span_id"]

    existing_starts: Dict[str, Mapping[str, Any]] = {}
    existing_finishes = set()
    for event in events:
        payload = event.get("payload", {})
        if payload.get("adapter") != "codex-rollout":
            continue
        call_id = str(payload.get("source_call_id") or "")
        if event.get("type") == "tool.started" and call_id:
            existing_starts[call_id] = event
        elif event.get("type") == "tool.finished" and call_id:
            existing_finishes.add(call_id)

    started_count = 0
    finished_count = 0
    resource_count = 0
    observer_calls_skipped = 0
    for call in parsed["calls"]:
        if _is_observer_call(call.get("input")):
            observer_calls_skipped += 1
            continue
        call_id = call["call_id"]
        span_id = "codex-" + sha256_text(call_id)[:24]
        started = existing_starts.get(call_id)
        if started is None:
            input_bytes = _serialized(call.get("input"))
            started = append_event(
                run_dir,
                event_type="tool.started",
                source_kind="adapter",
                source_id="codex-rollout",
                evidence_level="observed",
                phase="execute",
                span_id=span_id,
                parent_span_id=root_span,
                payload={
                    "adapter": "codex-rollout",
                    "source_call_id": call_id,
                    "name": call["name"],
                    "provider_status": call["status"],
                    "input": {
                        "sha256": sha256_bytes(input_bytes),
                        "bytes": len(input_bytes),
                        "retained": False,
                    },
                    "source_line": call["line"],
                },
            )
            existing_starts[call_id] = started
            started_count += 1
            for resource in _resource_matches(manifest, call.get("input"), parsed["session_cwd"]):
                append_event(
                    run_dir,
                    event_type="skill.resource_observed",
                    source_kind="adapter",
                    source_id="codex-rollout",
                    evidence_level="observed",
                    phase="orient",
                    parent_span_id=started["span_id"],
                    payload={
                        "adapter": "codex-rollout",
                        "source_call_id": call_id,
                        **resource,
                        "observation": "tool request referenced this skill source",
                    },
                )
                resource_count += 1

        if call_id in parsed["outputs"] and call_id not in existing_finishes:
            output_bytes = _serialized(parsed["outputs"][call_id])
            append_event(
                run_dir,
                event_type="tool.finished",
                source_kind="adapter",
                source_id="codex-rollout",
                evidence_level="observed",
                phase="execute",
                span_id=started["span_id"],
                parent_span_id=started["parent_span_id"],
                payload={
                    "adapter": "codex-rollout",
                    "source_call_id": call_id,
                    "name": call["name"],
                    "status": "completed",
                    "exit_code": None,
                    "output": {
                        "sha256": sha256_bytes(output_bytes),
                        "bytes": len(output_bytes),
                        "retained": False,
                    },
                },
            )
            existing_finishes.add(call_id)
            finished_count += 1

    return {
        "adapter": "codex-rollout",
        "rollout_sha256": parsed["rollout_sha256"],
        "calls_seen": len(parsed["calls"]),
        "started_imported": started_count,
        "finished_imported": finished_count,
        "resources_observed": resource_count,
        "observer_calls_skipped": observer_calls_skipped,
        "reasoning_records_skipped": parsed["skipped_reasoning"],
    }
