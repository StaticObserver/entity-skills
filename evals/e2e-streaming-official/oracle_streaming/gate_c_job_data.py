"""Gate C: scheduler/direct-backend and data verification.

astro runs under Slurm: job facts are verified from sacct (via ssh) — the
declared sbatch job id must map to exactly one sacct record with a clean
terminal state/exit code, resources and Elapsed consistent with the
declaration and the spec ceilings, and AllocTRES gres within the GPU
ceiling. The direct-backend branch (evaluate_exit_evidence, m87 variant) is
kept for reuse; dispatch is on the submission's run.scheduler.kind. The
shared sacct/nt2py helpers live in gate_c_base (copied from the
neutral-streaming oracle, extended with AllocTRES/record-count fields).
Data readability checks are identical to the neutral-streaming variant.
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
    hms = (spec.get("resources", {}).get("run_job", {}).get("walltime_ceiling")
           or spec.get("resource_ceiling", {}).get("walltime")
           or "00:10:00")
    try:
        h, m, s = (int(x) for x in hms.split(":"))
        return h * 3600 + m * 60 + s
    except (ValueError, KeyError, AttributeError):
        return 600


def _gpu_ceiling(submission: Dict[str, Any]) -> int:
    spec = submission.get("physics_spec", {})
    gpus = (spec.get("resources", {}).get("run_job", {}).get("gpus")
            or spec.get("resource_ceiling", {}).get("gpus") or 1)
    return int(gpus)


def _gres_gpu_count(tres: str) -> Optional[int]:
    """Sum the gres/gpu= counts in an AllocTRES string; None when no gres
    token is present (missing evidence, not zero)."""
    total = 0
    found = False
    for token in tres.split(","):
        token = token.strip()
        if token.startswith("gres/gpu") and "=" in token:
            try:
                total += int(token.rsplit("=", 1)[1])
            except ValueError:
                return None
            found = True
    return total if found else None


def evaluate_slurm_facts(job: Optional[Dict[str, Any]],
                         submission: Dict[str, Any]) -> List[Dict[str, str]]:
    """Slurm-only checks beyond the shared evaluate_job facts: exactly one
    sacct record for the declared job id (a requeued/rerun job shows more
    than one) and AllocTRES gres within the spec GPU ceiling. Returns no
    checks when sacct has no record (evaluate_job already reports that)."""
    if job is None:
        return []
    checks = []
    records = job.get("records")
    if records is None:
        checks.append(_check("single_job", "unknown",
                             "sacct record count unavailable"))
    else:
        checks.append(_check(
            "single_job",
            "pass" if records == 1 else "fail",
            f"{records} sacct record(s) for the declared job id (expected exactly 1)",
        ))
    gpus = _gres_gpu_count(str(job.get("tres", "")))
    if gpus is None:
        checks.append(_check("job_gres", "unknown",
                             "sacct reports no gres/gpu token in AllocTRES"))
    else:
        ceiling = _gpu_ceiling(submission)
        checks.append(_check(
            "job_gres",
            "pass" if gpus <= ceiling else "fail",
            f"AllocTRES gres/gpu={gpus} vs ceiling {ceiling}",
        ))
    return checks


def run(site: str, submission: Dict[str, Any], thresholds: Dict[str, Any],
        data_root: Optional[Path]) -> Dict[str, Any]:
    run_info = submission.get("run", {})
    scheduler = run_info.get("scheduler", {}) or {}
    kind = scheduler.get("kind", "")
    checks: List[Dict[str, str]] = []

    if kind == "slurm":
        job_id = str(scheduler.get("job_id") or run_info.get("slurm_job_id") or "")
        if job_id:
            job = sacct_job(site, job_id)
            checks.extend(evaluate_job(job, {
                "partition": run_info.get("partition", ""),
                "tasks": run_info.get("resources", {}).get("tasks", 1),
                "nodes": run_info.get("resources", {}).get("nodes", 1),
                "walltime_ceiling_seconds": _walltime_ceiling(submission),
            }))
            checks.extend(evaluate_slurm_facts(job, submission))
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
