#!/usr/bin/env bash
# U3 setup: nothing to stage beyond the run_round.sh fixtures. The kill is an
# operator action, described in README.md — this script only prints it.
set -euo pipefail

: "${HARNESS:?HARNESS env required}"

cat <<EOF
==> U3 setup: operator action required during the run:
    1. watch the cluster until the sim job is RUNNING:
         ssh siyuan 'squeue -u \$USER'
    2. kill it out-of-band:
         ssh siyuan 'scancel <jobid>'
    3. write the killed job id for the grader:
         echo <jobid> > "$HARNESS/killed-job.txt"
    4. send the follow-up user message:
         bash run_need.sh --followup U3 <variant> <run-name> [model]
EOF
