#!/usr/bin/env bash
# Start one evaluation round: create the run directory, register the trace,
# then launch the agent under test.
#
# Usage:
#   run_round.sh [--interactive] <skills-v5|no-entity-skills> <run-name> [model]
#
# Default (headless): launches `claude -p` in this terminal, capturing
# stream-json to transcript.jsonl.
# --interactive: setup only, then prints the command to paste in another
# window so you can watch the agent live in the Claude Code TUI. The TUI
# session transcript (~/.claude/projects/) is picked up by finish_round.sh.
#
# Example:
#   run_round.sh skills-v5 2026-07-21-S1 claude-sonnet-4-5
#   run_round.sh --interactive skills-v5 2026-07-21-S2
set -euo pipefail

INTERACTIVE=0
if [[ "${1:-}" == "--interactive" || "${1:-}" == "-i" ]]; then
  INTERACTIVE=1
  shift
fi

VARIANT="${1:?usage: run_round.sh [--interactive] <skills-v5|no-entity-skills> <run-name> [model]}"
RUN_NAME="${2:?usage: run_round.sh [--interactive] <skills-v5|no-entity-skills> <run-name> [model]}"
MODEL="${3:-unspecified}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURES="$REPO/evals/e2e-neutral-streaming"
OBS="$REPO/tools/skill_observability/skill_observer.py"
RUN="$HOME/entity-eval-runs/$RUN_NAME"
# Harness state (trace home, run_dir.txt, headless transcript) lives OUTSIDE
# the agent's reach: nothing under $RUN may reference the eval repo or the
# trace, or the agent will follow the signposts (observed in round S2).
HARNESS="$HOME/entity-eval-traces/$RUN_NAME"

# Skills are managed globally (~/.claude/skills) by the maintainer, never by
# this script: S rounds run with the full bundle installed, N rounds with the
# entity-* skills removed. The variant argument is a label only; nothing here
# touches, checks, or records skill paths.

mkdir -p "$RUN/project" "$RUN/controller" "$HARNESS"
cp "$FIXTURES/physics-spec.json" "$FIXTURES/task.md" "$RUN/project/"

hash_of() { shasum -a 256 "$1" 2>/dev/null | cut -d' ' -f1 || true; }
AGENT_CONFIG_HASH="$(hash_of "$HOME/.claude/settings.json")"
TOOL_CONFIG_HASH="$(hash_of "$HOME/.claude.json")"
: "${AGENT_CONFIG_HASH:=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855}"
: "${TOOL_CONFIG_HASH:=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855}"

START_ARGS=(
  --task-id e2e-neutral-streaming-v1
  --input-ref evals/e2e-neutral-streaming/task.md
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

if [[ $INTERACTIVE -eq 1 ]]; then
  ENV_LINE=""
  if [[ "$VARIANT" == "skills-v5" ]]; then
    ENV_LINE="export ENTITY_ROUTER_HOME='$RUN/controller'"
  fi
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
if [[ "$VARIANT" == "skills-v5" ]]; then
  export ENTITY_ROUTER_HOME="$RUN/controller"
fi

CLAUDE_ARGS=(-p "$(cat "$FIXTURES/task.md")" --output-format stream-json --verbose)
if [[ "$MODEL" != "unspecified" ]]; then
  CLAUDE_ARGS+=(--model "$MODEL")
fi
claude "${CLAUDE_ARGS[@]}" > "$HARNESS/transcript.jsonl"

echo
echo "==> agent finished. Next: finish_round.sh $RUN_NAME [completed|failed]"
