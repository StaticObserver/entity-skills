#!/usr/bin/env python3
"""GoalSpec validation and deterministic Operation planning."""

from __future__ import print_function

import getpass
import json
import os
import re
import subprocess

from entity_router_common import (
    RouterError,
    absolute,
    now_utc,
    run_on_site,
    sha256_file,
    source_manifest,
)
from entity_router_store import StoreError, canonical_hash


GOAL_SCHEMA_VERSION = 1
PLAN_SCHEMA_VERSION = 1
FORBIDDEN_GOAL_KEYS = {
    "case_uid", "operation_id", "workflow_id", "action_id", "plan_hash",
    "target_hash", "flow_hash", "locator", "bindings", "owner", "execution_domain",
    "lease", "revision",
}
GOAL_KEYS = {
    "run": {"schema_version", "kind", "input", "site", "compute", "executable",
            "case_id", "labels", "source_mode"},
    "build": {"schema_version", "kind", "site", "checkpoint", "executable",
              "case_id", "labels"},
    "data": {"schema_version", "kind", "run", "case_id", "labels"},
}


class PlanError(RouterError):
    def __init__(self, message, status="invalid_request", decisions=None):
        RouterError.__init__(self, message)
        self.status = status
        self.decisions = decisions or []


def _require_object(value, label):
    if not isinstance(value, dict):
        raise PlanError("%s must be an object" % label)
    return value


def validate_goal(goal):
    goal = _require_object(goal, "GoalSpec")
    unknown_control = set(goal).intersection(FORBIDDEN_GOAL_KEYS)
    if unknown_control:
        raise PlanError(
            "GoalSpec contains controller-derived field: %s" % sorted(unknown_control)[0]
        )
    if goal.get("schema_version") != GOAL_SCHEMA_VERSION:
        raise PlanError("GoalSpec schema_version must be 1")
    kind = goal.get("kind")
    if kind not in GOAL_KEYS:
        raise PlanError("GoalSpec kind is not supported: %s" % kind)
    unknown = set(goal).difference(GOAL_KEYS[kind])
    if unknown:
        raise PlanError("GoalSpec contains unknown field: %s" % sorted(unknown)[0])
    if "case_id" in goal and (not isinstance(goal["case_id"], str) or not goal["case_id"]):
        raise PlanError("case_id must be a non-empty string")
    labels = goal.get("labels", {})
    if (not isinstance(labels, dict)
            or any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in labels.items())):
        raise PlanError("labels must map strings to strings")
    if kind == "run":
        return _validate_run_goal(goal)
    if kind == "build":
        return _validate_build_goal(goal)
    return _validate_data_goal(goal)


def _validate_build_goal(goal):
    decisions = []
    for key in ["site", "checkpoint", "executable"]:
        if not isinstance(goal.get(key), str) or not goal[key].strip():
            decisions.append({"field": key, "question": "select the build %s" % key})
    if decisions:
        raise PlanError("GoalSpec needs user decisions", "needs_decision", decisions)
    return goal


def _validate_data_goal(goal):
    if "run" in goal and (not isinstance(goal["run"], str) or not goal["run"]):
        raise PlanError("run must be a non-empty run id or 'current'")
    return goal


def _validate_run_goal(goal):
    if "executable" in goal and (not isinstance(goal["executable"], str)
                                  or not goal["executable"]):
        raise PlanError("executable must be a non-empty string")
    if goal.get("source_mode", "snapshot") not in {"git-ref", "snapshot", "shared", "external"}:
        raise PlanError("source_mode is invalid")
    decisions = []
    for key in ["input", "site"]:
        if not isinstance(goal.get(key), str) or not goal[key].strip():
            decisions.append({"field": key, "question": "select the %s" % key})
    compute = goal.get("compute")
    if not isinstance(compute, dict):
        decisions.append({"field": "compute", "question": "confirm compute resources"})
        compute = {}
    allowed_compute = {
        "nodes", "tasks", "gpus", "cpus_per_task", "walltime", "partition",
        "qos", "submit_user", "precision",
    }
    unknown_compute = set(compute).difference(allowed_compute)
    if unknown_compute:
        raise PlanError("compute contains unknown field: %s" % sorted(unknown_compute)[0])
    for field in ["gpus", "walltime", "precision"]:
        if field not in compute:
            decisions.append({"field": "compute.%s" % field,
                              "question": "confirm %s" % field})
    if decisions:
        raise PlanError("GoalSpec needs user decisions", "needs_decision", decisions)
    if compute["precision"] not in {"single", "double"}:
        raise PlanError("compute.precision must be single or double")
    for field in ["nodes", "tasks", "gpus", "cpus_per_task"]:
        if field in compute and (not isinstance(compute[field], int)
                                 or isinstance(compute[field], bool)
                                 or compute[field] < 1):
            raise PlanError("compute.%s must be a positive integer" % field)
    for field in ["partition", "qos", "submit_user"]:
        if field in compute and (not isinstance(compute[field], str)
                                 or not re.match(r"^[A-Za-z0-9_.@+-]*$", compute[field])):
            raise PlanError("compute.%s is invalid" % field)
    if not re.match(r"^[0-9]+(?:-[0-9]{2})?:[0-9]{2}:[0-9]{2}$", compute["walltime"]):
        raise PlanError("compute.walltime must use HH:MM:SS or D-HH:MM:SS")
    return goal


def load_goal(path):
    try:
        with open(path, "r") as handle:
            value = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise PlanError("cannot read GoalSpec: %s" % exc)
    return validate_goal(value)


def _git_revision(path):
    process = subprocess.Popen(
        ["git", "-C", path, "rev-parse", "HEAD", "HEAD^{tree}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    stdout, unused = process.communicate()
    if process.returncode != 0:
        return {"kind": "path", "root": path}
    values = [line.strip() for line in stdout.splitlines() if line.strip()]
    dirty = subprocess.Popen(
        ["git", "-C", path, "status", "--porcelain"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    dirty_out, unused = dirty.communicate()
    return {"kind": "git", "commit": values[0], "tree": values[1],
            "dirty": dirty.returncode != 0 or bool(dirty_out.strip())}


def _sites(store):
    connection = store._connect()
    try:
        return [json.loads(row[0]) for row in connection.execute(
            "SELECT profile_json FROM sites ORDER BY site_id"
        )]
    finally:
        connection.close()


def _source_site(store, project_root):
    matches = []
    for profile in _sites(store):
        if profile.get("transport", {}).get("kind") != "local":
            continue
        root = profile.get("roots", {}).get("source_root")
        if not root:
            continue
        try:
            if os.path.commonpath([project_root, absolute(root)]) == absolute(root):
                matches.append((len(absolute(root)), profile["site_id"]))
        except ValueError:
            pass
    if not matches:
        raise PlanError(
            "no local Site source_root covers the project",
            "needs_decision",
            [{"field": "site", "question": "register a local source Site for the project"}],
        )
    matches.sort(reverse=True)
    return matches[0][1]


def _resolve_input(project_root, value):
    path = absolute(value if os.path.isabs(value) else os.path.join(project_root, value))
    try:
        inside = os.path.commonpath([path, project_root]) == project_root
    except ValueError:
        inside = False
    if not inside:
        raise PlanError("GoalSpec input is outside the project root")
    if not os.path.isfile(path):
        raise PlanError("GoalSpec input does not exist: %s" % path)
    return path


def _remote_file(profile, path):
    if profile.get("transport", {}).get("kind") == "local":
        return os.path.isfile(path)
    code, unused, unused_err = run_on_site(profile, ["test", "-f", path])
    return code == 0


def _current_build_executable(case, profile, explicit):
    if explicit:
        build_root = profile.get("roots", {}).get("build_root")
        if not build_root:
            raise PlanError("execution Site is missing build_root")
        path = explicit if os.path.isabs(explicit) else os.path.join(build_root, explicit)
        path = os.path.normpath(path)
        try:
            inside = os.path.commonpath([path, os.path.normpath(build_root)]) == os.path.normpath(build_root)
        except ValueError:
            inside = False
        if not inside:
            raise PlanError("explicit executable is outside the Site build_root")
        if not _remote_file(profile, path):
            raise PlanError("executable does not exist on execution Site: %s" % path)
        return path, ""
    current_id = case.get("current", {}).get("build_id", "")
    identities = case.get("identities", {}).get("build", {}).get("items", [])
    current = None
    for item in identities:
        if item.get("id") == current_id or item.get("identity_id") == current_id:
            current = item
            break
    if current is None:
        raise PlanError(
            "no verified current build executable is available",
            "needs_decision",
            [{"field": "executable", "question": "provide or build an executable"}],
        )
    candidates = []
    for output in current.get("outputs", current.get("evidence", [])):
        locator = output.get("locator", {}) if isinstance(output, dict) else {}
        path = locator.get("path", "")
        if locator.get("site_id") == profile["site_id"] and path:
            name = os.path.basename(path)
            if name == "entity.xc" or name.endswith(".xc"):
                candidates.append(path)
    if not candidates:
        raise PlanError(
            "current build identity has no executable evidence",
            "needs_decision",
            [{"field": "executable", "question": "select the verified executable"}],
        )
    candidates = sorted(set(candidates), key=lambda item: (os.path.basename(item) != "entity.xc", item))
    if not _remote_file(profile, candidates[0]):
        raise PlanError("current build executable is no longer present: %s" % candidates[0])
    return candidates[0], current_id


def _site_policy(profile, compute):
    policy = profile.get("policy", {})
    normalized = dict(compute)
    normalized.setdefault("nodes", 1)
    normalized.setdefault("tasks", int(normalized["gpus"]))
    normalized.setdefault("cpus_per_task", int(policy.get("default_cpus_per_gpu", 1)))
    normalized.setdefault("partition", policy.get("default_partition", ""))
    normalized.setdefault("qos", policy.get("default_qos", ""))
    if "submit_user" not in normalized:
        if policy.get("default_submit_user"):
            normalized["submit_user"] = policy["default_submit_user"]
        elif profile.get("transport", {}).get("kind") == "local":
            normalized["submit_user"] = getpass.getuser()
        else:
            raise PlanError(
                "SSH Slurm Site has no default_submit_user",
                "needs_decision",
                [{"field": "compute.submit_user",
                  "question": "confirm the scheduler user for Site %s" % profile["site_id"]}],
            )
    if (profile.get("scheduler", {}).get("kind") == "slurm"
            and not normalized.get("partition")):
        raise PlanError(
            "Slurm Site has no default_partition",
            "needs_decision",
            [{"field": "compute.partition",
              "question": "select a Slurm partition for Site %s" % profile["site_id"]}],
        )
    maximum = policy.get("max_cpu_per_gpu")
    if maximum is not None and normalized["cpus_per_task"] > int(maximum):
        raise PlanError(
            "compute.cpus_per_task exceeds Site max_cpu_per_gpu=%s" % maximum,
            "needs_decision",
            [{"field": "compute.cpus_per_task",
              "question": "choose no more than %s CPUs per GPU" % maximum}],
        )
    for field in ["partition", "qos", "submit_user"]:
        if (not isinstance(normalized[field], str)
                or not re.match(r"^[A-Za-z0-9_.@+-]*$", normalized[field])):
            raise PlanError("Site policy produced invalid compute.%s" % field)
    return normalized


def _operation_id(seed):
    return "op-" + canonical_hash(seed).split(":", 1)[1][:16]


def _source_identity(source_root, controller_artifacts=None):
    source_root = absolute(source_root)
    manifest = source_manifest(source_root)
    ignored = set()
    for path in controller_artifacts or []:
        path = absolute(path)
        try:
            if os.path.commonpath([path, source_root]) == source_root:
                ignored.add(os.path.relpath(path, source_root))
        except ValueError:
            pass
    files = [item for item in manifest.get("files", []) if item.get("path") not in ignored]
    identity = {"base_revision": manifest.get("base_revision", {}), "files": files}
    return {
        "snapshot_id": canonical_hash(identity).split(":", 1)[1],
        "base_revision": identity["base_revision"],
        "files": len(files),
    }, sorted(ignored)


def _simulation_confirmation(input_path):
    """Hard gate: the simulation parameter confirmation recorded by
    pgen_preflight.py confirm must exist and match the current input bytes."""
    path = input_path + ".decisions.json"
    question = (
        "show the parameter card to the user and record confirmation with "
        "pgen_preflight.py confirm %s --by <actor>" % input_path
    )
    if not os.path.isfile(path):
        raise PlanError(
            "simulation parameters have not been confirmed",
            "needs_decision",
            [{"field": "input", "question": question}],
        )
    try:
        with open(path, "r") as handle:
            record = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise PlanError("cannot read simulation confirmation: %s" % exc)
    if (not isinstance(record, dict)
            or record.get("kind") != "entity-pgen.simulation-confirmation"
            or record.get("input_sha256") != sha256_file(input_path)):
        raise PlanError(
            "simulation parameters changed since they were confirmed",
            "needs_decision",
            [{"field": "input", "question": question}],
        )
    return record


def _resolve_case(store, project_root, goal):
    try:
        return store.resolve_project(project_root), False
    except StoreError:
        source_site = _source_site(store, project_root)
        case_uid = "case-" + canonical_hash({"project_root": project_root}).split(":", 1)[1][:16]
        case = {
            "case_uid": case_uid,
            "case_id": goal.get("case_id") or os.path.basename(project_root),
            "project_root": project_root,
            "source": {
                "authority": {"site_id": source_site, "path": project_root},
                "transfer_policy": goal.get("source_mode", "snapshot"),
                "revision": _git_revision(project_root),
            },
            "current": {"source_id": "", "build_id": "", "run_id": "",
                        "active_run": None, "data_id": "", "analysis_id": ""},
            "identities": {}, "legacy": {},
        }
        return case, True


def plan_goal(store, project_root, goal, controller_artifacts=None):
    goal = validate_goal(goal)
    project_root = absolute(project_root)
    if not os.path.isdir(project_root):
        raise PlanError("project root does not exist: %s" % project_root)
    if goal["kind"] == "build":
        return _plan_build(store, project_root, goal)
    if goal["kind"] == "data":
        return _plan_data(store, project_root, goal)
    case, create_case = _resolve_case(store, project_root, goal)
    site_id = goal["site"]
    profile = store.get_site(site_id)
    if profile.get("scheduler", {}).get("kind") != "slurm":
        raise PlanError("run Goal currently requires a Slurm Site")
    roots = profile.get("roots", {})
    for key in ["build_root", "run_root", "staging_root"]:
        if not roots.get(key):
            raise PlanError("execution Site is missing %s" % key)
    input_path = _resolve_input(project_root, goal["input"])
    confirmation = _simulation_confirmation(input_path)
    source_authority = case["source"]["authority"]
    source_profile = store.get_site(source_authority["site_id"])
    if source_profile.get("transport", {}).get("kind") != "local":
        raise PlanError(
            "run planning currently requires a controller-local source authority",
            "needs_decision",
            [{"field": "source", "question": "materialize the exact source on a local authority"}],
        )
    source_fingerprint, ignored_artifacts = _source_identity(
        source_authority["path"], controller_artifacts
    )
    source_id = "source-" + source_fingerprint["snapshot_id"][:16]
    executable, build_id = _current_build_executable(case, profile, goal.get("executable"))
    compute = _site_policy(profile, goal["compute"])
    input_sha256 = sha256_file(input_path)
    seed = {
        "case_uid": case["case_uid"], "source_id": source_id,
        "input_sha256": input_sha256,
        "site_id": site_id, "executable": executable, "build_id": build_id,
        "compute": compute,
    }
    run_id = "run-" + canonical_hash(seed).split(":", 1)[1][:16]
    operation_id = _operation_id(seed)
    run_root = os.path.join(roots["run_root"], case["case_uid"], run_id)
    staging_root = os.path.join(roots["staging_root"], case["case_uid"], operation_id)
    receipt_root = os.path.join(staging_root, "receipts")
    manifest = os.path.join(run_root, "run-manifest.json")
    submit_script = os.path.join(run_root, "run.sbatch")
    staged_input = os.path.join(staging_root, "payloads", "input.toml")
    launch_receipt = os.path.join(receipt_root, "run-launch.json")
    prepare_receipt = os.path.join(receipt_root, "run-prepare.json")
    preflight_receipt = os.path.join(receipt_root, "run-preflight.json")
    job_name = "entity-%s" % operation_id
    run_spec = {"executable": executable, "compute": compute, "input_name": "input.toml"}
    run_identity = {
        "id": run_id, "kind": "run", "site_id": site_id,
        "root": {"site_id": site_id, "path": run_root},
        "parents": {"source_id": source_id, "build_id": build_id},
        "input_sha256": seed["input_sha256"], "compute": compute,
        "status": "planned",
    }
    manifest_payload = {
        "schema_version": 3, "case_uid": case["case_uid"], "run_id": run_id,
        "source_id": source_id, "build_id": build_id, "site_id": site_id,
        "input_sha256": seed["input_sha256"], "executable": executable,
        "compute": compute, "created_by_operation": operation_id,
    }
    steps = [
        {
            "step_id": "preflight", "kind": "run.preflight.v1", "site_id": site_id,
            "receipt": preflight_receipt,
            "allowed_roots": [staging_root],
            "request": {"run_spec": run_spec, "job_name": job_name,
                        "staging_root": staging_root},
        },
        {
            "step_id": "prepare", "kind": "run.prepare.v2", "site_id": site_id,
            "receipt": prepare_receipt,
            "allowed_roots": [staging_root, run_root],
            "payloads": [{"source": input_path, "target": staged_input,
                          "sha256": input_sha256}],
            "request": {"run_root": run_root, "manifest": manifest,
                        "manifest_payload": manifest_payload,
                        "submit_script": submit_script, "run_spec": run_spec,
                        "staging_root": staging_root, "staged_input": staged_input},
            "identity": run_identity,
        },
        {
            "step_id": "launch", "kind": "run.launch.v2", "site_id": site_id,
            "receipt": launch_receipt,
            "allowed_roots": [staging_root, run_root],
            "request": {"run_root": run_root, "submit_script": submit_script,
                        "job_name": job_name, "submit_user": compute["submit_user"]},
            "identity": run_identity,
        },
    ]
    plan_without_hash = {
        "schema_version": PLAN_SCHEMA_VERSION, "operation_id": operation_id,
        "case_uid": case["case_uid"], "project_root": project_root,
        "create_case": create_case, "goal_kind": "run",
        "case": {"case_uid": case["case_uid"], "case_id": case["case_id"],
                 "project_root": project_root, "source": case["source"],
                 "current": case["current"]},
        "goal_hash": canonical_hash(goal), "source_id": source_id,
        "controller_artifacts": ignored_artifacts,
        "source_identity": {
            "id": source_id, "kind": "source", "site_id": case["source"]["authority"]["site_id"],
            "root": case["source"]["authority"], "fingerprint": source_fingerprint,
        },
        "source_site_profile_hash": canonical_hash(source_profile),
        "site_id": site_id, "site_profile_hash": canonical_hash(profile),
        "run_id": run_id, "generated_at": now_utc(), "steps": steps,
    }
    plan = dict(plan_without_hash)
    stable = dict(plan_without_hash)
    stable.pop("generated_at", None)
    plan["plan_hash"] = canonical_hash(stable)
    return {
        "schema_version": 1, "kind": "entity-router.plan", "status": "ready",
        "state_mutated": False, "goal": goal, "plan": plan,
        "summary": {
            "project_root": project_root, "case_uid": case["case_uid"],
            "site_id": site_id, "run_id": run_id, "steps": [item["kind"] for item in steps],
            "compute": compute,
            "simulation_confirmation": {
                "confirmed_by": confirmation.get("confirmed_by", ""),
                "confirmed_at": confirmation.get("confirmed_at", ""),
                "defaults": bool(confirmation.get("defaults", False)),
            },
        },
    }


def require_verified_checkpoint(checkpoint):
    """Hard gate: a build Goal only registers checkpoints that env-build has
    verified (compatibility pass) and whose parameters were confirmed."""
    compatibility = checkpoint.get("compatibility", {})
    if not isinstance(compatibility, dict) or compatibility.get("status") != "pass":
        raise PlanError(
            "build checkpoint compatibility is not pass",
            "needs_decision",
            [{"field": "checkpoint",
              "question": "run entity_compat.py and resolve the failures"}],
        )
    parameters = checkpoint.get("decisions", {}).get("parameters", {})
    if not isinstance(parameters, dict) or not parameters.get("digest"):
        raise PlanError(
            "build parameters have not been confirmed",
            "needs_decision",
            [{"field": "checkpoint",
              "question": "record build parameter confirmation with "
                          "entity_checkpoint.py confirm"}],
        )


def _finish_plan(case, create_case, goal, profile, steps, kind_keys, summary):
    plan_without_hash = dict(kind_keys)
    plan_without_hash.update({
        "schema_version": PLAN_SCHEMA_VERSION,
        "case_uid": case["case_uid"], "project_root": case["project_root"],
        "create_case": create_case, "goal_kind": goal["kind"],
        "case": {"case_uid": case["case_uid"], "case_id": case["case_id"],
                 "project_root": case["project_root"], "source": case["source"],
                 "current": case["current"]},
        "goal_hash": canonical_hash(goal),
        "site_id": profile["site_id"],
        "site_profile_hash": canonical_hash(profile),
        "generated_at": now_utc(), "steps": steps,
    })
    plan = dict(plan_without_hash)
    stable = dict(plan_without_hash)
    stable.pop("generated_at", None)
    plan["plan_hash"] = canonical_hash(stable)
    return {
        "schema_version": 1, "kind": "entity-router.plan", "status": "ready",
        "state_mutated": False, "goal": goal, "plan": plan, "summary": summary,
    }


def _plan_build(store, project_root, goal):
    case, create_case = _resolve_case(store, project_root, goal)
    site_id = goal["site"]
    profile = store.get_site(site_id)
    roots = profile.get("roots", {})
    for key in ["build_root", "staging_root"]:
        if not roots.get(key):
            raise PlanError("execution Site is missing %s" % key)
    executable, unused = _current_build_executable(case, profile, goal["executable"])
    checkpoint_path = absolute(goal["checkpoint"])
    if not os.path.isfile(checkpoint_path):
        raise PlanError("build checkpoint does not exist: %s" % checkpoint_path)
    try:
        with open(checkpoint_path, "r") as handle:
            checkpoint = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise PlanError("cannot read build checkpoint: %s" % exc)
    if not isinstance(checkpoint, dict):
        raise PlanError("build checkpoint must contain a JSON object")
    require_verified_checkpoint(checkpoint)
    checkpoint_sha256 = sha256_file(checkpoint_path)
    seed = {"case_uid": case["case_uid"], "checkpoint_sha256": checkpoint_sha256,
            "executable": executable, "site_id": site_id}
    digest = canonical_hash(seed).split(":", 1)[1][:16]
    build_id = "build-" + digest
    operation_id = "op-" + digest
    staging_root = os.path.join(roots["staging_root"], case["case_uid"], operation_id)
    build_identity = {
        "id": build_id, "kind": "build", "site_id": site_id,
        "root": {"site_id": site_id, "path": os.path.dirname(executable)},
        "parents": {"source_id": case.get("current", {}).get("source_id", "")},
        "checkpoint_sha256": checkpoint_sha256, "status": "planned",
    }
    steps = [{
        "step_id": "register", "kind": "build.register.v1", "site_id": site_id,
        "receipt": os.path.join(staging_root, "receipts", "build-register.json"),
        "allowed_roots": [staging_root, roots["build_root"]],
        "request": {"executable": executable},
        "identity": build_identity,
    }]
    kind_keys = {"operation_id": operation_id, "build_id": build_id,
                 "checkpoint": checkpoint_path,
                 "checkpoint_sha256": checkpoint_sha256, "executable": executable}
    summary = {
        "project_root": project_root, "case_uid": case["case_uid"],
        "site_id": site_id, "build_id": build_id,
        "steps": [step["kind"] for step in steps],
        "parameters_confirmed_by": checkpoint["decisions"]["parameters"].get(
            "confirmed_by", ""),
    }
    return _finish_plan(case, create_case, goal, profile, steps, kind_keys, summary)


def _plan_data(store, project_root, goal):
    try:
        case = store.resolve_project(project_root)
        create_case = False
    except StoreError:
        raise PlanError(
            "no Case covers the project; complete a run Goal first",
            "needs_decision",
            [{"field": "run", "question": "select a Case with a submitted run"}],
        )
    requested = goal.get("run", "")
    run_id = (case.get("current", {}).get("run_id", "")
              if requested in {"", "current"} else requested)
    if not run_id:
        raise PlanError(
            "Case has no current run",
            "needs_decision",
            [{"field": "run", "question": "select the run to inventory"}],
        )
    run_identity = None
    for item in case.get("identities", {}).get("run", {}).get("items", []):
        if item.get("id") == run_id or item.get("identity_id") == run_id:
            run_identity = item
            break
    if run_identity is None:
        raise PlanError(
            "unknown run identity: %s" % run_id,
            "needs_decision",
            [{"field": "run", "question": "select a known run id"}],
        )
    root = run_identity.get("root", {})
    site_id = root.get("site_id") or run_identity.get("site_id", "")
    run_root = root.get("path", "")
    if not site_id or not run_root:
        raise PlanError("run identity has no usable root locator")
    profile = store.get_site(site_id)
    if not profile.get("roots", {}).get("staging_root"):
        raise PlanError("execution Site is missing staging_root")
    digest = canonical_hash({"case_uid": case["case_uid"], "run_id": run_id})
    digest = digest.split(":", 1)[1][:16]
    data_id = "data-" + digest
    operation_id = "op-" + digest
    staging_root = os.path.join(
        profile["roots"]["staging_root"], case["case_uid"], operation_id)
    data_identity = {
        "id": data_id, "kind": "data", "site_id": site_id,
        "root": {"site_id": site_id, "path": run_root},
        "parents": {"run_id": run_id}, "status": "planned",
    }
    steps = [{
        "step_id": "inventory", "kind": "data.inventory.v1", "site_id": site_id,
        "receipt": os.path.join(staging_root, "receipts", "data-inventory.json"),
        "allowed_roots": [staging_root, run_root],
        "request": {"run_root": run_root,
                    "manifest": os.path.join(run_root, "data-inventory.json")},
        "identity": data_identity,
    }]
    kind_keys = {"operation_id": operation_id, "data_id": data_id, "run_id": run_id}
    summary = {
        "project_root": project_root, "case_uid": case["case_uid"],
        "site_id": site_id, "data_id": data_id, "run_id": run_id,
        "steps": [step["kind"] for step in steps],
    }
    return _finish_plan(case, create_case, goal, profile, steps, kind_keys, summary)


PLAN_BASE_KEYS = {"schema_version", "operation_id", "case_uid", "project_root",
                  "create_case", "case", "goal_hash", "site_id",
                  "site_profile_hash", "generated_at", "steps", "plan_hash"}
PLAN_KIND_KEYS = {
    "run": {"goal_kind", "source_id", "controller_artifacts",
            "source_site_profile_hash", "source_identity", "run_id"},
    "build": {"goal_kind", "build_id", "checkpoint", "checkpoint_sha256",
              "executable"},
    "data": {"goal_kind", "data_id", "run_id"},
}
PLAN_STEP_SCHEMAS = {
    "run": [
        ("preflight", "run.preflight.v1",
         {"step_id", "kind", "site_id", "receipt", "allowed_roots", "request"},
         {"run_spec", "job_name", "staging_root"}),
        ("prepare", "run.prepare.v2",
         {"step_id", "kind", "site_id", "receipt", "allowed_roots", "payloads",
          "request", "identity"},
         {"run_root", "manifest", "manifest_payload", "submit_script", "run_spec",
          "staging_root", "staged_input"}),
        ("launch", "run.launch.v2",
         {"step_id", "kind", "site_id", "receipt", "allowed_roots", "request",
          "identity"},
         {"run_root", "submit_script", "job_name", "submit_user"}),
    ],
    "build": [
        ("register", "build.register.v1",
         {"step_id", "kind", "site_id", "receipt", "allowed_roots", "request",
          "identity"},
         {"executable"}),
    ],
    "data": [
        ("inventory", "data.inventory.v1",
         {"step_id", "kind", "site_id", "receipt", "allowed_roots", "request",
          "identity"},
         {"run_root", "manifest"}),
    ],
}


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise PlanError("invalid Operation Plan schema")
    kind = plan.get("goal_kind") or "run"
    if kind not in PLAN_KIND_KEYS:
        raise PlanError("Operation Plan has unsupported Goal kind: %s" % kind)
    required = set(PLAN_BASE_KEYS) | set(PLAN_KIND_KEYS[kind])
    if "goal_kind" not in plan:
        required.discard("goal_kind")
    if set(plan) != required:
        raise PlanError("Operation Plan keys differ from schema")
    unsigned = dict(plan)
    expected = unsigned.pop("plan_hash")
    unsigned.pop("generated_at", None)
    if canonical_hash(unsigned) != expected:
        raise PlanError("Operation Plan hash is invalid")
    steps = PLAN_STEP_SCHEMAS[kind]
    if not isinstance(plan["steps"], list) or len(plan["steps"]) != len(steps):
        raise PlanError("Operation Plan has wrong Step count for Goal kind %s" % kind)
    for index, (step_id, step_kind, step_keys, request_keys) in enumerate(steps):
        step = plan["steps"][index]
        if set(step) != step_keys or set(step.get("request", {})) != request_keys:
            raise PlanError("Operation Plan Step keys differ from schema")
        if step.get("kind") != step_kind:
            raise PlanError("Operation Plan contains unsupported Step kind")
        if step.get("step_id") != step_id:
            raise PlanError("Operation Plan Step order is invalid")
    return plan
