#!/usr/bin/env bash
# U5 setup: nothing to stage beyond the run_round.sh fixtures. The tamper is
# a grader action between stage 1 and the follow-up — see README.md.
set -euo pipefail

cat <<'EOF'
==> U5 setup: after the stage-1 agent finishes delivering:
    1. bash grade_need.sh U5 <run-name> --tamper   # modifies one delivered
       #    artifact in the agent's project; records it in tampered.txt
    2. bash run_need.sh --followup U5 <variant> <run-name> [model]
    3. bash grade_need.sh U5 <run-name>
EOF
