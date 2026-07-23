#!/usr/bin/env bash
# Launch one user-needs scenario: reuse run_round.sh for environment + trace
# setup, lay the scenario fixtures, then launch the agent on the scenario's
# natural-language prompt.
#
# Usage:
#   run_need.sh [--followup] <need-id> <skills-v5|skills-no-router> <run-name> [model] [-- <setup args>]
#
# Stage 1 (default): environment setup + agent launched with needs/<id>/prompt.md.
# --followup: for two-stage needs (prompt-followup.md exists), continue the
# same session with the follow-up user message AFTER the operator performed
# the out-of-band action described in needs/<id>/README.md (scancel for U3,
# kill+restart for U4, tamper for U5).
#
# needs/<id>/setup.sh receives RUN/HARNESS/VARIANT/REPO in the environment
# plus any args after `--`; it may render a final prompt at $RUN/prompt.rendered.md.
set -euo pipefail

FOLLOWUP=0
if [[ "${1:-}" == "--followup" ]]; then
  FOLLOWUP=1
  shift
fi

NEED_ID="${1:?usage: run_need.sh [--followup] <need-id> <skills-v5|skills-no-router> <run-name> [model] [-- <setup args>]}"
VARIANT="${2:?usage: run_need.sh [--followup] <need-id> <skills-v5|skills-no-router> <run-name> [model] [-- <setup args>]}"
RUN_NAME="${3:?usage: run_need.sh [--followup] <need-id> <skills-v5|skills-no-router> <run-name> [model] [-- <setup args>]}"
MODEL="${4:-unspecified}"
# `run_need.sh U6 <variant> <run> -- <setup args>` puts "--" in $4.
if [[ "$MODEL" == "--" || -z "$MODEL" ]]; then
  MODEL="unspecified"
fi
shift 4 || shift $#
[[ "${1:-}" == "--" ]] && shift
SETUP_ARGS=("$@")

SUITE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SUITE/../.." && pwd)"
NEED_DIR="$SUITE/needs/$NEED_ID"
if [[ ! -d "$NEED_DIR" ]]; then
  # allow short ids: U1 -> needs/U1-*
  CANDIDATE="$(find "$SUITE/needs" -maxdepth 1 -type d -name "$NEED_ID-*" | head -1 || true)"
  [[ -n "$CANDIDATE" ]] || { echo "error: unknown need '$NEED_ID' (looked for needs/$NEED_ID and needs/$NEED_ID-*)" >&2; exit 1; }
  NEED_DIR="$CANDIDATE"
fi

RUN="$HOME/entity-eval-runs/$RUN_NAME"
HARNESS="$HOME/entity-eval-traces/$RUN_NAME"

if [[ $FOLLOWUP -eq 0 ]]; then
  # Environment + trace registration via the e2e harness (interactive mode:
  # setup only, no agent launch). Its hardcoded fixture copy (task.md,
  # physics-spec.json, submission.schema.json) is harmless for every need;
  # scenario-specific fixtures are laid by setup.sh below.
  bash "$REPO/evals/e2e-neutral-streaming/run_round.sh" --interactive \
    "$VARIANT" "$RUN_NAME" "$MODEL"

  export RUN HARNESS VARIANT REPO NEED_DIR
  bash "$NEED_DIR/setup.sh" ${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}

  PROMPT="$RUN/prompt.rendered.md"
  [[ -s "$PROMPT" ]] || PROMPT="$NEED_DIR/prompt.md"
else
  PROMPT="$NEED_DIR/prompt-followup.md"
  [[ -s "$PROMPT" ]] || { echo "error: need '$NEED_ID' has no prompt-followup.md" >&2; exit 1; }
  [[ -d "$RUN/project" ]] || { echo "error: no stage-1 run at $RUN (run stage 1 first)" >&2; exit 1; }
  echo "==> follow-up stage: continuing the session in $RUN/project"
  echo "    (the out-of-band action in $NEED_DIR/README.md must be done BEFORE this)"
fi

echo "==> prompt: $PROMPT"
echo "==> launching agent in $RUN/project (transcript -> $HARNESS/transcript.jsonl)"

cd "$RUN/project"
if [[ "$VARIANT" == "skills-v5" ]]; then
  export ENTITY_ROUTER_HOME="$RUN/controller"
fi

CLAUDE_ARGS=(-p "$(cat "$PROMPT")" --output-format stream-json --verbose)
if [[ $FOLLOWUP -eq 1 ]]; then
  CLAUDE_ARGS+=(-c)  # continue the stage-1 session in this directory
fi
if [[ "$MODEL" != "unspecified" ]]; then
  CLAUDE_ARGS+=(--model "$MODEL")
fi
claude "${CLAUDE_ARGS[@]}" >> "$HARNESS/transcript.jsonl"

echo
echo "==> agent finished. Next: grade_need.sh $NEED_ID $RUN_NAME"
