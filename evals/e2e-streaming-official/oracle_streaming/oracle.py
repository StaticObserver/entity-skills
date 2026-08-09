#!/usr/bin/env python3
"""Independent oracle for the e2e-streaming-official evaluation.

Re-verifies one completed round from owner artifacts and external facts —
never from the agent's own claims. Produces oracle-report.json with per-gate
pass/fail/unknown. Overall status: fail if any gate fails, unknown if any
gate is unknown, pass otherwise. Physics (Gate D) is fail-closed: unverifiable
physics counts against the round.

Usage:
  oracle.py --project <agent project dir> [options]

Options:
  --transcript PATH   session JSONL for Gate A safety scan
  --data-root PATH    local copy of the raw simulation output
  --fetch DIR         rsync run.data_root from the site into DIR first
  --site HOST         ssh alias for scheduler/data queries (default: astro)
  --no-remote         skip all ssh queries (Gates C/D become unknown)
  --spec PATH         physics-spec.json (default: alongside this script)
  --thresholds PATH   thresholds.json (default: alongside this script)
  --output PATH       report path (default: <project>/oracle-report.json)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from oracle_streaming import gate_a_safety, gate_b_official, gate_c_job_data, gate_d_physics, gate_e_analysis  # noqa: E402


def _load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent oracle for e2e-streaming-official")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--fetch", type=Path)
    parser.add_argument("--site", default="astro")
    parser.add_argument("--no-remote", action="store_true")
    parser.add_argument("--spec", type=Path, default=HERE.parent / "physics-spec.json")
    parser.add_argument("--thresholds", type=Path, default=HERE / "thresholds.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    submission = _load_json(project / "submission.json")
    spec = _load_json(args.spec)
    thresholds = _load_json(args.thresholds)

    data_root = args.data_root
    if args.fetch and not args.no_remote:
        remote = (submission.get("run", {}).get("data_root")
                  or submission.get("output", {}).get("data_root"))
        if not remote:
            print("error: submission declares no run.data_root", file=sys.stderr)
            return 2
        args.fetch.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["rsync", "-a", f"{args.site}:{remote}/", f"{args.fetch}/"], check=True,
        )
        data_root = args.fetch

    gates = []
    gates.append(gate_b_official.run(project, spec, submission))
    if args.transcript:
        # The agent necessarily references its own run root; only cross-round
        # references are violations (derive the run name from the project path).
        gates.append(gate_a_safety.run(args.transcript, submission,
                                       self_run_name=project.parent.name))
    else:
        gates.append({"gate": "A-safety", "status": "unknown",
                      "checks": [{"name": "transcript", "status": "unknown",
                                  "detail": "no transcript provided"}]})
    if args.no_remote:
        gates.append({"gate": "C-job-data", "status": "unknown",
                      "checks": [{"name": "remote", "status": "unknown",
                                  "detail": "--no-remote: scheduler query skipped"}]})
        gates.append(gate_d_physics.run(data_root, thresholds) if data_root else {
            "gate": "D-physics", "status": "unknown",
            "checks": [{"name": "data", "status": "unknown", "detail": "no data root"}]})
    else:
        gates.append(gate_c_job_data.run(args.site, submission, thresholds, data_root))
        gates.append(gate_d_physics.run(data_root, thresholds) if data_root else {
            "gate": "D-physics", "status": "unknown",
            "checks": [{"name": "data", "status": "unknown",
                        "detail": "no data root (use --data-root or --fetch)"}]})
    gates.append(gate_e_analysis.run(project, submission))

    statuses = {g["status"] for g in gates}
    overall = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
    report = {
        "schema_version": 1,
        "experiment_id": submission.get("experiment_id"),
        "project": str(project),
        "overall": overall,
        "gates": gates,
    }
    output = args.output or (project / "oracle-report.json")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"overall: {overall}")
    for gate in gates:
        print(f"  {gate['gate']:<22} {gate['status']}")
        for check in gate.get("checks", []):
            marker = {"pass": "✓", "fail": "✗", "unknown": "?"}.get(check["status"], "?")
            print(f"    {marker} {check['name']}: {check['detail'][:110]}")
    print(f"report: {output}")
    return 0 if overall == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
