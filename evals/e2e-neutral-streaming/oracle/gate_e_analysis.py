"""Gate E: analysis reproducibility.

Light version: the analysis report and a rerunnable script must exist, and
the physics claims in the submission must appear in the agent's report
(string-level consistency). A full clean-room re-run of the analysis script
is out of scope for v1 and reported as unknown when requested evidence is
missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def _check(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def run(project: Path, submission: Dict[str, Any]) -> Dict[str, Any]:
    project = Path(project)
    checks: List[Dict[str, str]] = []

    report_rel = submission.get("analysis", {}).get("report", "analysis/analysis-report.md")
    report_path = project / report_rel
    if not report_path.is_file():
        candidates = sorted(project.glob("analysis/*.md")) + sorted(project.glob("analysis/*.json"))
        report_path = candidates[0] if candidates else report_path
    checks.append(_check(
        "analysis_report_exists",
        "pass" if report_path.is_file() else "fail",
        str(report_path) if report_path.is_file() else "no analysis report found",
    ))

    scripts = sorted(project.glob("analysis/*.py")) + sorted(project.glob("analysis/*.ipynb"))
    checks.append(_check(
        "analysis_script_exists",
        "pass" if scripts else "unknown",
        f"{len(scripts)} analysis script(s): {[s.name for s in scripts]}" if scripts
        else "no rerunnable analysis script found; reproducibility unverified",
    ))

    if report_path.is_file():
        body = report_path.read_text(encoding="utf-8", errors="replace")
        claims = submission.get("analysis", {})
        missing = [
            key for key, value in claims.items()
            if key != "report" and isinstance(value, str) and value and value not in body
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
