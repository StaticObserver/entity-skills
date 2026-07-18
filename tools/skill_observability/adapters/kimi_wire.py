"""Import observable tool calls and native usage from a Kimi Code session."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import TraceError, sha256_bytes
from .tool_trace import import_tool_trace


def _wire_files(session_path: Path) -> List[Path]:
    if session_path.is_file():
        return [session_path]
    files = sorted(session_path.glob("agents/*/wire.jsonl"))
    if not files:
        raise TraceError("Kimi session contains no agents/*/wire.jsonl")
    return files


def import_kimi_session(
    run_dir: Path, *, session_path: Path, parent_span_id: Optional[str] = None
) -> Dict[str, Any]:
    session_path = session_path.expanduser().resolve()
    calls: List[Dict[str, Any]] = []
    skipped = 0
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    digest_material = bytearray()
    cwd: Optional[str] = None
    state_path = session_path / "state.json" if session_path.is_dir() else None
    if state_path and state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            cwd = state.get("workDir")
        except (OSError, json.JSONDecodeError) as exc:
            raise TraceError("Kimi state.json is invalid: %s" % exc)
    for wire in _wire_files(session_path):
        raw = wire.read_bytes()
        digest_material.extend(str(wire.name).encode("utf-8") + b"\0" + raw + b"\0")
        agent_id = wire.parent.name
        by_id: Dict[str, Dict[str, Any]] = {}
        wire_usage = {
            "turn": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
                     "records": 0},
            "session": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
                        "records": 0},
        }
        for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TraceError("Kimi wire %s line %d is invalid JSON: %s" % (wire, number, exc))
            record_type = record.get("type")
            if record_type == "usage.record":
                native = record.get("usage") if isinstance(record.get("usage"), dict) else {}
                scope = "session" if record.get("usageScope") == "session" else "turn"
                wire_usage[scope]["input_tokens"] += int(native.get("inputOther") or 0)
                wire_usage[scope]["cached_input_tokens"] += int(native.get("inputCacheRead") or 0)
                wire_usage[scope]["input_tokens"] += int(native.get("inputCacheCreation") or 0)
                wire_usage[scope]["output_tokens"] += int(native.get("output") or 0)
                wire_usage[scope]["records"] += 1
                continue
            if record_type != "context.append_loop_event":
                continue
            event = record.get("event") if isinstance(record.get("event"), dict) else {}
            event_type = event.get("type")
            if event_type == "content.part":
                part = event.get("part") if isinstance(event.get("part"), dict) else {}
                if part.get("type") in {"think", "thinking", "reasoning"}:
                    skipped += 1
            elif event_type == "tool.call":
                native_id = str(event.get("toolCallId") or "")
                if not native_id:
                    raise TraceError("Kimi tool.call in %s line %d has no toolCallId" % (wire, number))
                call_id = agent_id + ":" + native_id
                call = {
                    "call_id": call_id,
                    "name": str(event.get("name") or "unknown-tool"),
                    "status": "requested",
                    "input": event.get("args"),
                    "line": number,
                    "agent_id": agent_id,
                    "has_output": False,
                }
                calls.append(call)
                by_id[native_id] = call
            elif event_type == "tool.result":
                native_id = str(event.get("toolCallId") or "")
                if native_id in by_id:
                    by_id[native_id].update({
                        "has_output": True,
                        "output": event.get("result"),
                        "is_error": False,
                    })
        selected_usage = wire_usage["turn"] if wire_usage["turn"]["records"] else wire_usage["session"]
        for key in usage:
            usage[key] += selected_usage[key]
    session_id = session_path.name if session_path.is_dir() else session_path.parent.parent.name
    return import_tool_trace(
        run_dir,
        adapter="kimi-wire",
        calls=calls,
        source_sha256=sha256_bytes(bytes(digest_material)),
        session_id=session_id,
        session_cwd=cwd,
        skipped_reasoning=skipped,
        usage=usage,
        parent_span_id=parent_span_id,
    )
