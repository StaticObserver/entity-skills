"""Offline phase segmentation for Claude Code transcripts.

Splits a Claude Code JSONL transcript into ordered lifecycle phases
(discover -> pgen -> env-build -> run -> analysis -> submission) using a
rule table matched against observable tool calls. Runs entirely post-hoc:
the agent under test is never instrumented, and the agent's context window
is unaffected.

Attribution model (deterministic):

- Records are walked in transcript order. The current phase starts unset;
  records before the first rule match fall into ``unclassified``.
- A record whose tool calls match a *later* phase advances the current
  phase; matches against earlier phases never regress it. Exploratory
  commands (``ssh``, ``ls``) therefore count as ``discover`` only until the
  pgen phase begins, and as part of whatever phase is active afterwards.
- Each record's token usage and tool calls are attributed to the phase
  active for that record.

Stdlib only, consistent with the rest of this package.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..core import TraceError, sha256_bytes

# Lifecycle order. Index in this list is the phase priority: a rule match may
# only advance the current phase, never regress it.
PHASE_ORDER = ["discover", "pgen", "env-build", "run", "analysis", "submission"]

# Default rule table. Each rule is (phase, regex). The regex is matched
# against "<tool name> <tool targets>" for every tool_use item, where targets
# are command lines and file paths only (never free-form content). Rules are
# deliberately usage-oriented: observational commands (squeue/sinfo) and
# skill documentation reads must not trigger a phase; only actual work does.
DEFAULT_RULES: Sequence[Tuple[str, str]] = (
    ("submission", r"submission\.json"),
    ("analysis", r"\bnt2\b|nt2\.Data|inspect_nt2_data"),
    ("run", r"entityctl\b.*\b(plan|apply)\b|\bsbatch\b"),
    ("env-build", r"\bcmake\b|\bmake\b|\bnvcc\b|\bspack\b|entity[-_](build|generate|run|state|compat|checkpoint)"),
    ("pgen", r"pgen\.hpp|pgen_preflight|design\.md"),
    ("discover", r"\bssh\b|\bsinfo\b|\bsqueue\b|\bscontrol\b|\bls\b|\bfind\b|module (list|avail|load)|\bwhich\b|\benv\b"),
)

# Tool targets under an installed skill directory are orientation (reading
# SKILL.md/references), never phase work.
SKILL_DOC_RE = re.compile(r"/\.claude/skills/")

SSH_RE = re.compile(r"\bssh\b|\bscp\b|\brsync\b")

# Fields whose *values* rule patterns are matched against. Deliberately only
# tool targets (command line, file paths, search patterns) — never free-form
# content such as Write/Edit file bodies or subagent prompts. A plan document
# that merely *mentions* submission.json must not trigger the submission
# phase; only a Write whose file_path IS submission.json may.
_MATCH_FIELDS = ("command", "file_path", "path", "pattern", "notebook_path")

_UNCLASSIFIED = "unclassified"


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _serialize_input(value: Any) -> str:
    """Build the match text for a tool input from target fields only."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts = [str(value[key]) for key in _MATCH_FIELDS if key in value]
        return " ".join(parts)
    return ""


def compile_rules(rules: Optional[Sequence[Mapping[str, str]]]) -> List[Tuple[int, "re.Pattern[str]"]]:
    """Compile a rule table into (phase_index, pattern) pairs.

    ``rules`` is a list of {"phase": name, "pattern": regex} objects; when
    None the built-in DEFAULT_RULES table is used.
    """
    table: Sequence[Tuple[str, str]]
    if rules is None:
        table = DEFAULT_RULES
    else:
        table = []
        for index, rule in enumerate(rules):
            phase = str(rule.get("phase") or "")
            pattern = str(rule.get("pattern") or "")
            if phase not in PHASE_ORDER:
                raise TraceError(
                    "rules entry %d has unknown phase %r (expected one of %s)"
                    % (index, phase, ", ".join(PHASE_ORDER))
                )
            if not pattern:
                raise TraceError("rules entry %d has an empty pattern" % index)
            table.append((phase, pattern))
    compiled: List[Tuple[int, "re.Pattern[str]"]] = []
    for phase, pattern in table:
        try:
            compiled.append((PHASE_ORDER.index(phase), re.compile(pattern)))
        except re.error as exc:
            raise TraceError("rule for phase %r is invalid regex: %s" % (phase, exc)) from exc
    return compiled


def _empty_bucket() -> Dict[str, Any]:
    return {
        "records": 0,
        "started_at": None,
        "ended_at": None,
        "wall_time_ms": 0,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
        "tool_calls": {"total": 0, "failed": 0},
        "ssh_calls": 0,
    }


def _bucket_add(bucket: Dict[str, Any], *, timestamp: Optional[datetime],
                timestamp_raw: Optional[str], usage: Mapping[str, int],
                calls: int, failed: int, ssh: int) -> None:
    bucket["records"] += 1
    if timestamp is not None:
        if bucket["started_at"] is None:
            bucket["started_at"] = timestamp_raw
            bucket["_start"] = timestamp
        bucket["ended_at"] = timestamp_raw
        bucket["_end"] = timestamp
    for key in bucket["usage"]:
        bucket["usage"][key] += int(usage.get(key) or 0)
    bucket["tool_calls"]["total"] += calls
    bucket["tool_calls"]["failed"] += failed
    bucket["ssh_calls"] += ssh


def _finalize_bucket(name: str, bucket: Dict[str, Any]) -> Dict[str, Any]:
    start = bucket.pop("_start", None)
    end = bucket.pop("_end", None)
    if start is not None and end is not None:
        bucket["wall_time_ms"] = max(0, int((end - start).total_seconds() * 1000))
    return {"name": name, **bucket}


def segment_transcript(
    transcript_path: Path,
    *,
    rules: Optional[Sequence[Mapping[str, str]]] = None,
    unclassified_token_limit: float = 0.10,
) -> Dict[str, Any]:
    """Segment a Claude Code transcript into lifecycle phases.

    Returns the phases report as a dict. Records whose timestamps are missing
    still contribute token/tool counts but not wall-clock bounds.
    """
    path = transcript_path.expanduser().resolve()
    raw = path.read_bytes()
    compiled = compile_rules(rules)

    buckets: Dict[str, Dict[str, Any]] = {name: _empty_bucket() for name in PHASE_ORDER}
    buckets[_UNCLASSIFIED] = _empty_bucket()
    current = -1  # index into PHASE_ORDER; -1 = unclassified
    session_id = ""

    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceError("Claude transcript line %d is invalid JSON: %s" % (number, exc))
        session_id = session_id or str(record.get("sessionId") or "")
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")
        usage_raw = message.get("usage") if isinstance(message.get("usage"), dict) else {}
        usage = {
            "input_tokens": int(usage_raw.get("input_tokens") or 0),
            "output_tokens": int(usage_raw.get("output_tokens") or 0),
            "cache_read_input_tokens": int(usage_raw.get("cache_read_input_tokens") or 0),
            "cache_creation_input_tokens": int(usage_raw.get("cache_creation_input_tokens") or 0),
        }

        calls = 0
        failed = 0
        ssh = 0
        best = -1
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type == "tool_use":
                    calls += 1
                    text = "%s %s" % (item.get("name") or "", _serialize_input(item.get("input")))
                    if SSH_RE.search(text):
                        ssh += 1
                    if SKILL_DOC_RE.search(text):
                        continue  # reading installed skill docs is orientation
                    for phase_index, pattern in compiled:
                        if phase_index > best and pattern.search(text):
                            best = phase_index
                elif item_type == "tool_result" and item.get("is_error"):
                    failed += 1

        if best > current:
            current = best
        bucket_name = PHASE_ORDER[current] if current >= 0 else _UNCLASSIFIED
        timestamp_raw = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
        _bucket_add(
            buckets[bucket_name],
            timestamp=_parse_time(timestamp_raw),
            timestamp_raw=timestamp_raw,
            usage=usage,
            calls=calls,
            failed=failed,
            ssh=ssh,
        )

    phases = [_finalize_bucket(name, buckets[name]) for name in PHASE_ORDER]
    unclassified = _finalize_bucket(_UNCLASSIFIED, buckets[_UNCLASSIFIED])

    totals = _empty_bucket()
    for bucket in [*phases, unclassified]:
        totals["records"] += bucket["records"]
        totals["wall_time_ms"] += bucket["wall_time_ms"]
        for key in totals["usage"]:
            totals["usage"][key] += bucket["usage"][key]
        totals["tool_calls"]["total"] += bucket["tool_calls"]["total"]
        totals["tool_calls"]["failed"] += bucket["tool_calls"]["failed"]
        totals["ssh_calls"] += bucket["ssh_calls"]
    totals.pop("started_at")
    totals.pop("ended_at")

    total_tokens = sum(totals["usage"].values())
    unclassified_tokens = sum(unclassified["usage"].values())
    unclassified_share = (unclassified_tokens / total_tokens) if total_tokens else 0.0
    comparable = unclassified_share <= unclassified_token_limit

    notes: List[str] = []
    if not comparable:
        notes.append(
            "unclassified token share %.1f%% exceeds %.1f%% limit; "
            "refine the rule table before comparing this trace"
            % (unclassified_share * 100, unclassified_token_limit * 100)
        )
    notes.append("wall_time_ms excludes scheduler queueing; derive queue time from scheduler facts")

    return {
        "schema_version": 1,
        "source": {
            "transcript_sha256": sha256_bytes(raw),
            "transcript_path": str(path),
            "session_id": session_id or path.stem,
        },
        "phase_order": list(PHASE_ORDER),
        "phases": phases,
        "unclassified": unclassified,
        "totals": totals,
        "unclassified_token_share": round(unclassified_share, 6),
        "comparable": comparable,
        "notes": notes,
    }


def write_phases_report(
    run_dir: Path,
    *,
    transcript_path: Path,
    rules: Optional[Sequence[Mapping[str, str]]] = None,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build the phases report and write it into the run directory."""
    report = segment_transcript(transcript_path, rules=rules)
    target = output_path or (Path(run_dir) / "phases.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report["written_to"] = str(target)
    return report
