"""Shared import path for observable provider tool-call transcripts.

Provider adapters normalize native records into calls and results. This module
stores only hashes and byte counts; prompts, messages, reasoning, and raw tool
payloads are never retained in the trace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

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


def serialized(value: Any) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")
    return canonical_json_bytes(value)


def resource_matches(
    manifest: Mapping[str, Any], call_input: Any, session_cwd: Optional[str]
) -> List[Dict[str, str]]:
    if not isinstance(call_input, str):
        try:
            call_input = canonical_json_bytes(call_input).decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            return []
    matches: List[Dict[str, str]] = []
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
        matched = next(
            (candidate for candidate in candidates if candidate and candidate in call_input),
            None,
        )
        name = str(skill.get("name") or "")
        if matched and name not in seen:
            matches.append({
                "name": name,
                "resource_ref": matched,
                "content_sha256": str(skill.get("content_sha256") or ""),
            })
            seen.add(name)
    return matches


def import_tool_trace(
    run_dir: Path,
    *,
    adapter: str,
    calls: Iterable[Mapping[str, Any]],
    source_sha256: str,
    session_id: str,
    session_cwd: Optional[str],
    skipped_reasoning: int,
    usage: Mapping[str, Optional[int]],
    parent_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    manifest = load_manifest(run_dir)
    events = read_jsonl(run_paths(run_dir)["events"], "events.jsonl")
    if not events:
        raise TraceError("run has no run.started event")
    root_span = parent_span_id or events[0]["span_id"]
    existing_starts: Dict[str, Mapping[str, Any]] = {}
    existing_finishes = set()
    for event in events:
        payload = event.get("payload", {})
        if payload.get("adapter") != adapter:
            continue
        call_id = str(payload.get("source_call_id") or "")
        if event.get("type") == "tool.started" and call_id:
            existing_starts[call_id] = event
        elif event.get("type") == "tool.finished" and call_id:
            existing_finishes.add(call_id)

    normalized = list(calls)
    started_count = 0
    finished_count = 0
    resource_count = 0
    for call in normalized:
        call_id = str(call.get("call_id") or "")
        if not call_id:
            raise TraceError("normalized provider tool call has no call_id")
        span_id = adapter.replace("-", "_") + "-" + sha256_text(call_id)[:24]
        started = existing_starts.get(call_id)
        common = {
            "adapter": adapter,
            "source_call_id": call_id,
            "native_session_id": session_id,
            "native_agent_id": str(call.get("agent_id") or ""),
            "agent_run_id": manifest["run_id"],
        }
        if started is None:
            input_bytes = serialized(call.get("input"))
            started = append_event(
                run_dir,
                event_type="tool.started",
                source_kind="adapter",
                source_id=adapter,
                evidence_level="observed",
                phase="execute",
                span_id=span_id,
                parent_span_id=root_span,
                payload={
                    **common,
                    "name": str(call.get("name") or "unknown-tool"),
                    "provider_status": str(call.get("status") or "unknown"),
                    "input": {
                        "sha256": sha256_bytes(input_bytes),
                        "bytes": len(input_bytes),
                        "retained": False,
                    },
                    "source_line": int(call.get("line") or 0),
                },
            )
            existing_starts[call_id] = started
            started_count += 1
            for resource in resource_matches(manifest, call.get("input"), session_cwd):
                append_event(
                    run_dir,
                    event_type="skill.resource_observed",
                    source_kind="adapter",
                    source_id=adapter,
                    evidence_level="observed",
                    phase="orient",
                    parent_span_id=started["span_id"],
                    payload={
                        **common,
                        **resource,
                        "observation": "tool request referenced this skill source",
                    },
                )
                resource_count += 1
        if call.get("has_output") and call_id not in existing_finishes:
            output_bytes = serialized(call.get("output"))
            is_error = call.get("is_error")
            status = "failed" if is_error else ("unknown" if is_error is None else "completed")
            append_event(
                run_dir,
                event_type="tool.finished",
                source_kind="adapter",
                source_id=adapter,
                evidence_level="observed",
                phase="execute",
                span_id=started["span_id"],
                parent_span_id=started["parent_span_id"],
                payload={
                    **common,
                    "name": str(call.get("name") or "unknown-tool"),
                    "status": status,
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
        "adapter": adapter,
        "source_sha256": source_sha256,
        "native_session_id": session_id,
        "agent_run_id": manifest["run_id"],
        "calls_seen": len(normalized),
        "started_imported": started_count,
        "finished_imported": finished_count,
        "resources_observed": resource_count,
        "reasoning_records_skipped": skipped_reasoning,
        "usage": dict(usage),
    }
