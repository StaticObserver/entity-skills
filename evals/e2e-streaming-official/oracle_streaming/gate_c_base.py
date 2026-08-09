"""Gate C: scheduler and data verification.

Independently confirms, from scheduler facts (sacct via ssh) and the raw
data itself, that the declared job really ran as declared and that the
produced data is readable and sane. The submission's claims are inputs to
locate facts, never evidence.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _check(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def sacct_job(site: str, job_id: str) -> Optional[Dict[str, Any]]:
    """Query sacct for one job. Returns parsed fields or None.

    Beyond the neutral-streaming original this variant also reports "tres"
    (AllocTRES, for the gres ceiling check) and "records" (number of sacct
    rows for the job id — a requeued/rerun job shows more than one).
    """
    fmt = "JobID,JobName,Partition,State,ExitCode,NNodes,NTasks,Elapsed,AllocTRES"
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", site,
             f"sacct -j {job_id} -X -n -P --format={fmt}"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    lines = [ln for ln in out.stdout.strip().splitlines() if ln.strip()]
    parts = lines[0].split("|")
    if len(parts) < 8:
        return None
    return {
        "job_id": parts[0], "name": parts[1], "partition": parts[2],
        "state": parts[3], "exit_code": parts[4], "nodes": parts[5],
        "tasks": parts[6], "elapsed": parts[7],
        "tres": parts[8] if len(parts) > 8 else "",
        "records": len(lines),
    }


def evaluate_job(job: Optional[Dict[str, str]], expected: Dict[str, Any]) -> List[Dict[str, str]]:
    """expected: {partition, tasks, nodes, walltime_ceiling_seconds}."""
    if job is None:
        return [_check("job_facts", "unknown", "sacct returned no record for the declared job id")]
    checks = []
    state_ok = job["state"].startswith("COMPLETED")
    exit_ok = job["exit_code"].split(":")[0] == "0"
    checks.append(_check(
        "job_terminal_state",
        "pass" if state_ok and exit_ok else "fail",
        f"state={job['state']} exit={job['exit_code']}",
    ))
    for key, field in (("partition", "partition"), ("tasks", "tasks"), ("nodes", "nodes")):
        want = str(expected.get(key))
        got = str(job[field])
        if not got:
            # sacct leaves some fields blank (e.g. NTasks for certain MPI
            # submissions); that is missing evidence, not a mismatch.
            checks.append(_check(f"job_{key}", "unknown",
                                 f"sacct reports no {field} for this job"))
            continue
        checks.append(_check(
            f"job_{key}",
            "pass" if got == want else "fail",
            f"{key}: expected {want}, sacct reports {got}",
        ))
    elapsed = job["elapsed"]
    try:
        h, m, s = (int(x) for x in elapsed.split(":"))
        seconds = h * 3600 + m * 60 + s
        ceiling = int(expected["walltime_ceiling_seconds"])
        checks.append(_check(
            "job_walltime",
            "pass" if seconds <= ceiling else "fail",
            f"elapsed {elapsed} ({seconds}s) vs ceiling {ceiling}s",
        ))
    except (ValueError, KeyError):
        checks.append(_check("job_walltime", "unknown", f"cannot parse elapsed {elapsed!r}"))
    return checks


def evaluate_data(data_root: Path, min_snapshots: int = 2) -> List[Dict[str, str]]:
    """nt2py must independently read >= min_snapshots of fields/particles,
    with monotonic time and finite values."""
    try:
        import numpy as np  # noqa: PLC0415
        import nt2  # noqa: PLC0415
    except ImportError as exc:
        return [_check("data_readable", "unknown", f"nt2py unavailable: {exc}")]
    try:
        data = nt2.Data(str(data_root))
    except Exception as exc:
        return [_check("data_readable", "fail", f"nt2.Data cannot open {data_root}: {exc}")]

    checks = []
    field_times = list(data.fields.t.values)
    checks.append(_check(
        "field_snapshots",
        "pass" if len(field_times) >= min_snapshots else "fail",
        f"{len(field_times)} field snapshots (need >= {min_snapshots})",
    ))
    particle_times = list(data.particles.times)
    checks.append(_check(
        "particle_snapshots",
        "pass" if len(particle_times) >= min_snapshots else "fail",
        f"{len(particle_times)} particle snapshots (need >= {min_snapshots})",
    ))
    monotonic = all(b > a for a, b in zip(field_times, field_times[1:]))
    checks.append(_check(
        "time_monotonic", "pass" if monotonic else "fail",
        "field snapshot times strictly increasing" if monotonic else "field times not monotonic",
    ))
    try:
        last = data.fields.sel(t=field_times[-1])
        finite = all(bool(np.isfinite(last[var].values).all()) for var in last.keys())
        checks.append(_check(
            "values_finite", "pass" if finite else "fail",
            "all field values finite at last snapshot" if finite else "NaN/Inf in fields",
        ))
    except Exception as exc:
        checks.append(_check("values_finite", "unknown", f"finite check failed: {exc}"))
    return checks


def run(site: str, submission: Dict[str, Any], thresholds: Dict[str, Any],
        data_root: Optional[Path]) -> Dict[str, Any]:
    run_info = submission.get("run", {})
    spec = submission.get("physics_spec", {})
    ceiling_hms = spec.get("resource_ceiling", {}).get("walltime", "00:10:00") \
        if "resource_ceiling" in spec else "00:10:00"
    try:
        h, m, s = (int(x) for x in ceiling_hms.split(":"))
        ceiling_seconds = h * 3600 + m * 60 + s
    except ValueError:
        ceiling_seconds = 600

    expected = {
        "partition": run_info.get("partition", "debuga100"),
        "tasks": run_info.get("resources", {}).get("tasks", 2),
        "nodes": run_info.get("resources", {}).get("nodes", 1),
        "walltime_ceiling_seconds": ceiling_seconds,
    }
    checks: List[Dict[str, str]] = []
    job_id = str(run_info.get("slurm_job_id") or "")
    if job_id:
        checks.extend(evaluate_job(sacct_job(site, job_id), expected))
    else:
        checks.append(_check("job_facts", "unknown", "submission declares no slurm_job_id"))

    if data_root and Path(data_root).is_dir():
        checks.extend(evaluate_data(Path(data_root)))
    else:
        checks.append(_check("data_readable", "unknown", "no local data root provided"))

    statuses = {c["status"] for c in checks}
    status = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
    return {"gate": "C-job-data", "status": status, "checks": checks}
