#!/usr/bin/env bash
# Start one evaluation round: create the run directory, register the trace,
# then launch the agent under test.
#
# Usage:
#   run_round.sh [--interactive] <skills-v5|skills-no-router> <run-name> [model]
#
# Default (headless): launches `claude -p` in this terminal, capturing
# stream-json to transcript.jsonl.
# --interactive: setup only, then prints the command to paste in another
# window so you can watch the agent live in the Claude Code TUI. The TUI
# session transcript (~/.claude/projects/) is picked up by finish_round.sh.
#
# Example:
#   run_round.sh skills-v5 2026-07-21-S1 claude-sonnet-4-5
#   run_round.sh --interactive skills-no-router 2026-07-22-Snr1
set -euo pipefail

INTERACTIVE=0
if [[ "${1:-}" == "--interactive" || "${1:-}" == "-i" ]]; then
  INTERACTIVE=1
  shift
fi

VARIANT="${1:?usage: run_round.sh [--interactive] <skills-v5|skills-no-router> <run-name> [model]}"
RUN_NAME="${2:?usage: run_round.sh [--interactive] <skills-v5|skills-no-router> <run-name> [model]}"
MODEL="${3:-unspecified}"

if [[ "$VARIANT" != "skills-v5" && "$VARIANT" != "skills-no-router" ]]; then
  echo "error: variant must be skills-v5 or skills-no-router (got '$VARIANT')" >&2
  exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURES="$REPO/evals/e2e-streaming-official"
OBS="$REPO/tools/skill_observability/skill_observer.py"
RUN="$HOME/entity-eval-runs/$RUN_NAME"
# Harness state (trace home, run_dir.txt, headless transcript) lives OUTSIDE
# the agent's reach: nothing under $RUN may reference the eval repo or the
# trace, or the agent will follow the signposts (observed in round S2).
HARNESS="$HOME/entity-eval-traces/$RUN_NAME"

# Variant semantics (the eval's independent variable is entity-ledger only):
#   skills-v5        full bundle: entity-ledger + env-build + pgen + nt2py
#   skills-no-router env-build + pgen + nt2py installed, entity-ledger absent
# Skills are managed globally (~/.claude/skills) by the maintainer, never by
# this script — but the variant is NOT a mere label: the projection state is
# verified here so a mislabeled round fails fast instead of silently measuring
# the wrong configuration.
SKILLS_DIR="$HOME/.claude/skills"
for s in entity-env-build entity-pgen entity-nt2py; do
  if [[ ! -e "$SKILLS_DIR/$s" ]]; then
    echo "error: $SKILLS_DIR/$s is missing; both variants require it" >&2
    exit 1
  fi
done
if [[ "$VARIANT" == "skills-v5" && ! -e "$SKILLS_DIR/entity-ledger" ]]; then
  echo "error: skills-v5 round but $SKILLS_DIR/entity-ledger is missing" >&2
  exit 1
fi
if [[ "$VARIANT" == "skills-no-router" && -e "$SKILLS_DIR/entity-ledger" ]]; then
  echo "error: skills-no-router round but $SKILLS_DIR/entity-ledger is present;" >&2
  echo "       move it away temporarily (maintainer manages skill projections)" >&2
  exit 1
fi

# Pre-flight contamination checks: the agent can see ~/entity-eval-runs, so it
# must be empty except this round's directory (S2 showed agents follow
# leftover signposts).
if [[ -d "$HOME/entity-eval-runs" ]]; then
  LEFTOVER="$(ls -A "$HOME/entity-eval-runs" | grep -vx "$RUN_NAME" || true)"
  if [[ -n "$LEFTOVER" ]]; then
    echo "error: ~/entity-eval-runs is not empty; previous rounds must be archived first:" >&2
    ls -la "$HOME/entity-eval-runs" >&2
    exit 1
  fi
fi
# Stale TUI session transcripts from earlier rounds (readable in principle):
# warn but do not block.
STALE_SESSIONS="$(find "$HOME/.claude/projects" -maxdepth 1 -type d \
  -name '*entity-eval-runs*' ! -newermt "$(date +%Y-%m-%d) 00:00" 2>/dev/null || true)"
if [[ -n "$STALE_SESSIONS" ]]; then
  echo "warning: stale session transcripts from earlier rounds under ~/.claude/projects/:" >&2
  printf '%s\n' "$STALE_SESSIONS" >&2
  echo "         consider removing them (see RUNBOOK.md)" >&2
fi

mkdir -p "$RUN/project" "$HARNESS"
# 0.7.0 note: no controller home is pre-seeded — the task requires the agent
# to create and adopt its own workspace inside the project directory.
cp "$FIXTURES/physics-spec.json" "$FIXTURES/task.md" \
   "$FIXTURES/fixtures/submission.schema.json" "$RUN/project/"

hash_of() { shasum -a 256 "$1" 2>/dev/null | cut -d' ' -f1 || true; }
AGENT_CONFIG_HASH="$(hash_of "$HOME/.claude/settings.json")"
TOOL_CONFIG_HASH="$(hash_of "$HOME/.claude.json")"
: "${AGENT_CONFIG_HASH:=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855}"
: "${TOOL_CONFIG_HASH:=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855}"

START_ARGS=(
  --task-id e2e-streaming-official-v1
  --input-ref evals/e2e-streaming-official/task.md
  --input-file "$FIXTURES/task.md"
  --variant "$VARIANT"
  --agent-provider claude --agent-model "$MODEL"
  --agent-configuration "$AGENT_CONFIG_HASH"
  --tool-profile claude-code-default --tool-configuration "$TOOL_CONFIG_HASH"
  --trace-home "$HARNESS"
)

cd "$REPO"
START_OUT="$(python3 "$OBS" start "${START_ARGS[@]}")"
echo "$START_OUT"
RUN_DIR="$(printf '%s' "$START_OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_dir"])')"
echo "$RUN_DIR" > "$HARNESS/run_dir.txt"

echo
echo "==> trace registered: $RUN_DIR"

# Version anchoring (S rounds only): record the installed entity-ledger bundle
# facts from `entityctl doctor` output (always JSON; doctor exit 2 on warnings
# still emits the payload). Read-only — the bundle is managed by the
# maintainer, never installed by this script.
if [[ "$VARIANT" == "skills-v5" ]]; then
  DOCTOR_OUT="$(python3 "$REPO/skills/entity-ledger/scripts/entityctl.py" doctor 2>/dev/null || true)"
  if printf '%s' "$DOCTOR_OUT" | python3 -c '
import json, sys
doc = json.load(sys.stdin)
rb = doc.get("runtime_bundle", {})
print(json.dumps({"bundle_version": rb.get("version") or "unknown",
                  "bundle_hash": rb.get("bundle_hash") or ""}, indent=2))
' > "$HARNESS/bundle.json" 2>/dev/null; then
    echo "==> bundle facts: $HARNESS/bundle.json"
  else
    echo '{"bundle_version":"unknown"}' > "$HARNESS/bundle.json"
    echo "warning: entityctl doctor failed; recorded bundle_version=unknown" >&2
  fi
fi

if [[ $INTERACTIVE -eq 1 ]]; then
  ENV_LINE=""
  cat <<EOF

==> interactive mode: open a NEW terminal window and run:

    cd '$RUN/project'
    $ENV_LINE
    claude

  task.md and physics-spec.json are already in that directory.
  Give the agent a first message like:

    Read task.md and physics-spec.json in this directory and complete the task.

  You can watch the agent live in the TUI. When it finishes, come back and run:

    bash $FIXTURES/finish_round.sh $RUN_NAME [completed|failed]

  finish_round.sh will auto-locate the TUI session transcript under
  ~/.claude/projects/ (override with: finish_round.sh $RUN_NAME <status> <transcript-path>).
EOF
  exit 0
fi

echo "==> launching agent in $RUN/project (transcript -> $HARNESS/transcript.jsonl)"

cd "$RUN/project"

CLAUDE_ARGS=(-p "$(cat "$FIXTURES/task.md")" --output-format stream-json --verbose)
if [[ "$MODEL" != "unspecified" ]]; then
  CLAUDE_ARGS+=(--model "$MODEL")
fi
claude "${CLAUDE_ARGS[@]}" > "$HARNESS/transcript.jsonl"

echo
echo "==> agent finished. Next: finish_round.sh $RUN_NAME [completed|failed]"
