#!/usr/bin/env bash
# Pull remote Slurm scripts/logs into the harness, then delete the remote
# artifacts of one evaluation round: the declared data root, the site-tree
# project directory (<tree>/projects/<slug>) when applicable, and the known
# auxiliary roots a round may create on astro (_pilot, _tools, a mistaken
# remote ~/entity-workspace). Queued/running entity-* jobs are listed and,
# with -f, scancelled. Everything is DRY-RUN by default; pass -f/--yes to
# actually remove/cancel.
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
sched = run.get("scheduler", {}) or {}
data_root = run.get("data_root") or (sub.get("output", {}) or {}).get("data_root") or ""
job_id = str(sched.get("job_id") or run.get("slurm_job_id") or "")
print(data_root, job_id)
EOF
)"
[[ -n "$DATA_ROOT" ]] || { echo "error: submission declares no data_root" >&2; exit 1; }
[[ "$DATA_ROOT" == /* || "$DATA_ROOT" == ~* ]] || {
  echo "error: refusing relative data_root: $DATA_ROOT" >&2; exit 1; }

PARENT="$(dirname "$DATA_ROOT")"
LOGS="$HARNESS/remote-logs"
mkdir -p "$LOGS"

# 1. Evidence first: Slurm scripts and logs from the run directory
#    (data_root's parent) — *.sbatch, *.log, slurm-*.out, manifests.
echo "==> pulling slurm scripts/logs from astro:$PARENT -> $LOGS"
rsync -a \
  --include='run.sh' --include='*.sbatch' --include='*.log' \
  --include='slurm-*.out' --include='.entity-exit-code' \
  --include='*-manifest.json' \
  --exclude='*' \
  "astro:$PARENT/" "$LOGS/" || echo "warning: rsync from $PARENT failed (already gone?)" >&2
if [[ -n "$JOB_ID" ]]; then
  rsync -a "astro:$PARENT/slurm-$JOB_ID.out" "$LOGS/" 2>/dev/null || true
fi
ls -la "$LOGS"

# 2. Deletion: dry-run unless -f/--yes.
# Site-tree rounds: when data_root lives under <tree>/projects/<slug>/..., the
# whole per-round project tree is the target, plus the known auxiliary roots
# an agent/pilot may have created (_pilot, _tools, a mistaken remote
# ~/entity-workspace).
TARGETS=("$DATA_ROOT")
PROJECT_TREE=""
if [[ "$DATA_ROOT" == *"/projects/"*"/"* ]]; then
  PROJECT_TREE="${DATA_ROOT%%/projects/*}/projects/$( \
    rest="${DATA_ROOT#*/projects/}"; echo "${rest%%/*}")"
fi
if [[ -n "$PROJECT_TREE" && "$PROJECT_TREE" == *entity* ]]; then
  TARGETS+=("$PROJECT_TREE")
elif [[ "$PARENT" != "$DATA_ROOT" && "$PARENT" != "/" && "$PARENT" != "$HOME" \
        && "$PARENT" != "~" && "$PARENT" == *entity* ]]; then
  TARGETS+=("$PARENT")
fi
for extra in '$HOME/entity-compute/_pilot' '$HOME/entity-compute/_tools' '$HOME/entity-workspace'; do
  TARGETS+=("$extra")
done
echo
echo "==> remote deletion targets on astro:"
printf '    %s\n' "${TARGETS[@]}"
if [[ $YES -ne 1 ]]; then
  echo "==> dry-run: nothing deleted. Re-run with -f/--yes to delete."
else
  for target in "${TARGETS[@]}"; do
    # expand the leading ~/$HOME on the remote, and only ever delete under
    # the user's home — nothing else is ours to remove
    resolved="$(ssh astro "eval echo \"$target\"")"
    case "$resolved" in
      /home/*) ;;
      *) echo "==> SKIP (refusing non-home path): $target -> $resolved" >&2; continue ;;
    esac
    echo "==> deleting astro:$resolved"
    ssh astro "rm -rf -- '$resolved'"
  done
fi

# 3. Leftover jobs: the round's declared job id plus any queued/running
#    entity-* job of the remote user (aborted rounds leave these behind).
#    Dry-run lists them; -f scancels.
echo
echo "==> leftover entity-* jobs on astro:"
LIVE_JOBS="$(ssh astro 'squeue -u "$USER" -h -o "%i %j"' 2>/dev/null || true)"
LEFTOVER_JOBS=""
while IFS= read -r line; do
  [[ -n "$line" ]] || continue
  jid="${line%% *}"
  jname="${line#* }"
  if [[ "$jname" == entity-* || ( -n "$JOB_ID" && "$jid" == "$JOB_ID" ) ]]; then
    LEFTOVER_JOBS+="$jid "
    echo "    $jid  $jname"
  fi
done <<< "$LIVE_JOBS"
if [[ -z "$LEFTOVER_JOBS" ]]; then
  echo "    (none)"
elif [[ $YES -ne 1 ]]; then
  echo "==> dry-run: jobs NOT cancelled. Re-run with -f/--yes to scancel:$LEFTOVER_JOBS"
else
  for jid in $LEFTOVER_JOBS; do
    echo "==> scancel $jid"
    ssh astro "scancel '$jid'" || echo "warning: scancel $jid failed" >&2
  done
fi
echo
echo "==> sacct since today on astro:"
ssh astro "sacct -S $(date +%F) -n -P --format=JobID,JobName,Partition,State,Elapsed" || true
