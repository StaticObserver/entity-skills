#!/usr/bin/env bash
# Finish one evaluation round: import the transcript, segment phases, close
# the trace. Must run after run_round.sh. Order matters: finish is terminal,
# so import/phases always run first.
#
# Usage:
#   finish_round.sh <run-name> [completed|failed] [transcript-path]
#
# Transcript resolution order:
#   1. explicit transcript-path argument;
#   2. $RUN/transcript.jsonl (headless run_round.sh);
#   3. newest session JSONL under ~/.claude/projects/ for the run's project
#      directory (interactive TUI run).
set -euo pipefail

RUN_NAME="${1:?usage: finish_round.sh <run-name> [completed|failed] [transcript-path]}"
STATUS="${2:-completed}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OBS="$REPO/tools/skill_observability/skill_observer.py"
RUN="$HOME/entity-eval-runs/$RUN_NAME"
HARNESS="$HOME/entity-eval-traces/$RUN_NAME"
RUN_DIR="$(cat "$HARNESS/run_dir.txt")"

TRANSCRIPT="${3:-}"
if [[ -z "$TRANSCRIPT" && -s "$HARNESS/transcript.jsonl" ]]; then
  TRANSCRIPT="$HARNESS/transcript.jsonl"
fi
if [[ -z "$TRANSCRIPT" ]]; then
  SLUG="$(echo "$RUN/project" | sed 's|/|-|g')"
  SESSIONS_DIR="$HOME/.claude/projects/$SLUG"
  TRANSCRIPT="$(ls -t "$SESSIONS_DIR"/*.jsonl 2>/dev/null | head -1 || true)"
fi
[[ -n "$TRANSCRIPT" && -s "$TRANSCRIPT" ]] || {
  echo "error: no transcript found for $RUN_NAME" >&2
  echo "       looked at: $HARNESS/transcript.jsonl and ~/.claude/projects/<project-slug>/" >&2
  exit 1
}
echo "==> transcript: $TRANSCRIPT"

cd "$REPO"

IMPORT_OUT="$(python3 "$OBS" import-claude --run-dir "$RUN_DIR" --transcript "$TRANSCRIPT")"
echo "$IMPORT_OUT"

# Phases writes <run_dir>/phases.json; exit 1 means unclassified share > 10%.
set +e
python3 "$OBS" phases --run-dir "$RUN_DIR" --transcript "$TRANSCRIPT"
PHASES_RC=$?
set -e
if [[ $PHASES_RC -ne 0 ]]; then
  echo "warning: phases reports comparable=false (unclassified > 10%);" >&2
  echo "         inspect $RUN_DIR/phases.json before trusting comparisons" >&2
fi

read INPUT_TOKENS OUTPUT_TOKENS <<< "$(printf '%s' "$IMPORT_OUT" | python3 -c '
import json, sys
u = json.load(sys.stdin)["usage"]
print(u.get("input_tokens") or 0, u.get("output_tokens") or 0)
')"
WALL_MS="$(python3 -c '
import json, sys
print(json.load(open(sys.argv[1]))["totals"]["wall_time_ms"])
' "$RUN_DIR/phases.json")"

python3 "$OBS" finish --run-dir "$RUN_DIR" --status "$STATUS" \
  --input-tokens "$INPUT_TOKENS" --output-tokens "$OUTPUT_TOKENS" \
  --wall-time-ms "$WALL_MS"

echo
echo "==> round closed: $RUN_DIR"
echo "==> phases:  $RUN_DIR/phases.json"
echo "==> remember to clean remote artifacts on siyuan for this round"
