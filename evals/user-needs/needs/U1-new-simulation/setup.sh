#!/usr/bin/env bash
# U1 setup: the run_round.sh fixture copy (task.md, physics-spec.json,
# submission.schema.json) IS this scenario's fixture — nothing more to lay.
set -euo pipefail

: "${RUN:?RUN env required}"
for f in task.md physics-spec.json submission.schema.json; do
  [[ -f "$RUN/project/$f" ]] || { echo "error: expected fixture missing: $RUN/project/$f" >&2; exit 1; }
done
echo "==> U1 setup: fixtures already in place (run_round.sh copy)"
