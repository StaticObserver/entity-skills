#!/usr/bin/env bash
# Grade one user-needs run: close the trace, derive activities, run the
# need-level verify.py, write need-report.json.
#
# Usage:
#   grade_need.sh <need-id> <run-name> [--offline <evidence-dir>]
#   grade_need.sh U5 <run-name> --tamper      # stage-1.5 helper, see needs/U5/README.md
#
# Live mode: finish_round.sh (idempotent) -> skill_observer activities ->
# needs/<id>/verify.py -> $HARNESS/need-report.json.
#
# Offline mode: grades retained evidence without touching it. The observer
# run_dir is copied to a scratch dir before `activities` runs (that subcommand
# appends events/artifacts to the run_dir), and the report goes to
# <evidence>/need-report-<need-id>.json (a new file; oracle-report.json,
# submission.json and friends are never overwritten).
set -euo pipefail

NEED_ID="${1:?usage: grade_need.sh <need-id> <run-name> [--offline <evidence-dir>] [--tamper]}"
RUN_NAME="${2:?usage: grade_need.sh <need-id> <run-name> [--offline <evidence-dir>] [--tamper]}"
shift 2

OFFLINE=0
EVIDENCE=""
TAMPER=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline) OFFLINE=1; EVIDENCE="${2:?--offline needs a directory}"; shift 2 ;;
    --tamper) TAMPER=1; shift ;;
    *) echo "error: unknown argument: $1" >&2; exit 1 ;;
  esac
done

SUITE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SUITE/../.." && pwd)"
OBS="$REPO/tools/skill_observability/skill_observer.py"
NEED_DIR="$SUITE/needs/$NEED_ID"
if [[ ! -d "$NEED_DIR" ]]; then
  CANDIDATE="$(find "$SUITE/needs" -maxdepth 1 -type d -name "$NEED_ID-*" | head -1 || true)"
  [[ -n "$CANDIDATE" ]] || { echo "error: unknown need '$NEED_ID'" >&2; exit 1; }
  NEED_DIR="$CANDIDATE"
fi

RUN="$HOME/entity-eval-runs/$RUN_NAME"
HARNESS="$HOME/entity-eval-traces/$RUN_NAME"

# --tamper: U5 stage between prompt.md and prompt-followup.md. Modify one
# delivered artifact IN THE AGENT'S PROJECT (never the retained evidence),
# record what was touched for the verify step.
if [[ $TAMPER -eq 1 ]]; then
  TARGET=""
  for candidate in "$RUN/project/analysis/report.md" "$RUN/project/input.toml"; do
    [[ -f "$candidate" ]] && TARGET="$candidate" && break
  done
  [[ -n "$TARGET" ]] || { echo "error: no delivered artifact found to tamper under $RUN/project" >&2; exit 1; }
  printf '\n(tampered by grade_need.sh at %s)\n' "$(date -u +%FT%TZ)" >> "$TARGET"
  echo "$TARGET" > "$HARNESS/tampered.txt"
  echo "==> tampered: $TARGET (recorded in $HARNESS/tampered.txt)"
  echo "    next: run_need.sh --followup U5 $RUN_NAME  -> then grade_need.sh U5 $RUN_NAME"
  exit 0
fi

VERIFY_ARGS=(--run-name "$RUN_NAME")

if [[ $OFFLINE -eq 1 ]]; then
  EVIDENCE="$(cd "$EVIDENCE" && pwd)"
  REPORT="$EVIDENCE/need-report-$NEED_ID.json"
  for protected in oracle-report.json submission.json run_dir.txt; do
    [[ "$REPORT" != "$EVIDENCE/$protected" ]] || { echo "error: report path would overwrite $protected" >&2; exit 1; }
  done
  # Transcript: evidence copy first, then the TUI session slug of the run.
  TRANSCRIPT=""
  for candidate in "$EVIDENCE/transcript.jsonl" "$EVIDENCE/session-transcript.jsonl"; do
    [[ -s "$candidate" ]] && TRANSCRIPT="$candidate" && break
  done
  if [[ -z "$TRANSCRIPT" && -d "$RUN/project" ]]; then
    SLUG="$(echo "$RUN/project" | sed 's|/|-|g')"
    TRANSCRIPT="$(ls -t "$HOME/.claude/projects/$SLUG"/*.jsonl 2>/dev/null | head -1 || true)"
  fi
  [[ -n "$TRANSCRIPT" ]] && VERIFY_ARGS+=(--transcript "$TRANSCRIPT")

  # activities on a SCRATCH COPY of the run_dir. Call the adapter directly
  # (not the CLI): the CLI also appends an event, which a) pollutes and
  # b) is rejected on already-finished (terminal) rounds.
  if [[ -f "$EVIDENCE/run_dir.txt" ]]; then
    SRC_RUN_DIR="$(cat "$EVIDENCE/run_dir.txt")"
    if [[ -d "$SRC_RUN_DIR" ]]; then
      SCRATCH="$(mktemp -d /tmp/need-grade-XXXXXX)"
      cp -R "$SRC_RUN_DIR" "$SCRATCH/run-dir"
      if [[ -n "$TRANSCRIPT" ]]; then
        REPO_TOOLS="$REPO/tools" python3 - "$SCRATCH/run-dir" "$TRANSCRIPT" <<'PY' >/dev/null \
          && echo "==> activities: $SCRATCH/run-dir/activities.json (scratch copy)" \
          || echo "warning: activities failed on scratch run_dir" >&2
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["REPO_TOOLS"])
from skill_observability.adapters.claude_activities import write_activities_report

write_activities_report(Path(sys.argv[1]), transcript_path=Path(sys.argv[2]))
PY
      fi
      VERIFY_ARGS+=(--trace-run-dir "$SCRATCH/run-dir")
    fi
  fi
  VERIFY_ARGS+=(--offline --evidence "$EVIDENCE" --output "$REPORT")
else
  REPORT="$HARNESS/need-report.json"
  bash "$REPO/evals/e2e-neutral-streaming/finish_round.sh" "$RUN_NAME" completed

  RUN_DIR="$(cat "$HARNESS/run_dir.txt")"
  TRANSCRIPT="$HARNESS/transcript.jsonl"
  if [[ ! -s "$TRANSCRIPT" ]]; then
    SLUG="$(echo "$RUN/project" | sed 's|/|-|g')"
    TRANSCRIPT="$(ls -t "$HOME/.claude/projects/$SLUG"/*.jsonl 2>/dev/null | head -1 || true)"
  fi
  [[ -n "$TRANSCRIPT" && -s "$TRANSCRIPT" ]] || { echo "error: no transcript found for $RUN_NAME" >&2; exit 1; }

  # finish_round.sh already derives activities.json before closing the trace;
  # re-running the subcommand here would fail (closed runs reject new events).
  if [[ ! -s "$RUN_DIR/activities.json" ]]; then
    python3 "$OBS" activities --run-dir "$RUN_DIR" --transcript "$TRANSCRIPT"
  fi

  # Oracle with remote verification (rsync data + sacct). Tolerate failure —
  # aborted rounds may have no submission.json, in which case verify.py falls
  # back to a local-only oracle pass.
  python3 "$REPO/evals/e2e-neutral-streaming/oracle/oracle.py" \
    --project "$RUN/project" --transcript "$TRANSCRIPT" \
    --fetch "$HARNESS/oracle-data" >/dev/null 2>&1 || true
  VERIFY_ARGS+=(--trace-run-dir "$RUN_DIR" --transcript "$TRANSCRIPT" --output "$REPORT")
fi

python3 "$NEED_DIR/verify.py" "${VERIFY_ARGS[@]}"
