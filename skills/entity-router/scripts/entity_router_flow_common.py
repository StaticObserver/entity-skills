#!/usr/bin/env python3
"""Deterministic read-only helpers for the Entity Router flow facade."""

from __future__ import print_function

import json
import os
import re

from entity_router_common import (
    RouterError,
    absolute,
    canonical_locator,
    load_registry,
    load_site_profile,
    locator_within,
    probe_locators_batch,
)
from entity_router_state import (  # noqa: E402
    canonical_hash,
    effective_source_revision,
    identity_record,
    load_state,
    required_execution,
    resolve_case,
    resource_root,
    validate_action_write_envelope,
)


STATUS_EXIT = {
    "pass": 0,
    "completed": 0,
    "observe_only": 0,
    "needs_decision": 10,
    "blocked": 20,
    "anomaly": 30,
    "invalid_request": 40,
    "revision_conflict": 50,
}
STATUS_PRIORITY = {"pass": 0, "needs_decision": 1, "blocked": 2, "anomaly": 3}
PHASES = {"orient", "pgen", "source", "build", "run", "data", "analysis"}
FLOW_REQUIRED = {
    "schema_version", "flow_id", "case_uid", "base_revision", "workflow_id",
    "target_hash", "goal", "steps", "stop_policy",
}
STEP_REQUIRED = {
    "index", "action_id", "action_type", "owner", "execution_domain",
    "execution_site_id", "runner", "identity_id", "spec_hash", "parents",
    "input_from", "inputs", "read_roots", "write_roots", "protected_paths",
    "resource_bindings", "constraints", "expected_outputs", "acceptance_checks",
    "runner_args",
}
FORBIDDEN_BUNDLE_ACTIONS = {"data.purge", "source.transfer-authority"}
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class FlowError(RouterError):
    def __init__(self, status, code, message, result=None):
        RouterError.__init__(self, message)
        self.status = status
        self.code = code
        self.result = result or {}


def issue(code, issue_class, message, subject=None, evidence=None, artifact_ref=None):
    return {
        "code": code,
        "class": issue_class,
        "message": message,
        "subject": subject or {},
        "evidence_fingerprint": canonical_hash(evidence or {}),
        "artifact_ref": artifact_ref,
    }


def status_for_issues(issues):
    status = "pass"
    for item in issues:
        candidate = item.get("class", "anomaly")
        if STATUS_PRIORITY.get(candidate, 3) > STATUS_PRIORITY[status]:
            status = candidate
    return status


def _case_locators(state):
    result = [state["source"]["authority"]]
    result.extend(state["artifacts"].values())
    for resource in state["resources"].values():
        if resource.get("root"):
            result.append(resource["root"])
        if resource.get("active"):
            result.append(resource["active"])
    return result


def select_case(home, case=None, cwd=None):
    if case:
        path = resolve_case(home, case)
        return path, load_state(path), []
    if not cwd:
        raise FlowError("invalid_request", "CASE_SELECTOR_REQUIRED",
                        "inspect requires --case or --cwd")
    current = absolute(cwd)
    matches = []
    registry = load_registry(home)
    for uid, record in sorted(registry.get("cases", {}).items()):
        path = absolute(record.get("control_root", ""))
        try:
            state = load_state(path)
        except RouterError:
            continue
        matched = current == path or locator_within(
            {"site_id": state["control"]["site_id"], "path": current},
            {"site_id": state["control"]["site_id"], "path": path},
        )
        if not matched:
            for locator in _case_locators(state):
                try:
                    profile = load_site_profile(home, locator["site_id"])
                except RouterError:
                    continue
                if profile["transport"]["kind"] != "local":
                    continue
                local = canonical_locator(home, locator)
                if locator_within({"site_id": local["site_id"], "path": current}, local):
                    matched = True
                    break
        if matched:
            matches.append({
                "case_uid": uid,
                "case_id": state["case_id"],
                "control_root": path,
                "revision": state["revision"],
            })
    if not matches:
        raise FlowError("needs_decision", "CASE_NOT_FOUND",
                        "cwd does not match a registered Case", {"candidates": []})
    if len(matches) != 1:
        raise FlowError("needs_decision", "CASE_AMBIGUOUS",
                        "cwd matches multiple registered Cases",
                        {"candidates": matches[:8]})
    path = matches[0]["control_root"]
    return path, load_state(path), matches


def _positive(status):
    return status not in {
        "unresolved", "absent", "none", "unknown", "unmaterialized",
        "planned", "stale", "failed", "fail", "stopped", "corrupt",
    }


def _evidence_within(entries, root):
    if not root:
        return False
    for entry in entries:
        locator = entry.get("locator")
        if locator and locator_within(locator, root):
            return True
    return False


def _live_locators(state, phase):
    locators = []
    if phase in {"orient", "pgen", "source"}:
        locators.append({"locator": state["source"]["authority"], "kind": "git"})
        locators.extend({"locator": value, "kind": "auto"} for value in state["artifacts"].values())
    if phase == "build":
        root = resource_root(state, "build")
        if root:
            locators.append({"locator": root, "kind": "auto"})
    if phase == "run":
        active = state["resources"]["run"].get("active") or resource_root(state, "run")
        if active:
            locators.append({"locator": active, "kind": "auto"})
    if phase == "data":
        root = resource_root(state, "data")
        if root:
            locators.append({"locator": root, "kind": "auto"})
    if phase == "analysis":
        root = resource_root(state, "analysis")
        if root:
            locators.append({"locator": root, "kind": "auto"})
    return locators


def live_probe(home, state, phase):
    grouped = {}
    for item in _live_locators(state, phase):
        grouped.setdefault(item["locator"]["site_id"], []).append(item)
    evidence = []
    issues = []
    remote_calls = 0
    for site_id, items in sorted(grouped.items()):
        try:
            profile = load_site_profile(home, site_id)
            values = probe_locators_batch(home, site_id, items)
            evidence.extend(values)
            if profile["transport"]["kind"] == "ssh":
                remote_calls += 1
        except RouterError as exc:
            issues.append(issue(
                "SITE_UNREACHABLE", "blocked", str(exc),
                {"kind": "site", "id": site_id}, {"phase": phase},
            ))
    return evidence, issues, remote_calls


def check_case(home, case_dir, state, live=False, phase="orient"):
    issues = []
    target = state["workflow"].get("target")
    if target is None:
        issues.append(issue(
            "WF_TARGET_MISSING", "needs_decision",
            "active flow requires a structured workflow target",
            {"kind": "workflow", "id": state["workflow"]["workflow_id"]},
        ))
    elif state["workflow"].get("target_hash") != canonical_hash(target):
        issues.append(issue(
            "WF_TARGET_HASH_DRIFT", "anomaly", "workflow target hash is stale",
            {"kind": "workflow", "id": state["workflow"]["workflow_id"]}, target,
        ))
    action_id = state["workflow"].get("active_action_id", "")
    if action_id:
        action_dir = os.path.join(case_dir, "actions", action_id)
        request_path = os.path.join(action_dir, "request.json")
        result_path = os.path.join(action_dir, "result.json")
        if not os.path.isfile(request_path):
            issues.append(issue(
                "ACTION_REQUEST_MISSING", "anomaly", "active Action request is missing",
                {"kind": "action", "id": action_id},
            ))
        else:
            with open(request_path, "r") as handle:
                request = json.load(handle)
            if os.path.isfile(result_path):
                issues.append(issue(
                    "ACTION_RESULT_ON_ACTIVE", "anomaly",
                    "active Action already has a terminal result",
                    {"kind": "action", "id": action_id}, request,
                ))
            try:
                owner, domain = required_execution(request["action_type"])
                if request.get("owner") != owner or request.get("execution_domain") != domain:
                    raise RouterError("owner or execution domain differs from fixed contract")
                validate_action_write_envelope(
                    state, request["action_type"], request["execution_site_id"],
                    request.get("write_roots", []), home,
                )
                orchestration = request.get("orchestration", {})
                if orchestration.get("flow_id") and orchestration.get("target_hash") != state["workflow"].get("target_hash"):
                    raise RouterError("active flow Action target hash differs from workflow target")
            except (RouterError, KeyError) as exc:
                issues.append(issue(
                    "ACTION_OWNER_ENVELOPE", "anomaly", str(exc),
                    {"kind": "action", "id": action_id}, request,
                ))
    current_source = canonical_hash(effective_source_revision(state))
    build = identity_record(state, "build", state["resources"]["build"].get("current_id", ""))
    if build:
        parent_source = build.get("parents", {}).get("source_revision_hash")
        if not parent_source and build.get("source_revision"):
            parent_source = canonical_hash(build["source_revision"])
        expected_source = (target or {}).get("source_revision_hash") or current_source
        if parent_source and parent_source != expected_source:
            issues.append(issue(
                "ID_BUILD_SOURCE_MISMATCH", "anomaly",
                "current build does not reference the target source revision",
                {"kind": "build", "id": build["id"]}, build,
            ))
    run = identity_record(state, "run", state["resources"]["run"].get("current_id", ""))
    if run:
        parent_build = run.get("parents", {}).get("build_id") or run.get("build_id", "")
        expected_build = (target or {}).get("build_id") or state["resources"]["build"].get("current_id", "")
        if parent_build and parent_build != expected_build:
            issues.append(issue(
                "ID_RUN_BUILD_MISMATCH", "anomaly",
                "current run does not reference the target build identity",
                {"kind": "run", "id": run["id"]}, run,
            ))
    active = state["resources"]["run"].get("active")
    run_root = resource_root(state, "run")
    if active and (not run_root or not locator_within(active, run_root)):
        issues.append(issue(
            "ID_ACTIVE_RUN_SCOPE", "anomaly", "active run is outside run root",
            {"kind": "run", "id": state["resources"]["run"].get("current_id", "")}, active,
        ))
    data = identity_record(state, "data", state["resources"]["data"].get("current_id", ""))
    if data:
        parent_run = data.get("parents", {}).get("run_id", "")
        if parent_run != state["resources"]["run"].get("current_id", ""):
            issues.append(issue(
                "ID_DATA_RUN_MISMATCH", "anomaly",
                "current data does not reference the current run identity",
                {"kind": "data", "id": data["id"]}, data,
            ))
    data_ready = state["readiness"]["data"]
    data_root = resource_root(state, "data")
    data_scope_ok = bool(data and data.get("root") and data_root
                         and locator_within(data["root"], data_root))
    if (_positive(data_ready["status"]) and not data_scope_ok
            and not _evidence_within(data_ready.get("evidence", []), data_root)):
        issues.append(issue(
            "ID_DATA_SCOPE", "anomaly", "positive data evidence is outside current data root",
            {"kind": "data", "id": state["resources"]["data"].get("current_id", "")}, data_ready,
        ))
    analysis = identity_record(state, "analysis", state["resources"]["analysis"].get("current_id", ""))
    if analysis:
        parent_data = analysis.get("parents", {}).get("data_id", "")
        if parent_data != state["resources"]["data"].get("current_id", ""):
            issues.append(issue(
                "ID_ANALYSIS_DATA_MISMATCH", "anomaly",
                "current analysis does not reference the current data identity",
                {"kind": "analysis", "id": analysis["id"]}, analysis,
            ))
    live_evidence = []
    remote_calls = 0
    if live:
        live_evidence, live_issues, remote_calls = live_probe(home, state, phase)
        issues.extend(live_issues)
    return {
        "schema_version": 1,
        "status": status_for_issues(issues),
        "case_uid": state["case_uid"],
        "revision": state["revision"],
        "issues": issues,
        "live_evidence": live_evidence,
        "metrics": {"remote_calls": remote_calls},
    }


def compact_summary(state, checked):
    action_id = state["workflow"].get("active_action_id", "")
    active_action = None
    if action_id:
        active_action = {"id": action_id, "type": "", "flow_id": ""}
        case_dir = state["control"]["root"]
        request_path = os.path.join(case_dir, "actions", action_id, "request.json")
        try:
            with open(request_path, "r") as handle:
                request = json.load(handle)
            active_action["type"] = request.get("action_type", "")
            active_action["flow_id"] = request.get("orchestration", {}).get("flow_id", "")
        except (IOError, OSError, ValueError):
            pass
    return {
        "case_uid": state["case_uid"],
        "revision": state["revision"],
        "workflow": {
            "id": state["workflow"]["workflow_id"],
            "phase": state["workflow"]["phase"],
            "status": state["workflow"]["status"],
            "target_hash": state["workflow"].get("target_hash", ""),
        },
        "active_action": active_action,
        "readiness": {key: value["status"] for key, value in state["readiness"].items()},
        "identities": {
            "source": canonical_hash(effective_source_revision(state)),
            "build": state["resources"]["build"].get("current_id", ""),
            "run": state["resources"]["run"].get("current_id", ""),
            "data": state["resources"]["data"].get("current_id", ""),
            "analysis": state["resources"]["analysis"].get("current_id", ""),
        },
        "allowed_actions": state["workflow"].get("allowed_actions", []),
        "issues": checked["issues"],
        "decision_required": checked["status"] == "needs_decision",
    }


def bound_payload(payload, limit=4096):
    value = json.loads(json.dumps(payload))
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if len(rendered.encode("utf-8")) <= limit:
        return value
    if isinstance(value.get("issues"), list):
        value["issues"] = value["issues"][:4]
        for item in value["issues"]:
            item["message"] = item.get("message", "")[:200]
    result = value.get("result")
    if isinstance(result, dict) and isinstance(result.get("candidates"), list):
        result["candidates"] = result["candidates"][:4]
    value["truncated"] = True
    return value


def load_flow_request(path):
    with open(absolute(path), "r") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise FlowError("invalid_request", "FLOW_SCHEMA", "flow request must be an object")
    missing = FLOW_REQUIRED.difference(value)
    unknown = set(value).difference(FLOW_REQUIRED)
    if missing or unknown:
        raise FlowError(
            "invalid_request", "FLOW_SCHEMA",
            "flow request keys differ from schema; missing=%s unknown=%s" %
            (sorted(missing), sorted(unknown)),
        )
    if value.get("schema_version") != 1:
        raise FlowError("invalid_request", "FLOW_SCHEMA", "flow request must use schema_version 1")
    for key in ["flow_id", "case_uid", "workflow_id", "goal"]:
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise FlowError("invalid_request", "FLOW_SCHEMA", "%s must be a non-empty string" % key)
    if (not isinstance(value.get("base_revision"), int)
            or isinstance(value.get("base_revision"), bool)
            or value["base_revision"] < 0):
        raise FlowError("invalid_request", "FLOW_SCHEMA", "base_revision must be a non-negative integer")
    if not isinstance(value.get("target_hash"), str) or not HASH_RE.match(value["target_hash"]):
        raise FlowError("invalid_request", "FLOW_SCHEMA", "target_hash must be sha256:<digest>")
    stop = value.get("stop_policy")
    stop_keys = {"on_completed", "on_needs_decision", "on_blocked", "on_anomaly"}
    if (not isinstance(stop, dict) or set(stop) != stop_keys
            or stop.get("on_completed") not in {"continue", "return"}
            or any(stop.get(key) != "return" for key in
                   ["on_needs_decision", "on_blocked", "on_anomaly"])):
        raise FlowError("invalid_request", "FLOW_SCHEMA", "stop_policy differs from the fixed contract")
    steps = value.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise FlowError("invalid_request", "FLOW_SCHEMA", "flow request requires 1 to 8 steps")
    action_ids = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise FlowError("invalid_request", "FLOW_STEP_SCHEMA", "flow step must be an object")
        missing = STEP_REQUIRED.difference(step)
        unknown = set(step).difference(STEP_REQUIRED)
        if missing or unknown:
            raise FlowError(
                "invalid_request", "FLOW_STEP_SCHEMA",
                "flow step keys differ from schema; missing=%s unknown=%s" %
                (sorted(missing), sorted(unknown)),
            )
        if step["index"] != index:
            raise FlowError("invalid_request", "FLOW_STEP_INDEX", "flow step indexes must be contiguous")
        if step["action_id"] in action_ids:
            raise FlowError("invalid_request", "FLOW_ACTION_ID", "flow Action IDs must be unique")
        action_ids.add(step["action_id"])
        for key in ["action_id", "action_type", "owner", "execution_domain",
                    "execution_site_id", "runner"]:
            if not isinstance(step.get(key), str) or not step[key].strip():
                raise FlowError("invalid_request", "FLOW_STEP_SCHEMA",
                                "step %s must be a non-empty string" % key)
        for key in ["identity_id", "spec_hash"]:
            if not isinstance(step.get(key), str):
                raise FlowError("invalid_request", "FLOW_STEP_SCHEMA",
                                "step %s must be a string" % key)
        if not isinstance(step.get("parents"), dict) or not all(
                isinstance(key, str) and key and isinstance(item, str) and item
                for key, item in step["parents"].items()):
            raise FlowError("invalid_request", "FLOW_STEP_SCHEMA",
                            "step parents must map non-empty strings")
        if not isinstance(step.get("resource_bindings"), dict):
            raise FlowError("invalid_request", "FLOW_STEP_SCHEMA",
                            "resource_bindings must be an object")
        if not isinstance(step.get("runner_args"), dict):
            raise FlowError("invalid_request", "FLOW_STEP_SCHEMA", "runner_args must be an object")
        if step["action_type"] in FORBIDDEN_BUNDLE_ACTIONS:
            raise FlowError("invalid_request", "FLOW_FORBIDDEN_ACTION",
                            "destructive or authority Actions require an independent request")
        try:
            owner, domain = required_execution(step["action_type"])
        except RouterError as exc:
            raise FlowError("invalid_request", "FLOW_ACTION_CONTRACT", str(exc))
        if step["owner"] != owner or step["execution_domain"] != domain:
            raise FlowError("invalid_request", "FLOW_ACTION_CONTRACT",
                            "flow step owner/domain differs from fixed Action contract")
        if not isinstance(step["write_roots"], list) or not step["write_roots"]:
            raise FlowError("invalid_request", "FLOW_STEP_SCHEMA", "flow step requires write_roots")
        for key in ["inputs", "read_roots", "write_roots", "protected_paths", "expected_outputs"]:
            if not isinstance(step.get(key), list):
                raise FlowError("invalid_request", "FLOW_STEP_SCHEMA", "%s must be an array" % key)
            for locator in step[key]:
                if (not isinstance(locator, dict) or set(locator) != {"site_id", "path"}
                        or not isinstance(locator.get("site_id"), str) or not locator["site_id"]
                        or not isinstance(locator.get("path"), str) or not locator["path"].startswith("/")):
                    raise FlowError("invalid_request", "FLOW_LOCATOR_SCHEMA",
                                    "%s contains an invalid Locator" % key)
        for key, locator in step["resource_bindings"].items():
            if (not isinstance(key, str) or not key or not isinstance(locator, dict)
                    or set(locator) != {"site_id", "path"}
                    or not isinstance(locator.get("site_id"), str) or not locator["site_id"]
                    or not isinstance(locator.get("path"), str) or not locator["path"].startswith("/")):
                raise FlowError("invalid_request", "FLOW_LOCATOR_SCHEMA",
                                "resource_bindings contains an invalid Locator")
        for key in ["constraints", "acceptance_checks"]:
            if not isinstance(step.get(key), list) or not all(
                    isinstance(item, str) for item in step[key]):
                raise FlowError("invalid_request", "FLOW_STEP_SCHEMA", "%s must contain strings" % key)
        if not isinstance(step.get("input_from"), list):
            raise FlowError("invalid_request", "FLOW_STEP_SCHEMA", "input_from must be an array")
        for dependency in step["input_from"]:
            if (not isinstance(dependency, dict)
                    or set(dependency) != {"step_index", "role", "expected_locator"}
                    or not isinstance(dependency.get("step_index"), int)
                    or isinstance(dependency.get("step_index"), bool)
                    or not isinstance(dependency.get("role"), str) or not dependency["role"]):
                raise FlowError("invalid_request", "FLOW_INPUT_FROM",
                                "input_from entry differs from the fixed contract")
            locator = dependency.get("expected_locator")
            if (not isinstance(locator, dict) or set(locator) != {"site_id", "path"}
                    or not isinstance(locator.get("site_id"), str) or not locator["site_id"]
                    or not isinstance(locator.get("path"), str) or not locator["path"].startswith("/")):
                raise FlowError("invalid_request", "FLOW_INPUT_FROM",
                                "input_from expected_locator is invalid")
            if dependency.get("step_index", index) >= index:
                raise FlowError("invalid_request", "FLOW_INPUT_FROM",
                                "input_from must reference an earlier step")
        runner_args = step.get("runner_args", {})
        if any(key in runner_args for key in {"command", "shell", "script_text", "pre_command"}):
            raise FlowError("invalid_request", "FLOW_ARBITRARY_SHELL",
                            "runner_args may not contain shell or command text")
    return value, canonical_hash(value)
