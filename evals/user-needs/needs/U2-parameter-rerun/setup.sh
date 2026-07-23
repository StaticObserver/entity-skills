#!/usr/bin/env bash
# U2 setup: stage the prior U1 run's artifacts as "existing work" and record
# the old data root (plus a remote file snapshot for the preservation check).
#
# Usage: setup.sh --prior <run-name|evidence-dir>
set -euo pipefail

: "${RUN:?RUN env required}"
: "${REPO:?REPO env required}"

PRIOR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prior) PRIOR="${2:?--prior needs a value}"; shift 2 ;;
    *) echo "error: unknown setup argument: $1" >&2; exit 1 ;;
  esac
done
[[ -n "$PRIOR" ]] || { echo "error: U2 needs --prior <run-name|evidence-dir> (run U1 first)" >&2; exit 1; }

# Resolve prior project + submission: live run dir, else retained evidence.
if [[ -d "$PRIOR" ]]; then
  EVID="$PRIOR"; PRIOR_PROJECT=""
else
  EVID="$HOME/entity-eval-traces/$PRIOR"
  PRIOR_PROJECT="$HOME/entity-eval-runs/$PRIOR/project"
fi

copy_prior_artifacts() {
  local src="$1"
  local copied=0
  for item in input.toml pgen.hpp docs; do
    if [[ -e "$src/$item" ]]; then
      cp -R "$src/$item" "$RUN/project/"
      copied=1
    fi
  done
  return $((1 - copied))
}

if [[ -n "$PRIOR_PROJECT" && -d "$PRIOR_PROJECT" ]]; then
  copy_prior_artifacts "$PRIOR_PROJECT" || true
elif [[ -d "$EVID/project-snapshot" ]]; then
  copy_prior_artifacts "$EVID/project-snapshot" || true
fi
[[ -f "$RUN/project/input.toml" ]] || {
  echo "error: could not stage prior U1 artifacts (no input.toml found in live run or evidence)" >&2
  echo "       pass --prior pointing at a completed U1 run or its evidence dir" >&2
  exit 1
}

# Old data root: prior submission.json first, else router export.
OLD_ROOT=""
for sub in "${PRIOR_PROJECT:+$PRIOR_PROJECT/submission.json}" "$EVID/submission.json"; do
  [[ -f "$sub" ]] || continue
  OLD_ROOT="$(python3 -c '
import json, sys
s = json.load(open(sys.argv[1]))
print((s.get("run") or {}).get("data_root") or (s.get("output") or {}).get("data_root") or "")
' "$sub")"
  [[ -n "$OLD_ROOT" ]] && break
done
[[ -n "$OLD_ROOT" ]] || { echo "error: could not determine the old run data_root" >&2; exit 1; }
echo "$OLD_ROOT" > "$RUN/u2-prior-data-root.txt"
echo "==> U2 setup: prior artifacts staged; old data root: $OLD_ROOT"

# Remote snapshot for the post-run preservation check (skip silently if the
# site is unreachable; verify then reports unknown).
if ssh -o BatchMode=yes -o ConnectTimeout=8 siyuan \
    "find '$OLD_ROOT' -type f -printf '%p %T@ %s\n' | sort" > "$RUN/u2-old-root-snapshot.txt" 2>/dev/null \
    && [[ -s "$RUN/u2-old-root-snapshot.txt" ]]; then
  echo "==> U2 setup: old root snapshot: $RUN/u2-old-root-snapshot.txt ($(wc -l < "$RUN/u2-old-root-snapshot.txt" | tr -d ' ') files)"
else
  rm -f "$RUN/u2-old-root-snapshot.txt"
  echo "warning: siyuan unreachable; old-root preservation check will be unknown" >&2
fi
