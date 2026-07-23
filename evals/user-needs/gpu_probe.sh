#!/usr/bin/env bash
# Probe whether GPU jobs can actually START for our account on siyuan.
# Submits a 1-GPU nvidia-smi job on debuga100 and waits up to 150s for it to
# leave PENDING. Prints PROBE_OK if it ran, PROBE_BLOCKED otherwise.
set -uo pipefail

JOBID="$(ssh -o BatchMode=yes -o ConnectTimeout=10 siyuan \
  'sbatch --parsable --partition=debuga100 --qos=debug --nodes=1 --ntasks=1 \
   --gres=gpu:1 --time=00:02:00 --wrap="nvidia-smi -L"' 2>/dev/null)"
if [[ -z "$JOBID" ]]; then
  echo "PROBE_ERROR: sbatch failed"
  exit 1
fi
for i in $(seq 1 10); do
  sleep 15
  STATE="$(ssh -o BatchMode=yes -o ConnectTimeout=10 siyuan \
    "squeue -j $JOBID -h -o %T 2>/dev/null; sacct -j $JOBID -X -n -P --format=State 2>/dev/null | head -1" \
    | grep -v '^$' | head -1)"
  case "$STATE" in
    RUNNING|COMPLETED|COMPLETING)
      echo "PROBE_OK job=$JOBID state=$STATE"
      ssh -o BatchMode=yes -o ConnectTimeout=10 siyuan "scancel $JOBID" >/dev/null 2>&1
      exit 0
      ;;
    FAILED|CANCELLED*|TIMEOUT|NODE_FAIL)
      # It started (scheduler gave it a node) even though it failed — GPU accessible.
      echo "PROBE_OK job=$JOBID state=$STATE (started, exit non-zero)"
      exit 0
      ;;
  esac
done
REASON="$(ssh -o BatchMode=yes -o ConnectTimeout=10 siyuan "squeue -j $JOBID -h -o %R" 2>/dev/null)"
ssh -o BatchMode=yes -o ConnectTimeout=10 siyuan "scancel $JOBID" >/dev/null 2>&1
echo "PROBE_BLOCKED job=$JOBID reason=$REASON"
exit 1
