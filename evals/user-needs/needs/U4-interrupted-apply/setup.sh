#!/usr/bin/env bash
# U4 setup: nothing to stage beyond the run_round.sh fixtures. The interrupt
# is an operator action, described in README.md — this script only prints it.
set -euo pipefail

: "${HARNESS:?HARNESS env required}"

cat <<EOF
==> U4 setup: operator action required during the run:
    1. watch the transcript until an `entityctl ... apply` call appears:
         tail -f "$HARNESS/transcript.jsonl"
    2. kill the agent process mid-apply (e.g. Ctrl-C or `kill <pid>`);
       run_need.sh returns to the shell.
    3. restart the session with the follow-up message:
         bash run_need.sh --followup U4 <variant> <run-name> [model]
EOF