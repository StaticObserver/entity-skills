"""Validators that link existing owner evidence into an observability run."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .core import TraceError, append_event, load_json, register_artifact


ArtifactSpec = Tuple[Path, str, str, str]


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


def _check(checks: List[Dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def _status(checks: Sequence[Mapping[str, Any]], anchored: bool = True) -> str:
    if any(not item.get("passed") for item in checks):
        return "fail"
    return "pass" if anchored else "unknown"


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _operation_from_snapshot(snapshot: Mapping[str, Any], operation_id: str) -> Mapping[str, Any]:
    if snapshot.get("operation_id") == operation_id:
        return snapshot
    operations = snapshot.get("operations")
    if isinstance(operations, list):
        matches = [item for item in operations
                   if isinstance(item, dict) and item.get("operation_id") == operation_id]
        if len(matches) == 1:
            return matches[0]
    return {}


def _record(
    run_dir: Path,
    *,
    validator: str,
    status: str,
    checks: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    artifacts: Sequence[ArtifactSpec],
    parent_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    event = append_event(
        run_dir,
        event_type="validation.finished",
        source_kind="validator",
        source_id=validator,
        evidence_level="verified",
        phase="verify",
        parent_span_id=parent_span_id,
        payload={
            "validator": validator,
            "status": status,
            "checks": list(checks),
            "summary": dict(summary),
        },
    )
    linked = []
    seen = set()
    for path, role, authority, site_id in artifacts:
        resolved = path.expanduser().resolve()
        key = (str(resolved), role, authority, site_id)
        if key in seen:
            continue
        seen.add(key)
        artifact = register_artifact(
            run_dir,
            path=resolved,
            role=role,
            authority=authority,
            produced_by=event["event_id"],
            site_id=site_id,
            media_type="application/json" if resolved.suffix.lower() == ".json" else None,
        )
        linked.append(artifact["artifact_id"])
    return {
        "validator": validator,
        "status": status,
        "event_id": event["event_id"],
        "artifact_ids": linked,
        "checks": list(checks),
        "summary": dict(summary),
    }


def validate_router_action(
    run_dir: Path,
    *,
    request_path: Path,
    result_path: Optional[Path] = None,
    case_state_path: Optional[Path] = None,
    parent_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    request_path = request_path.expanduser().resolve()
    request = load_json(request_path, "Router Action request")
    checks: List[Dict[str, Any]] = []
    required = {
        "schema_version", "case_revision", "case_uid", "workflow_id", "action_id",
        "action_type", "owner", "execution_domain", "execution_site_id", "write_roots",
        "acceptance_checks",
    }
    _check(checks, "request.required-fields", required.issubset(request),
           "Action request contains the v2 identity and envelope fields")
    _check(checks, "request.schema", request.get("schema_version") == 2,
           "Action request uses schema v2")
    action_id = str(request.get("action_id") or "")
    _check(checks, "request.controller-shape",
           request_path.name == "request.json" and request_path.parent.name == action_id,
           "request path is actions/<action_id>/request.json")
    action_type = str(request.get("action_type") or "")
    prefix = action_type.split(".", 1)[0]
    expected = ACTION_EXECUTION.get(prefix)
    _check(checks, "request.execution-contract", expected is not None,
           "Action prefix has a fixed owner and execution domain")
    if expected is not None:
        _check(checks, "request.owner", request.get("owner") == expected[0],
               f"owner matches {expected[0]}")
        _check(checks, "request.execution-domain", request.get("execution_domain") == expected[1],
               f"execution_domain matches {expected[1]}")
    roots = request.get("write_roots")
    _check(checks, "request.write-roots", isinstance(roots, list),
           "write_roots is a locator array")

    artifacts: List[ArtifactSpec] = [
        (request_path, "action-request", "entity-router-action-request", "controller")
    ]
    anchored = False
    if result_path is not None:
        result_path = result_path.expanduser().resolve()
        result = load_json(result_path, "Router Action result")
        artifacts.append((result_path, "action-result", "entity-router-action-result", "controller"))
        anchored = True
        _check(checks, "result.schema", result.get("schema_version") == 2,
               "Action result uses schema v2")
        for key in ("case_uid", "workflow_id", "action_id", "action_type", "owner", "execution_site_id"):
            _check(checks, f"result.matches-{key}", result.get(key) == request.get(key),
                   f"result {key} matches request")
        terminal = result.get("status") in {"completed", "failed", "blocked", "cancelled"}
        _check(checks, "result.terminal", terminal, "Action result has a terminal status")
        if result.get("status") == "completed":
            verification = result.get("verification")
            acceptance = request.get("acceptance_checks")
            valid_counts = isinstance(verification, list) and isinstance(acceptance, list)
            _check(checks, "result.acceptance-evidence",
                   valid_counts and len(verification) >= len(acceptance),
                   "completed result has at least one verification per acceptance check")
            outputs = result.get("outputs")
            output_shape = isinstance(outputs, list) and all(
                isinstance(item, dict) and isinstance(item.get("locator"), dict)
                and isinstance(item.get("fingerprint"), dict)
                for item in outputs
            )
            _check(checks, "result.output-evidence", output_shape,
                   "completed output entries carry locator and fingerprint evidence")
    elif case_state_path is not None:
        case_state_path = case_state_path.expanduser().resolve()
        state = load_json(case_state_path, "Router Case state")
        artifacts.append((case_state_path, "case-state", "entity-router-case-state", "controller"))
        anchored = True
        _check(checks, "case.schema", state.get("schema_version") == 3,
               "Case state uses schema v3")
        _check(checks, "case.uid", state.get("case_uid") == request.get("case_uid"),
               "Case UID matches request")
        workflow = state.get("workflow") if isinstance(state.get("workflow"), dict) else {}
        _check(checks, "case.workflow", workflow.get("workflow_id") == request.get("workflow_id"),
               "workflow ID matches request")
        _check(checks, "case.active-action", workflow.get("active_action_id") == action_id,
               "Action is currently active")
        _check(checks, "case.revision", state.get("revision") == request.get("case_revision", -2) + 1,
               "Case revision is the revision immediately after Action start")

    status = _status(checks, anchored=anchored)
    return _record(
        run_dir,
        validator="entity-router-action-v2",
        status=status,
        checks=checks,
        summary={
            "case_uid": request.get("case_uid", ""),
            "action_id": action_id,
            "action_type": action_type,
            "execution_site_id": request.get("execution_site_id", ""),
            "anchor": "result" if result_path else ("case-state" if case_state_path else "none"),
        },
        artifacts=artifacts,
        parent_span_id=parent_span_id,
    )


def validate_router_operation(
    run_dir: Path,
    *,
    plan_path: Path,
    operation_path: Path,
    receipt_paths: Sequence[Path],
    status_path: Optional[Path] = None,
    scheduler_path: Optional[Path] = None,
    parent_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a Router v5 Goal/Plan/Operation/receipt evidence chain."""

    plan_path = plan_path.expanduser().resolve()
    operation_path = operation_path.expanduser().resolve()
    envelope = load_json(plan_path, "Router v5 Plan envelope")
    snapshot = load_json(operation_path, "Router v5 Operation snapshot")
    checks: List[Dict[str, Any]] = []
    artifacts: List[ArtifactSpec] = [
        (plan_path, "operation-plan", "entity-router-v5-plan", "controller"),
        (operation_path, "operation-snapshot", "entity-router-v5-store-export", "controller"),
    ]

    _check(checks, "plan.envelope",
           envelope.get("schema_version") == 1
           and envelope.get("kind") == "entity-router.plan"
           and envelope.get("status") == "ready"
           and envelope.get("state_mutated") is False,
           "Plan artifact is a read-only ready v5 Plan envelope")
    goal = envelope.get("goal") if isinstance(envelope.get("goal"), dict) else {}
    plan = envelope.get("plan") if isinstance(envelope.get("plan"), dict) else {}
    _check(checks, "goal.schema", goal.get("schema_version") == 1 and goal.get("kind") == "run",
           "GoalSpec is a v1 run Goal")
    forbidden_goal = {
        "case_uid", "operation_id", "run_id", "plan_hash", "locator", "binding",
        "owner", "execution_domain", "lease", "command", "shell", "script_text",
    }
    _check(checks, "goal.semantic-only", not (set(goal) & forbidden_goal),
           "GoalSpec contains no controller-derived or executable command fields")

    unsigned = dict(plan)
    actual_plan_hash = unsigned.pop("plan_hash", "")
    unsigned.pop("generated_at", None)
    _check(checks, "plan.hash", bool(actual_plan_hash)
           and _canonical_hash(unsigned) == actual_plan_hash,
           "Plan hash matches the canonical immutable Plan")
    _check(checks, "plan.goal-hash", plan.get("goal_hash") == _canonical_hash(goal),
           "Plan binds the exact GoalSpec")
    operation_id = str(plan.get("operation_id") or "")
    case_uid = str(plan.get("case_uid") or "")
    run_id = str(plan.get("run_id") or "")
    _check(checks, "plan.identities", bool(operation_id and case_uid and run_id),
           "Plan derives Case, Operation, and run identities")
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    _check(checks, "plan.steps", [item.get("kind") for item in steps
                                  if isinstance(item, dict)] == [
                                      "run.preflight.v1", "run.prepare.v2", "run.launch.v2"
                                  ], "Plan has the fixed three-step run sequence")

    operation = _operation_from_snapshot(snapshot, operation_id)
    _check(checks, "operation.present", bool(operation),
           "controller snapshot contains exactly the planned Operation")
    _check(checks, "operation.identity",
           operation.get("case_uid") == case_uid
           and operation.get("goal_hash") == plan.get("goal_hash")
           and operation.get("plan_hash") == actual_plan_hash,
           "Operation binds the planned Case, Goal, and Plan hashes")
    _check(checks, "operation.embedded",
           operation.get("goal") == goal and operation.get("plan") == plan,
           "controller snapshot preserves the exact Goal and Plan")
    _check(checks, "operation.completed", operation.get("status") == "completed",
           "Operation has a successful terminal state")
    operation_steps = operation.get("steps") if isinstance(operation.get("steps"), list) else []
    _check(checks, "operation.steps", len(operation_steps) == len(steps)
           and all(isinstance(item, dict) and item.get("status") == "committed"
                   for item in operation_steps),
           "every planned Step is committed")

    supplied_receipts: Dict[int, Tuple[Path, Mapping[str, Any]]] = {}
    duplicate_receipt_index = False
    for path in receipt_paths:
        resolved = path.expanduser().resolve()
        receipt = load_json(resolved, "Router v5 Step receipt")
        index = receipt.get("step_index")
        if isinstance(index, int) and not isinstance(index, bool):
            if index in supplied_receipts:
                duplicate_receipt_index = True
            supplied_receipts[index] = (resolved, receipt)
    _check(checks, "receipts.complete",
           len(receipt_paths) == len(steps)
           and not duplicate_receipt_index
           and set(supplied_receipts) == set(range(len(steps))),
           "one owner-site receipt is supplied for every planned Step")
    launch_receipt: Mapping[str, Any] = {}
    for index, step in enumerate(steps):
        path, receipt = supplied_receipts.get(index, (Path("."), {}))
        matches = (
            receipt.get("schema_version") == 1
            and receipt.get("operation_id") == operation_id
            and receipt.get("plan_hash") == actual_plan_hash
            and receipt.get("step_index") == index
            and receipt.get("step_id") == step.get("step_id")
            and receipt.get("kind") == step.get("kind")
        )
        _check(checks, "receipt.%d.identity" % index, matches,
               "receipt matches its Operation and Step identity")
        _check(checks, "receipt.%d.verified" % index,
               receipt.get("state") == "outputs_verified",
               "receipt reached independently verifiable output state")
        if index < len(operation_steps):
            stored = operation_steps[index]
            _check(checks, "receipt.%d.effect" % index,
                   stored.get("effect") == receipt.get("effect_identity", {}),
                   "controller committed the receipt effect")
            _check(checks, "receipt.%d.outputs" % index,
                   stored.get("evidence") == receipt.get("outputs", []),
                   "controller committed the verified receipt outputs")
        if path.is_file():
            artifacts.append((path, "step-receipt", "entity-router-v5-site-receipt",
                              str(step.get("site_id") or "execution-site")))
        if step.get("kind") == "run.launch.v2":
            launch_receipt = receipt

    launch = steps[2] if len(steps) == 3 and isinstance(steps[2], dict) else {}
    launch_request = launch.get("request") if isinstance(launch.get("request"), dict) else {}
    expected_comment = "entity-router:%s:%s" % (
        operation_id, actual_plan_hash.split(":", 1)[-1][:16]
    )
    effect = launch_receipt.get("effect_identity") \
        if isinstance(launch_receipt.get("effect_identity"), dict) else {}
    _check(checks, "launch.effect",
           effect.get("scheduler") == "slurm" and bool(effect.get("job_id"))
           and effect.get("job_name") == launch_request.get("job_name")
           and effect.get("submit_user") == launch_request.get("submit_user")
           and effect.get("run_root") == launch_request.get("run_root")
           and effect.get("comment") == expected_comment,
           "launch receipt carries the exact scheduler effect identity")

    if scheduler_path is not None:
        scheduler_path = scheduler_path.expanduser().resolve()
        scheduler = load_json(scheduler_path, "scheduler snapshot")
        artifacts.append((scheduler_path, "scheduler-snapshot",
                          "independent-slurm-snapshot", str(plan.get("site_id") or "execution-site")))
        jobs = scheduler.get("jobs") if isinstance(scheduler.get("jobs"), list) else []
        query = scheduler.get("query") if isinstance(scheduler.get("query"), dict) else {}
        _check(checks, "scheduler.schema",
               scheduler.get("schema_version") == 1 and scheduler.get("scheduler") == "slurm",
               "scheduler evidence is a v1 Slurm snapshot")
        _check(checks, "scheduler.query",
               query == {"job_name": launch_request.get("job_name"),
                         "submit_user": launch_request.get("submit_user"),
                         "run_root": launch_request.get("run_root"),
                         "comment": expected_comment},
               "scheduler snapshot uses the immutable launch identity")
        _check(checks, "scheduler.single-effect", len(jobs) == 1,
               "exactly one scheduler job matches the launch identity")
        if len(jobs) == 1:
            job = jobs[0]
            _check(checks, "scheduler.matches-receipt",
                   all(job.get(key) == effect.get(key)
                       for key in ("job_id", "job_name", "submit_user", "run_root", "comment")),
                   "independent scheduler job matches the launch receipt")
    else:
        _check(checks, "scheduler.snapshot", False,
               "completed Operation requires an independent scheduler snapshot")

    status_anchor = "none"
    if status_path is not None:
        status_path = status_path.expanduser().resolve()
        status = load_json(status_path, "Router v5 status snapshot")
        artifacts.append((status_path, "router-status", "entity-router-v5-status", "controller"))
        status_anchor = "status"
        current = status.get("current") if isinstance(status.get("current"), dict) else {}
        run_identity = status.get("run") if isinstance(status.get("run"), dict) else {}
        _check(checks, "status.schema",
               status.get("schema_version") == 1
               and status.get("kind") == "entity-router.status"
               and status.get("state_mutated") is False,
               "status is a read-only v5 status snapshot")
        _check(checks, "status.identity",
               status.get("case_uid") == case_uid
               and current.get("source_id") == plan.get("source_id")
               and current.get("run_id") == run_id,
               "status preserves the planned Case/source/run identity")
        _check(checks, "status.scheduler",
               run_identity.get("id") == run_id
               and run_identity.get("scheduler", {}).get("job_id") == effect.get("job_id"),
               "status run identity carries the verified scheduler effect")
    else:
        _check(checks, "status.snapshot", False,
               "completed Operation requires a controller-local status snapshot")

    run_identity = steps[1].get("identity", {}) if len(steps) > 1 else {}
    parents = run_identity.get("parents") if isinstance(run_identity.get("parents"), dict) else {}
    _check(checks, "identity.source-run",
           run_identity.get("id") == run_id
           and parents.get("source_id") == plan.get("source_id")
           and "build_id" in parents,
           "run identity binds its source and declared build parent field")

    return _record(
        run_dir,
        validator="entity-router-operation-v5",
        status=_status(checks),
        checks=checks,
        summary={
            "case_uid": case_uid,
            "operation_id": operation_id,
            "run_id": run_id,
            "site_id": plan.get("site_id", ""),
            "operation_status": operation.get("status", "missing"),
            "job_id": effect.get("job_id", ""),
            "status_anchor": status_anchor,
        },
        artifacts=artifacts,
        parent_span_id=parent_span_id,
    )


def validate_pgen_preflight(
    run_dir: Path,
    *,
    result_path: Path,
    expected: str,
    action_request_path: Optional[Path] = None,
    parent_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    result_path = result_path.expanduser().resolve()
    result = load_json(result_path, "PGen preflight result")
    checks: List[Dict[str, Any]] = []
    required = {"allowed", "mode", "target", "case_uid", "control_root", "action_id", "reason"}
    _check(checks, "result.required-fields", required.issubset(result),
           "preflight result contains the public decision fields")
    _check(checks, "result.allowed-type", isinstance(result.get("allowed"), bool),
           "allowed is a boolean")
    wanted = expected == "allowed"
    _check(checks, "result.expected-decision", result.get("allowed") is wanted,
           f"preflight decision matches expected={expected}")
    target = result.get("target") if isinstance(result.get("target"), dict) else {}
    _check(checks, "result.target-locator",
           bool(target.get("site_id")) and Path(str(target.get("path") or "")).is_absolute(),
           "target is a structured absolute Locator")
    mode = str(result.get("mode") or "")
    allowed_modes = {
        "managed-readonly", "standalone-readonly", "standalone-write", "managed-write",
        "router-required", "ambiguous",
    }
    _check(checks, "result.mode", mode in allowed_modes, "mode is a known preflight outcome")

    artifacts: List[ArtifactSpec] = [
        (result_path, "preflight-result", "entity-pgen-preflight", "controller")
    ]
    if wanted and mode == "managed-write":
        _check(checks, "managed.identity",
               bool(result.get("case_uid")) and bool(result.get("action_id")) and bool(result.get("control_root")),
               "managed write identifies its Case, Action, and controller root")
        _check(checks, "managed.action-request", action_request_path is not None,
               "managed write is linked to its Action request")
        if action_request_path is not None:
            action_request_path = action_request_path.expanduser().resolve()
            request = load_json(action_request_path, "PGen Action request")
            artifacts.append((action_request_path, "action-request", "entity-router-action-request", "controller"))
            _check(checks, "managed.action-id", request.get("action_id") == result.get("action_id"),
                   "preflight Action ID matches request")
            _check(checks, "managed.case-uid", request.get("case_uid") == result.get("case_uid"),
                   "preflight Case UID matches request")
            _check(checks, "managed.owner", request.get("owner") == "entity-pgen"
                   and request.get("execution_domain") == "entity-pgen",
                   "Action owner and execution domain are entity-pgen")
            roots = request.get("write_roots") if isinstance(request.get("write_roots"), list) else []
            covered = False
            for root in roots:
                if not isinstance(root, dict) or root.get("site_id") != target.get("site_id"):
                    continue
                try:
                    if _within(Path(str(target.get("path"))), Path(str(root.get("path")))):
                        covered = True
                        break
                except (OSError, ValueError):
                    pass
            _check(checks, "managed.envelope", covered,
                   "target is inside a same-site Action write root")
    if not wanted:
        _check(checks, "denial.mode", mode in {"router-required", "ambiguous"},
               "denied write fails closed with a routing or ambiguity outcome")

    return _record(
        run_dir,
        validator="entity-pgen-preflight-v1",
        status=_status(checks),
        checks=checks,
        summary={
            "expected": expected,
            "allowed": result.get("allowed"),
            "mode": mode,
            "case_uid": result.get("case_uid", ""),
            "action_id": result.get("action_id", ""),
        },
        artifacts=artifacts,
        parent_span_id=parent_span_id,
    )


def validate_env_build(
    run_dir: Path,
    *,
    requirements_path: Path,
    expected: str,
    checkpoint_path: Optional[Path] = None,
    env_path: Optional[Path] = None,
    parent_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    requirements_path = requirements_path.expanduser().resolve()
    requirements = load_json(requirements_path, "env-build requirements")
    checks: List[Dict[str, Any]] = []
    _check(checks, "requirements.schema", requirements.get("schema_version") == 2,
           "requirements use the current schema v2")
    entity = requirements.get("entity") if isinstance(requirements.get("entity"), dict) else {}
    _check(checks, "requirements.site", bool(entity.get("site_id")),
           "build site_id is explicit")
    _check(checks, "requirements.source-revision", isinstance(entity.get("source_revision"), dict)
           and bool(entity.get("source_revision")), "source revision identity is present")
    build_root = Path(str(entity.get("build_root") or ""))
    _check(checks, "requirements.build-root", build_root.is_absolute(),
           "build root is absolute and explicit")
    result = requirements.get("build_result") if isinstance(requirements.get("build_result"), dict) else {}
    _check(checks, "result.expected-status", result.get("status") == expected,
           f"build_result.status matches expected={expected}")

    artifacts: List[ArtifactSpec] = [
        (requirements_path, "requirements", "entity-env-build-requirements", str(entity.get("site_id") or "build-site"))
    ]
    site_id = str(entity.get("site_id") or "build-site")
    log_path = Path(str(result.get("runner_log") or ""))
    script_path = Path(str(result.get("script") or ""))
    executable_path = Path(str(result.get("expected_executable") or ""))
    script_record = requirements.get("entity_build_script") \
        if isinstance(requirements.get("entity_build_script"), dict) else {}
    generated_from = script_record.get("generated_from") \
        if isinstance(script_record.get("generated_from"), dict) else {}
    checkpoint_path = (checkpoint_path or Path(str(generated_from.get("checkpoint_json") or ""))).expanduser()
    env_path = (env_path or Path(str(generated_from.get("env_sh") or ""))).expanduser()
    if expected == "pass":
        _check(checks, "result.exit-code", result.get("exit_code") == 0,
               "successful build exit code is zero")
        _check(checks, "result.runner-log", log_path.is_file(),
               "runner log exists")
        _check(checks, "result.script", script_path.is_file(),
               "executed build script exists")
        _check(checks, "result.executable", executable_path.is_file() and os.access(str(executable_path), os.X_OK),
               "expected executable exists and is executable")
        _check(checks, "result.executable-root",
               executable_path.is_absolute() and build_root.is_absolute() and _within(executable_path, build_root),
               "expected executable belongs to the immutable build root")
        _check(checks, "script.generated", script_record.get("status") == "generated",
               "build script has a generated record")
        _check(checks, "script.path",
               script_path.is_file() and Path(str(script_record.get("path") or "")).resolve() == script_path.resolve(),
               "executed script matches the generated script record")
        _check(checks, "script.env", env_path.is_file(),
               "generated env.sh exists")
        _check(checks, "script.checkpoint", checkpoint_path.is_file(),
               "dependency checkpoint exists")
        if checkpoint_path.is_file():
            checkpoint = load_json(checkpoint_path.resolve(), "env-build checkpoint")
            _check(checks, "checkpoint.schema", checkpoint.get("schema_version") == 2,
                   "checkpoint uses schema v2")
            compatibility = checkpoint.get("compatibility") \
                if isinstance(checkpoint.get("compatibility"), dict) else {}
            _check(checks, "checkpoint.compatibility", compatibility.get("status") == "pass",
                   "checkpoint compatibility status is pass")
            checkpoint_entity = checkpoint.get("entity") \
                if isinstance(checkpoint.get("entity"), dict) else {}
            identity_fields = (
                "site_id", "source_checkout", "source_revision", "build_root", "deps_root", "artifacts_root"
            )
            _check(checks, "checkpoint.identity",
                   all(checkpoint_entity.get(key) == entity.get(key) for key in identity_fields),
                   "checkpoint site, source revision, and build paths match requirements")
            checkpoint_env = checkpoint.get("env_sh") \
                if isinstance(checkpoint.get("env_sh"), dict) else {}
            _check(checks, "checkpoint.env-status", checkpoint_env.get("status") == "generated",
                   "checkpoint records a generated env.sh")
            _check(checks, "checkpoint.env-path",
                   env_path.is_file() and Path(str(checkpoint_env.get("path") or "")).resolve() == env_path.resolve(),
                   "checkpoint env.sh path matches build generation input")
            _check(checks, "checkpoint.env-fingerprint",
                   bool(checkpoint_env.get("generated_at"))
                   and generated_from.get("env_fingerprint") == checkpoint_env.get("generated_at"),
                   "build script records the current env.sh generation fingerprint")
    elif expected == "fail":
        _check(checks, "result.exit-code", isinstance(result.get("exit_code"), int)
               and result.get("exit_code") != 0, "failed build has a non-zero exit code")
        _check(checks, "result.runner-log", log_path.is_file(),
               "failure preserves a runner log")

    for path, role, authority in (
        (log_path, "runner-log", "entity-env-build-runner-log"),
        (script_path, "build-script", "entity-env-build-script"),
        (executable_path, "executable", "entity-env-build-executable"),
        (env_path, "environment-script", "entity-env-build-env"),
        (checkpoint_path, "dependency-checkpoint", "entity-env-build-checkpoint"),
    ):
        if path.is_file():
            artifacts.append((path, role, authority, site_id))

    return _record(
        run_dir,
        validator="entity-env-build-result-v2",
        status=_status(checks),
        checks=checks,
        summary={
            "expected": expected,
            "actual": result.get("status", "missing"),
            "site_id": entity.get("site_id", ""),
            "build_root": str(build_root) if build_root.is_absolute() else "",
            "run_id": result.get("run_id", ""),
            "source_revision_kind": (entity.get("source_revision") or {}).get("kind", "")
            if isinstance(entity.get("source_revision"), dict) else "",
        },
        artifacts=artifacts,
        parent_span_id=parent_span_id,
    )


def validate_nt2py_inventory(
    run_dir: Path,
    *,
    inventory_path: Path,
    expected: str,
    parent_span_id: Optional[str] = None,
) -> Dict[str, Any]:
    inventory_path = inventory_path.expanduser().resolve()
    inventory = load_json(inventory_path, "nt2py inventory")
    checks: List[Dict[str, Any]] = []
    _check(checks, "inventory.schema", inventory.get("schema_version") == 1,
           "inventory uses schema v1")
    _check(checks, "inventory.expected-status", inventory.get("status") == expected,
           f"inventory status matches expected={expected}")
    data_root = Path(str(inventory.get("data_root") or ""))
    _check(checks, "inventory.data-root", data_root.is_absolute(),
           "inventory records an absolute Entity data root")
    _check(checks, "inventory.output-safety",
           data_root.is_absolute() and not _within(inventory_path, data_root),
           "inventory artifact is outside the Entity data root")
    if expected == "ok":
        for key in ("fields", "particles", "spectra", "diagnostics"):
            _check(checks, f"inventory.{key}", isinstance(inventory.get(key), dict),
                   f"inventory contains {key} metadata")
        _check(checks, "inventory.version", bool(inventory.get("nt2py_version")),
               "installed nt2py version is recorded")
    elif expected == "error":
        _check(checks, "inventory.error", isinstance(inventory.get("error"), dict),
               "failed inventory includes a structured error")

    return _record(
        run_dir,
        validator="entity-nt2py-inventory-v1",
        status=_status(checks),
        checks=checks,
        summary={
            "expected": expected,
            "actual": inventory.get("status", "missing"),
            "data_root": str(data_root) if data_root.is_absolute() else "",
            "nt2py_version": inventory.get("nt2py_version"),
            "version_match": inventory.get("version_match"),
        },
        artifacts=[
            (inventory_path, "data-inventory", "entity-nt2py-inventory", "data-site")
        ],
        parent_span_id=parent_span_id,
    )
