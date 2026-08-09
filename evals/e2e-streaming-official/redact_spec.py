#!/usr/bin/env python3
"""Produce the agent-facing redacted physics spec.

The full physics-spec.json carries the astro Slurm answers (partition,
gres, QoS, analysis partitions) for the oracle; handing it verbatim to the
agent under test would leak the self-discovery checkpoints. This filter
keeps the physics, the compile contract, and the resource *budget* while
dropping the site-specific Slurm details. The oracle always scores against
the full spec (oracle.py --spec default).

Usage: redact_spec.py <full-spec.json> <output.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Resource fields that are answers to the discovery checkpoints.
RUN_JOB_DROP = ("partition", "gres", "qos", "time_limit")
BUILD_JOB_DROP = ("partition",)
ANALYSIS_JOB_DROP = ("partitions",)


def redact(spec: dict) -> dict:
    redacted = json.loads(json.dumps(spec))
    runtime = redacted.get("runtime", {})
    if "note" in runtime:
        # the gold-run note names the site hardware; the agent only needs
        # the calibration status
        runtime["note"] = ("calibrated against the gold run; details "
                           "deliberately omitted from the agent-facing spec")
    resources = redacted.get("resources", {})
    run_job = resources.get("run_job", {})
    for key in RUN_JOB_DROP:
        run_job.pop(key, None)
    run_job["note"] = (
        "Slurm run job; partition/gres/QoS are deliberately unspecified — "
        "discover them from the site. walltime_ceiling is the eval budget, "
        "not a Slurm directive"
    )
    build_job = resources.get("build_job", {})
    for key in BUILD_JOB_DROP:
        build_job.pop(key, None)
    analysis_job = resources.get("analysis_job", {})
    for key in ANALYSIS_JOB_DROP:
        analysis_job.pop(key, None)
    analysis_job["note"] = (
        "analysis/rendering jobs go to CPU partitions; never the GPU "
        "simulation partition"
    )
    return redacted


def main_with(argv) -> int:
    if len(argv) != 2:
        print("usage: redact_spec.py <full-spec.json> <output.json>", file=sys.stderr)
        return 2
    spec = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    out = json.dumps(redact(spec), indent=2, ensure_ascii=False) + "\n"
    Path(argv[1]).write_text(out, encoding="utf-8")
    return 0


def main() -> int:
    return main_with(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
