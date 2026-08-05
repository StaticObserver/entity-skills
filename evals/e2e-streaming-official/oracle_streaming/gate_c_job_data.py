"""Gate C: scheduler/direct-backend and data verification.

m87 has no scheduler (direct backend): job facts are verified from the
recorded direct-launch evidence — the executor's exit file
(<run_root>/.entity-exit-code) inside the fetched data root — instead of
sacct. The Slurm branch is kept for completeness (helpers live in
gate_c_base, copied unchanged from the neutral-streaming oracle). Data
readability checks are identical to the neutral-streaming variant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from oracle_streaming.gate_c_base import (  # noqa: E402
    _check,
    evaluate_data,
    evaluate_job,
    sacct_job,
)


def evaluate_exit_evidence(data_root: Path, declared_exit: Optional[int]) -> List[Dict[str, str]]:
    """Direct-backend job facts: the executor's exit file is the terminal
    evidence. Missing file = unknown; non-zero = fail; a declared exit code
    in the submission that disagrees with the file = fail."""
    exit_file = Path(data_root) / ".entity-exit-code"
    if not exit_file.is_file():
        return [_check("exit_evidence", "unknown",
                       "no .entity-exit-code in the fetched run root")]
    text = exit_file.read_text(encoding="utf-8")
    try:
        code = int(text.strip())
    except ValueError:
        return [_check("exit_evidence", "fail",
                       f"unparseable exit file: {text!r}")]
    checks = [_check(
        "exit_evidence",
        "pass" if code == 0 else "fail",
        f"recorded exit code {code}",
    )]
    if declared_exit is not None and int(declared_exit) != code:
        checks.append(_check(
            "exit_code_consistent", "fail",
            f"submission declares exit {declared_exit}, exit file says {code}",
        ))
    return checks


def _walltime_ceiling(submission: Dict[str, Any]) -> int:
    spec = submission.get("physics_spec", {})
    hms = spec.get("resource_ceiling", {}).get("walltime", "00:10:00")
    try:
        h, m, s = (int(x) for x in hms.split(":"))
        return h * 3600 + m * 60 + s
    except (ValueError, KeyError):
        return 600


def run(site: str, submission: Dict[str, Any], thresholds: Dict[str, Any],
        data_root: Optional[Path]) -> Dict[str, Any]:
    run_info = submission.get("run", {})
    scheduler = run_info.get("scheduler", {}) or {}
    kind = scheduler.get("kind", "")
    checks: List[Dict[str, str]] = []

    if kind == "slurm":
        job_id = str(scheduler.get("job_id") or run_info.get("slurm_job_id") or "")
        if job_id:
            checks.extend(evaluate_job(sacct_job(site, job_id), {
                "partition": run_info.get("partition", ""),
                "tasks": run_info.get("resources", {}).get("tasks", 1),
                "nodes": run_info.get("resources", {}).get("nodes", 1),
                "walltime_ceiling_seconds": _walltime_ceiling(submission),
            }))
        else:
            checks.append(_check("job_facts", "unknown", "submission declares no slurm job id"))
    elif kind == "direct":
        if data_root and Path(data_root).is_dir():
            checks.extend(evaluate_exit_evidence(
                Path(data_root), run_info.get("exit_code")))
        else:
            checks.append(_check("exit_evidence", "unknown",
                                 "direct backend: no local data root to read the exit file from"))
        walltime = run_info.get("walltime_seconds")
        if walltime is not None:
            ceiling = _walltime_ceiling(submission)
            checks.append(_check(
                "job_walltime",
                "pass" if int(walltime) <= ceiling else "fail",
                f"declared walltime {walltime}s vs ceiling {ceiling}s",
            ))
    else:
        checks.append(_check("job_facts", "unknown",
                             "submission declares no scheduler kind (direct/slurm)"))

    if data_root and Path(data_root).is_dir():
        checks.extend(evaluate_data(Path(data_root)))
    else:
        checks.append(_check("data_readable", "unknown", "no local data root provided"))

    statuses = {c["status"] for c in checks}
    status = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
    return {"gate": "C-job-data", "status": status, "checks": checks}
