"""Offline activity tagging for Claude Code transcripts.

Classifies every observable tool call in a Claude Code JSONL transcript
into exactly one activity category (explore, pgen-authoring, build,
job-submit, job-monitor, data-analysis, documentation, other). Unlike
claude_phases there is NO state machine and no ordering assumption: a
pgen file written after a build command still counts as pgen-authoring,
and a build command issued during analysis still counts as build. This
makes the metric robust for agents that explore freely, interleave work,
or backtrack.

Attribution model (deterministic):

- Each tool_use item is classified independently. Match text is
  "<tool name> <tool targets>" with targets limited to command lines and
  file paths (never Write/Edit bodies), exactly as in claude_phases.
  The first matching rule in the (ordered) rule table wins; unmatched
  calls fall into ``other``. Reads of installed skill docs
  (/.claude/skills/) are counted separately and join no category.
- Record-level token/time attribution is multi-label: a record counts
  toward EVERY category its tool calls touch, so the per-category usage
  sums may exceed the transcript totals. Category buckets therefore
  measure "effort touching this activity", not a partition.
- sbatch submissions inside Bash commands are parsed structurally (not
  just regex-tagged) to build the job_lifecycle section; a build-class
  sbatch is categorized as ``build`` rather than ``job-submit``.

The report is descriptive only: it never emits a comparable/fail verdict.
``unclassified_tool_share`` is informational for refining the rule table.

Stdlib only, consistent with the rest of this package.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..core import TraceError, _assert_write_root_safe, load_manifest, run_paths, sha256_bytes
from .claude_phases import _parse_time
from .skill_adoption import SKILL_DOC_RE, match_text, summarize_skill_adoption

# Fixed category set. Every tool_use lands in exactly one of these;
# ``other`` is the catch-all for calls no rule matched.
CATEGORIES = [
    "explore",
    "pgen-authoring",
    "build",
    "job-submit",
    "job-monitor",
    "data-analysis",
    "documentation",
    "other",
]

# Default rule table. Ordered (category, regex) pairs matched against
# "<tool name> <tool targets>"; the first match wins. Work-oriented rules
# precede ``explore`` so an ssh wrapper around real work is classified by
# the work, not by the transport. sbatch is deliberately absent: Bash
# commands containing sbatch are classified structurally (build-class
# submissions count as ``build``, the rest as ``job-submit``).
DEFAULT_RULES: Sequence[Tuple[str, str]] = (
    ("pgen-authoring", r"pgen\.hpp|input[^\s]*\.toml|design\.md"),
    ("job-submit", r"\bscancel\b|\bentityctl\b.*\brecord\b"),
    ("job-monitor", r"\bsqueue\b|\bsacct\b|\bscontrol\b|\bentityctl\b.*\bstatus\b"),
    ("build", r"\bcmake\b|\bmake\b|\bnvcc\b|\bspack\b|\bninja\b"),
    ("data-analysis", r"\bnt2\b|\bnt2py\b|nt2\.Data|inspect_nt2_data"),
    ("documentation", r"submission\.json|\bREADME\b|\breport\.md\b|\banalysis\.md\b"),
    ("explore", r"\bssh\b|\bscp\b|\brsync\b|\bsinfo\b|\bls\b|\bfind\b"
                r"|module\s+(list|avail|load)|\bwhich\b|\benv\b|\bcat\b|\bhead\b|\btail\b"
                r"|\bgrep\b|^Read\s|^Grep\s|^Glob\s|^LS\s"),
)

# Bare sbatch invocations only: the lookbehind excludes script paths such
# as "run.sbatch" or "/usr/bin/sbatch" from counting as submissions.
SBATCH_RE = re.compile(r"(?<![\w./-])sbatch\b")

# Job name from --job-name=<name>, --job-name <name>, -J<name>, -J <name>.
_JOB_NAME_RE = re.compile(r"(?:--job-name(?:=|\s+)|-J\s?)([^\s\"']+)")

# Build-class heuristics: the job name/script mentions a build, or the
# submitted command text (heredoc/script body) invokes a build tool.
BUILD_NAME_RE = re.compile(r"build|rebuild|kk|deps|compile", re.IGNORECASE)
BUILD_CONTENT_RE = re.compile(r"\b(cmake|make|nvcc|ninja)\b")

# sbatch flags whose argument is a separate token (skipped when looking
# for the script path).
_FLAGS_WITH_ARG = frozenset({
    "-J", "--job-name", "-o", "--output", "-e", "--error", "-t", "--time",
    "-p", "--partition", "-A", "--account", "-N", "--nodes", "-n", "--ntasks",
    "-c", "--cpus-per-task", "--mem", "-D", "--chdir", "-w", "--nodelist",
    "-q", "--qos", "--gres", "--comment", "--export",
})

# A plausible script-path token starts with a word char, path separator, or
# shell expansion marker. Anything else (e.g. the "===" in
# `echo "=== sbatch ==="`) marks the match as a text mention, not a real
# submission.
_SCRIPT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_~$./]")

# Shell redirection tokens ("2>&1", "2>/dev/null", ">out") are never scripts.
_REDIRECT_TOKEN_RE = re.compile(r"^\d*>{1,2}")

# --wrap submissions carry their payload inline; there is no script path.
_WRAP_RE = re.compile(r"--wrap(?:=|\s+)([\"']?)([^\s\"']*)")

# A submission whose payload launches the simulation is sim-class.
_RUN_CONTENT_RE = re.compile(r"\b(srun|mpirun|mpiexec)\b|entity\.xc")

POLL_PATTERNS: Sequence[Tuple[str, "re.Pattern[str]"]] = (
    ("squeue", re.compile(r"\bsqueue\b")),
    ("sacct", re.compile(r"\bsacct\b")),
    ("scontrol", re.compile(r"\bscontrol\b")),
)


def compile_rules(rules: Optional[Sequence[Mapping[str, str]]]) -> List[Tuple[str, "re.Pattern[str]"]]:
    """Compile a rule table into ordered (category, pattern) pairs.

    ``rules`` is a list of {"category": name, "pattern": regex} objects;
    when None the built-in DEFAULT_RULES table is used. The first matching
    rule wins during classification.
    """
    table: Sequence[Tuple[str, str]]
    if rules is None:
        table = DEFAULT_RULES
    else:
        table = []
        for index, rule in enumerate(rules):
            category = str(rule.get("category") or "")
            pattern = str(rule.get("pattern") or "")
            if category not in CATEGORIES:
                raise TraceError(
                    "rules entry %d has unknown category %r (expected one of %s)"
                    % (index, category, ", ".join(CATEGORIES))
                )
            if not pattern:
                raise TraceError("rules entry %d has an empty pattern" % index)
            table.append((category, pattern))
    compiled: List[Tuple[str, "re.Pattern[str]"]] = []
    for category, pattern in table:
        try:
            compiled.append((category, re.compile(pattern)))
        except re.error as exc:
            raise TraceError("rule for category %r is invalid regex: %s" % (category, exc)) from exc
    return compiled


def parse_sbatch(command: str) -> List[Dict[str, Any]]:
    """Extract every sbatch submission from a Bash command string.

    Each submission gets a job_name (from --job-name/-J, else the script
    path basename, else "unknown" for heredocs/stdin) and a job_class:
    "build" when the name mentions build/rebuild/kk/deps/compile or the
    submitted text invokes cmake/make/nvcc/ninja, else "sim".
    """
    matches = list(SBATCH_RE.finditer(command))
    submissions: List[Dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(command)
        segment = command[match.end():end]
        name: Optional[str] = None
        job_name = _JOB_NAME_RE.search(segment)
        if job_name:
            name = job_name.group(1)
        script: Optional[str] = None
        heredoc = False
        wrap = _WRAP_RE.search(segment)
        if name is None and wrap:
            first = wrap.group(2) or "wrap"
            name = f"wrap:{first[:32]}"
        if name is None:
            tokens = segment.replace("<<", " << ").split()
            skip_next = False
            for token in tokens:
                if skip_next:
                    skip_next = False
                    continue
                if token == "<<":
                    heredoc = True  # submission via stdin: real, but nameless
                    break
                if token in _FLAGS_WITH_ARG:
                    skip_next = True
                    continue
                if token.startswith("-") or _REDIRECT_TOKEN_RE.match(token):
                    continue
                candidate = token.strip("\"'").rstrip(";")
                if not _SCRIPT_TOKEN_RE.match(candidate):
                    break  # text mention ("echo '=== sbatch ==='"), not a submission
                script = candidate
                break
        if name is None and script is None and not heredoc:
            continue  # no script path, no --job-name, no stdin: not a real submission
        label = name or (PurePosixPath(script).name if script else "unknown")
        # A submission that launches the simulation (srun/mpirun/entity.xc) is
        # sim-class even when the script body also mentions build tools
        # (e.g. "module load cmake" in a --wrap payload).
        job_class = (
            "sim"
            if _RUN_CONTENT_RE.search(segment)
            else "build"
            if BUILD_NAME_RE.search(label) or BUILD_CONTENT_RE.search(segment)
            else "sim"
        )
        submissions.append({"job_name": label, "job_class": job_class})
    return submissions


def _classify_call(
    name: Any,
    tool_input: Any,
    compiled: Sequence[Tuple[str, "re.Pattern[str]"]],
) -> Optional[str]:
    """Classify one tool_use into a category.

    Returns None for installed-skill doc reads (counted separately, never
    in a category). Bash commands containing sbatch are classified by the
    parsed submissions; everything else goes through the rule table.
    """
    text = match_text(name, tool_input)
    if SKILL_DOC_RE.search(text):
        return None
    if isinstance(tool_input, Mapping):
        command = tool_input.get("command")
        if isinstance(command, str) and SBATCH_RE.search(command):
            submissions = parse_sbatch(command)
            if any(s["job_class"] == "build" for s in submissions):
                return "build"
            return "job-submit"
    for category, pattern in compiled:
        if pattern.search(text):
            return category
    return "other"


def _empty_bucket() -> Dict[str, Any]:
    return {
        "records": 0,
        "tool_calls": 0,
        "started_at": None,
        "ended_at": None,
        "wall_time_ms": 0,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


def _bucket_add(bucket: Dict[str, Any], *, timestamp_raw: Optional[str],
                usage: Mapping[str, int], calls: int) -> None:
    bucket["records"] += 1
    timestamp = _parse_time(timestamp_raw)
    if timestamp is not None:
        if bucket["started_at"] is None:
            bucket["started_at"] = timestamp_raw
            bucket["_start"] = timestamp
        bucket["ended_at"] = timestamp_raw
        bucket["_end"] = timestamp
    for key in bucket["usage"]:
        bucket["usage"][key] += int(usage.get(key) or 0)
    bucket["tool_calls"] += calls


def _finalize_bucket(name: str, bucket: Dict[str, Any]) -> Dict[str, Any]:
    start = bucket.pop("_start", None)
    end = bucket.pop("_end", None)
    if start is not None and end is not None:
        bucket["wall_time_ms"] = max(0, int((end - start).total_seconds() * 1000))
    return {"name": name, **bucket}


def analyze_transcript(
    transcript_path: Path,
    *,
    rules: Optional[Sequence[Mapping[str, str]]] = None,
) -> Dict[str, Any]:
    """Tag a Claude Code transcript with activity categories.

    Returns the activities report as a dict. Records whose timestamps are
    missing still contribute token/tool counts but not wall-clock bounds.
    """
    path = transcript_path.expanduser().resolve()
    raw = path.read_bytes()
    compiled = compile_rules(rules)

    buckets: Dict[str, Dict[str, Any]] = {name: _empty_bucket() for name in CATEGORIES}
    session_id = ""
    adoption_calls: List[Dict[str, Any]] = []
    skill_doc_reads = 0
    total_tool_calls = 0
    total_records = 0
    totals_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    submissions: List[Dict[str, Any]] = []
    polls: Dict[str, int] = {name: 0 for name, _ in POLL_PATTERNS}

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
        timestamp_raw = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
        total_records += 1
        for key in totals_usage:
            totals_usage[key] += usage[key]

        # category -> number of this record's tool calls in that category
        touched: Dict[str, int] = {}
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "tool_use":
                    continue
                total_tool_calls += 1
                name = item.get("name")
                tool_input = item.get("input")
                adoption_calls.append({"name": name, "input": tool_input})
                category = _classify_call(name, tool_input, compiled)
                if category is None:
                    skill_doc_reads += 1
                    continue
                touched[category] = touched.get(category, 0) + 1
                if isinstance(tool_input, Mapping):
                    command = tool_input.get("command")
                    if isinstance(command, str):
                        for submission in parse_sbatch(command):
                            submissions.append({**submission, "timestamp": timestamp_raw})
                        for poll_name, pattern in POLL_PATTERNS:
                            polls[poll_name] += len(pattern.findall(command))

        for category, calls in touched.items():
            _bucket_add(buckets[category], timestamp_raw=timestamp_raw, usage=usage, calls=calls)

    categories = [_finalize_bucket(name, buckets[name]) for name in CATEGORIES]

    # Job lifecycle: group submissions by job name, preserving order.
    jobs: Dict[str, Dict[str, Any]] = {}
    for submission in submissions:
        entry = jobs.setdefault(submission["job_name"], {
            "job_class": submission["job_class"],
            "submissions": [],
            # Terminal-state verification (sacct at the eval site) fills
            # this in; this module never sshes out.
            "first_success_attempt": None,
        })
        if submission["job_class"] == "build":
            entry["job_class"] = "build"
        entry["submissions"].append({
            "timestamp": submission["timestamp"],
            "job_class": submission["job_class"],
        })
    job_lifecycle = {
        "submissions_total": len(submissions),
        "build_submissions": sum(1 for s in submissions if s["job_class"] == "build"),
        "sim_submissions": sum(1 for s in submissions if s["job_class"] == "sim"),
        "jobs": jobs,
        "polls": polls,
    }

    classified_calls = total_tool_calls - skill_doc_reads
    other_calls = buckets["other"]["tool_calls"]
    unclassified_share = (other_calls / classified_calls) if classified_calls else 0.0

    notes = [
        "record-level attribution is multi-label: a record's tokens/time count "
        "toward every category its tool calls touch, so category usage sums may "
        "exceed totals",
        "unclassified_tool_share = 'other' tool calls / classified tool calls "
        "(skill-doc reads excluded); informational only, never a pass/fail gate",
        "job_lifecycle.first_success_attempt is filled by eval-side sacct "
        "verification; this module never contacts the cluster",
    ]

    return {
        "schema_version": 1,
        "source": {
            "transcript_sha256": sha256_bytes(raw),
            "transcript_path": str(path),
            "session_id": session_id or path.stem,
        },
        "category_order": list(CATEGORIES),
        "categories": categories,
        "totals": {
            "records": total_records,
            "tool_calls": total_tool_calls,
            "usage": totals_usage,
        },
        "unclassified_tool_share": round(unclassified_share, 6),
        "skill_doc_reads": skill_doc_reads,
        "job_lifecycle": job_lifecycle,
        "skill_adoption": summarize_skill_adoption(adoption_calls),
        "notes": notes,
    }


def write_activities_report(
    run_dir: Path,
    *,
    transcript_path: Path,
    rules: Optional[Sequence[Mapping[str, str]]] = None,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build the activities report and write it into the run directory."""
    manifest = load_manifest(run_dir)
    report = analyze_transcript(transcript_path, rules=rules)
    target = (output_path or run_paths(run_dir)["root"] / "activities.json").expanduser().resolve()
    _assert_write_root_safe(target, manifest["capture"]["protected_roots"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report["written_to"] = str(target)
    return report
