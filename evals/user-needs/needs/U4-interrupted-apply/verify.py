#!/usr/bin/env python3
"""U4 (agent killed mid-apply, then restarted) verification.

Checks: no duplicate sbatch submissions after the restart (same job name
submitted once, unless the first attempt verifiably FAILED), no unresolved
anomaly Operations in the router store, and the data was delivered.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verify_common as vc  # noqa: E402


def main() -> int:
    ns = vc.parse_args("U4", "U4 interrupted-apply verification")
    ctx = vc.resolve_context(ns)
    checks = []

    # 1. no duplicate sbatch per job name
    activities = ctx["activities"]
    if not activities:
        checks.append(vc.check("no_duplicate_sbatch", "unknown",
                               "no activities.json (job_lifecycle unavailable)"))
    else:
        jobs = (activities.get("job_lifecycle") or {}).get("jobs") or {}
        duplicates = {name: len(j.get("submissions", []))
                      for name, j in jobs.items() if len(j.get("submissions", [])) > 1}
        if not duplicates:
            checks.append(vc.check(
                "no_duplicate_sbatch", "pass",
                f"every job name submitted exactly once ({len(jobs)} job(s): {sorted(jobs)})"))
        else:
            checks.append(vc.check(
                "no_duplicate_sbatch", "fail",
                f"job names with >1 submission (name: count): {duplicates}; "
                "acceptable only if the first attempt verifiably FAILED — review sacct manually"))

    # 2. router store has no unresolved anomaly Operations
    export = vc.read_router_export(ctx["router_home"])
    if export is None:
        checks.append(vc.check("no_anomaly_operations", "unknown",
                               "router store unreadable/missing"))
    else:
        operations = export.get("operations", [])
        anomalies = [op for op in operations if op.get("status") == "anomaly"]
        if not anomalies:
            checks.append(vc.check(
                "no_anomaly_operations", "pass",
                f"{len(operations)} operation(s), none in anomaly state"))
        else:
            resolved = []
            for op in anomalies:
                later_completed = any(
                    other.get("status") == "completed"
                    and other.get("case_uid") == op.get("case_uid")
                    and other.get("created_at", "") > op.get("created_at", "")
                    for other in operations)
                if later_completed:
                    resolved.append(op.get("operation_id"))
            if len(resolved) == len(anomalies):
                checks.append(vc.check(
                    "no_anomaly_operations", "pass",
                    f"{len(anomalies)} anomaly operation(s) all superseded by later completed "
                    "operations; cross-check job uniqueness in no_duplicate_sbatch"))
            else:
                checks.append(vc.check(
                    "no_anomaly_operations", "fail",
                    f"{len(anomalies) - len(resolved)} anomaly operation(s) without a later "
                    f"completed operation: {[op.get('operation_id') for op in anomalies]}"))

    # 3. data delivered
    oracle = ctx["oracle_report"]
    if oracle is None:
        checks.append(vc.check("data_delivered", "unknown", "no oracle report available"))
    else:
        gate_d = vc.oracle_gate(oracle, "D")
        d_status = gate_d["status"] if gate_d else "unknown"
        status = "pass" if d_status == "pass" else ("fail" if d_status == "fail" else "unknown")
        checks.append(vc.check("data_delivered", status,
                               f"oracle overall={oracle.get('overall')}, gate D={d_status}"))

    vc.finalize(ns, ctx, checks, [])
    return 0


if __name__ == "__main__":
    sys.exit(main())
