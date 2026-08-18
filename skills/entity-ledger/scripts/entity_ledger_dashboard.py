#!/usr/bin/env python3
"""Project dashboard: readiness board, run ledger and derived next steps.

Read-only presentation over controller-local Case facts.  The board answers
"where is the project", the deriver answers "what is next"; both are computed
from stored facts and never stored themselves.  Local probes are limited to
the project checkout (git revision, PGen confirmation records).  This module
is standard-library only and Python 3.6 compatible.
"""

from __future__ import print_function

import os

from entity_ledger_common import find_identity, load_simulation_confirmation
from entity_ledger_facts import _git_revision
from entity_ledger_store import StoreError
from entity_ledger_workspace import (
    WorkspaceError,
    load_project_yaml,
    workspace_for_ledger_home,
)


BOARD_ORDER = ["source", "pgen", "build", "run", "data", "analysis"]


def _pgen_cell(project_root):
    """PGen readiness from local confirmation records: a TOML input counts as
    confirmed only when its ``.decisions.json`` still matches the file bytes.
    Scans the project root and, for workspace projects, the registered
    source authority directory (project.yaml ``source``)."""
    if not os.path.isdir(project_root):
        return {"state": "unknown", "detail": "project root not on this machine"}
    scan_roots = [project_root]
    try:
        source_rel = load_project_yaml(project_root).get("source") or ""
    except WorkspaceError:
        source_rel = ""
    if source_rel:
        source_dir = os.path.join(project_root, source_rel)
        if (os.path.isdir(source_dir)
                and os.path.realpath(source_dir) != os.path.realpath(project_root)):
            scan_roots.append(source_dir)
    confirmed = []
    unconfirmed = []
    for root in scan_roots:
        prefix = "" if root == project_root else (
            os.path.relpath(root, project_root) + "/")
        for name in sorted(os.listdir(root)):
            if not name.endswith(".toml"):
                continue
            unused_record, matches = load_simulation_confirmation(
                os.path.join(root, name))
            if matches:
                confirmed.append(prefix + name)
            else:
                unconfirmed.append(prefix + name)
    if confirmed and not unconfirmed:
        return {"state": "confirmed", "detail": ", ".join(confirmed)}
    if confirmed:
        return {"state": "partial",
                "detail": "confirmed %s; unconfirmed %s" % (
                    ", ".join(confirmed), ", ".join(unconfirmed))}
    if unconfirmed:
        return {"state": "unconfirmed", "detail": ", ".join(unconfirmed)}
    return {"state": "unknown",
            "detail": "no TOML inputs under project root or source authority"}


def _source_cell(case, project_root, alerts):
    source = case.get("source", {})
    authority = source.get("authority") or {}
    if not authority:
        return {"state": "missing", "detail": "source not materialized yet"}
    revision = source.get("revision") or {}
    label = ""
    if revision.get("kind") == "git":
        label = (revision.get("commit") or "")[:8] + " @ "
    detail = "%s%s:%s" % (label, authority.get("site_id", "?"),
                          authority.get("path", "?"))
    if revision.get("kind") == "git" and os.path.isdir(project_root):
        current = _git_revision(project_root)
        if current.get("kind") == "git":
            if current.get("commit") != revision.get("commit"):
                alerts.append(
                    "source recorded as %s, current HEAD is %s — build/run may be stale"
                    % ((revision.get("commit") or "")[:8],
                       (current.get("commit") or "")[:8]))
                detail += " (HEAD changed)"
            elif current.get("dirty") and not revision.get("dirty"):
                detail += " (uncommitted changes in working tree)"
    return {"state": "established", "detail": detail}


def _build_cell(case, current):
    build_id = current.get("build_id", "")
    payload = find_identity(
        case.get("identities", {}).get("build", {}).get("items", []), build_id)
    if not build_id or payload is None:
        return {"state": "missing", "detail": "—"}
    outputs = payload.get("outputs", [])
    locator = outputs[0].get("locator", {}) if outputs else {}
    name = os.path.basename(locator.get("path", "")) or build_id
    return {"state": payload.get("status", "verified"),
            "detail": "%s @ %s" % (name, locator.get("site_id", "?"))}


def _scheduler_brief(payload):
    scheduler = payload.get("scheduler", {})
    if scheduler.get("job_id"):
        return "job %s" % scheduler["job_id"]
    if scheduler.get("pid"):
        return "pid %s" % scheduler["pid"]
    return ""


def _run_cell(case, current, live):
    run_id = current.get("run_id", "")
    payload = find_identity(
        case.get("identities", {}).get("run", {}).get("items", []), run_id)
    if not run_id or payload is None:
        return {"state": "none", "detail": "—"}
    state = payload.get("status", "unknown")
    brief = _scheduler_brief(payload)
    detail = "%s @ %s" % (run_id, payload.get("site_id", "?"))
    if brief:
        detail += " (%s)" % brief
    if payload.get("exit_code") is not None:
        detail += "; exit %s" % payload["exit_code"]
    if payload.get("exit_anomaly"):
        detail += "; known benign teardown abort"
    if payload.get("abort"):
        detail += "; aborted manually (%s)" % payload["abort"].get("reason", "")
    if live:
        live_state = live.get("state", "")
        if live_state == "EXITED":
            # A non-zero live exit means the run failed: mapping it to plain
            # "exited" would make the deriver suggest inventorying the
            # outputs of a failed run.
            state = "failed" if live.get("exit_code") else "exited"
            detail += "; exit %s" % live.get("exit_code", "?")
        elif live_state == "RUNNING":
            state = "running"
        elif live_state == "NOT_FOUND":
            state = "gone"
        elif live_state in {"UNKNOWN", ""} and live.get("warning"):
            detail += "; live probe unavailable"
        elif live_state:
            detail += "; %s" % live_state
    return {"state": state, "detail": detail}


def _data_cell(case, current):
    data_id = current.get("data_id", "")
    payload = find_identity(
        case.get("identities", {}).get("data", {}).get("items", []), data_id)
    if not data_id or payload is None:
        return {"state": "missing", "detail": "—"}
    return {"state": payload.get("status", "inventoried"),
            "detail": "%s files" % payload.get("files", "?")}


def _analysis_cell(case, current):
    """Readiness of the current analysis identity.  Staleness is derived at
    read time (the board is always computed from stored facts): an analysis
    is stale exactly when its parent data is no longer the current data."""
    analysis_id = current.get("analysis_id", "")
    payload = find_identity(
        case.get("identities", {}).get("analysis", {}).get("items", []),
        analysis_id)
    if not analysis_id or payload is None:
        return {"state": "none", "detail": "—"}
    parent_data = payload.get("parents", {}).get("data_id", "")
    stale = bool(parent_data) and parent_data != current.get("data_id", "")
    detail = "%s @ %s" % (payload.get("script", analysis_id),
                          payload.get("site_id", "?"))
    if payload.get("manifest"):
        detail += " (manifest %s)" % payload["manifest"]
    if payload.get("env_stack"):
        detail += " (env %s)" % payload["env_stack"]
    if payload.get("hardcoded_paths"):
        detail += "; script has hardcoded paths (legacy, parameterization recommended)"
    if stale:
        detail += "; parent data is no longer current"
    return {"state": "stale" if stale else "established", "detail": detail}


def derive_next_steps(board, run_id):
    """The deriver: map board facts to suggested next steps.  These rules
    replace a stored state machine — they are computed on every read and can
    never drift from the recorded facts."""
    steps = []
    run_state = board["run"]["state"]
    if run_state in {"exited", "completed"} and board["data"]["state"] == "missing":
        steps.append("run %s reached a terminal state; inventory outputs with "
                     "entityctl record data" % run_id)
    elif run_state == "failed":
        steps.append("run %s failed; check run_root logs to find the cause, "
                     "fix it and rerun" % run_id)
    elif run_state == "aborted":
        steps.append("run %s was aborted manually; to continue, derive a new "
                     "run with changed inputs/parameters and rerun" % run_id)
    elif run_state in {"submitted", "running"}:
        steps.append("run %s is running; track the terminal state with "
                     "status --live or record run-exit" % run_id)
    elif run_state == "prepared":
        steps.append("run %s is prepared; submit with entityctl record run-launch"
                     % run_id)
    elif run_state == "gone":
        steps.append("run %s record disagrees with the backend (job_gone); "
                     "check for out-of-band changes" % run_id)
    if board["pgen"]["state"] in {"unconfirmed", "partial"}:
        steps.append("confirm simulation parameters: "
                     "pgen_preflight.py confirm <input> --by <actor>")
    if board["build"]["state"] == "missing" and board["source"]["state"] != "missing":
        steps.append("build: compile with entity-env-build, then register with "
                     "entityctl record build")
    if board["data"]["state"] == "inventoried":
        steps.append("data inventoried; analyze with entity-nt2py")
    if not steps:
        steps.append("no blockers; proceed per the research goal (edit the PGen, "
                     "rerun with new parameters, or analyze the data)")
    return steps[:4]


def _intent_drift(store, case, db_intent):
    """Detect a hand-edited intent.md that diverged from the db intent (the
    db is the authority).  Returns the drift note or ""."""
    if not db_intent:
        return ""
    workspace = workspace_for_ledger_home(store.home)
    if not workspace or not case.get("project_uid"):
        return ""
    try:
        project = store.get_project(case["project_uid"])
    except StoreError:
        return ""
    path = os.path.join(
        workspace, "projects", project["slug"], "cases",
        case["case_id"], "intent.md")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r") as handle:
            text = handle.read().strip()
    except (IOError, OSError):
        return ""
    if text == db_intent:
        return ""
    return "intent.md diverged from the db record (db is authoritative): %s" % path


def build_dashboard(store, project_root, status=None, case_slug=None):
    """Assemble the dashboard from controller-local facts.  ``status`` is an
    optional status_for_project result supplying live probes and divergences."""
    case = store.resolve_project(project_root, case_slug)
    current = case.get("current", {})
    live = (status or {}).get("live")
    alerts = []
    for item in (status or {}).get("divergences", []):
        alerts.append("out-of-band change %s: %s" % (item.get("kind", "?"),
                                                     item.get("detail", "")))
    board = {
        "source": _source_cell(case, case.get("project_root") or project_root, alerts),
        "pgen": _pgen_cell(case.get("project_root") or project_root),
        "build": _build_cell(case, current),
        "run": _run_cell(case, current, live),
        "data": _data_cell(case, current),
        "analysis": _analysis_cell(case, current),
    }
    ledger = []
    for item in case.get("identities", {}).get("run", {}).get("items", []):
        ledger.append({
            "run_id": item.get("id", ""),
            "site_id": item.get("site_id", ""),
            "status": item.get("status", "unknown"),
            "scheduler": _scheduler_brief(item),
        })
    # The intent is the only stored pointer (not derivable): it is written
    # explicitly into current["intent"] by entityctl record intent; when it
    # has not been written the dashboard shows "not recorded"
    intent_record = current.get("intent") or {}
    intent = intent_record.get("text") or "not recorded"
    if intent_record.get("recorded_at") and intent_record.get("text"):
        intent += " (recorded at %s)" % intent_record["recorded_at"]
    pending = list(alerts)
    drift = _intent_drift(store, case, intent_record.get("text", ""))
    if drift:
        pending.append(drift)
    if board["pgen"]["state"] in {"unconfirmed", "partial"}:
        pending.append("simulation parameters unconfirmed: %s" % board["pgen"]["detail"])
    project = None
    if case.get("project_uid"):
        project = store.get_project(case["project_uid"])
    return {
        "schema_version": 1, "kind": "entity-ledger.dashboard",
        "state_mutated": False,
        "remote_calls": (status or {}).get("remote_calls", 0),
        "case_uid": case["case_uid"], "case_id": case.get("case_id", ""),
        "project_uid": case.get("project_uid"),
        "project": project,
        "project_root": case.get("project_root") or project_root,
        "updated_at": case.get("updated_at", ""),
        "intent": intent, "board": board, "runs": ledger,
        "pending": pending,
        "next_steps": derive_next_steps(board, current.get("run_id", "")),
        "live": live,
    }


def _project_line(dashboard):
    project = dashboard.get("project")
    if project:
        return "Project  %s (%s)" % (project["slug"], dashboard["project_root"])
    return "Project  %s" % dashboard["project_root"]


def render_text(dashboard):
    """Compact human-readable rendering; normal output stays well under 4 KiB."""
    lines = [
        "Case %s (%s)  updated %s" % (dashboard["case_id"],
                                      dashboard["case_uid"],
                                      dashboard["updated_at"] or "?"),
        _project_line(dashboard),
        "Goal  %s" % dashboard["intent"],
        "",
        "Readiness board",
    ]
    for name in BOARD_ORDER:
        cell = dashboard["board"][name]
        lines.append("  %-9s %-12s %s" % (name, cell["state"], cell["detail"]))
    if dashboard["runs"]:
        lines += ["", "Run ledger"]
        for item in dashboard["runs"][-5:]:
            brief = ("  %s" % item["scheduler"]) if item["scheduler"] else ""
            lines.append("  %-22s %-10s %s%s" % (
                item["run_id"], item["status"], item["site_id"], brief))
    if dashboard["pending"]:
        lines += ["", "Pending"]
        for item in dashboard["pending"]:
            lines.append("  - %s" % item)
    lines += ["", "Suggested next steps"]
    for index, step in enumerate(dashboard["next_steps"], 1):
        lines.append("  %d. %s" % (index, step))
    live = dashboard.get("live")
    if live:
        lines += ["", "Live probe: %s (%s, %d remote calls)" % (
            live.get("state", "?"), live.get("observed_at", "?"),
            dashboard["remote_calls"])]
    return "\n".join(lines)
