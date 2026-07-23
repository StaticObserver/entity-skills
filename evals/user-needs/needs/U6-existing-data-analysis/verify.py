#!/usr/bin/env python3
"""U6 (existing-data analysis) verification.

Checks: analysis deliverables exist; the ux number in the report matches an
independent nt2py recompute on the data root; analyze.py actually reruns
against the data root; and the data root stayed free of analysis artifacts.
Analysis is NOT a router Goal — no router checks here by design.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verify_common as vc  # noqa: E402

UX_ABS_TOL = 0.02   # absolute slack on the reported mean ux
UX_REL_TOL = 0.10   # ... or 10% relative, whichever is larger
RERUN_TIMEOUT = 900
FLOAT_RE = re.compile(r"[-+]?\d+\.\d+(?:[eE][-+]?\d+)?")
ANALYSIS_ARTIFACT_RES = re.compile(
    r"(^|/)(analysis/|report\.md$|analyze.*\.py$|.*\.(png|pdf|ipynb)$)")


def _project(ctx) -> Path | None:
    if ctx["project"]:
        return ctx["project"]
    if ctx["evidence"] and (ctx["evidence"] / "project-snapshot").is_dir():
        return ctx["evidence"] / "project-snapshot"
    return None


def _data_root(ctx) -> Path | None:
    # offline: retained evidence; live: the harness oracle-data fetch dir.
    for base in (ctx["evidence"], ctx.get("harness")):
        if base and (base / "oracle-data").is_dir():
            return base / "oracle-data"
    return None


def main() -> int:
    ns = vc.parse_args("U6", "U6 existing-data-analysis verification")
    ctx = vc.resolve_context(ns)
    checks = []
    project = _project(ctx)
    data_root = _data_root(ctx)

    # 1. analysis deliverables exist (Gate E style)
    if project is None:
        checks.append(vc.check("analysis_artifacts_exist", "unknown",
                               "no project (or evidence project-snapshot) available"))
    else:
        report = project / "analysis" / "report.md"
        if not report.is_file():
            candidates = sorted((project / "analysis").glob("*.md")) if (project / "analysis").is_dir() else []
            report = candidates[0] if candidates else report
        scripts = sorted((project / "analysis").glob("*.py")) if (project / "analysis").is_dir() else []
        missing = []
        if not report.is_file():
            missing.append("report.md")
        if not scripts:
            missing.append("analyze.py")
        checks.append(vc.check(
            "analysis_artifacts_exist", "fail" if missing else "pass",
            f"missing: {missing}" if missing else f"report={report.name}, scripts={[s.name for s in scripts]}"))

    # 2. reported ux matches an independent recompute
    recomputed = vc.ux_metrics(data_root, target=0.2) if data_root else None
    if recomputed is None or project is None or not (project / "analysis").is_dir():
        reason = ("no data root for recompute" if data_root is None
                  else "ux recompute failed (nt2py unavailable or unreadable data)"
                  if recomputed is None else "no analysis report to compare")
        checks.append(vc.check("ux_value_consistent", "unknown", reason))
    else:
        reports = sorted((project / "analysis").glob("*.md"))
        body = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in reports)
        truth = recomputed["last_mean_ux"]
        ux_numbers = []
        for line in body.splitlines():
            if re.search(r"\bux\b|streaming|drift", line, re.IGNORECASE):
                for token in FLOAT_RE.findall(line):
                    value = float(token)
                    if 0.3 * truth <= value <= 3 * truth:
                        ux_numbers.append(value)
        tol = max(UX_ABS_TOL, UX_REL_TOL * abs(truth))
        close = [v for v in ux_numbers if abs(v - truth) <= tol]
        if close:
            checks.append(vc.check(
                "ux_value_consistent", "pass",
                f"report ux {close[0]:.4f} within {tol:.4f} of recomputed mean {truth:.4f}"))
        elif ux_numbers:
            checks.append(vc.check(
                "ux_value_consistent", "fail",
                f"report ux candidates {ux_numbers} all deviate >{tol:.4f} from recomputed {truth:.4f}"))
        else:
            checks.append(vc.check(
                "ux_value_consistent", "unknown",
                f"no ux-like number found in report (recomputed mean {truth:.4f})"))

    # 3. analyze.py reruns against the data root
    scripts = sorted((project / "analysis").glob("*.py")) if project and (project / "analysis").is_dir() else []
    if not scripts or data_root is None:
        checks.append(vc.check(
            "analyze_rerunnable", "unknown",
            "no analysis script to rerun" if not scripts else "no local data root for the rerun"))
    else:
        script = scripts[0]
        attempts = [[sys.executable, str(script), str(data_root)],
                    [sys.executable, str(script), "--data-root", str(data_root)]]
        outcome = None
        for argv in attempts:
            try:
                proc = subprocess.run(argv, capture_output=True, text=True,
                                      timeout=RERUN_TIMEOUT, cwd=script.parent)
            except subprocess.TimeoutExpired:
                outcome = ("fail", f"rerun timed out after {RERUN_TIMEOUT}s: {' '.join(argv)}")
                continue
            if proc.returncode == 0:
                outcome = ("pass", f"exit 0: {' '.join(argv)}")
                break
            outcome = ("fail", f"exit {proc.returncode}: {' '.join(argv)} "
                               f"(stderr: {proc.stderr.strip()[:160]})")
        checks.append(vc.check("analyze_rerunnable", outcome[0], outcome[1]))

    # 4. data root stayed read-only (no analysis artifacts inside it)
    if data_root is None:
        checks.append(vc.check("data_root_readonly", "unknown",
                               "no local data root to inspect"))
    else:
        offenders = [str(p.relative_to(data_root)) for p in data_root.rglob("*")
                     if p.is_file() and ANALYSIS_ARTIFACT_RES.search(str(p.relative_to(data_root)))]
        checks.append(vc.check(
            "data_root_readonly", "fail" if offenders else "pass",
            f"analysis artifacts inside data root: {offenders[:10]}" if offenders
            else f"no analysis artifacts under {data_root}"))

    vc.finalize(ns, ctx, checks, [])
    return 0


if __name__ == "__main__":
    sys.exit(main())
