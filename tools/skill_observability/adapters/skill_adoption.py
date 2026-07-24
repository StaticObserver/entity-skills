"""Shared skill-adoption accounting for transcript adapters.

Both the phase segmentation (claude_phases) and the activity tagging
(claude_activities) adapters report how much of the observed work went
through skill scripts versus raw equivalent commands. The rule table and
the summary-shape logic live here so the two reports stay consistent.

Attribution model (deterministic):

- Each tool_use item is reduced to "<tool name> <tool targets>" where
  targets are command lines and file paths only (never free-form content).
- Tool targets under an installed skill directory (SKILL_DOC_RE) are
  orientation reads and are skipped entirely.
- Each remaining tool_use counts in at most ONE adoption category: the
  first matching rule in ADOPTION_RULES wins, so ``entityctl record`` is
  skill.ledger only and ``entity-build.sh`` is skill.env_build only.

Stdlib only, consistent with the rest of this package.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

# Skill adoption rule table. Ordered (category, regex) pairs matched
# against "<tool name> <tool targets>"; the first match wins.
ADOPTION_RULES: Sequence[Tuple[str, str]] = (
    ("control_plane_surgery", r"\bsqlite3?\b"),
    ("skill.ledger", r"\bentityctl\b"),
    ("skill.env_build", r"entity[-_]checkpoint|entity[-_]compat|entity-build\.sh"),
    ("skill.pgen", r"pgen_preflight"),
    ("skill.nt2py", r"\bnt2\b|nt2\.Data|inspect_nt2_data"),
    ("raw.sbatch", r"\bsbatch\b"),
    ("raw.srun", r"\bsrun\b"),
    ("raw.scancel", r"\bscancel\b"),
    ("raw.scheduler_poll", r"\b(squeue|sacct|scontrol)\b"),
    ("raw.build", r"\b(cmake|make|nvcc|spack)\b"),
)

COMPILED_ADOPTION_RULES: List[Tuple[str, "re.Pattern[str]"]] = [
    (category, re.compile(pattern)) for category, pattern in ADOPTION_RULES
]

# Tool targets under an installed skill directory are orientation (reading
# SKILL.md/references), never skill adoption.
SKILL_DOC_RE = re.compile(r"/\.claude/skills/")

# Fields whose *values* rule patterns are matched against. Deliberately only
# tool targets (command line, file paths, search patterns) — never free-form
# content such as Write/Edit file bodies or subagent prompts.
MATCH_FIELDS = ("command", "file_path", "path", "pattern", "notebook_path")

SKILL_CALL_KINDS = ("ledger", "env_build", "pgen", "nt2py")
RAW_CALL_KINDS = ("sbatch", "srun", "scancel", "scheduler_poll", "build")


def serialize_input(value: Any) -> str:
    """Build the match text for a tool input from target fields only."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts = [str(value[key]) for key in MATCH_FIELDS if key in value]
        return " ".join(parts)
    return ""


def match_text(name: Any, tool_input: Any) -> str:
    """Build the "<tool name> <tool targets>" text rules match against."""
    return "%s %s" % (name or "", serialize_input(tool_input))


def is_skill_doc(text: str) -> bool:
    """True when the match text points into an installed skill directory."""
    return bool(SKILL_DOC_RE.search(text))


def count_adoption(calls: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """Count tool calls against ADOPTION_RULES.

    ``calls`` is an iterable of {"name": ..., "input": ...} mappings.
    Returns one counter per rule-table category; skill-doc reads are
    skipped, and each call counts in at most one category.

    The skill-doc skip only applies to read-type tools: a *Bash command*
    that references an installed skill path is executing the script
    (``python3 ~/.claude/skills/entity-ledger/scripts/entityctl.py ...``),
    which is exactly the adoption we want to count.
    """
    counts: Dict[str, int] = {category: 0 for category, _ in COMPILED_ADOPTION_RULES}
    for call in calls:
        text = match_text(call.get("name"), call.get("input"))
        if call.get("name") != "Bash" and is_skill_doc(text):
            continue  # reading installed skill docs is orientation
        for category, pattern in COMPILED_ADOPTION_RULES:
            if pattern.search(text):
                counts[category] += 1
                break
    return counts


def summarize_skill_adoption(calls: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build the skill_adoption report section for a list of tool calls.

    ``calls`` is an iterable of {"name": ..., "input": ...} mappings. The
    returned dict is shared by phases.json and activities.json:

    - skill_calls: per-skill script invocations plus total;
    - raw_calls: raw equivalent commands (sbatch/srun/scancel/scheduler
      polls/build tools) plus total;
    - control_plane_surgery_calls: direct sqlite writes to the control
      plane, counted separately from both sides;
    - skill_call_share: skill / (skill + raw), None when both are zero.
    """
    counts = count_adoption(calls)
    skill_calls = {name: counts["skill." + name] for name in SKILL_CALL_KINDS}
    skill_calls["total"] = sum(skill_calls.values())
    raw_calls = {name: counts["raw." + name] for name in RAW_CALL_KINDS}
    raw_calls["total"] = sum(raw_calls.values())
    skill_total = skill_calls["total"]
    raw_total = raw_calls["total"]
    return {
        "skill_calls": skill_calls,
        "raw_calls": raw_calls,
        "control_plane_surgery_calls": counts["control_plane_surgery"],
        "skill_call_share": (
            round(skill_total / (skill_total + raw_total), 6)
            if skill_total + raw_total > 0
            else None
        ),
    }
