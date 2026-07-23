#!/usr/bin/env python3
"""U2 (parameter change rerun, skills variant only) verification.

Checks: the new TOML got its own preflight decision record (input_sha256
match), old and new run identities are distinct, the old run root is
untouched, and the new data actually streams at the new ux target
(gate_d-style recompute with the expected value as a parameter).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verify_common as vc  # noqa: E402

UX_TOLERANCE = 0.05  # mirrors thresholds.json ux_drift_relative_max


def _decisions_records(project: Path):
    records = []
    for path in sorted(project.rglob("*.decisions.json")):
        doc = vc.load_json(path)
        if doc and doc.get("input_sha256"):
            records.append((path, doc))
    return records


def _run_data_roots(export: dict):
    """(identity_id, data_root) pairs from run-dimension identity payloads."""
    roots = []
    for case in export.get("cases", []):
        run_dim = (case.get("identities") or {}).get("run") or {}
        for item in run_dim.get("items", []):
            if not isinstance(item, dict):
                continue
            root = item.get("data_root") or (item.get("output") or {}).get("data_root")
            rid = item.get("run_id") or item.get("identity_id") or run_dim.get("current_id")
            if root:
                roots.append((rid, root))
    return roots


def main() -> int:
    ns = vc.parse_args("U2", "U2 parameter-rerun verification")
    ctx = vc.resolve_context(ns)
    checks = []
    notes = []
    expected_ux = ns.expected_ux if ns.expected_ux is not None else 0.3

    # 1. new TOML has a matching preflight decision record
    if not ctx["project"]:
        checks.append(vc.check("new_decisions_digest", "unknown", "no project directory available"))
    else:
        records = _decisions_records(ctx["project"])
        tomls = {vc.sha256_file(t): t for t in ctx["project"].rglob("*.toml")}
        matched = [(p, d, tomls[d["input_sha256"]]) for p, d in records
                   if d["input_sha256"] in tomls]
        new_matches = [(p, d, t) for p, d, t in matched
                       if "0.3" in t.read_text(encoding="utf-8", errors="replace")]
        if new_matches:
            p, _d, t = new_matches[-1]
            checks.append(vc.check(
                "new_decisions_digest", "pass",
                f"{p.name} input_sha256 matches new TOML {t.name} "
                f"({len(records)} decision record(s) total)"))
        elif matched:
            checks.append(vc.check(
                "new_decisions_digest", "fail",
                "decision records match only the old TOML; no record digests a ux=0.3 TOML"))
        else:
            checks.append(vc.check(
                "new_decisions_digest", "fail",
                f"no .decisions.json record matches any project TOML "
                f"({len(records)} record(s), {len(tomls)} TOML(s))"))

    # 2. old and new run identities differ
    export = vc.read_router_export(ctx["router_home"])
    if export is None:
        checks.append(vc.check("distinct_run_ids", "unknown",
                               "router store unreadable/missing"))
        data_roots = []
    else:
        run_ids = vc.router_run_identities(export)
        data_roots = _run_data_roots(export)
        if len(run_ids) >= 2:
            checks.append(vc.check("distinct_run_ids", "pass",
                                   f"{len(run_ids)} distinct run identities"))
        elif run_ids:
            checks.append(vc.check("distinct_run_ids", "fail",
                                   f"only one run identity after rerun: {run_ids}"))
        else:
            checks.append(vc.check("distinct_run_ids", "fail",
                                   "no run identities in router export"))

    # 3. old run root preserved (snapshot taken by setup.sh, re-listed now)
    run_dir = ctx["project"].parent if ctx["project"] else None
    snapshot = run_dir / "u2-old-root-snapshot.txt" if run_dir else None
    old_root_file = run_dir / "u2-prior-data-root.txt" if run_dir else None
    if not snapshot or not snapshot.is_file():
        checks.append(vc.check("old_run_root_preserved", "unknown",
                               "no setup-time snapshot (site unreachable at setup, or live run dir gone)"))
    else:
        old_root = old_root_file.read_text(encoding="utf-8").strip()
        try:
            proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ctx["site"],
                 f"find '{old_root}' -type f -printf '%p %T@ %s\\n' | sort"],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            proc = None
            detail = f"ssh failed: {exc}"
        if proc is None or proc.returncode != 0:
            checks.append(vc.check("old_run_root_preserved", "unknown",
                                   f"siyuan unreachable at grade time ({detail if proc is None else proc.stderr.strip()[:160]})"))
        elif proc.stdout == snapshot.read_text(encoding="utf-8"):
            checks.append(vc.check("old_run_root_preserved", "pass",
                                   f"old root identical to setup snapshot ({old_root})"))
        else:
            checks.append(vc.check("old_run_root_preserved", "fail",
                                   f"old root changed since setup snapshot ({old_root})"))

    # 4. new data streams at the new ux target (independent recompute)
    data_root = None
    if ctx["evidence"] and (ctx["evidence"] / "oracle-data").is_dir():
        data_root = ctx["evidence"] / "oracle-data"
    elif data_roots and not ctx["offline"]:
        # newest run identity's data root; fetch it locally for the recompute
        _rid, remote_root = data_roots[-1]
        fetch_dir = Path(tempfile.mkdtemp(prefix="u2-data-")) / "oracle-data"
        fetch_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["rsync", "-a", f"{ctx['site']}:{remote_root}/", f"{fetch_dir}/"],
            capture_output=True, text=True, timeout=1800)
        if proc.returncode == 0:
            data_root = fetch_dir
    if data_root is None:
        checks.append(vc.check("gate_d_ux_new_target", "unknown",
                               "no new-run data root available for recompute"))
    else:
        metrics = vc.ux_metrics(data_root, target=expected_ux)
        if metrics is None:
            checks.append(vc.check("gate_d_ux_new_target", "unknown",
                                   f"ux recompute failed on {data_root} (nt2py unavailable or unreadable data)"))
        else:
            ok = metrics["drift_rel_max"] <= UX_TOLERANCE
            checks.append(vc.check(
                "gate_d_ux_new_target", "pass" if ok else "fail",
                f"max |mean_ux - {expected_ux}| / {expected_ux} = {metrics['drift_rel_max']:.4f} "
                f"over {metrics['snapshots']} snapshots (tolerance {UX_TOLERANCE})"))

    vc.finalize(ns, ctx, checks, notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
