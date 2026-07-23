#!/usr/bin/env bash
# U6 setup: render the prompt with the data root of a completed run.
#
# Usage: setup.sh (--data-root <remote-path> | --evidence <evidence-dir>)
set -euo pipefail

: "${RUN:?RUN env required}"
: "${NEED_DIR:?NEED_DIR env required}"

DATA_ROOT=""
EVIDENCE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-root) DATA_ROOT="${2:?--data-root needs a value}"; shift 2 ;;
    --evidence) EVIDENCE="${2:?--evidence needs a directory}"; shift 2 ;;
    *) echo "error: unknown setup argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$DATA_ROOT" && -n "$EVIDENCE" ]]; then
  [[ -f "$EVIDENCE/submission.json" ]] || {
    echo "error: $EVIDENCE/submission.json not found (need a completed run's evidence)" >&2; exit 1; }
  DATA_ROOT="$(python3 -c '
import json, sys
s = json.load(open(sys.argv[1]))
print((s.get("run") or {}).get("data_root") or (s.get("output") or {}).get("data_root") or "")
' "$EVIDENCE/submission.json")"
fi
[[ -n "$DATA_ROOT" ]] || {
  echo "error: U6 needs --data-root <remote-path> or --evidence <dir with submission.json>" >&2
  exit 1
}

sed "s|@DATA_ROOT@|$DATA_ROOT|g" "$NEED_DIR/prompt.md" > "$RUN/prompt.rendered.md"
echo "==> U6 setup: prompt rendered with data root $DATA_ROOT"
echo "    (rendered prompt: $RUN/prompt.rendered.md)"
