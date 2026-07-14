#!/usr/bin/env python3
"""Deterministic state controller bundled with the Entity Router skill.

The implementation intentionally uses only the Python standard library and is
compatible with Python 3.6 for older HPC login nodes.
"""

from __future__ import print_function

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager


SCHEMA_VERSION = 2
CASE_STATUSES = {"active", "suspended", "blocked", "complete", "archived"}
WORKFLOW_STATUSES = {"active", "suspended", "blocked", "complete"}
ACTION_TERMINAL = {"completed", "failed", "blocked", "cancelled"}
READINESS_STATUSES = {
    "orientation": {"unresolved", "ready"},
    "pgen": {"absent", "designing", "implemented", "verified", "stale", "failed"},
    "build": {"absent", "planned", "running", "pass", "fail", "stale"},
    "run": {
        "none", "prepared", "submitted", "running", "completed", "failed",
        "stopped", "stale"
    },
    "data": {"absent", "partial", "ready", "corrupt", "unknown"},
    "analysis": {"none", "planned", "running", "complete", "stale"},
}


class StateError(Exception):
    pass


def now_utc():
    value = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def absolute(path):
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def is_within(path, root):
    path = absolute(path)
    root = absolute(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_for(path):
    path = absolute(path)
    item = {"path": path, "observed_at": now_utc()}
    if os.path.isfile(path):
        item["kind"] = "file"
        item["sha256"] = sha256_file(path)
    elif os.path.isdir(path):
        item["kind"] = "directory"
    else:
        item["kind"] = "missing"
    return item


def atomic_write_json(path, value):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def append_event(case_dir, event_type, revision, details=None):
    event = {
        "time": now_utc(),
        "event": event_type,
        "revision": revision,
        "details": details or {},
    }
    path = os.path.join(case_dir, "_case", "events.jsonl")
    with open(path, "a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def save_workflow_snapshot(case_dir, state, label):
    workflow_id = state["workflow"].get("workflow_id", "workflow")
    safe_id = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in workflow_id
    )
    filename = "%s-r%s-%s.json" % (safe_id, state["revision"], label)
    path = os.path.join(case_dir, "_case", "history", filename)
    atomic_write_json(path, state)
    return path


def state_path(case_dir):
    return os.path.join(case_dir, "_case", "case.json")


def load_state(case_dir):
    path = state_path(case_dir)
    if not os.path.isfile(path):
        raise StateError("case state not found: %s" % path)
    with open(path, "r") as handle:
        state = json.load(handle)
    validate_state(state, case_dir)
    return state


@contextmanager
def locked_case(case_dir):
    control_dir = os.path.join(case_dir, "_case")
    if not os.path.isdir(control_dir):
        raise StateError("case control directory not found: %s" % control_dir)
    lock_path = os.path.join(control_dir, ".lock")
    with open(lock_path, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def require_revision(state, expected):
    if expected is None:
        raise StateError("--expected-revision is required for mutations")
    if state["revision"] != expected:
        raise StateError(
            "revision conflict: expected %s, current %s" %
            (expected, state["revision"])
        )


def readiness(status, evidence=None):
    return {"status": status, "evidence": evidence or []}


def allowed_actions(state):
    if state["case_status"] in {"suspended", "archived"}:
        return []
    if state["workflow"]["status"] in {"suspended", "complete"}:
        return []
    if state["workflow"].get("active_action_id"):
        return []

    result = []
    r = state["readiness"]
    if r["orientation"]["status"] != "ready":
        return ["orient"]

    pgen = r["pgen"]["status"]
    build = r["build"]["status"]
    run = r["run"]["status"]
    data = r["data"]["status"]
    analysis = r["analysis"]["status"]

    if pgen in {"absent", "designing", "stale", "failed"}:
        result.extend(["pgen.design", "pgen.fix"])
    if pgen in {"implemented", "verified"}:
        result.extend(["pgen.verify", "pgen.edit"])
    if pgen == "verified" and build in {"absent", "planned", "fail", "stale"}:
        result.extend(["build.plan", "build.compile"])
    if build == "running":
        result.append("build.monitor")
    if pgen == "verified" and build == "pass" and run in {"none", "stale"}:
        result.append("run.prepare")
    if run == "prepared":
        result.append("run.launch")
    if run in {"submitted", "running"}:
        result.append("run.monitor")
    if run in {"completed", "failed", "stopped"}:
        result.append("run.resume")
    if run == "failed" or build == "fail" or pgen == "failed":
        result.append("failure.triage")
    if data in {"partial", "ready", "unknown"}:
        result.append("data.inspect")
    if data in {"partial", "ready"} and analysis in {"none", "planned", "stale"}:
        result.append("analysis.run")
    return sorted(set(result))


def set_allowed_actions(state):
    actions = allowed_actions(state)
    state["workflow"]["allowed_actions"] = actions
    if state["workflow"].get("active_action_id"):
        return
    current_next = state["workflow"].get("next_action", "")
    if current_next not in actions:
        state["workflow"]["next_action"] = actions[0] if actions else ""


def validate_state(state, case_dir=None):
    required = {
        "schema_version", "revision", "case_id", "case_status", "identity",
        "memory", "scope", "workflow", "readiness"
    }
    missing = sorted(required.difference(state))
    if missing:
        raise StateError("case.json missing keys: %s" % ", ".join(missing))
    if state["schema_version"] != SCHEMA_VERSION:
        raise StateError(
            "unsupported schema_version %r; expected %s" %
            (state["schema_version"], SCHEMA_VERSION)
        )
    if not isinstance(state["revision"], int) or state["revision"] < 0:
        raise StateError("revision must be a non-negative integer")
    if state["case_status"] not in CASE_STATUSES:
        raise StateError("invalid case_status: %s" % state["case_status"])
    workflow = state["workflow"]
    if workflow.get("status") not in WORKFLOW_STATUSES:
        raise StateError("invalid workflow status: %s" % workflow.get("status"))
    for dimension, statuses in READINESS_STATUSES.items():
        if dimension not in state["readiness"]:
            raise StateError("missing readiness dimension: %s" % dimension)
        current = state["readiness"][dimension].get("status")
        if current not in statuses:
            raise StateError("invalid readiness %s=%s" % (dimension, current))
    if case_dir is not None:
        recorded = state["scope"].get("case_dir", "")
        if recorded and absolute(recorded) != absolute(case_dir):
            raise StateError("case path does not match recorded scope.case_dir")


def resolve_case(value):
    path = absolute(value)
    if os.path.isfile(os.path.join(path, "_case", "case.json")):
        return path
    raise StateError("not an Entity case directory: %s" % path)


def parse_key_value(items, label):
    result = {}
    for item in items or []:
        if "=" not in item:
            raise StateError("%s must use NAME=VALUE: %s" % (label, item))
        key, value = item.split("=", 1)
        if not key or not value:
            raise StateError("%s must use non-empty NAME=VALUE: %s" % (label, item))
        result[key] = value
    return result


def validate_write_roots(case_dir, roots, protected_paths):
    normalized = []
    for root in roots:
        path = absolute(root)
        if not is_within(path, case_dir):
            raise StateError("write root is outside case directory: %s" % path)
        for protected in protected_paths:
            protected = absolute(protected)
            if is_within(path, protected) or is_within(protected, path):
                raise StateError("write root overlaps protected path: %s" % path)
        normalized.append(path)
    if not normalized:
        raise StateError("at least one --write-root is required")
    return sorted(set(normalized))


def build_initial_state(args, case_dir):
    workdir = absolute(args.workdir)
    checkout = absolute(args.entity_checkout)
    pgen_path = os.path.join(case_dir, "pgen.hpp")
    toml_path = os.path.join(case_dir, "%s.toml" % args.pgen)
    design_doc = os.path.join(case_dir, "docs", "design.md")
    oriented = os.path.isdir(workdir) and os.path.isdir(checkout)
    orientation_evidence = [evidence_for(workdir), evidence_for(checkout)]
    pgen_status = "implemented" if os.path.isfile(pgen_path) else "absent"
    pgen_evidence = [evidence_for(pgen_path)] if os.path.isfile(pgen_path) else []
    timestamp = now_utc()
    state = {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "case_id": args.case_id,
        "case_status": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_opened_at": timestamp,
        "identity": {"name": args.name or args.case_id, "summary": args.summary or "", "tags": []},
        "memory": {
            "goal": args.goal,
            "done_when": args.done_when or [],
            "confirmed_decisions": [],
            "open_questions": [],
            "constraints": [],
            "out_of_scope": [],
            "last_summary": "",
        },
        "scope": {
            "entity_workdir": workdir,
            "case_dir": case_dir,
            "entity_checkout": checkout,
            "entity_commit": args.entity_commit or "",
            "pgen": args.pgen,
            "pgen_path": pgen_path,
            "toml_path": toml_path,
            "design_doc": design_doc,
            "active_run": "",
            "protected_paths": [],
        },
        "workflow": {
            "workflow_id": args.workflow_id,
            "type": args.workflow_type,
            "status": "active",
            "phase": "orient",
            "owner": "router",
            "active_action_id": "",
            "allowed_actions": [],
            "next_action": "",
            "blockers": [],
        },
        "readiness": {
            "orientation": readiness("ready" if oriented else "unresolved", orientation_evidence),
            "pgen": readiness(pgen_status, pgen_evidence),
            "build": readiness("absent"),
            "run": readiness("none"),
            "data": readiness("absent"),
            "analysis": readiness("none"),
        },
    }
    set_allowed_actions(state)
    return state


def command_create(args):
    workdir = absolute(args.workdir)
    if not os.path.isdir(workdir):
        raise StateError("ENTITY_WORKDIR does not exist: %s" % workdir)
    problems_dir = os.path.join(workdir, "problems")
    if not os.path.isdir(problems_dir):
        os.makedirs(problems_dir)
    case_dir = absolute(args.case_dir or os.path.join(problems_dir, args.case_id))
    if not is_within(case_dir, problems_dir):
        raise StateError("case directory must be under ENTITY_WORKDIR/problems")
    control_dir = os.path.join(case_dir, "_case")
    if os.path.exists(state_path(case_dir)):
        raise StateError("case already exists: %s" % case_dir)
    for path in [control_dir, os.path.join(control_dir, "actions"), os.path.join(control_dir, "history")]:
        if not os.path.isdir(path):
            os.makedirs(path)
    state = build_initial_state(args, case_dir)
    validate_state(state, case_dir)
    atomic_write_json(state_path(case_dir), state)
    open(os.path.join(control_dir, "events.jsonl"), "a").close()
    append_event(case_dir, "case.created", 0, {"workflow_id": args.workflow_id})
    return {"ok": True, "case_dir": case_dir, "revision": 0, "state": state}


def command_list(args):
    workdir = absolute(args.workdir)
    problems = os.path.join(workdir, "problems")
    cases = []
    if os.path.isdir(problems):
        for name in sorted(os.listdir(problems)):
            candidate = os.path.join(problems, name)
            if os.path.isfile(state_path(candidate)):
                try:
                    state = load_state(candidate)
                    cases.append({
                        "case_id": state["case_id"],
                        "case_dir": candidate,
                        "case_status": state["case_status"],
                        "workflow_status": state["workflow"]["status"],
                        "next_action": state["workflow"].get("next_action", ""),
                        "revision": state["revision"],
                    })
                except (StateError, ValueError) as exc:
                    cases.append({"case_id": name, "case_dir": candidate, "error": str(exc)})
    return {"ok": True, "workdir": workdir, "cases": cases}


def command_show(args):
    case_dir = resolve_case(args.case)
    state = load_state(case_dir)
    return {"ok": True, "case_dir": case_dir, "state": state}


def command_verify(args):
    case_dir = resolve_case(args.case)
    state = load_state(case_dir)
    action_id = state["workflow"].get("active_action_id", "")
    issues = []
    if action_id:
        request = os.path.join(case_dir, "_case", "actions", action_id, "request.json")
        if not os.path.isfile(request):
            issues.append("active action request is missing: %s" % request)
    state_allowed = state["workflow"].get("allowed_actions", [])
    calculated = allowed_actions(state)
    if state_allowed != calculated:
        issues.append("allowed_actions is stale")
    return {
        "ok": not issues,
        "case_dir": case_dir,
        "revision": state["revision"],
        "issues": issues,
        "calculated_allowed_actions": calculated,
    }


def command_start_action(args):
    case_dir = resolve_case(args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["case_status"] != "active" or state["workflow"]["status"] != "active":
            raise StateError("case and workflow must both be active")
        if state["workflow"].get("active_action_id"):
            raise StateError("another action is already active")
        if args.action_type not in state["workflow"].get("allowed_actions", []):
            raise StateError("action is not allowed in current state: %s" % args.action_type)

        protected = state["scope"].get("protected_paths", []) + (args.protected_path or [])
        write_roots = validate_write_roots(case_dir, args.write_root or [], protected)
        read_roots = sorted(set(absolute(path) for path in (args.read_root or [])))
        inputs = []
        for path in args.input or []:
            item = evidence_for(path)
            if item["kind"] == "missing":
                raise StateError("action input does not exist: %s" % item["path"])
            if not any(is_within(item["path"], root) for root in read_roots + write_roots):
                raise StateError("action input is outside read/write roots: %s" % item["path"])
            inputs.append(item)

        failure_evidence = []
        for path in args.failure_evidence or []:
            item = evidence_for(path)
            if item["kind"] == "missing":
                raise StateError("failure evidence does not exist: %s" % item["path"])
            if not any(is_within(item["path"], root) for root in read_roots + write_roots):
                raise StateError("failure evidence is outside read/write roots: %s" % item["path"])
            failure_evidence.append(item)

        action_dir = os.path.join(case_dir, "_case", "actions", args.action_id)
        request_path = os.path.join(action_dir, "request.json")
        if os.path.exists(action_dir):
            raise StateError("action id already exists: %s" % args.action_id)
        os.makedirs(action_dir)
        request = {
            "schema_version": 1,
            "case_revision": state["revision"],
            "case_id": state["case_id"],
            "workflow_id": state["workflow"]["workflow_id"],
            "action_id": args.action_id,
            "action_type": args.action_type,
            "owner": args.owner,
            "execution_domain": args.execution_domain,
            "goal": args.goal,
            "playbook": args.playbook or "",
            "inputs": inputs,
            "read_roots": read_roots,
            "write_roots": write_roots,
            "protected_paths": sorted(set(absolute(path) for path in protected)),
            "constraints": args.constraint or [],
            "expected_outputs": args.expected_output or [],
            "acceptance_checks": args.acceptance_check or [],
            "failure_evidence": failure_evidence,
            "started_at": now_utc(),
        }
        atomic_write_json(request_path, request)

        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["workflow"]["owner"] = args.owner
        state["workflow"]["phase"] = args.action_type.split(".", 1)[0]
        state["workflow"]["active_action_id"] = args.action_id
        state["workflow"]["allowed_actions"] = []
        state["workflow"]["next_action"] = ""
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "action.started", state["revision"], {
            "action_id": args.action_id,
            "action_type": args.action_type,
            "owner": args.owner,
        })
        return {
            "ok": True,
            "case_dir": case_dir,
            "revision": state["revision"],
            "request": request_path,
        }


def parse_readiness_updates(items):
    parsed = parse_key_value(items, "--readiness")
    for dimension, status in parsed.items():
        if dimension not in READINESS_STATUSES:
            raise StateError("unknown readiness dimension: %s" % dimension)
        if status not in READINESS_STATUSES[dimension]:
            raise StateError("invalid readiness %s=%s" % (dimension, status))
    return parsed


def parse_dimension_items(items, label):
    result = {}
    for raw in items or []:
        if "=" not in raw:
            raise StateError("%s must use DIMENSION=VALUE: %s" % (label, raw))
        dimension, value = raw.split("=", 1)
        if dimension not in READINESS_STATUSES:
            raise StateError("unknown readiness dimension: %s" % dimension)
        if not value:
            raise StateError("%s value cannot be empty" % label)
        result.setdefault(dimension, []).append(value)
    return result


def command_finish_action(args):
    case_dir = resolve_case(args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if args.status not in ACTION_TERMINAL:
            raise StateError("invalid terminal action status: %s" % args.status)
        if state["workflow"].get("active_action_id") != args.action_id:
            raise StateError("action is not the active action: %s" % args.action_id)

        action_dir = os.path.join(case_dir, "_case", "actions", args.action_id)
        request_path = os.path.join(action_dir, "request.json")
        if not os.path.isfile(request_path):
            raise StateError("action request is missing: %s" % request_path)
        with open(request_path, "r") as handle:
            request = json.load(handle)

        outputs = []
        for path in args.output or []:
            item = evidence_for(path)
            if item["kind"] == "missing":
                raise StateError("declared output does not exist: %s" % item["path"])
            if not any(is_within(item["path"], root) for root in request["write_roots"]):
                raise StateError("output is outside Action write roots: %s" % item["path"])
            outputs.append(item)

        if args.status == "completed":
            if request.get("expected_outputs") and not outputs:
                raise StateError("completed Action requires verified output evidence")
            required_checks = len(request.get("acceptance_checks", []))
            if len(args.verification or []) < required_checks:
                raise StateError(
                    "completed Action requires at least one verification per acceptance check"
                )

        updates = parse_readiness_updates(args.readiness)
        for dimension, status in updates.items():
            state["readiness"][dimension] = readiness(status, list(outputs))

        result = {
            "schema_version": 1,
            "case_id": state["case_id"],
            "workflow_id": state["workflow"]["workflow_id"],
            "action_id": args.action_id,
            "action_type": request["action_type"],
            "owner": request["owner"],
            "status": args.status,
            "outputs": outputs,
            "verification": args.verification or [],
            "blockers": args.blocker or [],
            "diagnosis": args.diagnosis or "",
            "suggested_owner": args.suggested_owner or "",
            "started_at": request["started_at"],
            "finished_at": now_utc(),
        }
        result_path = os.path.join(action_dir, "result.json")
        if os.path.exists(result_path):
            raise StateError("action result already exists: %s" % result_path)
        atomic_write_json(result_path, result)

        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["workflow"]["active_action_id"] = ""
        state["workflow"]["owner"] = "router"
        state["workflow"]["blockers"] = args.blocker or []
        if args.status == "blocked":
            state["case_status"] = "blocked"
            state["workflow"]["status"] = "blocked"
        elif args.status == "failed":
            state["case_status"] = "active"
            state["workflow"]["status"] = "active"
        else:
            state["case_status"] = "active"
            state["workflow"]["status"] = "active"
        state["workflow"]["next_action"] = args.next_action or ""
        set_allowed_actions(state)
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "action.%s" % args.status, state["revision"], {
            "action_id": args.action_id,
            "readiness": updates,
        })
        return {
            "ok": True,
            "case_dir": case_dir,
            "revision": state["revision"],
            "result": result_path,
            "allowed_actions": state["workflow"]["allowed_actions"],
        }


def evidence_changed(item):
    path = item.get("path", "")
    if not path or not os.path.exists(path):
        return True
    if item.get("kind") == "file" and item.get("sha256"):
        return sha256_file(path) != item["sha256"]
    return False


def command_refresh(args):
    case_dir = resolve_case(args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        changed_dimensions = []
        for dimension, item in state["readiness"].items():
            evidence = item.get("evidence", [])
            if evidence and any(evidence_changed(entry) for entry in evidence):
                changed_dimensions.append(dimension)
                if dimension == "orientation":
                    item["status"] = "unresolved"
                elif dimension == "data":
                    item["status"] = "unknown"
                elif "stale" in READINESS_STATUSES[dimension]:
                    item["status"] = "stale"

        if "pgen" in changed_dimensions:
            if state["readiness"]["build"]["status"] != "absent":
                state["readiness"]["build"]["status"] = "stale"
            if state["readiness"]["run"]["status"] in {"prepared", "submitted"}:
                state["readiness"]["run"]["status"] = "stale"
        if "build" in changed_dimensions and state["readiness"]["run"]["status"] == "prepared":
            state["readiness"]["run"]["status"] = "stale"
        if "data" in changed_dimensions and state["readiness"]["analysis"]["status"] != "none":
            state["readiness"]["analysis"]["status"] = "stale"

        if changed_dimensions:
            state["revision"] += 1
            state["updated_at"] = now_utc()
            set_allowed_actions(state)
            atomic_write_json(state_path(case_dir), state)
            append_event(case_dir, "case.refreshed", state["revision"], {
                "changed_dimensions": changed_dimensions,
            })
        return {
            "ok": True,
            "case_dir": case_dir,
            "revision": state["revision"],
            "changed_dimensions": changed_dimensions,
            "state": state,
        }


def command_reconcile(args):
    case_dir = resolve_case(args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"].get("active_action_id"):
            raise StateError("cannot reconcile while an action is active")
        updates = parse_readiness_updates(args.readiness)
        evidence_paths = parse_dimension_items(args.evidence, "--evidence")
        observations = parse_dimension_items(args.observation, "--observation")

        evidence_by_dimension = {}
        for dimension in READINESS_STATUSES:
            entries = []
            for path in evidence_paths.get(dimension, []):
                item = evidence_for(path)
                if item["kind"] == "missing":
                    raise StateError("reconcile evidence does not exist: %s" % item["path"])
                entries.append(item)
            for value in observations.get(dimension, []):
                entries.append({
                    "kind": "observation",
                    "value": value,
                    "observed_at": now_utc(),
                })
            evidence_by_dimension[dimension] = entries

        neutral = {"unresolved", "absent", "none", "unknown", "planned"}
        for dimension, status in updates.items():
            entries = evidence_by_dimension.get(dimension, [])
            if status not in neutral and not entries:
                raise StateError(
                    "readiness %s=%s requires --evidence or --observation" %
                    (dimension, status)
                )
            state["readiness"][dimension] = readiness(status, entries)

        if args.active_run:
            active_run = absolute(args.active_run)
            if not is_within(active_run, case_dir) or not os.path.isdir(active_run):
                raise StateError("active run must be an existing directory inside the Case")
            state["scope"]["active_run"] = active_run
        if args.entity_commit is not None:
            state["scope"]["entity_commit"] = args.entity_commit
        protected = list(state["scope"].get("protected_paths", []))
        for path in args.protect_path or []:
            candidate = absolute(path)
            if not is_within(candidate, case_dir):
                raise StateError("protected path must be inside the Case: %s" % candidate)
            if candidate not in protected:
                protected.append(candidate)
        for path in args.unprotect_path or []:
            candidate = absolute(path)
            protected = [item for item in protected if absolute(item) != candidate]
        state["scope"]["protected_paths"] = sorted(protected)

        if not updates and not args.active_run and args.entity_commit is None and not args.protect_path and not args.unprotect_path:
            raise StateError("reconcile requires a readiness or scope update")
        state["revision"] += 1
        state["updated_at"] = now_utc()
        set_allowed_actions(state)
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "case.reconciled", state["revision"], {
            "readiness": updates,
            "active_run": state["scope"].get("active_run", ""),
        })
        return {
            "ok": True,
            "case_dir": case_dir,
            "revision": state["revision"],
            "allowed_actions": state["workflow"]["allowed_actions"],
        }


def append_unique(target, values):
    changed = False
    for value in values or []:
        if value not in target:
            target.append(value)
            changed = True
    return changed


def command_update_memory(args):
    case_dir = resolve_case(args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"].get("active_action_id"):
            raise StateError("cannot update Case memory while an action is active")
        memory = state["memory"]
        changed = False
        if args.goal is not None and args.goal != memory.get("goal"):
            memory["goal"] = args.goal
            changed = True
        if args.done_when is not None and args.done_when != memory.get("done_when", []):
            memory["done_when"] = args.done_when
            changed = True
        changed = append_unique(memory["confirmed_decisions"], args.decision) or changed
        changed = append_unique(memory["open_questions"], args.open_question) or changed
        changed = append_unique(memory["constraints"], args.constraint) or changed
        changed = append_unique(memory["out_of_scope"], args.out_of_scope) or changed
        for question in args.resolve_question or []:
            if question in memory["open_questions"]:
                memory["open_questions"].remove(question)
                changed = True
        if args.summary is not None and args.summary != memory.get("last_summary"):
            memory["last_summary"] = args.summary
            changed = True
        if not changed:
            raise StateError("memory update does not change Case state")
        state["revision"] += 1
        state["updated_at"] = now_utc()
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "case.memory_updated", state["revision"], {
            "decisions_added": args.decision or [],
            "questions_added": args.open_question or [],
            "questions_resolved": args.resolve_question or [],
        })
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"]}


def command_suspend(args):
    case_dir = resolve_case(args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"].get("active_action_id"):
            raise StateError("cannot suspend a case with an active action")
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["case_status"] = "suspended"
        state["workflow"]["status"] = "suspended"
        state["memory"]["last_summary"] = args.summary
        set_allowed_actions(state)
        atomic_write_json(state_path(case_dir), state)
        snapshot = save_workflow_snapshot(case_dir, state, "suspended")
        append_event(case_dir, "case.suspended", state["revision"], {"summary": args.summary})
        return {
            "ok": True,
            "case_dir": case_dir,
            "revision": state["revision"],
            "snapshot": snapshot,
        }


def command_resume(args):
    case_dir = resolve_case(args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["case_status"] not in {"suspended", "blocked"}:
            raise StateError("only suspended or blocked cases can be resumed")
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["last_opened_at"] = now_utc()
        state["case_status"] = "active"
        state["workflow"]["status"] = "active"
        state["workflow"]["blockers"] = []
        set_allowed_actions(state)
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "case.resumed", state["revision"])
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"]}


def command_complete_workflow(args):
    case_dir = resolve_case(args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"].get("active_action_id"):
            raise StateError("cannot complete a workflow with an active action")
        if state["workflow"].get("blockers"):
            raise StateError("cannot complete a workflow with blockers")
        done_when = state["memory"].get("done_when", [])
        verification = args.verification or []
        if len(verification) < len(done_when):
            raise StateError(
                "completion requires at least one verification per done_when item"
            )
        evidence = []
        for path in args.evidence or []:
            item = evidence_for(path)
            if item["kind"] == "missing":
                raise StateError("completion evidence does not exist: %s" % item["path"])
            evidence.append(item)
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["case_status"] = "complete"
        state["workflow"]["status"] = "complete"
        state["workflow"]["owner"] = "router"
        state["workflow"]["next_action"] = ""
        state["workflow"]["allowed_actions"] = []
        state["memory"]["last_summary"] = args.summary
        atomic_write_json(state_path(case_dir), state)
        snapshot = save_workflow_snapshot(case_dir, state, "complete")
        append_event(case_dir, "workflow.completed", state["revision"], {
            "verification": verification,
            "evidence": evidence,
        })
        return {
            "ok": True,
            "case_dir": case_dir,
            "revision": state["revision"],
            "snapshot": snapshot,
        }


def command_new_workflow(args):
    case_dir = resolve_case(args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"]["status"] != "complete":
            raise StateError("a new workflow requires the current workflow to be complete")
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["last_opened_at"] = now_utc()
        state["case_status"] = "active"
        state["memory"]["goal"] = args.goal
        state["memory"]["done_when"] = args.done_when or []
        state["memory"]["last_summary"] = ""
        state["workflow"] = {
            "workflow_id": args.workflow_id,
            "type": args.workflow_type,
            "status": "active",
            "phase": "orient",
            "owner": "router",
            "active_action_id": "",
            "allowed_actions": [],
            "next_action": "",
            "blockers": [],
        }
        set_allowed_actions(state)
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "workflow.created", state["revision"], {
            "workflow_id": args.workflow_id,
            "workflow_type": args.workflow_type,
        })
        return {
            "ok": True,
            "case_dir": case_dir,
            "revision": state["revision"],
            "allowed_actions": state["workflow"]["allowed_actions"],
        }


def add_common_case_argument(parser):
    parser.add_argument("--case", required=True, help="Path to problems/<case_id>")


def build_parser():
    parser = argparse.ArgumentParser(description="Entity Router case-state controller")
    sub = parser.add_subparsers(dest="command")

    create = sub.add_parser("create", help="Create a Case and initial Workflow")
    create.add_argument("--workdir", required=True)
    create.add_argument("--case-id", required=True)
    create.add_argument("--case-dir")
    create.add_argument("--entity-checkout", required=True)
    create.add_argument("--entity-commit", default="")
    create.add_argument("--pgen", required=True)
    create.add_argument("--goal", required=True)
    create.add_argument("--done-when", action="append", default=[])
    create.add_argument("--name")
    create.add_argument("--summary")
    create.add_argument("--workflow-id", default="wf-initial")
    create.add_argument("--workflow-type", default="new-simulation")
    create.set_defaults(func=command_create)

    list_cases = sub.add_parser("list", help="List Cases under ENTITY_WORKDIR")
    list_cases.add_argument("--workdir", required=True)
    list_cases.set_defaults(func=command_list)

    show = sub.add_parser("show", help="Show a Case state")
    add_common_case_argument(show)
    show.set_defaults(func=command_show)

    verify = sub.add_parser("verify", help="Validate Case state and control files")
    add_common_case_argument(verify)
    verify.set_defaults(func=command_verify)

    start = sub.add_parser("start-action", help="Create an immutable Action Contract")
    add_common_case_argument(start)
    start.add_argument("--expected-revision", required=True, type=int)
    start.add_argument("--action-id", required=True)
    start.add_argument("--action-type", required=True)
    start.add_argument("--owner", required=True)
    start.add_argument("--execution-domain", required=True)
    start.add_argument("--goal", required=True)
    start.add_argument("--playbook")
    start.add_argument("--input", action="append", default=[])
    start.add_argument("--read-root", action="append", default=[])
    start.add_argument("--write-root", action="append", default=[])
    start.add_argument("--protected-path", action="append", default=[])
    start.add_argument("--constraint", action="append", default=[])
    start.add_argument("--expected-output", action="append", default=[])
    start.add_argument("--acceptance-check", action="append", default=[])
    start.add_argument("--failure-evidence", action="append", default=[])
    start.set_defaults(func=command_start_action)

    finish = sub.add_parser("finish-action", help="Verify and close the active Action")
    add_common_case_argument(finish)
    finish.add_argument("--expected-revision", required=True, type=int)
    finish.add_argument("--action-id", required=True)
    finish.add_argument("--status", required=True, choices=sorted(ACTION_TERMINAL))
    finish.add_argument("--output", action="append", default=[])
    finish.add_argument("--verification", action="append", default=[])
    finish.add_argument("--blocker", action="append", default=[])
    finish.add_argument("--diagnosis")
    finish.add_argument("--suggested-owner")
    finish.add_argument("--readiness", action="append", default=[])
    finish.add_argument("--next-action")
    finish.set_defaults(func=command_finish_action)

    refresh = sub.add_parser("refresh", help="Recheck evidence fingerprints and propagate stale")
    add_common_case_argument(refresh)
    refresh.add_argument("--expected-revision", required=True, type=int)
    refresh.set_defaults(func=command_refresh)

    reconcile = sub.add_parser("reconcile", help="Record verified external evidence and scope")
    add_common_case_argument(reconcile)
    reconcile.add_argument("--expected-revision", required=True, type=int)
    reconcile.add_argument("--readiness", action="append", default=[])
    reconcile.add_argument("--evidence", action="append", default=[])
    reconcile.add_argument("--observation", action="append", default=[])
    reconcile.add_argument("--active-run")
    reconcile.add_argument("--entity-commit")
    reconcile.add_argument("--protect-path", action="append", default=[])
    reconcile.add_argument("--unprotect-path", action="append", default=[])
    reconcile.set_defaults(func=command_reconcile)

    update_memory = sub.add_parser("update-memory", help="Update compact Case memory")
    add_common_case_argument(update_memory)
    update_memory.add_argument("--expected-revision", required=True, type=int)
    update_memory.add_argument("--goal")
    update_memory.add_argument("--done-when", action="append", default=None)
    update_memory.add_argument("--decision", action="append", default=[])
    update_memory.add_argument("--open-question", action="append", default=[])
    update_memory.add_argument("--resolve-question", action="append", default=[])
    update_memory.add_argument("--constraint", action="append", default=[])
    update_memory.add_argument("--out-of-scope", action="append", default=[])
    update_memory.add_argument("--summary")
    update_memory.set_defaults(func=command_update_memory)

    suspend = sub.add_parser("suspend", help="Safely suspend a Case")
    add_common_case_argument(suspend)
    suspend.add_argument("--expected-revision", required=True, type=int)
    suspend.add_argument("--summary", required=True)
    suspend.set_defaults(func=command_suspend)

    resume = sub.add_parser("resume", help="Resume a suspended or blocked Case")
    add_common_case_argument(resume)
    resume.add_argument("--expected-revision", required=True, type=int)
    resume.set_defaults(func=command_resume)

    complete = sub.add_parser("complete-workflow", help="Complete the current Workflow with evidence")
    add_common_case_argument(complete)
    complete.add_argument("--expected-revision", required=True, type=int)
    complete.add_argument("--summary", required=True)
    complete.add_argument("--verification", action="append", default=[])
    complete.add_argument("--evidence", action="append", default=[])
    complete.set_defaults(func=command_complete_workflow)

    new_workflow = sub.add_parser("new-workflow", help="Start a new Workflow in a completed Case")
    add_common_case_argument(new_workflow)
    new_workflow.add_argument("--expected-revision", required=True, type=int)
    new_workflow.add_argument("--workflow-id", required=True)
    new_workflow.add_argument("--workflow-type", required=True)
    new_workflow.add_argument("--goal", required=True)
    new_workflow.add_argument("--done-when", action="append", default=[])
    new_workflow.set_defaults(func=command_new_workflow)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        result = args.func(args)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("ok", False) else 1
    except (StateError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
