#!/usr/bin/env bash
# Pull remote Slurm scripts/logs into the harness, then delete the remote
# artifacts of one evaluation round. Deletion is DRY-RUN by default; pass
# -f/--yes to actually remove.
#
# Usage:
#   clean_remote.sh <run-name> [-f|--yes]
set -euo pipefail

YES=0
RUN_NAME=""
for arg in "$@"; do
  case "$arg" in
    -f|--yes) YES=1 ;;
    -h|--help) echo "usage: clean_remote.sh <run-name> [-f|--yes]"; exit 0 ;;
    *) RUN_NAME="$arg" ;;
  esac
done
[[ -n "$RUN_NAME" ]] || { echo "usage: clean_remote.sh <run-name> [-f|--yes]" >&2; exit 1; }

RUN="$HOME/entity-eval-runs/$RUN_NAME"
HARNESS="$HOME/entity-eval-traces/$RUN_NAME"

# Locate the submission: live project first, then the finish_round snapshot.
SUBMISSION=""
for candidate in "$RUN/project/submission.json" "$HARNESS/project-snapshot/submission.json"; do
  [[ -f "$candidate" ]] && SUBMISSION="$candidate" && break
done
[[ -n "$SUBMISSION" ]] || { echo "error: no submission.json found for $RUN_NAME" >&2; exit 1; }
echo "==> submission: $SUBMISSION"

read -r DATA_ROOT JOB_ID <<< "$(python3 - "$SUBMISSION" <<'EOF'
import json, sys
sub = json.load(open(sys.argv[1]))
run = sub.get("run", {}) or {}
data_root = run.get("data_root") or (sub.get("output", {}) or {}).get("data_root") or ""
job_id = str(run.get("slurm_job_id") or "")
print(data_root, job_id)
EOF
)"
[[ -n "$DATA_ROOT" ]] || { echo "error: submission declares no data_root" >&2; exit 1; }
[[ "$DATA_ROOT" == /* || "$DATA_ROOT" == ~* ]] || {
  echo "error: refusing relative data_root: $DATA_ROOT" >&2; exit 1; }

PARENT="$(dirname "$DATA_ROOT")"
LOGS="$HARNESS/remote-logs"
mkdir -p "$LOGS"

# 1. Evidence first: direct-backend run scripts and logs from the run root
#    (m87 has no Slurm) — run.sh, run.log, the exit file, manifests.
echo "==> pulling slurm scripts/logs from m87:$PARENT -> $LOGS"
rsync -a \
  --include='run.sh' --include='run.sbatch' --include='*.log' \
  --include='.entity-exit-code' --include='*-manifest.json' \
  --exclude='*' \
  "m87:$DATA_ROOT/" "$LOGS/" || echo "warning: rsync from $DATA_ROOT failed (already gone?)" >&2
ls -la "$LOGS"

# 2. Deletion: dry-run unless -f/--yes.
TARGETS=("$DATA_ROOT")
if [[ "$PARENT" != "$DATA_ROOT" && "$PARENT" != "/" && "$PARENT" != "$HOME" \
      && "$PARENT" != "~" && "$PARENT" == *entity* ]]; then
  TARGETS+=("$PARENT")
fi
echo
echo "==> remote deletion targets on m87:"
printf '    %s\n' "${TARGETS[@]}"
if [[ $YES -ne 1 ]]; then
  echo "==> dry-run: nothing deleted. Re-run with -f/--yes to delete."
else
  for target in "${TARGETS[@]}"; do
    echo "==> deleting m87:$target"
    ssh m87 "rm -rf -- '$target'"
  done
fi

# 3. Confirm no leftover entity processes (m87 has no scheduler).
echo
echo "==> leftover entity processes on m87:"
ssh m87 'pgrep -af "entity.xc|run.sh" || echo "  (none)"' || true
