#!/usr/bin/env python3
"""Controller-authoritative multi-site Case state for Entity simulations."""

from __future__ import print_function

import argparse
import fcntl
import json
import os
import shlex
import shutil
import sys
import uuid
from contextlib import contextmanager

from entity_router_common import (
    RouterError,
    absolute,
    atomic_write_json,
    canonical_locator,
    ensure_home,
    list_site_profiles,
    load_json,
    load_registry,
    load_site_profile,
    locator_text,
    locator_within,
    locators_overlap,
    now_utc,
    parse_locator,
    probe_locator,
    register_case,
    router_home,
    run_command,
    run_on_site,
    save_site_profile,
    unregister_case,
)


SCHEMA_VERSION = 3
CASE_STATUSES = {"active", "suspended", "blocked", "complete", "archived"}
WORKFLOW_STATUSES = {"active", "suspended", "blocked", "complete"}
ACTION_TERMINAL = {"completed", "failed", "blocked", "cancelled"}
READINESS_STATUSES = {
    "orientation": {"unresolved", "ready"},
    "pgen": {"absent", "designing", "implemented", "verified", "stale", "failed"},
    "source": {"unmaterialized", "materializing", "ready", "stale", "failed"},
    "build": {"absent", "planned", "running", "pass", "fail", "stale"},
    "run": {"none", "prepared", "submitted", "running", "completed", "failed", "stopped", "stale"},
    "data": {"absent", "partial", "ready", "corrupt", "unknown"},
    "analysis": {"none", "planned", "running", "complete", "stale"},
}

ACTION_EXECUTION = {
    "orient": ("router", "router"),
    "pgen": ("entity-pgen", "entity-pgen"),
    "source": ("router", "playbook-sync"),
    "build": ("entity-env-build", "entity-env-build"),
    "data": ("entity-nt2py", "entity-nt2py"),
    "run": ("playbook-run", "playbook-run"),
    "analysis": ("playbook-analysis", "playbook-analysis"),
    "failure": ("failure-triage", "failure-triage"),
}


class StateError(RouterError):
    pass


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def state_path(case_dir):
    return os.path.join(absolute(case_dir), "case.json")


def events_path(case_dir):
    return os.path.join(absolute(case_dir), "events.jsonl")


def append_event(case_dir, event_type, revision, details=None):
    event = {
        "time": now_utc(),
        "event": event_type,
        "revision": revision,
        "details": details or {},
    }
    with open(events_path(case_dir), "a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def locked_case(case_dir):
    lock_path = os.path.join(absolute(case_dir), ".lock")
    handle = open(lock_path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def readiness(status, evidence=None):
    return {"status": status, "evidence": evidence or []}


def required_execution(action_type):
    prefix = action_type.split(".", 1)[0]
    if prefix not in ACTION_EXECUTION:
        raise StateError("action has no execution contract: %s" % action_type)
    return ACTION_EXECUTION[prefix]


def validate_state(state, case_dir=None):
    required = {
        "schema_version", "revision", "case_uid", "case_id", "case_status",
        "control", "identity", "memory", "source", "artifacts", "resources",
        "workflow", "readiness",
    }
    missing = sorted(required.difference(state))
    if missing:
        raise StateError("case.json missing keys: %s" % ", ".join(missing))
    if state["schema_version"] != SCHEMA_VERSION:
        raise StateError("unsupported Case schema_version: %s" % state["schema_version"])
    if not isinstance(state["revision"], int) or state["revision"] < 0:
        raise StateError("revision must be a non-negative integer")
    if state["case_status"] not in CASE_STATUSES:
        raise StateError("invalid case_status")
    if state["workflow"].get("status") not in WORKFLOW_STATUSES:
        raise StateError("invalid workflow status")
    for dimension, statuses in READINESS_STATUSES.items():
        if dimension not in state["readiness"]:
            raise StateError("missing readiness dimension: %s" % dimension)
        if state["readiness"][dimension].get("status") not in statuses:
            raise StateError("invalid readiness %s" % dimension)
    if case_dir and absolute(state["control"]["root"]) != absolute(case_dir):
        raise StateError("Case control.root does not match case.json location")
    control_locator = {
        "site_id": state["control"]["site_id"],
        "path": state["control"]["root"],
    }
    for key in ["authority"]:
        parse_locator(state["source"][key])
    if locators_overlap(control_locator, state["source"]["authority"]):
        raise StateError("Router control root must be separate from the source authority checkout")
    for value in state["artifacts"].values():
        locator = parse_locator(value)
        if locator["site_id"] != state["source"]["authority"]["site_id"]:
            raise StateError("PGen, TOML, and design locators must be on the source authority site")
        if not locator_within(locator, state["source"]["authority"]):
            raise StateError("PGen, TOML, and design locators must be inside the source authority root")


def load_state(case_dir):
    value = load_json(state_path(case_dir), "Case state")
    validate_state(value, case_dir)
    return value


def resolve_case(home, value):
    candidate = absolute(value)
    if os.path.isfile(state_path(candidate)):
        return candidate
    registry = load_registry(home)
    matches = []
    for uid, record in registry["cases"].items():
        if value == uid or value == record.get("case_id"):
            path = absolute(record["control_root"])
            if os.path.isfile(state_path(path)):
                matches.append(path)
    if not matches:
        raise StateError("unknown Case UID, ID, or control path: %s" % value)
    if len(set(matches)) != 1:
        raise StateError("Case ID is ambiguous; use case_uid or exact control path")
    return matches[0]


def require_revision(state, expected):
    if expected is None:
        raise StateError("--expected-revision is required for mutations")
    if state["revision"] != expected:
        raise StateError("revision conflict: expected %s, current %s" % (expected, state["revision"]))


def all_case_locators(state):
    result = [state["source"]["authority"]]
    result.extend(state["source"].get("replicas", []))
    result.extend(state["artifacts"].values())
    for resource in state["resources"].values():
        if resource.get("root"):
            result.append(resource["root"])
    return [parse_locator(item) for item in result]


def referenced_sites(state):
    result = {state["control"]["site_id"]}
    result.update(item["site_id"] for item in all_case_locators(state))
    return sorted(result)


def allowed_actions(state):
    if state["case_status"] in {"suspended", "archived"}:
        return []
    if state["workflow"]["status"] in {"suspended", "complete"}:
        return []
    if state["workflow"].get("active_action_id"):
        return []
    r = state["readiness"]
    if r["orientation"]["status"] != "ready":
        return ["orient"]
    result = []
    pgen = r["pgen"]["status"]
    source = r["source"]["status"]
    build = r["build"]["status"]
    run = r["run"]["status"]
    data = r["data"]["status"]
    analysis = r["analysis"]["status"]
    if pgen in {"absent", "designing", "stale", "failed"}:
        result.extend(["pgen.design", "pgen.fix"])
    if pgen in {"implemented", "verified"}:
        result.extend(["pgen.verify", "pgen.edit"])
    if pgen == "verified" and source in {"unmaterialized", "stale", "failed"}:
        result.append("source.materialize")
    if state["source"].get("replicas"):
        result.append("source.transfer-authority")
    if pgen == "verified" and source == "ready" and build in {"absent", "planned", "fail", "stale"}:
        result.extend(["build.plan", "build.compile"])
    if build == "running":
        result.append("build.monitor")
    if pgen == "verified" and source == "ready" and build == "pass" and run in {"none", "stale"}:
        result.append("run.prepare")
    if run == "prepared":
        result.append("run.launch")
    if run in {"submitted", "running"}:
        result.append("run.monitor")
    if run in {"completed", "failed", "stopped"}:
        result.append("run.resume")
    if run == "failed" or build == "fail" or pgen == "failed" or source == "failed":
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
    if state["workflow"].get("next_action") not in actions:
        state["workflow"]["next_action"] = actions[0] if actions else ""


def probe_safe(home, locator, kind="auto"):
    try:
        return probe_locator(home, locator, kind)
    except RouterError as exc:
        return {
            "locator": parse_locator(locator),
            "kind": "unreachable",
            "fingerprint": {},
            "observed_at": now_utc(),
            "observer_site": "controller",
            "error": str(exc),
        }


def parse_resource(home, locator):
    return {
        "root": canonical_locator(home, locator) if locator else None,
        "current_id": "",
        "identities": [],
    }


def effective_source_revision(state):
    materializations = state["source"].get("materializations", [])
    if materializations:
        outputs = materializations[-1].get("outputs", [])
        if outputs:
            evidence = outputs[0]
            fingerprint = dict(evidence.get("fingerprint", {}))
            kind = evidence.get("kind", "")
            if fingerprint.get("kind") == "git":
                kind = "git"
            revision = {"kind": kind, "locator": evidence.get("locator")}
            revision.update(fingerprint)
            return revision
    fingerprint = dict(state["source"].get("revision", {}))
    kind = "git" if fingerprint.get("kind") == "git" else "authority"
    revision = {"kind": kind, "locator": state["source"]["authority"]}
    revision.update(fingerprint)
    return revision


def build_initial_state(args, case_dir, case_uid):
    source = canonical_locator(args.router_home, args.source_authority)
    artifacts = {
        "pgen": canonical_locator(args.router_home, args.pgen_locator),
        "toml": canonical_locator(args.router_home, args.toml_locator),
        "design": canonical_locator(args.router_home, args.design_locator),
    }
    replicas = [canonical_locator(args.router_home, item) for item in args.source_replica]
    resources = {
        "build": parse_resource(args.router_home, args.build_root),
        "run": parse_resource(args.router_home, args.run_root),
        "data": parse_resource(args.router_home, args.data_root or args.run_root),
        "analysis": parse_resource(args.router_home, args.analysis_root or args.run_root),
    }
    source_evidence = probe_safe(args.router_home, source, "git")
    pgen_evidence = probe_safe(args.router_home, artifacts["pgen"])
    sites_ready = True
    site_ids = {args.controller_site, source["site_id"]}
    site_ids.update(item["site_id"] for item in replicas)
    site_ids.update(item["site_id"] for item in artifacts.values())
    site_ids.update(item["root"]["site_id"] for item in resources.values() if item["root"])
    for site_id in site_ids:
        try:
            load_site_profile(args.router_home, site_id)
        except RouterError:
            sites_ready = False
    oriented = sites_ready and source_evidence["kind"] not in {"missing", "unreachable"}
    build_root = resources["build"]["root"]
    source_ready = not build_root or build_root["site_id"] == source["site_id"]
    timestamp = now_utc()
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "case_uid": case_uid,
        "case_id": args.case_id,
        "case_status": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_opened_at": timestamp,
        "control": {"site_id": args.controller_site, "root": absolute(case_dir)},
        "identity": {"name": args.name or args.case_id, "summary": args.summary or "", "tags": []},
        "memory": {
            "goal": args.goal,
            "done_when": args.done_when,
            "confirmed_decisions": [],
            "open_questions": [],
            "constraints": [],
            "out_of_scope": [],
            "last_summary": "",
        },
        "source": {
            "authority": source,
            "replicas": replicas,
            "transfer_policy": args.transfer_policy,
            "revision": source_evidence.get("fingerprint", {}),
            "materializations": [],
        },
        "artifacts": artifacts,
        "resources": resources,
        "legacy": {},
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
            "orientation": readiness("ready" if oriented else "unresolved", [source_evidence]),
            "pgen": readiness("implemented" if pgen_evidence["kind"] == "file" else "absent", [pgen_evidence] if pgen_evidence["kind"] == "file" else []),
            "source": readiness("ready" if source_ready else "unmaterialized", [source_evidence] if source_ready else []),
            "build": readiness("absent"),
            "run": readiness("none"),
            "data": readiness("absent"),
            "analysis": readiness("none"),
        },
    }


def command_create(args):
    home = ensure_home(args.router_home)
    controller = load_site_profile(home, args.controller_site)
    if controller["transport"]["kind"] != "local":
        raise StateError("controller site must use local transport")
    case_uid = args.case_uid or str(uuid.uuid4())
    control_root = absolute(args.control_root or os.path.join(home, "cases"))
    case_dir = absolute(args.case_dir or os.path.join(control_root, "%s-%s" % (args.case_id, case_uid[:8])))
    if os.path.exists(case_dir):
        raise StateError("Case control directory already exists: %s" % case_dir)
    os.makedirs(case_dir)
    for relative in ["actions", "history", "evidence"]:
        os.makedirs(os.path.join(case_dir, relative))
    open(events_path(case_dir), "a").close()
    try:
        state = build_initial_state(args, case_dir, case_uid)
        set_allowed_actions(state)
        validate_state(state, case_dir)
        atomic_write_json(state_path(case_dir), state)
        register_case(home, case_uid, args.case_id, case_dir)
        append_event(case_dir, "case.created", 0, {"workflow_id": args.workflow_id})
    except Exception:
        shutil.rmtree(case_dir, ignore_errors=True)
        raise
    return {"ok": True, "case_dir": case_dir, "case_uid": case_uid, "revision": 0, "state": state}


def command_list(args):
    registry = load_registry(args.router_home)
    cases = []
    for uid, record in sorted(registry["cases"].items()):
        path = absolute(record["control_root"])
        try:
            state = load_state(path)
            cases.append({
                "case_uid": uid,
                "case_id": state["case_id"],
                "control_root": path,
                "case_status": state["case_status"],
                "workflow_status": state["workflow"]["status"],
                "next_action": state["workflow"].get("next_action", ""),
                "revision": state["revision"],
            })
        except RouterError as exc:
            cases.append({"case_uid": uid, "control_root": path, "error": str(exc)})
    return {"ok": True, "cases": cases}


def command_rebuild_registry(args):
    roots = args.scan_root or [os.path.join(args.router_home, "cases")]
    cases = {}
    for root in roots:
        root = absolute(root)
        if not os.path.isdir(root):
            continue
        for current, dirs, files in os.walk(root):
            if "case.json" not in files:
                continue
            try:
                state = load_json(os.path.join(current, "case.json"), "Case state")
                if state.get("schema_version") != SCHEMA_VERSION:
                    continue
                validate_state(state, current)
            except (RouterError, ValueError, KeyError):
                continue
            cases[state["case_uid"]] = {
                "case_uid": state["case_uid"],
                "case_id": state["case_id"],
                "control_root": absolute(current),
            }
            dirs[:] = []
    registry = {"schema_version": 1, "updated_at": now_utc(), "cases": cases}
    atomic_write_json(os.path.join(args.router_home, "registry.json"), registry)
    return {"ok": True, "registry": os.path.join(args.router_home, "registry.json"),
            "cases": len(cases)}


def command_show(args):
    case_dir = resolve_case(args.router_home, args.case)
    return {"ok": True, "case_dir": case_dir, "state": load_state(case_dir)}


def command_verify(args):
    case_dir = resolve_case(args.router_home, args.case)
    state = load_state(case_dir)
    issues = []
    for site_id in referenced_sites(state):
        try:
            load_site_profile(args.router_home, site_id)
        except RouterError as exc:
            issues.append(str(exc))
    action_id = state["workflow"].get("active_action_id", "")
    if action_id and not os.path.isfile(os.path.join(case_dir, "actions", action_id, "request.json")):
        issues.append("active Action request is missing")
    if state["workflow"].get("allowed_actions", []) != allowed_actions(state):
        issues.append("allowed_actions is stale")
    registry = load_registry(args.router_home)
    record = registry["cases"].get(state["case_uid"])
    if not record or absolute(record["control_root"]) != case_dir:
        issues.append("Case registry entry is missing or stale")
    return {"ok": not issues, "case_dir": case_dir, "revision": state["revision"], "issues": issues}


def validate_root_sites(roots, execution_site):
    for root in roots:
        if root["site_id"] != execution_site:
            raise StateError("write root site differs from execution_site_id: %s" % locator_text(root))


def resource_root(state, name):
    value = state["resources"].get(name, {}).get("root")
    return parse_locator(value) if value else None


def validate_action_write_envelope(state, action_type, execution_site, write_roots, home):
    validate_root_sites(write_roots, execution_site)
    control_locator = {"site_id": state["control"]["site_id"], "path": state["control"]["root"]}
    for root in write_roots:
        if locators_overlap(root, control_locator):
            raise StateError("Action may not write controller Case state: %s" % locator_text(root))
    prefix = action_type.split(".", 1)[0]
    allowed = []
    if prefix == "pgen":
        if execution_site != state["source"]["authority"]["site_id"]:
            raise StateError("pgen Action must execute on the source authority site")
        design = state["artifacts"]["design"]
        allowed = [state["artifacts"]["pgen"], state["artifacts"]["toml"], {
            "site_id": design["site_id"], "path": os.path.dirname(design["path"]),
        }]
    elif prefix == "build":
        root = resource_root(state, "build")
        if not root:
            raise StateError("build root is not configured")
        allowed = [root]
    elif prefix == "run":
        root = resource_root(state, "run")
        if not root:
            raise StateError("run root is not configured")
        allowed = [root]
    elif prefix == "data":
        profile = load_site_profile(home, execution_site)
        roots = profile.get("roots", {})
        for key in ["analysis_root", "staging_root"]:
            if roots.get(key):
                allowed.append({"site_id": execution_site, "path": roots[key]})
        root = resource_root(state, "analysis")
        if root and root["site_id"] == execution_site:
            allowed.append(root)
    elif prefix == "analysis":
        root = resource_root(state, "analysis")
        if not root:
            raise StateError("analysis root is not configured")
        allowed = [root]
    elif prefix == "source":
        profile = load_site_profile(home, execution_site)
        roots = profile.get("roots", {})
        for key in ["source_root", "staging_root"]:
            if roots.get(key):
                allowed.append({"site_id": execution_site, "path": roots[key]})
        allowed.extend(item for item in state["source"].get("replicas", []) if item["site_id"] == execution_site)
    if allowed:
        for root in write_roots:
            if not any(locator_within(root, item) for item in allowed):
                raise StateError("Action write root is outside the owner envelope: %s" % locator_text(root))


def parse_locators(home, values):
    return [canonical_locator(home, value) for value in values or []]


def locator_covered(locator, roots):
    return any(locator_within(locator, root) for root in roots)


def worker_request_locator(home, state, execution_site, request_path, action_id):
    profile = load_site_profile(home, execution_site)
    if profile["transport"]["kind"] == "local":
        return {"site_id": execution_site, "path": absolute(request_path)}
    staging = profile.get("roots", {}).get("staging_root")
    if not staging:
        raise StateError("remote execution site requires staging_root")
    destination = os.path.join(staging, state["case_uid"], "actions", action_id, "request.json")
    return {"site_id": execution_site, "path": destination}


def stage_request(home, worker_request, request_path):
    profile = load_site_profile(home, worker_request["site_id"])
    if profile["transport"]["kind"] == "local":
        return
    destination = worker_request["path"]
    alias = profile["transport"]["ssh_alias"]
    code, unused, stderr = run_on_site(profile, ["mkdir", "-p", os.path.dirname(destination)])
    if code != 0:
        raise StateError("cannot create remote Action staging directory: %s" % stderr.strip())
    code, unused, stderr = run_command([
        "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        request_path, "%s:%s" % (alias, shlex.quote(destination)),
    ])
    if code != 0:
        raise StateError("cannot stage remote Action request: %s" % stderr.strip())


def command_start_action(args):
    case_dir = resolve_case(args.router_home, args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["case_status"] != "active" or state["workflow"]["status"] != "active":
            raise StateError("case and workflow must both be active")
        if state["workflow"].get("active_action_id"):
            raise StateError("another Action is already active")
        if args.action_type not in state["workflow"].get("allowed_actions", []):
            raise StateError("action is not allowed in current state: %s" % args.action_type)
        required_owner, required_domain = required_execution(args.action_type)
        if args.owner != required_owner or args.execution_domain != required_domain:
            raise StateError("action execution mismatch: %s requires owner=%s execution_domain=%s" % (args.action_type, required_owner, required_domain))
        prefix = args.action_type.split(".", 1)[0]
        if args.action_type in {"build.compile", "run.prepare"} and not args.identity_id:
            raise StateError("%s requires --identity-id" % args.action_type)
        if args.identity_id and prefix in {"build", "run"}:
            identities = state["resources"][prefix].get("identities", [])
            if any(item.get("id") == args.identity_id for item in identities):
                raise StateError("%s identity already exists: %s" % (prefix, args.identity_id))
        if args.action_type == "run.prepare" and not state["resources"]["build"].get("current_id"):
            raise StateError("run.prepare requires a current immutable build identity")
        load_site_profile(args.router_home, args.execution_site)
        read_roots = parse_locators(args.router_home, args.read_root)
        write_roots = parse_locators(args.router_home, args.write_root)
        protected = parse_locators(args.router_home, args.protected_path)
        control_locator = {
            "site_id": state["control"]["site_id"],
            "path": state["control"]["root"],
        }
        if control_locator not in protected:
            protected.append(control_locator)
        if not write_roots:
            raise StateError("at least one --write-root locator is required")
        validate_action_write_envelope(state, args.action_type, args.execution_site, write_roots, args.router_home)
        for root in write_roots:
            if any(locators_overlap(root, item) for item in protected):
                raise StateError("write root overlaps protected locator: %s" % locator_text(root))
        inputs = []
        for raw in args.input:
            locator = canonical_locator(args.router_home, raw)
            if not locator_covered(locator, read_roots + write_roots):
                raise StateError("Action input is outside read/write roots: %s" % locator_text(locator))
            evidence = probe_locator(args.router_home, locator)
            if evidence["kind"] == "missing":
                raise StateError("Action input does not exist: %s" % locator_text(locator))
            inputs.append(evidence)
        expected_outputs = parse_locators(args.router_home, args.expected_output)
        for locator in expected_outputs:
            if not locator_covered(locator, write_roots):
                raise StateError("expected output is outside Action write roots: %s" % locator_text(locator))
        action_dir = os.path.join(case_dir, "actions", args.action_id)
        request_path = os.path.join(action_dir, "request.json")
        if os.path.exists(action_dir):
            raise StateError("Action ID already exists: %s" % args.action_id)
        os.makedirs(action_dir)
        worker_request = worker_request_locator(
            args.router_home, state, args.execution_site, request_path, args.action_id
        )
        request = {
            "schema_version": 2,
            "case_revision": state["revision"],
            "case_uid": state["case_uid"],
            "case_id": state["case_id"],
            "workflow_id": state["workflow"]["workflow_id"],
            "action_id": args.action_id,
            "action_type": args.action_type,
            "owner": args.owner,
            "execution_domain": args.execution_domain,
            "execution_site_id": args.execution_site,
            "identity_id": args.identity_id or "",
            "source_revision": effective_source_revision(state),
            "build_id": state["resources"]["build"].get("current_id", ""),
            "run_id": state["resources"]["run"].get("current_id", ""),
            "goal": args.goal,
            "playbook": args.playbook or "",
            "inputs": inputs,
            "read_roots": read_roots,
            "write_roots": write_roots,
            "protected_paths": protected,
            "constraints": args.constraint,
            "expected_outputs": expected_outputs,
            "acceptance_checks": args.acceptance_check,
            "failure_evidence": [],
            "worker_request": worker_request,
            "started_at": now_utc(),
        }
        try:
            atomic_write_json(request_path, request)
            stage_request(args.router_home, worker_request, request_path)
        except Exception:
            shutil.rmtree(action_dir, ignore_errors=True)
            raise
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["workflow"]["owner"] = args.owner
        state["workflow"]["phase"] = args.action_type.split(".", 1)[0]
        state["workflow"]["active_action_id"] = args.action_id
        state["workflow"]["allowed_actions"] = []
        state["workflow"]["next_action"] = ""
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "action.started", state["revision"], {"action_id": args.action_id, "execution_site_id": args.execution_site})
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"], "request": request_path, "worker_request": request["worker_request"]}


def parse_key_value(items, label):
    result = {}
    for item in items or []:
        if "=" not in item:
            raise StateError("%s must use NAME=VALUE" % label)
        key, value = item.split("=", 1)
        if not key or not value:
            raise StateError("%s requires non-empty name and value" % label)
        result[key] = value
    return result


def parse_readiness_updates(items):
    updates = parse_key_value(items, "--readiness")
    for dimension, status in updates.items():
        if dimension not in READINESS_STATUSES or status not in READINESS_STATUSES[dimension]:
            raise StateError("invalid readiness %s=%s" % (dimension, status))
    return updates


def command_finish_action(args):
    case_dir = resolve_case(args.router_home, args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"].get("active_action_id") != args.action_id:
            raise StateError("Action is not active: %s" % args.action_id)
        action_dir = os.path.join(case_dir, "actions", args.action_id)
        request = load_json(os.path.join(action_dir, "request.json"), "Action request")
        outputs = []
        for raw in args.output:
            locator = canonical_locator(args.router_home, raw)
            if not locator_covered(locator, request["write_roots"]):
                raise StateError("output is outside Action write roots: %s" % locator_text(locator))
            evidence = probe_locator(args.router_home, locator)
            if evidence["kind"] == "missing":
                raise StateError("declared output does not exist: %s" % locator_text(locator))
            outputs.append(evidence)
        if args.status == "completed":
            for expected in request.get("expected_outputs", []):
                if not any(locator_within(item["locator"], expected) for item in outputs):
                    raise StateError("completed Action lacks expected output evidence: %s" % locator_text(expected))
            if len(args.verification) < len(request.get("acceptance_checks", [])):
                raise StateError("completed Action requires at least one verification per acceptance check")
        updates = parse_readiness_updates(args.readiness)
        authority_transfer = None
        if request["action_type"] == "source.transfer-authority" and args.status == "completed":
            if not args.new_authority:
                raise StateError("completed source.transfer-authority requires --new-authority")
            new_authority = canonical_locator(args.router_home, args.new_authority)
            if new_authority not in state["source"].get("replicas", []):
                raise StateError("new authority must be a registered source replica")
            old_authority = state["source"]["authority"]
            old_evidence = probe_locator(args.router_home, old_authority, "git")
            new_evidence = probe_locator(args.router_home, new_authority, "git")
            old_fp = old_evidence.get("fingerprint", {})
            new_fp = new_evidence.get("fingerprint", {})
            if not old_fp.get("commit") or old_fp != new_fp or old_fp.get("dirty"):
                raise StateError("authority transfer requires identical clean Git commit and tree evidence")
            remapped = {}
            for name, locator in state["artifacts"].items():
                relative = os.path.relpath(locator["path"], old_authority["path"])
                if relative == os.pardir or relative.startswith(os.pardir + os.sep):
                    raise StateError("cannot remap artifact outside old authority root")
                remapped[name] = {
                    "site_id": new_authority["site_id"],
                    "path": os.path.normpath(os.path.join(new_authority["path"], relative)),
                }
            authority_transfer = {
                "old": old_authority,
                "new": new_authority,
                "evidence": [old_evidence, new_evidence],
                "artifacts": remapped,
            }
        for dimension, status in updates.items():
            state["readiness"][dimension] = readiness(status, list(outputs))
        result = {
            "schema_version": 2,
            "case_uid": state["case_uid"],
            "case_id": state["case_id"],
            "workflow_id": state["workflow"]["workflow_id"],
            "action_id": args.action_id,
            "action_type": request["action_type"],
            "owner": request["owner"],
            "execution_site_id": request["execution_site_id"],
            "status": args.status,
            "outputs": outputs,
            "verification": args.verification,
            "blockers": args.blocker,
            "diagnosis": args.diagnosis or "",
            "suggested_owner": args.suggested_owner or "",
            "started_at": request["started_at"],
            "finished_at": now_utc(),
        }
        result_path = os.path.join(action_dir, "result.json")
        if os.path.exists(result_path):
            raise StateError("Action result already exists")
        atomic_write_json(result_path, result)
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["workflow"]["active_action_id"] = ""
        state["workflow"]["owner"] = "router"
        state["workflow"]["blockers"] = args.blocker
        state["workflow"]["status"] = "blocked" if args.status == "blocked" else "active"
        state["case_status"] = "blocked" if args.status == "blocked" else "active"
        state["workflow"]["next_action"] = args.next_action or ""
        if request["action_type"] == "source.materialize" and args.status == "completed":
            state["source"]["materializations"].append({
                "site_id": request["execution_site_id"],
                "outputs": outputs,
                "verified_at": now_utc(),
            })
        if request["action_type"] == "build.compile" and args.status == "completed":
            identity = request.get("identity_id", "")
            if not identity:
                raise StateError("completed build.compile has no immutable build identity")
            record = {
                "id": identity,
                "site_id": request["execution_site_id"],
                "source_revision": request.get("source_revision", {}),
                "outputs": outputs,
                "verified_at": now_utc(),
            }
            state["resources"]["build"].setdefault("identities", []).append(record)
            state["resources"]["build"]["current_id"] = identity
        if request["action_type"] == "run.prepare" and args.status == "completed":
            identity = request.get("identity_id", "")
            if not identity:
                raise StateError("completed run.prepare has no immutable run identity")
            record = {
                "id": identity,
                "site_id": request["execution_site_id"],
                "build_id": request.get("build_id", ""),
                "outputs": outputs,
                "verified_at": now_utc(),
            }
            state["resources"]["run"].setdefault("identities", []).append(record)
            state["resources"]["run"]["current_id"] = identity
        if (request["action_type"] in {"pgen.design", "pgen.edit", "pgen.fix"}
                and args.status == "completed"):
            authority_evidence = probe_safe(args.router_home, state["source"]["authority"], "git")
            state["source"]["revision"] = authority_evidence.get("fingerprint", {})
            state["readiness"]["source"] = readiness("stale", [authority_evidence])
            if state["readiness"]["build"]["status"] != "absent":
                state["readiness"]["build"]["status"] = "stale"
            if state["readiness"]["run"]["status"] in {"prepared", "submitted", "running"}:
                state["readiness"]["run"]["status"] = "stale"
        if authority_transfer:
            state["source"]["authority"] = authority_transfer["new"]
            state["source"]["replicas"] = [authority_transfer["old"]] + [
                item for item in state["source"].get("replicas", [])
                if item != authority_transfer["new"] and item != authority_transfer["old"]
            ]
            state["source"]["revision"] = authority_transfer["evidence"][1]["fingerprint"]
            state["artifacts"] = authority_transfer["artifacts"]
            state["readiness"]["pgen"] = readiness("verified", authority_transfer["evidence"])
            state["readiness"]["source"] = readiness("ready", authority_transfer["evidence"])
            if state["readiness"]["build"]["status"] != "absent":
                state["readiness"]["build"]["status"] = "stale"
            if state["readiness"]["run"]["status"] not in {"none", "completed", "failed", "stopped"}:
                state["readiness"]["run"]["status"] = "stale"
        set_allowed_actions(state)
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "action.%s" % args.status, state["revision"], {"action_id": args.action_id, "readiness": updates})
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"], "result": result_path, "allowed_actions": state["workflow"]["allowed_actions"]}


def fingerprint_changed(home, evidence):
    if evidence.get("kind") == "observation":
        return False
    locator = evidence.get("locator")
    if not locator:
        return True
    current = probe_safe(home, locator)
    return current.get("kind") != evidence.get("kind") or current.get("fingerprint") != evidence.get("fingerprint")


def command_refresh(args):
    case_dir = resolve_case(args.router_home, args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        changed = []
        for dimension, item in state["readiness"].items():
            evidence = item.get("evidence", [])
            if evidence and any(fingerprint_changed(args.router_home, entry) for entry in evidence):
                changed.append(dimension)
                if dimension == "orientation":
                    item["status"] = "unresolved"
                elif dimension == "data":
                    item["status"] = "unknown"
                elif "stale" in READINESS_STATUSES[dimension]:
                    item["status"] = "stale"
        if "pgen" in changed:
            state["readiness"]["source"]["status"] = "stale"
            if state["readiness"]["build"]["status"] != "absent":
                state["readiness"]["build"]["status"] = "stale"
            if state["readiness"]["run"]["status"] in {"prepared", "submitted"}:
                state["readiness"]["run"]["status"] = "stale"
        if "source" in changed and state["readiness"]["build"]["status"] != "absent":
            state["readiness"]["build"]["status"] = "stale"
        if "build" in changed and state["readiness"]["run"]["status"] == "prepared":
            state["readiness"]["run"]["status"] = "stale"
        if "data" in changed and state["readiness"]["analysis"]["status"] != "none":
            state["readiness"]["analysis"]["status"] = "stale"
        if changed:
            state["revision"] += 1
            state["updated_at"] = now_utc()
            set_allowed_actions(state)
            atomic_write_json(state_path(case_dir), state)
            append_event(case_dir, "case.refreshed", state["revision"], {"changed_dimensions": changed})
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"], "changed_dimensions": changed, "state": state}


def command_reconcile(args):
    case_dir = resolve_case(args.router_home, args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"].get("active_action_id"):
            raise StateError("cannot reconcile while an Action is active")
        updates = parse_readiness_updates(args.readiness)
        evidence_values = {}
        for raw in args.evidence:
            if "=" not in raw:
                raise StateError("--evidence must use DIMENSION=LOCATOR")
            dimension, value = raw.split("=", 1)
            if dimension not in READINESS_STATUSES:
                raise StateError("unknown readiness dimension in --evidence: %s" % dimension)
            evidence_values.setdefault(dimension, []).append(probe_locator(args.router_home, value))
        observations = {}
        for raw in args.observation:
            if "=" not in raw:
                raise StateError("--observation must use DIMENSION=VALUE")
            dimension, value = raw.split("=", 1)
            if dimension not in READINESS_STATUSES:
                raise StateError("unknown readiness dimension in --observation: %s" % dimension)
            observations.setdefault(dimension, []).append({
                "kind": "observation", "value": value, "observed_at": now_utc(), "observer_site": "controller",
            })
        neutral = {"unresolved", "absent", "none", "unknown", "unmaterialized", "planned"}
        for dimension, status in updates.items():
            entries = evidence_values.get(dimension, []) + observations.get(dimension, [])
            if status not in neutral and not entries:
                raise StateError("readiness %s=%s requires evidence or observation" % (dimension, status))
            state["readiness"][dimension] = readiness(status, entries)
        if args.active_run:
            state["resources"]["run"]["current_id"] = args.active_run_id or "external"
            state["resources"]["run"]["active"] = canonical_locator(args.router_home, args.active_run)
        for raw in args.protect_path:
            state.setdefault("protected_paths", []).append(canonical_locator(args.router_home, raw))
        if not updates and not args.active_run and not args.protect_path:
            raise StateError("reconcile requires a readiness or scope update")
        state["revision"] += 1
        state["updated_at"] = now_utc()
        set_allowed_actions(state)
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "case.reconciled", state["revision"], {"readiness": updates})
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"], "allowed_actions": state["workflow"]["allowed_actions"]}


def command_update_memory(args):
    case_dir = resolve_case(args.router_home, args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"].get("active_action_id"):
            raise StateError("cannot update memory while an Action is active")
        memory = state["memory"]
        changed = False
        if args.goal is not None and args.goal != memory["goal"]:
            memory["goal"] = args.goal
            changed = True
        if args.done_when is not None and args.done_when != memory["done_when"]:
            memory["done_when"] = args.done_when
            changed = True
        for key, values in [
            ("confirmed_decisions", args.decision),
            ("open_questions", args.open_question),
            ("constraints", args.constraint),
            ("out_of_scope", args.out_of_scope),
        ]:
            for value in values:
                if value not in memory[key]:
                    memory[key].append(value)
                    changed = True
        for value in args.resolve_question:
            if value in memory["open_questions"]:
                memory["open_questions"].remove(value)
                changed = True
        if args.summary is not None and args.summary != memory["last_summary"]:
            memory["last_summary"] = args.summary
            changed = True
        if not changed:
            raise StateError("memory update does not change Case state")
        state["revision"] += 1
        state["updated_at"] = now_utc()
        atomic_write_json(state_path(case_dir), state)
        append_event(case_dir, "case.memory_updated", state["revision"])
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"]}


def save_snapshot(case_dir, state, suffix):
    path = os.path.join(case_dir, "history", "%s-%s-r%s.json" % (state["workflow"]["workflow_id"], suffix, state["revision"]))
    atomic_write_json(path, state)
    return path


def command_suspend(args):
    return _set_suspended(args, True)


def command_resume(args):
    return _set_suspended(args, False)


def _set_suspended(args, suspended):
    case_dir = resolve_case(args.router_home, args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"].get("active_action_id"):
            raise StateError("cannot change suspension with an active Action")
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["case_status"] = "suspended" if suspended else "active"
        state["workflow"]["status"] = "suspended" if suspended else "active"
        if suspended:
            state["memory"]["last_summary"] = args.summary
        set_allowed_actions(state)
        atomic_write_json(state_path(case_dir), state)
        snapshot = save_snapshot(case_dir, state, "suspended") if suspended else ""
        append_event(case_dir, "case.suspended" if suspended else "case.resumed", state["revision"])
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"], "snapshot": snapshot, "allowed_actions": state["workflow"]["allowed_actions"]}


def command_complete_workflow(args):
    case_dir = resolve_case(args.router_home, args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"].get("active_action_id"):
            raise StateError("cannot complete workflow with active Action")
        if len(args.verification) < len(state["memory"].get("done_when", [])):
            raise StateError("completion requires one verification per done_when")
        evidence = [probe_locator(args.router_home, value) for value in args.evidence]
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["case_status"] = "complete"
        state["workflow"]["status"] = "complete"
        state["workflow"]["owner"] = "router"
        state["workflow"]["allowed_actions"] = []
        state["workflow"]["next_action"] = ""
        state["memory"]["last_summary"] = args.summary
        atomic_write_json(state_path(case_dir), state)
        snapshot = save_snapshot(case_dir, state, "complete")
        append_event(case_dir, "workflow.completed", state["revision"], {"verification": args.verification, "evidence": evidence})
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"], "snapshot": snapshot}


def command_new_workflow(args):
    case_dir = resolve_case(args.router_home, args.case)
    with locked_case(case_dir):
        state = load_state(case_dir)
        require_revision(state, args.expected_revision)
        if state["workflow"]["status"] != "complete":
            raise StateError("new workflow requires current workflow complete")
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["case_status"] = "active"
        state["memory"]["goal"] = args.goal
        state["memory"]["done_when"] = args.done_when
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
        append_event(case_dir, "workflow.created", state["revision"], {"workflow_id": args.workflow_id})
        return {"ok": True, "case_dir": case_dir, "revision": state["revision"], "allowed_actions": state["workflow"]["allowed_actions"]}


def command_migrate_case(args):
    legacy_case = absolute(args.legacy_case)
    old_path = os.path.join(legacy_case, "_case", "case.json")
    old = load_json(old_path, "v2 Case state")
    if old.get("schema_version") != 2:
        raise StateError("migrate-case accepts only schema v2 Cases")
    scope = old.get("scope", {})
    proposal = {
        "legacy_case": legacy_case,
        "legacy_site": args.legacy_site,
        "source_authority": "%s:%s" % (args.legacy_site, legacy_case),
        "pgen": "%s:%s" % (args.legacy_site, scope.get("pgen_path", os.path.join(legacy_case, "pgen.hpp"))),
        "toml": "%s:%s" % (args.legacy_site, scope.get("toml_path", os.path.join(legacy_case, "%s.toml" % old.get("case_id", "pgen")))),
        "design": "%s:%s" % (args.legacy_site, scope.get("design_doc", os.path.join(legacy_case, "docs", "design.md"))),
    }
    if args.dry_run:
        return {"ok": True, "dry_run": True, "proposal": proposal}
    if not args.commit:
        raise StateError("migrate-case requires --dry-run or --commit")
    try:
        load_site_profile(args.router_home, args.controller_site)
    except RouterError:
        save_site_profile(args.router_home, {
            "schema_version": 1,
            "site_id": args.controller_site,
            "display_name": "Migration controller",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "none"},
            "roots": {},
            "shared_mappings": [],
            "created_at": now_utc(),
            "updated_at": now_utc(),
        })
    try:
        load_site_profile(args.router_home, args.legacy_site)
    except RouterError:
        save_site_profile(args.router_home, {
            "schema_version": 1,
            "site_id": args.legacy_site,
            "display_name": "Imported v2 local workspace",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "none"},
            "roots": {
                "source_root": scope.get("entity_checkout", legacy_case),
                "build_root": os.path.join(legacy_case, "build"),
                "run_root": legacy_case,
                "staging_root": legacy_case,
            },
            "created_at": now_utc(),
            "updated_at": now_utc(),
        })
    create_args = argparse.Namespace(
        router_home=args.router_home,
        case_uid=args.case_uid,
        case_id=old.get("case_id", os.path.basename(legacy_case)),
        control_root=args.control_root,
        case_dir=None,
        controller_site=args.controller_site,
        source_authority=proposal["source_authority"],
        source_replica=[],
        transfer_policy="external",
        pgen_locator=proposal["pgen"],
        toml_locator=proposal["toml"],
        design_locator=proposal["design"],
        build_root="%s:%s" % (args.legacy_site, os.path.join(legacy_case, "build")),
        run_root="%s:%s" % (args.legacy_site, legacy_case),
        data_root="%s:%s" % (args.legacy_site, legacy_case),
        analysis_root="%s:%s" % (args.legacy_site, legacy_case),
        goal=old.get("memory", {}).get("goal", "migrated v2 Case"),
        done_when=old.get("memory", {}).get("done_when", []),
        name=old.get("identity", {}).get("name"),
        summary=old.get("identity", {}).get("summary"),
        workflow_id="migrated-%s" % old.get("workflow", {}).get("workflow_id", "workflow"),
        workflow_type=old.get("workflow", {}).get("type", "migrated"),
    )
    created = command_create(create_args)
    new_case = created["case_dir"]
    old_suspended = False
    try:
        legacy_copy = os.path.join(new_case, "evidence", "legacy-v2-control")
        shutil.copytree(os.path.join(legacy_case, "_case"), legacy_copy)
        state = load_state(new_case)
        state["case_status"] = "suspended"
        state["workflow"]["status"] = "suspended"
        state["legacy"] = {"schema_version": 2, "case_root": legacy_case, "control_copy": legacy_copy}
        atomic_write_json(state_path(new_case), state)
        validate_state(load_state(new_case), new_case)
        backup = dict(old)
        atomic_write_json(os.path.join(legacy_case, "_case", "migration-backup.json"), backup)
        old["case_status"] = "suspended"
        old.setdefault("workflow", {})["status"] = "suspended"
        old.setdefault("memory", {})["last_summary"] = "Migrated to Router v3 Case %s" % created["case_uid"]
        atomic_write_json(old_path, old)
        old_suspended = True
        state["revision"] += 1
        state["updated_at"] = now_utc()
        state["case_status"] = "active"
        state["workflow"]["status"] = "active"
        set_allowed_actions(state)
        atomic_write_json(state_path(new_case), state)
        append_event(new_case, "case.migrated", state["revision"], {"legacy_case": legacy_case})
        created["revision"] = state["revision"]
        created["state"] = state
    except Exception:
        if not old_suspended:
            shutil.rmtree(new_case, ignore_errors=True)
            unregister_case(args.router_home, created["case_uid"], new_case)
        raise
    created["migration"] = {"legacy_case": legacy_case, "control_copy": legacy_copy}
    return created


def add_common_case(parser):
    parser.add_argument("--case", required=True)


def build_parser():
    parser = argparse.ArgumentParser(description="Entity Router v3 Case controller")
    parser.add_argument("--router-home", default=router_home())
    sub = parser.add_subparsers(dest="command")
    create = sub.add_parser("create")
    create.add_argument("--control-root")
    create.add_argument("--case-dir")
    create.add_argument("--case-id", required=True)
    create.add_argument("--case-uid")
    create.add_argument("--controller-site", default="local")
    create.add_argument("--source-authority", required=True)
    create.add_argument("--source-replica", action="append", default=[])
    create.add_argument("--transfer-policy", choices=["git-ref", "snapshot", "shared", "external"], default="git-ref")
    create.add_argument("--pgen-locator", required=True)
    create.add_argument("--toml-locator", required=True)
    create.add_argument("--design-locator", required=True)
    create.add_argument("--build-root")
    create.add_argument("--run-root")
    create.add_argument("--data-root")
    create.add_argument("--analysis-root")
    create.add_argument("--goal", required=True)
    create.add_argument("--done-when", action="append", default=[])
    create.add_argument("--name")
    create.add_argument("--summary")
    create.add_argument("--workflow-id", default="wf-initial")
    create.add_argument("--workflow-type", default="new-simulation")
    create.set_defaults(func=command_create)
    listing = sub.add_parser("list")
    listing.set_defaults(func=command_list)
    rebuild = sub.add_parser("rebuild-registry")
    rebuild.add_argument("--scan-root", action="append", default=[])
    rebuild.set_defaults(func=command_rebuild_registry)
    show = sub.add_parser("show"); add_common_case(show); show.set_defaults(func=command_show)
    verify = sub.add_parser("verify"); add_common_case(verify); verify.set_defaults(func=command_verify)
    start = sub.add_parser("start-action"); add_common_case(start)
    start.add_argument("--expected-revision", required=True, type=int)
    start.add_argument("--action-id", required=True)
    start.add_argument("--action-type", required=True)
    start.add_argument("--owner", required=True)
    start.add_argument("--execution-domain", required=True)
    start.add_argument("--execution-site", required=True)
    start.add_argument("--identity-id")
    start.add_argument("--goal", required=True)
    start.add_argument("--playbook")
    start.add_argument("--input", action="append", default=[])
    start.add_argument("--read-root", action="append", default=[])
    start.add_argument("--write-root", action="append", default=[])
    start.add_argument("--protected-path", action="append", default=[])
    start.add_argument("--constraint", action="append", default=[])
    start.add_argument("--expected-output", action="append", default=[])
    start.add_argument("--acceptance-check", action="append", default=[])
    start.set_defaults(func=command_start_action)
    finish = sub.add_parser("finish-action"); add_common_case(finish)
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
    finish.add_argument("--new-authority")
    finish.set_defaults(func=command_finish_action)
    refresh = sub.add_parser("refresh"); add_common_case(refresh)
    refresh.add_argument("--expected-revision", required=True, type=int); refresh.set_defaults(func=command_refresh)
    reconcile = sub.add_parser("reconcile"); add_common_case(reconcile)
    reconcile.add_argument("--expected-revision", required=True, type=int)
    reconcile.add_argument("--readiness", action="append", default=[])
    reconcile.add_argument("--evidence", action="append", default=[])
    reconcile.add_argument("--observation", action="append", default=[])
    reconcile.add_argument("--active-run")
    reconcile.add_argument("--active-run-id")
    reconcile.add_argument("--protect-path", action="append", default=[])
    reconcile.set_defaults(func=command_reconcile)
    memory = sub.add_parser("update-memory"); add_common_case(memory)
    memory.add_argument("--expected-revision", required=True, type=int)
    memory.add_argument("--goal")
    memory.add_argument("--done-when", action="append", default=None)
    memory.add_argument("--decision", action="append", default=[])
    memory.add_argument("--open-question", action="append", default=[])
    memory.add_argument("--resolve-question", action="append", default=[])
    memory.add_argument("--constraint", action="append", default=[])
    memory.add_argument("--out-of-scope", action="append", default=[])
    memory.add_argument("--summary")
    memory.set_defaults(func=command_update_memory)
    suspend = sub.add_parser("suspend"); add_common_case(suspend)
    suspend.add_argument("--expected-revision", required=True, type=int); suspend.add_argument("--summary", required=True); suspend.set_defaults(func=command_suspend)
    resume = sub.add_parser("resume"); add_common_case(resume)
    resume.add_argument("--expected-revision", required=True, type=int); resume.set_defaults(func=command_resume)
    complete = sub.add_parser("complete-workflow"); add_common_case(complete)
    complete.add_argument("--expected-revision", required=True, type=int)
    complete.add_argument("--summary", required=True)
    complete.add_argument("--verification", action="append", default=[])
    complete.add_argument("--evidence", action="append", default=[])
    complete.set_defaults(func=command_complete_workflow)
    workflow = sub.add_parser("new-workflow"); add_common_case(workflow)
    workflow.add_argument("--expected-revision", required=True, type=int)
    workflow.add_argument("--workflow-id", required=True)
    workflow.add_argument("--workflow-type", required=True)
    workflow.add_argument("--goal", required=True)
    workflow.add_argument("--done-when", action="append", default=[])
    workflow.set_defaults(func=command_new_workflow)
    migrate = sub.add_parser("migrate-case")
    migrate.add_argument("--legacy-case", required=True)
    migrate.add_argument("--legacy-site", default="legacy-local")
    migrate.add_argument("--controller-site", default="local")
    migrate.add_argument("--control-root")
    migrate.add_argument("--case-uid")
    mode = migrate.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--commit", action="store_true")
    migrate.set_defaults(func=command_migrate_case)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.error("a command is required")
    args.router_home = ensure_home(args.router_home)
    try:
        payload = args.func(args)
        emit(payload)
        return 0 if payload.get("ok", True) else 2
    except (RouterError, OSError, ValueError, KeyError) as exc:
        emit({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
