"""Gate E: analysis reproducibility (streaming-official variant).

Same contract as the neutral-streaming gate, plus the 0.7.0 script-library
convention: the rerunnable script may live in analysis/ or in the project
analysis/scripts/ library. A full clean-room re-run stays out of scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def _check(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def run(project: Path, submission: Dict[str, Any]) -> Dict[str, Any]:
    project = Path(project)
    checks: List[Dict[str, str]] = []

    report_rel = submission.get("analysis", {}).get("report", "analysis/report.md")
    report_path = project / report_rel
    if not report_path.is_file():
        candidates = sorted(project.glob("analysis/*.md"))
        report_path = candidates[0] if candidates else report_path
    checks.append(_check(
        "analysis_report_exists",
        "pass" if report_path.is_file() else "fail",
        str(report_path) if report_path.is_file() else "no analysis report found",
    ))

    script_rel = submission.get("analysis", {}).get("script", "")
    script_path = project / script_rel if script_rel else None
    if script_path is not None and not script_path.is_file():
        candidates = sorted(project.glob("analysis/*.py")) \
            + sorted(project.glob("analysis/scripts/**/*.py", recursive=True))
        script_path = candidates[0] if candidates else script_path
    elif script_path is None:
        candidates = sorted(project.glob("analysis/*.py")) \
            + sorted(project.glob("analysis/scripts/**/*.py", recursive=True))
        script_path = candidates[0] if candidates else None
    checks.append(_check(
        "analysis_script_exists",
        "pass" if script_path is not None and script_path.is_file() else "fail",
        str(script_path) if script_path is not None and script_path.is_file()
        else "no rerunnable analysis script found (analysis/ or analysis/scripts/)",
    ))

    if report_path.is_file():
        body = report_path.read_text(encoding="utf-8", errors="replace")
        claims = submission.get("analysis", {})
        missing = [
            key for key, value in claims.items()
            if key not in ("report", "script")
            and isinstance(value, str) and value and value not in body
        ]
        checks.append(_check(
            "claims_consistent_with_report",
            "pass" if not missing else "unknown",
            "all submission analysis claims appear in the report"
            if not missing else f"claims not found verbatim in report: {missing}",
        ))

    statuses = {c["status"] for c in checks}
    status = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
    return {"gate": "E-analysis", "status": status, "checks": checks}
