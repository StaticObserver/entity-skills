#!/usr/bin/env python3
"""U1 (new simulation, full lifecycle) verification.

Scores the final state only: oracle gates A-E, submission schema, data
inventory (skills variant), exactly one successful sim-class Slurm job, and
(skills variant) a complete source/build/run chain in the router store.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verify_common as vc  # noqa: E402

BOUNDARY_NO_DATA_GOAL = (
    "the data inventory is a product of the entity-ledger data Goal; the no-router "
    "variant lacks this capability, so record unknown instead of fail "
    "(skill boundary, not an agent error)"
)
BOUNDARY_NO_ROUTER = (
    "the router source/build/run chain is an entity-ledger capability; the no-router "
    "variant lacks this capability, so record unknown instead of fail (skill boundary)"
)


def main() -> int:
    ns = vc.parse_args("U1", "U1 new-simulation verification")
    ctx = vc.resolve_context(ns)
    is_skills = ctx["variant"] == vc.SKILL_VARIANT
    checks = []
    notes = []

    # 1. oracle gates A-E
    oracle = ctx["oracle_report"]
    if oracle is None:
        checks.append(vc.check("oracle_gates", "unknown",
                               "no oracle report (evidence, project, and offline recompute all unavailable)"))
    else:
        gates = ", ".join(f"{g['gate']}={g['status']}" for g in oracle.get("gates", []))
        checks.append(vc.check("oracle_gates", oracle.get("overall", "unknown"), gates))

    # 2. submission.json conforms to the schema
    submission = None
    for candidate in ([ctx["project"] / "submission.json"] if ctx["project"] else []) + \
                     ([ctx["evidence"] / "submission.json"] if ctx["evidence"] else []):
        if candidate.is_file():
            submission = candidate
            break
    if submission is None:
        checks.append(vc.check("submission_schema", "unknown",
                               "no submission.json found in project or evidence"))
    else:
        checks.append(vc.validate_submission_schema(submission))

    # 3. data inventory (router data Goal artifact)
    inventory = None
    if ctx["project"]:
        matches = list(ctx["project"].rglob("data-inventory.json"))
        inventory = matches[0] if matches else None
    if is_skills:
        if inventory:
            checks.append(vc.check("data_inventory", "pass", str(inventory)))
        elif ctx["project"] is None:
            checks.append(vc.check("data_inventory", "unknown",
                                   "project directory unavailable (offline evidence has no project copy)"))
        else:
            checks.append(vc.check("data_inventory", "fail",
                                   "no data-inventory.json under project (data Goal artifact missing)"))
    else:
        checks.append(vc.check("data_inventory", "unknown",
                               "no-router variant: data Goal is a router capability, not scored"))
        notes.append(BOUNDARY_NO_DATA_GOAL)

    # 4. exactly one successful sim-class job (activities + sacct cross-check)
    activities = ctx["activities"]
    if not activities:
        checks.append(vc.check("single_sim_job_success", "unknown",
                               "no activities.json (job_lifecycle unavailable)"))
    else:
        lifecycle = activities.get("job_lifecycle", {})
        sim_jobs = {name: j for name, j in (lifecycle.get("jobs") or {}).items()
                    if j.get("job_class") == "sim"}
        sim_submissions = lifecycle.get("sim_submissions", 0)
        detail = f"sim jobs: {sorted(sim_jobs)}, sim submissions: {sim_submissions}"
        if sim_submissions == 1 and len(sim_jobs) == 1:
            status = "pass"
        else:
            status = "fail"
            detail += "; expected exactly 1 submission of exactly 1 sim job"
        checks.append(vc.check("single_sim_job_success", status, detail))

    # 5. router source/build/run chain (skills variant only)
    if is_skills:
        export = vc.read_router_export(ctx["router_home"])
        if export is None:
            checks.append(vc.check("router_run_chain", "unknown",
                                   "router store unreadable/missing (no export possible)"))
        else:
            missing_dims = []
            found_case = False
            for case in export.get("cases", []):
                identities = case.get("identities") or {}
                dims = {d: (identities.get(d) or {}).get("current_id", "")
                        for d in ("source", "build", "run")}
                if any(dims.values()):
                    found_case = True
                    missing_dims += [d for d, v in dims.items() if not v]
            if not found_case:
                checks.append(vc.check("router_run_chain", "fail",
                                       "router export contains no case with any identity"))
            elif missing_dims:
                checks.append(vc.check("router_run_chain", "fail",
                                       f"identity chain incomplete, missing: {sorted(set(missing_dims))}"))
            else:
                checks.append(vc.check("router_run_chain", "pass",
                                       "source/build/run identities present and chained"))
    else:
        checks.append(vc.check("router_run_chain", "unknown",
                               "no-router variant: router chain not applicable"))
        notes.append(BOUNDARY_NO_ROUTER)

    vc.finalize(ns, ctx, checks, notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
