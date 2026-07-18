#!/usr/bin/env python3
"""Compact deterministic facade for Entity Router Case inspection and checks."""

from __future__ import print_function

import argparse
import json
import os
import subprocess
import sys
import time

from entity_router_common import (
    RouterError,
    atomic_write_json,
    canonical_locator,
    ensure_home,
    load_site_profile,
    locator_text,
    locator_within,
    now_utc,
    router_home,
)
from entity_router_flow_common import (
    FlowError,
    PHASES,
    STATUS_EXIT,
    bound_payload,
    check_case,
    compact_summary,
    load_flow_request,
    select_case,
)
from entity_router_flow_runners import RunnerOutcome, preflight_step, run_step
from entity_router_state import canonical_hash, load_state
from entity_router_status import collect_site_status


def emit(value):
    payload = bound_payload(value)
    if isinstance(payload.get("metrics"), dict):
        for unused in range(3):
            rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
            payload["metrics"]["output_bytes"] = len(rendered.encode("utf-8"))
    print(json.dumps(payload, indent=2, sort_keys=True))


def command_inspect(args):
    case_dir, state, unused = select_case(args.router_home, args.case, args.cwd)
    checked = check_case(args.router_home, case_dir, state, args.live, args.phase)
    summary = compact_summary(state, checked)
    summary["status"] = checked["status"]
    summary["metrics"] = {
        "tool_calls": 1,
        "remote_calls": checked["metrics"]["remote_calls"],
        "output_bytes": 0,
    }
    return checked["status"], summary


def command_check(args):
    case_dir, state, unused = select_case(args.router_home, args.case, None)
    checked = check_case(args.router_home, case_dir, state, args.live, args.phase)
    checked.pop("live_evidence", None)
    checked["metrics"].update({"tool_calls": 1, "output_bytes": 0})
    return checked["status"], checked


def _read_json(path, label):
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise FlowError("anomaly", "FLOW_HISTORY_INVALID",
                        "%s is unreadable: %s" % (label, exc))


def _state_command(home, values):
    script = os.path.join(os.path.dirname(__file__), "entity_router_state.py")
    command = [sys.executable, script, "--router-home", home] + values
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        message = (stderr or stdout or "state command failed").strip()
        lowered = message.lower()
        if "revision conflict" in lowered or "expected revision" in lowered:
            raise FlowError("revision_conflict", "FLOW_REVISION_CONFLICT", message)
        raise FlowError("anomaly", "FLOW_STATE_MUTATION_FAILED", message)
    try:
        return json.loads(stdout)
    except ValueError:
        raise FlowError("anomaly", "FLOW_STATE_RESPONSE_INVALID",
                        "state command did not return JSON")


def _action_paths(case_dir, action_id):
    root = os.path.join(case_dir, "actions", action_id)
    return os.path.join(root, "request.json"), os.path.join(root, "result.json")


def _validate_request_state(flow, flow_hash, state):
    if flow["case_uid"] != state["case_uid"]:
        raise FlowError("invalid_request", "FLOW_CASE_MISMATCH",
                        "flow request case_uid differs from selected Case")
    if flow["workflow_id"] != state["workflow"]["workflow_id"]:
        raise FlowError("revision_conflict", "FLOW_WORKFLOW_MISMATCH",
                        "workflow identity changed after the flow was prepared")
    if flow["target_hash"] != state["workflow"].get("target_hash", ""):
        raise FlowError("revision_conflict", "FLOW_TARGET_DRIFT",
                        "workflow target changed after the flow was prepared")
    if not flow_hash.startswith("sha256:"):
        raise FlowError("invalid_request", "FLOW_HASH_INVALID",
                        "flow request hash is invalid")


def _history(case_dir, flow, flow_hash, state):
    completed = []
    active = None
    seen_gap = False
    for step in flow["steps"]:
        request_path, result_path = _action_paths(case_dir, step["action_id"])
        request_exists = os.path.isfile(request_path)
        result_exists = os.path.isfile(result_path)
        if not request_exists:
            if result_exists:
                raise FlowError("anomaly", "FLOW_RESULT_WITHOUT_REQUEST",
                                "Action result exists without its request")
            seen_gap = True
            continue
        if seen_gap:
            raise FlowError("revision_conflict", "FLOW_HISTORY_GAP",
                            "flow Action history is not a contiguous prefix")
        request = _read_json(request_path, "Action request")
        orchestration = request.get("orchestration", {})
        expected = {
            "flow_id": flow["flow_id"],
            "flow_request_hash": flow_hash,
            "target_hash": flow["target_hash"],
            "step_index": step["index"],
            "runner": step["runner"],
        }
        if any(orchestration.get(key) != value for key, value in expected.items()):
            raise FlowError("revision_conflict", "FLOW_ACTION_COLLISION",
                            "existing Action ID belongs to a different flow step")
        if request.get("action_type") != step["action_type"]:
            raise FlowError("revision_conflict", "FLOW_ACTION_COLLISION",
                            "existing Action type differs from flow step")
        if result_exists:
            result = _read_json(result_path, "Action result")
            if result.get("status") != "completed":
                prior = "blocked" if result.get("status") == "blocked" else "anomaly"
                raise FlowError(prior, "FLOW_PRIOR_STEP_TERMINAL",
                                "a prior flow step ended as %s" % result.get("status"),
                                {"step_index": step["index"], "action_id": step["action_id"]})
            completed.append((step, result))
        else:
            if active is not None:
                raise FlowError("anomaly", "FLOW_MULTIPLE_ACTIVE",
                                "multiple flow Actions lack results")
            active = step
    expected_revision = flow["base_revision"] + 2 * len(completed) + (1 if active else 0)
    if state["revision"] != expected_revision:
        raise FlowError(
            "revision_conflict", "FLOW_REVISION_CONFLICT",
            "Case revision %s does not match flow-owned revision %s" %
            (state["revision"], expected_revision),
        )
    active_id = state["workflow"].get("active_action_id", "")
    if active and active_id != active["action_id"]:
        raise FlowError("revision_conflict", "FLOW_ACTIVE_ACTION_MISMATCH",
                        "Case active Action differs from the flow receipt")
    if not active and active_id:
        raise FlowError("revision_conflict", "FLOW_EXTERNAL_ACTION_ACTIVE",
                        "another Action is active")
    return completed, active


def _apply_launch_identity(home, step, dependency, prior_step):
    locator = canonical_locator(home, dependency["expected_locator"])
    profile = load_site_profile(home, locator["site_id"])
    if profile["transport"]["kind"] != "local":
        raise FlowError("blocked", "FLOW_DEPENDENCY_REMOTE",
                        "remote launch receipt resolution is not implemented")
    receipt = _read_json(locator["path"], "launch receipt")
    if (receipt.get("state") != "outputs_verified"
            or receipt.get("case_uid") != step["case_uid"]
            or receipt.get("action_id") != prior_step["action_id"]):
        raise FlowError("anomaly", "FLOW_LAUNCH_RECEIPT_IDENTITY",
                        "launch receipt identity or state is invalid")
    identity = receipt.get("effect_identity", {})
    updates = {}
    if identity.get("job_id"):
        updates["job_id"] = str(identity["job_id"])
    elif identity.get("pid") and identity.get("pid_start_ticks"):
        updates["pid"] = identity["pid"]
        updates["pid_start_ticks"] = str(identity["pid_start_ticks"])
        if identity.get("pid_record"):
            updates["pid_record"] = identity["pid_record"]
    else:
        raise FlowError("anomaly", "FLOW_LAUNCH_IDENTITY_MISSING",
                        "launch receipt lacks a scheduler or PID identity")
    runner_args = dict(step["runner_args"])
    for key, value in updates.items():
        current = runner_args.get(key)
        if current is not None and current != "" and current != value:
            raise FlowError("revision_conflict", "FLOW_LAUNCH_IDENTITY_CONFLICT",
                            "monitor runner_args conflict with launch receipt identity")
        runner_args[key] = value
    step["runner_args"] = runner_args


def _resolve_dependencies(home, step, completed):
    inputs = list(step["inputs"])
    results = {item[0]["index"]: item for item in completed}
    for dependency in step["input_from"]:
        prior = results.get(dependency["step_index"])
        if prior is None:
            raise FlowError("invalid_request", "FLOW_INPUT_UNAVAILABLE",
                            "input_from does not reference a completed step")
        prior_step, result = prior
        expected = canonical_locator(home, dependency["expected_locator"])
        found = False
        for output in result.get("outputs", []):
            locator = output.get("locator") if isinstance(output, dict) else None
            if locator == expected:
                found = True
                break
        if not found:
            raise FlowError("anomaly", "FLOW_INPUT_IDENTITY_MISMATCH",
                            "dependency output does not match expected_locator")
        if expected not in inputs:
            inputs.append(expected)
        if dependency["role"] == "launch_receipt":
            _apply_launch_identity(home, step, dependency, prior_step)
    return inputs


def _append_many(command, option, values, formatter=None):
    for value in values:
        command.extend([option, formatter(value) if formatter else value])


def _start_step(home, flow, flow_hash, state, step, inputs):
    command = [
        "start-action", "--case", flow["case_uid"],
        "--expected-revision", str(state["revision"]),
        "--action-id", step["action_id"], "--action-type", step["action_type"],
        "--owner", step["owner"], "--execution-domain", step["execution_domain"],
        "--execution-site", step["execution_site_id"],
        "--flow-id", flow["flow_id"], "--flow-request-hash", flow_hash,
        "--target-hash", flow["target_hash"],
        "--flow-step-index", str(step["index"]), "--runner", step["runner"],
        "--runner-args-json", json.dumps(step["runner_args"], sort_keys=True,
                                          separators=(",", ":")),
        "--goal", flow["goal"],
    ]
    if step["identity_id"]:
        command.extend(["--identity-id", step["identity_id"]])
    if step["spec_hash"]:
        command.extend(["--spec-hash", step["spec_hash"]])
    _append_many(command, "--parent", ["%s=%s" % item for item in sorted(step["parents"].items())])
    _append_many(command, "--resource-binding", [
        "%s=%s" % (key, locator_text(value))
        for key, value in sorted(step["resource_bindings"].items())
    ])
    for option, values in [
            ("--input", inputs), ("--read-root", step["read_roots"]),
            ("--write-root", step["write_roots"]),
            ("--protected-path", step["protected_paths"]),
            ("--expected-output", step["expected_outputs"])]:
        _append_many(command, option, values, locator_text)
    _append_many(command, "--constraint", step["constraints"])
    _append_many(command, "--acceptance-check", step["acceptance_checks"])
    return _state_command(home, command)


def _finish_step(home, flow, revision, step, outcome):
    if outcome.status == "completed":
        verification = outcome.verification
        valid = (isinstance(verification, list)
                 and all(isinstance(item, str) and item.strip() for item in verification))
        if not valid or len(verification) < len(step["acceptance_checks"]):
            outcome.status = "anomaly"
            outcome.readiness = {}
            outcome.message = "runner did not provide verified evidence for every acceptance check"
    terminal = {"completed": "completed", "needs_decision": "cancelled",
                "blocked": "blocked", "anomaly": "failed"}.get(outcome.status, "failed")
    command = [
        "finish-action", "--case", flow["case_uid"],
        "--expected-revision", str(revision), "--action-id", step["action_id"],
        "--status", terminal,
    ]
    _append_many(command, "--output", outcome.outputs, locator_text)
    if outcome.status == "completed":
        _append_many(command, "--verification", outcome.verification)
        _append_many(command, "--readiness", [
            "%s=%s" % item for item in sorted(outcome.readiness.items())
        ])
    else:
        command.extend(["--diagnosis", outcome.message or "runner did not complete"])
        command.extend(["--blocker", outcome.message or "runner did not complete"])
        command.extend(["--suggested-owner", step["owner"]])
    return _state_command(home, command)


def _flow_result(status, flow, state, steps, issues=None, artifacts=None, calls=0):
    return status, {
        "schema_version": 1,
        "status": status,
        "case_uid": state["case_uid"],
        "revision": state["revision"],
        "flow_id": flow["flow_id"],
        "result": {"steps": steps},
        "issues": issues or [],
        "artifact_refs": artifacts or [],
        "metrics": {"tool_calls": calls, "remote_calls": 0, "output_bytes": 0},
    }


def _model_worker_locators(home, step):
    args = step.get("runner_args", {})
    allowed = {"skill", "playbook", "worker_envelope", "worker_result"}
    if set(args) != allowed:
        raise FlowError("invalid_request", "WORKER_RUNNER_ARGS",
                        "model.worker.v1 requires exactly skill, playbook, worker_envelope, worker_result")
    envelope = canonical_locator(home, args["worker_envelope"])
    result = canonical_locator(home, args["worker_result"])
    if envelope["site_id"] != step["execution_site_id"] or result["site_id"] != step["execution_site_id"]:
        raise FlowError("invalid_request", "WORKER_SITE_MISMATCH",
                        "worker artifacts must be on the execution site")
    roots = [canonical_locator(home, item) for item in step["write_roots"]]
    if not all(any(locator_within(item, root) for root in roots) for item in [envelope, result]):
        raise FlowError("invalid_request", "WORKER_ENVELOPE_VIOLATION",
                        "worker artifacts are outside step write roots")
    profile = load_site_profile(home, step["execution_site_id"])
    if profile["transport"]["kind"] != "local":
        raise FlowError("blocked", "WORKER_REMOTE_STAGING",
                        "remote model Worker staging is not implemented")
    return envelope, result


def _prepare_model_step(home, flow, flow_hash, case_dir, state, step, completed, active):
    envelope_locator, result_locator = _model_worker_locators(home, step)
    inputs = _resolve_dependencies(home, step, completed)
    calls = 1
    cached = active is not None
    if active is None:
        started = _start_step(home, flow, flow_hash, state, step, inputs)
        calls += 1
        state = load_state(case_dir)
        if state["revision"] != started["revision"]:
            raise FlowError("revision_conflict", "FLOW_REVISION_CONFLICT",
                            "Case changed immediately after Worker Action start")
    request_path, unused = _action_paths(case_dir, step["action_id"])
    request = _read_json(request_path, "Worker Action request")
    request_hash = canonical_hash(request)
    envelope = {
        "schema_version": 1, "case_uid": state["case_uid"],
        "action_id": step["action_id"], "owner": step["owner"],
        "execution_domain": step["execution_domain"], "request": request,
        "request_hash": request_hash, "skill": step["runner_args"]["skill"],
        "playbook": step["runner_args"]["playbook"],
        "worker_result": {"locator": result_locator, "request_hash": request_hash},
    }
    if os.path.isfile(envelope_locator["path"]):
        existing = _read_json(envelope_locator["path"], "Worker envelope")
        if existing.get("request_hash") != request_hash:
            raise FlowError("revision_conflict", "WORKER_ENVELOPE_COLLISION",
                            "existing Worker envelope belongs to another request")
    else:
        atomic_write_json(envelope_locator["path"], envelope)
    return _flow_result(
        "observe_only", flow, state,
        [{"index": step["index"], "action_id": step["action_id"],
          "status": "worker_prepared", "cached": cached,
          "request_hash": request_hash, "worker_result": result_locator}],
        artifacts=[envelope_locator], calls=calls,
    )


def _resume_model_step(home, flow, flow_hash, case_dir, state, step, result_path):
    envelope_locator, expected_result = _model_worker_locators(home, step)
    supplied = canonical_locator(home, result_path) if result_path else expected_result
    if supplied != expected_result:
        raise FlowError("invalid_request", "WORKER_RESULT_LOCATOR",
                        "resume result differs from the prepared result Locator")
    request_path, unused = _action_paths(case_dir, step["action_id"])
    request = _read_json(request_path, "Worker Action request")
    request_hash = canonical_hash(request)
    result = _read_json(supplied["path"], "Worker result")
    required = {"schema_version", "case_uid", "action_id", "request_hash",
                "status", "outputs", "verification", "message"}
    if set(result) != required or result.get("schema_version") != 1:
        raise FlowError("invalid_request", "WORKER_RESULT_SCHEMA",
                        "Worker result keys differ from the fixed schema")
    if (result["case_uid"] != state["case_uid"] or result["action_id"] != step["action_id"]
            or result["request_hash"] != request_hash):
        raise FlowError("revision_conflict", "WORKER_RESULT_IDENTITY",
                        "Worker result identity does not match active Action")
    if result["status"] not in {"completed", "needs_decision", "anomaly"}:
        raise FlowError("invalid_request", "WORKER_RESULT_STATUS",
                        "Worker result status is invalid")
    outputs = [canonical_locator(home, item) for item in result["outputs"]]
    readiness = {"analysis": "complete"} if result["status"] == "completed" else {}
    outcome = RunnerOutcome(
        result["status"], outputs, result["verification"], readiness,
        result["message"], receipt=envelope_locator,
    )
    finished = _finish_step(home, flow, state["revision"], step, outcome)
    state = load_state(case_dir)
    status = result["status"]
    issues = []
    if status != "completed":
        issues.append({
            "code": "WORKER_%s" % status.upper(),
            "class": status if status == "needs_decision" else "anomaly",
            "message": result["message"], "subject": {"action_id": step["action_id"]},
            "evidence_fingerprint": canonical_hash(result), "artifact_ref": supplied,
        })
    return _flow_result(
        status, flow, state,
        [{"index": step["index"], "action_id": step["action_id"],
          "status": status, "cached": False}],
        issues=issues, artifacts=[envelope_locator, supplied], calls=2,
    )


def command_execute(args):
    flow, flow_hash = load_flow_request(args.request)
    case_dir, state, unused = select_case(args.router_home, flow["case_uid"], None)
    _validate_request_state(flow, flow_hash, state)
    completed, active = _history(case_dir, flow, flow_hash, state)
    step_results = [{"index": step["index"], "action_id": step["action_id"],
                     "status": "completed", "cached": True}
                    for step, result in completed]
    calls = 1
    start_index = len(completed)
    if active and active["index"] != start_index:
        raise FlowError("revision_conflict", "FLOW_ACTIVE_STEP_ORDER",
                        "active flow step is not the next contiguous step")
    selected = flow["steps"][start_index] if start_index < len(flow["steps"]) else None
    if args.prepare or args.resume:
        if selected is None:
            return _flow_result("completed", flow, state, step_results, calls=calls)
        if args.step is None or args.step != selected["index"]:
            raise FlowError("invalid_request", "WORKER_STEP_SELECTION",
                            "prepare/resume must select the next flow step")
        if selected["runner"] != "model.worker.v1":
            raise FlowError("invalid_request", "WORKER_RUNNER_REQUIRED",
                            "prepare/resume only accepts model.worker.v1")
        selected = dict(selected)
        selected["case_uid"] = state["case_uid"]
        if args.prepare:
            return _prepare_model_step(args.router_home, flow, flow_hash, case_dir,
                                       state, selected, completed, active)
        if active is None:
            raise FlowError("revision_conflict", "WORKER_ACTION_NOT_ACTIVE",
                            "resume requires an active prepared Worker Action")
        return _resume_model_step(args.router_home, flow, flow_hash, case_dir, state,
                                  selected, args.worker_result)
    for step in flow["steps"][start_index:]:
        step = dict(step)
        step["case_uid"] = state["case_uid"]
        if step["runner"] == "model.worker.v1":
            raise FlowError("needs_decision", "FLOW_MODEL_STEP_REQUIRES_PREPARE",
                            "model-owned step requires prepare/resume delegation",
                            {"step_index": step["index"], "action_id": step["action_id"]})
        inputs = _resolve_dependencies(args.router_home, step, completed)
        try:
            preflight_step(args.router_home, step)
        except RouterError as exc:
            status = "blocked" if "remote runner staging" in str(exc) else "invalid_request"
            raise FlowError(status, "FLOW_RUNNER_PREFLIGHT", str(exc),
                            {"step_index": step["index"]})
        if active is None:
            started = _start_step(args.router_home, flow, flow_hash, state, step, inputs)
            calls += 1
            state = load_state(case_dir)
            if state["revision"] != started["revision"]:
                raise FlowError("revision_conflict", "FLOW_REVISION_CONFLICT",
                                "Case changed immediately after Action start")
        if step["runner"] == "run.monitor.v1":
            step_results.append({
                "index": step["index"], "action_id": step["action_id"],
                "status": "observing", "cached": active is not None,
            })
            return _flow_result("observe_only", flow, state, step_results, calls=calls)
        try:
            outcome = run_step(args.router_home, step, flow_hash)
        except (RouterError, OSError, ValueError, KeyError) as exc:
            outcome = RunnerOutcome("anomaly", message=str(exc))
        calls += 1
        finished = _finish_step(args.router_home, flow, state["revision"], step, outcome)
        calls += 1
        state = load_state(case_dir)
        if state["revision"] != finished["revision"]:
            raise FlowError("revision_conflict", "FLOW_REVISION_CONFLICT",
                            "Case changed immediately after Action finish")
        item = {"index": step["index"], "action_id": step["action_id"],
                "status": outcome.status, "cached": False}
        step_results.append(item)
        if outcome.receipt:
            item["receipt"] = outcome.receipt
        if outcome.status != "completed":
            issue_class = outcome.status if outcome.status in {"needs_decision", "blocked"} else "anomaly"
            issues = [{
                "code": "FLOW_STEP_%s" % outcome.status.upper(),
                "class": issue_class,
                "message": outcome.message or "flow step did not complete",
                "subject": {"step_index": step["index"], "action_id": step["action_id"]},
                "evidence_fingerprint": "", "artifact_ref": outcome.receipt,
            }]
            return _flow_result(outcome.status, flow, state, step_results, issues,
                                [outcome.receipt] if outcome.receipt else [], calls)
        completed.append((step, _read_json(_action_paths(case_dir, step["action_id"])[1],
                                           "Action result")))
        active = None
        if flow["stop_policy"].get("on_completed") == "return":
            break
    status = "completed" if len(completed) == len(flow["steps"]) else "pass"
    return _flow_result(status, flow, state, step_results, calls=calls)


def _append_trace(path, value):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "a") as handle:
        handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _watch_finish(home, state, request, status, trace, observation, message, suppressed):
    terminal = {"completed": "completed", "anomaly": "failed", "blocked": "blocked"}[status]
    command = [
        "finish-action", "--case", state["case_uid"],
        "--expected-revision", str(state["revision"]),
        "--action-id", request["action_id"], "--status", terminal,
        "--output", locator_text(trace),
    ]
    if status == "completed":
        checks = request.get("acceptance_checks", [])
        for check in checks:
            command.extend(["--verification", "terminal acceptance passed: %s" % check])
        command.extend(["--readiness", "run=completed"])
        command.extend(["--readiness", "data=unknown"])
    else:
        command.extend(["--diagnosis", message, "--blocker", message,
                        "--suggested-owner", request["owner"]])
        if status == "anomaly":
            command.extend(["--readiness", "run=failed"])
    finished = _state_command(home, command)
    current = load_state(state["control"]["root"])
    issue_list = []
    if status != "completed":
        issue_list.append({
            "code": "MONITOR_%s" % status.upper(),
            "class": status,
            "message": message,
            "subject": {"action_id": request["action_id"], "run_id": request.get("run_id", "")},
            "evidence_fingerprint": canonical_hash(observation or {}),
            "artifact_ref": trace,
        })
    payload_status = status
    return payload_status, {
        "schema_version": 1, "status": payload_status,
        "case_uid": current["case_uid"], "revision": finished["revision"],
        "flow_id": request.get("orchestration", {}).get("flow_id", ""),
        "result": {"action_id": request["action_id"], "observation": observation,
                   "unchanged_polls_suppressed": suppressed},
        "issues": issue_list, "artifact_refs": [trace],
        "metrics": {"tool_calls": 1, "remote_calls": 0, "output_bytes": 0,
                    "unchanged_polls_suppressed": suppressed},
    }


def _zero_exit_code(value):
    text = str(value or "").strip()
    return text == "0" or text.startswith("0:")


def _pid_exit_code(home, config, status_config):
    value = config.get("pid_record")
    if not value:
        return None
    locator = canonical_locator(home, value)
    if not os.path.isfile(locator["path"]):
        return None
    payload = _read_json(locator["path"], "PID terminal record")
    if (str(payload.get("pid", "")) != str(status_config.get("pid", ""))
            or str(payload.get("pid_start_ticks", "")) != str(
                status_config.get("pid_start_ticks", ""))
            or payload.get("run_root") != status_config.get("run_root")):
        raise FlowError("revision_conflict", "MONITOR_PID_RECORD_IDENTITY",
                        "PID terminal record differs from the monitored process identity")
    return payload.get("exit_code")


def command_watch(args):
    case_dir, state, unused = select_case(args.router_home, args.case, None)
    if state["workflow"].get("active_action_id") != args.action:
        raise FlowError("revision_conflict", "MONITOR_ACTION_NOT_ACTIVE",
                        "requested monitor Action is not active")
    request_path, result_path = _action_paths(case_dir, args.action)
    request = _read_json(request_path, "monitor Action request")
    if request.get("action_type") != "run.monitor":
        raise FlowError("invalid_request", "MONITOR_ACTION_TYPE",
                        "watch only accepts run.monitor Actions")
    orchestration = request.get("orchestration", {})
    if orchestration.get("flow_request_hash") != args.flow_request_hash:
        raise FlowError("revision_conflict", "MONITOR_FLOW_HASH_MISMATCH",
                        "watch flow hash differs from the active Action")
    if os.path.exists(result_path):
        raise FlowError("revision_conflict", "MONITOR_ALREADY_FINISHED",
                        "monitor Action already has a result")
    config = dict(request.get("runner_args", {}))
    if not config:
        raise FlowError("invalid_request", "MONITOR_CONFIG_MISSING",
                        "monitor Action lacks immutable runner_args")
    trace = canonical_locator(args.router_home, config.pop("trace"))
    if trace["site_id"] != request["execution_site_id"]:
        raise FlowError("invalid_request", "MONITOR_TRACE_SITE",
                        "monitor trace is on the wrong site")
    if not any(locator_within(trace, root) for root in request["write_roots"]):
        raise FlowError("invalid_request", "MONITOR_TRACE_ENVELOPE",
                        "monitor trace is outside Action write roots")
    run_root = canonical_locator(args.router_home, config["run_root"])
    active_root = state["resources"]["run"].get("active")
    if request.get("run_id") != state["resources"]["run"].get("current_id") or run_root != active_root:
        raise FlowError("revision_conflict", "MONITOR_RUN_IDENTITY_MISMATCH",
                        "monitor request does not reference the active run identity")
    profile = load_site_profile(args.router_home, request["execution_site_id"])
    status_config = {
        "site_id": request["execution_site_id"], "run_id": request["run_id"],
        "run_root": run_root["path"],
        "scheduler": profile.get("scheduler", {}).get("kind", "none"),
        "job_id": config.get("job_id", ""), "pid": config.get("pid"),
        "pid_start_ticks": config.get("pid_start_ticks", ""),
        "progress_log": config.get("progress_log", "logs/stdout.log"),
        "stderr_log": config.get("stderr_log", "logs/stderr.log"),
        "fields_root": config.get("fields_root", "data/fields"),
        "checkpoint_root": config.get("checkpoint_root", "data/checkpoints"),
        "field_pattern": config.get("field_pattern", "fields.*.bp"),
        "checkpoint_pattern": config.get("checkpoint_pattern", "step-*.bp"),
        "total_steps": config.get("total_steps"), "target_time": config.get("target_time"),
        "tail_bytes": 131072, "profile": "quick",
    }
    start = time.time()
    last_fingerprint = ""
    suppressed = 0
    observation = {}
    _append_trace(trace["path"], {"kind": "monitor.started", "observed_at": now_utc()})
    while True:
        try:
            observation = collect_site_status(args.router_home, profile, status_config)
        except (RouterError, OSError, ValueError, KeyError) as exc:
            _append_trace(trace["path"], {"kind": "monitor.offline", "message": str(exc),
                                          "observed_at": now_utc()})
            return _watch_finish(args.router_home, state, request, "blocked", trace,
                                 observation, "monitor site is offline: %s" % exc, suppressed)
        compact = {
            "observed_at": observation.get("observed_at"),
            "scheduler": observation.get("scheduler"),
            "process": observation.get("process"),
            "progress": observation.get("progress"),
            "terminal": observation.get("terminal"),
            "anomaly": observation.get("anomaly"),
        }
        fingerprint = canonical_hash({key: value for key, value in compact.items()
                                      if key != "observed_at"})
        if fingerprint == last_fingerprint:
            suppressed += 1
        else:
            _append_trace(trace["path"], compact)
            last_fingerprint = fingerprint
        if observation.get("anomaly"):
            return _watch_finish(args.router_home, state, request, "anomaly", trace,
                                 observation, "run monitor observed fatal or identity evidence", suppressed)
        if observation.get("terminal"):
            scheduler_state = observation.get("scheduler", {}).get("state", "")
            exit_code = observation.get("scheduler", {}).get("exit_code", "")
            message = "run reached a non-success terminal state"
            if status_config["job_id"]:
                if scheduler_state == "COMPLETED" and _zero_exit_code(exit_code):
                    status = "completed"
                elif scheduler_state == "COMPLETED" and not exit_code:
                    status = "blocked"
                    message = "scheduler terminal state lacks verified exit code"
                else:
                    status = "anomaly"
            else:
                process_exit = _pid_exit_code(args.router_home, config, status_config)
                if process_exit is None:
                    status = "blocked"
                    message = "process disappeared without a verified terminal exit record"
                else:
                    status = "completed" if _zero_exit_code(process_exit) else "anomaly"
            return _watch_finish(args.router_home, state, request, status, trace,
                                 observation, message, suppressed)
        if time.time() - start >= args.timeout_seconds:
            _append_trace(trace["path"], {"kind": "monitor.timeout", "observed_at": now_utc()})
            return _watch_finish(args.router_home, state, request, "blocked", trace,
                                 observation, "monitor timeout reached", suppressed)
        time.sleep(args.interval_seconds)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--router-home", default=router_home())
    sub = parser.add_subparsers(dest="command")
    inspect = sub.add_parser("inspect")
    selector = inspect.add_mutually_exclusive_group(required=True)
    selector.add_argument("--case")
    selector.add_argument("--cwd")
    inspect.add_argument("--live", action="store_true")
    inspect.add_argument("--phase", choices=sorted(PHASES), default="orient")
    inspect.set_defaults(func=command_inspect)
    check = sub.add_parser("check")
    check.add_argument("--case", required=True)
    check.add_argument("--live", action="store_true")
    check.add_argument("--phase", choices=sorted(PHASES), default="orient")
    check.set_defaults(func=command_check)
    execute = sub.add_parser("execute")
    execute.add_argument("--request", required=True)
    mode = execute.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--resume", action="store_true")
    execute.add_argument("--step", type=int)
    execute.add_argument("--worker-result")
    execute.set_defaults(func=command_execute)
    watch = sub.add_parser("watch")
    watch.add_argument("--case", required=True)
    watch.add_argument("--action", required=True)
    watch.add_argument("--flow-request-hash", required=True)
    watch.add_argument("--interval-seconds", type=float, default=60.0)
    watch.add_argument("--timeout-seconds", type=float, default=86400.0)
    watch.set_defaults(func=command_watch)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.error("a command is required")
    args.router_home = ensure_home(args.router_home)
    try:
        status, payload = args.func(args)
        emit(payload)
        return STATUS_EXIT[status]
    except FlowError as exc:
        emit({
            "schema_version": 1,
            "status": exc.status,
            "case_uid": "",
            "revision": 0,
            "flow_id": "",
            "result": exc.result,
            "issues": [{
                "code": exc.code,
                "class": exc.status if exc.status in {"needs_decision", "blocked", "anomaly"} else "anomaly",
                "message": str(exc),
                "subject": {},
                "evidence_fingerprint": "",
                "artifact_ref": None,
            }],
            "artifact_refs": [],
            "metrics": {"tool_calls": 0, "remote_calls": 0, "output_bytes": 0},
        })
        return STATUS_EXIT.get(exc.status, 40)
    except (RouterError, OSError, ValueError, KeyError) as exc:
        emit({
            "schema_version": 1,
            "status": "anomaly",
            "case_uid": "",
            "revision": 0,
            "flow_id": "",
            "result": {},
            "issues": [{
                "code": "FLOW_INSPECTION_FAILED",
                "class": "anomaly",
                "message": str(exc),
                "subject": {},
                "evidence_fingerprint": "",
                "artifact_ref": None,
            }],
            "artifact_refs": [],
            "metrics": {"tool_calls": 0, "remote_calls": 0, "output_bytes": 0},
        })
        return 30


if __name__ == "__main__":
    sys.exit(main())
