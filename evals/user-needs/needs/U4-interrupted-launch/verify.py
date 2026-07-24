#!/usr/bin/env python3
"""U4 (agent killed mid `record run-launch`, then restarted) verification.

Checks: no duplicate sbatch submissions after the restart (same job name
submitted once, unless the first attempt verifiably FAILED), the router
store's run facts are complete with no half-baked launch state, and the data
was delivered.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verify_common as vc  # noqa: E402


def main() -> int:
    ns = vc.parse_args("U4", "U4 interrupted-launch verification")
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

    # 2. router store run facts are complete: with store schema v2 the
    # retired operations table no longer exists, so "no anomaly" now means
    # every booked run identity is internally consistent — a submitted run
    # must carry its scheduler handle (job_id/pid), a terminal run must
    # carry an exit code, and every launched run must have a matching
    # record.run-launch audit event (a prepared-but-unlaunched run is a
    # valid pending state, not half-baked)
    export = vc.read_router_export(ctx["router_home"])
    if export is None:
        checks.append(vc.check("run_facts_consistent", "unknown",
                               "router store unreadable/missing"))
    else:
        launched = {
            (event.get("payload") or {}).get("run_id")
            for event in export.get("events", [])
            if event.get("event_type") == "record.run-launch"
        }
        problems = []
        runs = 0
        for case in export.get("cases", []):
            identities = (case.get("identities") or {}).get("run") or {}
            for item in identities.get("items", []):
                runs += 1
                run_id = item.get("id", "?")
                status = item.get("status", "")
                scheduler = item.get("scheduler") or {}
                if status == "submitted" and not (
                        scheduler.get("job_id") or scheduler.get("pid")):
                    problems.append(
                        "run %s is submitted without a scheduler handle" % run_id)
                if status in {"completed", "failed"} \
                        and item.get("exit_code") is None:
                    problems.append(
                        "run %s is %s without an exit code" % (run_id, status))
                if status in {"submitted", "completed", "failed"} \
                        and run_id not in launched:
                    problems.append(
                        "run %s is %s without a record.run-launch event"
                        % (run_id, status))
        if not problems:
            checks.append(vc.check(
                "run_facts_consistent", "pass",
                f"{runs} run identitie(s), all consistent with the audit events"))
        else:
            checks.append(vc.check(
                "run_facts_consistent", "fail",
                f"half-baked run facts: {problems}"))

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
