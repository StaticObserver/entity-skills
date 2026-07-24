#!/usr/bin/env python3
"""Shared verification helpers for the user-needs evaluation suite.

A need-level verify.py scores ONLY the final objective state (oracle gates,
scheduler facts, router store export, transcript-level claims) — never the
agent's path. This library factors out the common plumbing:

  - oracle invocation / report loading
  - sacct queries (BatchMode ssh; unreachable -> unknown, never fail)
  - router store export via entityctl
  - activities.json (skill_observer) loading
  - submission schema validation
  - transcript scanning (assistant claims, Bash commands)
  - need-report assembly

Check status vocabulary: pass | fail | unknown. Overall: fail > unknown > pass.
Known skill limits are NOT failures: they go into skill_boundary_notes and the
affected check is reported as unknown with the boundary named in its detail.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[3]
E2E = REPO / "evals" / "e2e-neutral-streaming"
ORACLE_PY = E2E / "oracle" / "oracle.py"
SUBMISSION_SCHEMA = E2E / "fixtures" / "submission.schema.json"
ENTITYCTL = REPO / "skills" / "entity-ledger" / "scripts" / "entityctl.py"
SKILL_VARIANT = "skills-v5"
# The contrast group keeps env-build/pgen/nt2py and removes only entity-ledger
# (the eval's independent variable is the router, not the whole bundle).
CONTRAST_VARIANT = "skills-no-router"


# ---------------------------------------------------------------------------
# small helpers

def load_json(path: Any) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check(name: str, status: str, detail: str) -> Dict[str, str]:
    if status not in ("pass", "fail", "unknown"):
        raise ValueError(f"bad check status: {status}")
    return {"name": name, "status": status, "detail": detail}


def overall_of(checks: List[Dict[str, str]]) -> str:
    statuses = {c["status"] for c in checks}
    if "fail" in statuses:
        return "fail"
    if "unknown" in statuses:
        return "unknown"
    return "pass"


def sha256_file(path: Any) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# standard verify.py CLI + context resolution

def parse_args(need_id: str, description: str) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--need-id", default=need_id)
    p.add_argument("--run-name", required=True)
    p.add_argument("--variant", help="fallback when the trace manifest is unreadable")
    p.add_argument("--project", type=Path, help="agent project dir (default: ~/entity-eval-runs/<run>/project)")
    p.add_argument("--router-home", type=Path, help="ENTITY_LEDGER_HOME (default: ~/entity-eval-runs/<run>/controller)")
    p.add_argument("--transcript", type=Path)
    p.add_argument("--activities", type=Path, help="activities.json (default: <trace-run-dir>/activities.json)")
    p.add_argument("--trace-run-dir", type=Path, help="skill_observer run_dir")
    p.add_argument("--oracle-report", type=Path, help="precomputed oracle-report.json")
    p.add_argument("--evidence", type=Path, help="retained evidence dir (offline mode)")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--output", type=Path, required=True, help="need-report.json path")
    p.add_argument("--site", default="siyuan")
    p.add_argument("--expected-ux", type=float, default=None, help="U2: ux target for the rerun")
    return p.parse_args()


def resolve_context(ns: argparse.Namespace) -> Dict[str, Any]:
    """Resolve every input a need-level verify may need, offline-aware."""
    ctx: Dict[str, Any] = {"site": ns.site, "offline": bool(ns.offline)}
    evidence = ns.evidence.expanduser().resolve() if ns.evidence else None
    ctx["evidence"] = evidence

    run_project = Path.home() / "entity-eval-runs" / ns.run_name / "project"
    run_controller = Path.home() / "entity-eval-runs" / ns.run_name / "controller"
    harness = Path.home() / "entity-eval-traces" / ns.run_name
    ctx["harness"] = harness

    project = ns.project or (run_project if run_project.is_dir() else None)
    ctx["project"] = Path(project).expanduser().resolve() if project else None

    router_home = ns.router_home or (run_controller if run_controller.is_dir() else None)
    ctx["router_home"] = Path(router_home).expanduser().resolve() if router_home else None

    # trace run_dir: explicit, else evidence/run_dir.txt, else harness/run_dir.txt
    trace_run_dir = ns.trace_run_dir
    if trace_run_dir is None:
        for base in (evidence, harness):
            if base and (base / "run_dir.txt").is_file():
                candidate = (base / "run_dir.txt").read_text(encoding="utf-8").strip()
                if candidate:
                    trace_run_dir = Path(candidate)
                    break
    ctx["trace_run_dir"] = Path(trace_run_dir).expanduser().resolve() if trace_run_dir else None

    # variant: manifest first, CLI fallback
    variant = None
    if ctx["trace_run_dir"]:
        manifest = load_json(ctx["trace_run_dir"] / "manifest.json")
        if manifest:
            variant = manifest.get("variant")
    ctx["variant"] = variant or ns.variant or "unknown"

    # transcript: explicit, else evidence copies, else harness, else TUI session slug
    transcript = ns.transcript
    candidates = []
    if evidence:
        candidates += [evidence / "transcript.jsonl", evidence / "session-transcript.jsonl"]
    candidates.append(harness / "transcript.jsonl")
    if ctx["project"]:
        slug = str(ctx["project"]).replace("/", "-")
        session_dir = Path.home() / ".claude" / "projects" / slug
        if session_dir.is_dir():
            sessions = sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            candidates += sessions[:1]
    if transcript is None:
        transcript = next((c for c in candidates if c.is_file() and c.stat().st_size > 0), None)
    ctx["transcript"] = Path(transcript).expanduser().resolve() if transcript else None

    # activities.json
    activities = None
    activities_path = ns.activities
    if activities_path is None and ctx["trace_run_dir"]:
        default = ctx["trace_run_dir"] / "activities.json"
        if default.is_file():
            activities_path = default
    if activities_path and Path(activities_path).is_file():
        activities = load_json(activities_path)
    ctx["activities"] = activities

    # oracle report: explicit, else evidence, else project, else run oracle offline
    oracle_report = None
    oracle_candidates = []
    if ns.oracle_report:
        oracle_candidates.append(ns.oracle_report)
    if evidence:
        oracle_candidates.append(evidence / "oracle-report.json")
    if ctx["project"]:
        oracle_candidates.append(ctx["project"] / "oracle-report.json")
    for candidate in oracle_candidates:
        if Path(candidate).is_file():
            oracle_report = load_json(candidate)
            if oracle_report:
                break
    if oracle_report is None:
        data_root = None
        if evidence and (evidence / "oracle-data").is_dir():
            data_root = evidence / "oracle-data"
        if ctx["project"] and (ctx["project"] / "submission.json").is_file():
            oracle_report = run_oracle(
                ctx["project"], transcript=ctx["transcript"],
                data_root=data_root, no_remote=True,
            )
    ctx["oracle_report"] = oracle_report
    return ctx


# ---------------------------------------------------------------------------
# oracle

def run_oracle(project: Any, transcript: Any = None, data_root: Any = None,
               no_remote: bool = True, output: Any = None) -> Optional[dict]:
    """Run the e2e oracle and return its report dict (None on failure)."""
    cmd = [sys.executable, str(ORACLE_PY), "--project", str(project)]
    if transcript:
        cmd += ["--transcript", str(transcript)]
    if data_root:
        cmd += ["--data-root", str(data_root)]
    if no_remote:
        cmd += ["--no-remote"]
    if output is None:
        output = Path(tempfile.mkdtemp(prefix="need-oracle-")) / "oracle-report.json"
    cmd += ["--output", str(output)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return load_json(output)


def oracle_gate(oracle_report: Optional[dict], gate_prefix: str) -> Optional[dict]:
    if not oracle_report:
        return None
    for gate in oracle_report.get("gates", []):
        if gate.get("gate", "").startswith(gate_prefix):
            return gate
    return None


# ---------------------------------------------------------------------------
# cluster / router / observer facts

def sacct_job_summary(site: str, job_ids: List[str]) -> Dict[str, Any]:
    """Query sacct over BatchMode ssh. Unreachable -> {'reachable': False}."""
    if not job_ids:
        return {"reachable": False, "jobs": {}, "detail": "no job ids supplied"}
    remote = "sacct -j {} --format=JobID,JobName,State,ExitCode,Elapsed -P -n".format(
        ",".join(job_ids))
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", site, remote]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"reachable": False, "jobs": {}, "detail": f"ssh failed: {exc}"}
    if proc.returncode != 0:
        return {"reachable": False, "jobs": {},
                "detail": f"sacct rc={proc.returncode}: {proc.stderr.strip()[:200]}"}
    jobs: Dict[str, Any] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("|")
        if len(parts) < 4 or "." in parts[0]:
            continue  # skip batch/extern steps
        jobs[parts[0]] = {"job_name": parts[1], "state": parts[2],
                          "exit_code": parts[3],
                          "elapsed": parts[4] if len(parts) > 4 else ""}
    return {"reachable": True, "jobs": jobs, "detail": f"{len(jobs)} job(s)"}


def read_router_export(router_home: Any) -> Optional[dict]:
    """Export the router store via entityctl. None when no router home exists."""
    if not router_home or not Path(router_home).is_dir():
        return None
    output = Path(tempfile.mkdtemp(prefix="router-export-")) / "store.json"
    cmd = [sys.executable, str(ENTITYCTL), "--router-home", str(router_home),
           "export", "--output", str(output)]
    env = dict(os.environ, ENTITY_LEDGER_HOME=str(router_home))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return load_json(output)


def router_run_identities(export: Optional[dict]) -> List[str]:
    """All current + historical run identity ids across cases."""
    run_ids: List[str] = []
    if not export:
        return run_ids
    for case in export.get("cases", []):
        run_dim = (case.get("identities") or {}).get("run") or {}
        if run_dim.get("current_id"):
            run_ids.append(run_dim["current_id"])
        for item in run_dim.get("items", []):
            rid = item.get("run_id") or item.get("identity_id")
            if rid:
                run_ids.append(rid)
    seen: List[str] = []
    for rid in run_ids:
        if rid not in seen:
            seen.append(rid)
    return seen


def read_activities(trace_run_dir: Any) -> Optional[dict]:
    if not trace_run_dir:
        return None
    return load_json(Path(trace_run_dir) / "activities.json")


def validate_submission_schema(submission_path: Any,
                               schema_path: Any = SUBMISSION_SCHEMA) -> Dict[str, str]:
    name = "submission_schema"
    submission_path = Path(submission_path)
    if not submission_path.is_file():
        return check(name, "fail", f"submission.json missing at {submission_path}")
    submission = load_json(submission_path)
    schema = load_json(schema_path)
    if submission is None:
        return check(name, "fail", f"submission.json is not valid JSON: {submission_path}")
    if schema is None:
        return check(name, "unknown", f"schema unreadable: {schema_path}")
    try:
        import jsonschema
        jsonschema.validate(submission, schema)
    except ImportError:
        required = schema.get("required", [])
        missing = [k for k in required if k not in submission]
        status = "pass" if not missing else "fail"
        return check(name, status,
                     "required keys present (jsonschema unavailable, shallow check)"
                     if not missing else f"missing required keys: {missing}")
    except Exception as exc:  # jsonschema.ValidationError and friends
        return check(name, "fail", f"schema violation: {str(exc)[:300]}")
    return check(name, "pass", f"conforms to {Path(schema_path).name}")


# ---------------------------------------------------------------------------
# transcript scanning

def iter_transcript(path: Any):
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except OSError:
        return


def _message_content(rec: dict) -> List[Any]:
    msg = rec.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("content"), list):
        return msg["content"]
    return []


def assistant_texts(path: Any, last_n: Optional[int] = None) -> List[str]:
    texts: List[str] = []
    if not path:
        return texts
    for rec in iter_transcript(path):
        if rec.get("type") != "assistant":
            continue
        for item in _message_content(rec):
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                texts.append(item["text"])
    return texts[-last_n:] if last_n else texts


def bash_commands(path: Any) -> List[str]:
    commands: List[str] = []
    if not path:
        return commands
    for rec in iter_transcript(path):
        if rec.get("type") != "assistant":
            continue
        for item in _message_content(rec):
            if (isinstance(item, dict) and item.get("type") == "tool_use"
                    and item.get("name") == "Bash"):
                cmd = (item.get("input") or {}).get("command")
                if isinstance(cmd, str):
                    commands.append(cmd)
    return commands


def transcript_search(path: Any, patterns: List[str]) -> List[str]:
    """Return the patterns that match any assistant text or Bash command."""
    haystacks = assistant_texts(path) + bash_commands(path)
    joined = "\n".join(haystacks)
    return [p for p in patterns if re.search(p, joined)]


# ---------------------------------------------------------------------------
# physics recompute (mirrors oracle gate_d; parameterized ux target)

def ux_metrics(data_root: Any, target: float = 0.2) -> Optional[Dict[str, Any]]:
    """Per-snapshot weight-averaged mean ux and max relative drift vs target.

    Independent of the agent's analysis; requires nt2py. Returns None when the
    data cannot be read.
    """
    sys.path.insert(0, str(E2E))
    try:
        from oracle import gate_d_physics  # noqa: PLC0415
        import nt2  # noqa: PLC0415
    except ImportError:
        return None
    try:
        data = nt2.Data(str(data_root))
        particles = data.particles
        times = list(particles.times)
        if not times:
            return None
        per_snapshot: List[float] = []
        for t in times:
            species_means: List[float] = []
            for sp in particles.species:
                snap = particles.sel(t=t, method="nearest").sel(sp=sp).load(cols=["ux", "w"])
                ux_vals = [float(v) for v in snap["ux"].values]
                try:
                    w_vals = [float(v) for v in snap["w"].values]
                except Exception:
                    w_vals = None
                mean, _weighted = gate_d_physics.weighted_mean(ux_vals, w_vals)
                species_means.append(mean)
            per_snapshot.append(sum(species_means) / len(species_means))
        return {
            "target": target,
            "snapshots": len(times),
            "last_mean_ux": per_snapshot[-1],
            "drift_rel_max": max(abs(m - target) / abs(target) for m in per_snapshot),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# report assembly

def finalize(ns: argparse.Namespace, ctx: Dict[str, Any],
             checks: List[Dict[str, str]],
             boundary_notes: List[str],
             extra: Optional[Dict[str, Any]] = None) -> dict:
    activities = ctx.get("activities") or {}
    oracle_report = ctx.get("oracle_report") or {}
    report: Dict[str, Any] = {
        "schema_version": 1,
        "need_id": ns.need_id,
        "run_name": ns.run_name,
        "variant": ctx.get("variant", "unknown"),
        "mode": "offline" if ns.offline else "live",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "checks": checks,
        "overall": overall_of(checks),
        "skill_boundary_notes": boundary_notes,
        "activities_summary": {
            "job_lifecycle": activities.get("job_lifecycle"),
            "skill_adoption": activities.get("skill_adoption"),
        } if activities else None,
        "oracle_overall": oracle_report.get("overall"),
    }
    if ns.offline:
        report["offline_note"] = (
            "graded from retained evidence; live cluster/router facts were "
            "re-queried only where reachable, missing inputs are reported as "
            "unknown with the reason in the check detail")
    if extra:
        report.update(extra)
    output = Path(ns.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"overall: {report['overall']}")
    for c in checks:
        marker = {"pass": "✓", "fail": "✗", "unknown": "?"}[c["status"]]
        print(f"  {marker} {c['name']}: {c['detail'][:120]}")
    for note in boundary_notes:
        print(f"  [boundary] {note}")
    print(f"report: {output}")
    return report
