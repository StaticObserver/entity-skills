"""Import observable tool calls from a Claude Code project transcript."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import TraceError, sha256_bytes
from .tool_trace import import_tool_trace


def _load(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    calls: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    session_id = ""
    cwd: Optional[str] = None
    skipped = 0
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceError("Claude transcript line %d is invalid JSON: %s" % (number, exc))
        session_id = session_id or str(record.get("sessionId") or "")
        cwd = cwd or record.get("cwd")
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        message_usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
        usage["input_tokens"] += int(message_usage.get("input_tokens") or 0)
        usage["cached_input_tokens"] += int(
            message_usage.get("cache_read_input_tokens") or 0
        )
        usage["output_tokens"] += int(message_usage.get("output_tokens") or 0)
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "thinking":
                skipped += 1
            elif item_type == "tool_use":
                call_id = str(item.get("id") or "")
                if not call_id:
                    raise TraceError("Claude tool_use on line %d has no id" % number)
                call = {
                    "call_id": call_id,
                    "name": str(item.get("name") or "unknown-tool"),
                    "status": "requested",
                    "input": item.get("input"),
                    "line": number,
                    "agent_id": "main",
                    "has_output": False,
                }
                calls.append(call)
                by_id[call_id] = call
            elif item_type == "tool_result":
                call_id = str(item.get("tool_use_id") or "")
                if call_id in by_id:
                    by_id[call_id].update({
                        "has_output": True,
                        "output": item.get("content"),
                        "is_error": bool(item.get("is_error")),
                    })
    return {
        "calls": calls,
        "session_id": session_id or path.stem,
        "cwd": cwd,
        "skipped": skipped,
        "usage": usage,
        "sha256": sha256_bytes(raw),
    }


def import_claude_transcript(
    run_dir: Path, *, transcript_path: Path, parent_span_id: Optional[str] = None
) -> Dict[str, Any]:
    path = transcript_path.expanduser().resolve()
    parsed = _load(path)
    return import_tool_trace(
        run_dir,
        adapter="claude-transcript",
        calls=parsed["calls"],
        source_sha256=parsed["sha256"],
        session_id=parsed["session_id"],
        session_cwd=parsed["cwd"],
        skipped_reasoning=parsed["skipped"],
        usage=parsed["usage"],
        parent_span_id=parent_span_id,
    )
