#!/usr/bin/env python3
"""Apply immutable Operation Plans and expose compact controller status."""

from __future__ import print_function

import json
import os
import shlex
import shutil
import tempfile
import threading

from entity_router_common import (
    RouterError,
    absolute,
    atomic_write_json,
    now_utc,
    run_command,
    run_on_site,
    sha256_file,
)
from entity_router_planner import (
    _source_identity,
    require_verified_checkpoint,
    validate_goal,
    validate_plan,
)
from entity_router_store import StoreError, canonical_hash


class OperationError(RouterError):
    pass


def _json_from_stdout(stdout, label):
    for line in reversed((stdout or "").splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise OperationError("%s returned invalid JSON" % label)


def _copy_verified(source, target, expected):
    if sha256_file(source) != expected:
        raise OperationError("payload changed since planning: %s" % source)
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    if os.path.isfile(target):
        if sha256_file(target) != expected:
            raise OperationError("staged payload exists with another identity: %s" % target)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".payload-", dir=parent)
    os.close(descriptor)
    try:
        shutil.copy2(source, temporary)
        if sha256_file(temporary) != expected:
            raise OperationError("copied payload failed identity verification")
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


class ExecutorClient(object):
    def __init__(self, profile):
        self.profile = profile
        self.transport = profile.get("transport", {}).get("kind")
        self.alias = profile.get("transport", {}).get("ssh_alias", "")
        self.script = os.path.join(os.path.dirname(__file__), "entity_router_executor.py")
        self.digest = sha256_file(self.script)
        staging = profile.get("roots", {}).get("staging_root")
        if not staging:
            raise OperationError("execution Site has no staging_root")
        self.remote_script = os.path.join(
            staging, ".entity-router-executor", self.digest, "entity_router_executor.py"
        )

    def _remote_hash(self, path):
        script = (
            "import hashlib,os,sys; p=sys.argv[1]; "
            "print(hashlib.sha256(open(p,'rb').read()).hexdigest() if os.path.isfile(p) else '')"
        )
        code, stdout, stderr = run_on_site(self.profile, ["python3", "-c", script, path])
        if code != 0:
            raise OperationError("cannot verify remote file: %s" % (stderr.strip() or stdout.strip()))
        return stdout.strip()

    def _scp(self, source, target):
        code, unused, stderr = run_command([
            "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            source, "%s:%s" % (self.alias, shlex.quote(target)),
        ])
        if code != 0:
            raise OperationError("cannot stage remote file: %s" % stderr.strip())

    def ensure_executor(self):
        if self.transport == "local":
            _copy_verified(self.script, self.remote_script, self.digest)
            return self.remote_script
        parent = os.path.dirname(self.remote_script)
        code, unused, stderr = run_on_site(self.profile, ["mkdir", "-p", parent])
        if code != 0:
            raise OperationError("cannot prepare remote executor directory: %s" % stderr.strip())
        current = self._remote_hash(self.remote_script)
        if current:
            if current != self.digest:
                raise OperationError("content-addressed remote executor has wrong identity")
            return self.remote_script
        temporary = self.remote_script + ".tmp-%d" % os.getpid()
        self._scp(self.script, temporary)
        if self._remote_hash(temporary) != self.digest:
            raise OperationError("remote executor failed identity verification")
        code, unused, stderr = run_on_site(
            self.profile, ["python3", "-c", "import os,sys; os.replace(sys.argv[1],sys.argv[2])",
                           temporary, self.remote_script]
        )
        if code != 0:
            raise OperationError("cannot activate remote executor: %s" % stderr.strip())
        return self.remote_script

    def stage_payload(self, payload):
        source = absolute(payload["source"])
        target = payload["target"]
        expected = payload["sha256"]
        if self.transport == "local":
            _copy_verified(source, target, expected)
            return
        if sha256_file(source) != expected:
            raise OperationError("payload changed since planning: %s" % source)
        parent = os.path.dirname(target)
        code, unused, stderr = run_on_site(self.profile, ["mkdir", "-p", parent])
        if code != 0:
            raise OperationError("cannot prepare remote payload directory: %s" % stderr.strip())
        current = self._remote_hash(target)
        if current:
            if current != expected:
                raise OperationError("staged payload exists with another identity")
            return
        temporary = target + ".tmp-%d" % os.getpid()
        self._scp(source, temporary)
        if self._remote_hash(temporary) != expected:
            raise OperationError("remote payload failed identity verification")
        code, unused, stderr = run_on_site(
            self.profile, ["python3", "-c", "import os,sys; os.replace(sys.argv[1],sys.argv[2])",
                           temporary, target]
        )
        if code != 0:
            raise OperationError("cannot activate remote payload: %s" % stderr.strip())

    def _stage_envelope(self, envelope):
        request_path = os.path.join(
            os.path.dirname(envelope["receipt"]), envelope["step_id"] + "-request.json"
        )
        if self.transport == "local":
            atomic_write_json(request_path, envelope)
            return request_path
        descriptor, local_path = tempfile.mkstemp(prefix="entity-step-", suffix=".json")
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(envelope, handle, indent=2, sort_keys=True)
                handle.write("\n")
            parent = os.path.dirname(request_path)
            code, unused, stderr = run_on_site(self.profile, ["mkdir", "-p", parent])
            if code != 0:
                raise OperationError("cannot prepare remote request directory: %s" % stderr.strip())
            self._scp(local_path, request_path)
            return request_path
        finally:
            try:
                os.unlink(local_path)
            except OSError:
                pass

    def invoke(self, command, envelope):
        executor = self.ensure_executor()
        request_path = self._stage_envelope(envelope)
        code, stdout, stderr = run_on_site(
            self.profile, ["python3", executor, command, "--request", request_path]
        )
        result = _json_from_stdout(stdout, "Site executor")
        if code != 0 or result.get("status") not in {"completed", "verified"}:
            raise OperationError(
                result.get("message") or stderr.strip() or "Site executor failed"
            )
        return result


class ClaimHeartbeat(object):
    def __init__(self, store, operation_id, token, ttl_seconds=90):
        self.store = store
        self.operation_id = operation_id
        self.token = token
        self.ttl_seconds = ttl_seconds
        self.stop_event = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True

    def _run(self):
        while not self.stop_event.wait(max(5, self.ttl_seconds // 3)):
            try:
                self.store.renew_claim(self.operation_id, self.token, self.ttl_seconds)
            except Exception as exc:
                self.error = exc
                return

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def check(self):
        if self.error is not None:
            raise OperationError("Operation claim heartbeat failed: %s" % self.error)


def _verify_source(plan):
    source_root = plan["source_identity"]["root"]["path"]
    artifacts = [os.path.join(source_root, path)
                 for path in plan.get("controller_artifacts", [])]
    current, unused = _source_identity(source_root, artifacts)
    if current != plan["source_identity"]["fingerprint"]:
        raise OperationError("project source changed after planning; create a new plan")


def _validate_derivations(goal, plan, profile, source_profile, plan_path):
    project_root = absolute(plan["project_root"])
    case_spec = plan["case"]
    if set(case_spec) != {"case_uid", "case_id", "project_root", "source", "current"}:
        raise OperationError("Plan Case keys differ from schema")
    if (case_spec["case_uid"] != plan["case_uid"]
            or absolute(case_spec["project_root"]) != project_root):
        raise OperationError("Plan Case does not match the project")
    source_identity = plan["source_identity"]
    authority = case_spec.get("source", {}).get("authority", {})
    if (source_identity.get("id") != plan["source_id"]
            or source_identity.get("kind") != "source"
            or source_identity.get("root") != authority):
        raise OperationError("Plan source identity differs from source authority")
    source_root = absolute(authority.get("path", ""))
    declared_source_root = absolute(
        source_profile.get("roots", {}).get("source_root", "")
    )
    try:
        source_inside = os.path.commonpath(
            [source_root, os.path.normpath(declared_source_root)]
        ) == os.path.normpath(declared_source_root)
    except (TypeError, ValueError):
        source_inside = False
    if (source_profile.get("transport", {}).get("kind") != "local" or not source_inside):
        raise OperationError("source authority is outside the local source Site")
    expected_artifacts = []
    if plan_path:
        normalized_plan = absolute(plan_path)
        try:
            if os.path.commonpath([normalized_plan, source_root]) == source_root:
                expected_artifacts = [os.path.relpath(normalized_plan, source_root)]
        except ValueError:
            pass
    if plan.get("controller_artifacts") != expected_artifacts:
        raise OperationError("Plan source exclusions do not match the Plan artifact")
    input_path = absolute(
        goal["input"] if os.path.isabs(goal["input"])
        else os.path.join(project_root, goal["input"])
    )
    prepare = plan["steps"][1]
    launch = plan["steps"][2]
    preflight = plan["steps"][0]
    run_spec = prepare.get("request", {}).get("run_spec", {})
    run_identity = prepare.get("identity", {})
    compute = run_spec.get("compute", {})
    build_id = run_identity.get("parents", {}).get("build_id", "")
    input_sha256 = sha256_file(input_path)
    seed = {
        "case_uid": plan["case_uid"], "source_id": plan["source_id"],
        "input_sha256": input_sha256, "site_id": plan["site_id"],
        "executable": run_spec.get("executable"), "build_id": build_id,
        "compute": compute,
    }
    digest = canonical_hash(seed).split(":", 1)[1][:16]
    if plan["run_id"] != "run-" + digest or plan["operation_id"] != "op-" + digest:
        raise OperationError("derived Operation or run identity is invalid")
    roots = profile.get("roots", {})
    expected_run = os.path.join(roots["run_root"], plan["case_uid"], plan["run_id"])
    expected_stage = os.path.join(
        roots["staging_root"], plan["case_uid"], plan["operation_id"]
    )
    expected_receipts = [
        os.path.join(expected_stage, "receipts", "run-preflight.json"),
        os.path.join(expected_stage, "receipts", "run-prepare.json"),
        os.path.join(expected_stage, "receipts", "run-launch.json"),
    ]
    expected_allowed = [[expected_stage], [expected_stage, expected_run],
                        [expected_stage, expected_run]]
    for index, step in enumerate(plan["steps"]):
        if step.get("site_id") != plan["site_id"]:
            raise OperationError("Step Site differs from Operation Site")
        if step.get("receipt") != expected_receipts[index]:
            raise OperationError("derived Step receipt is invalid")
        if step.get("allowed_roots") != expected_allowed[index]:
            raise OperationError("derived Step allowed roots are invalid")
    executable = run_spec.get("executable", "")
    try:
        executable_inside = os.path.commonpath(
            [os.path.normpath(executable), os.path.normpath(roots["build_root"])]
        ) == os.path.normpath(roots["build_root"])
    except (TypeError, ValueError):
        executable_inside = False
    if not executable_inside:
        raise OperationError("Plan executable is outside the Site build_root")
    payloads = prepare.get("payloads", [])
    expected_input_target = os.path.join(expected_stage, "payloads", "input.toml")
    if payloads != [{"source": input_path, "target": expected_input_target,
                     "sha256": input_sha256}]:
        raise OperationError("derived input payload is invalid")
    expected_submit = os.path.join(expected_run, "run.sbatch")
    expected_manifest = os.path.join(expected_run, "run-manifest.json")
    expected_job_name = "entity-%s" % plan["operation_id"]
    if (preflight["request"].get("run_spec") != run_spec
            or preflight["request"].get("job_name") != expected_job_name
            or preflight["request"].get("staging_root") != expected_stage
            or prepare["request"].get("run_root") != expected_run
            or prepare["request"].get("staged_input") != expected_input_target
            or prepare["request"].get("submit_script") != expected_submit
            or prepare["request"].get("manifest") != expected_manifest
            or prepare["request"].get("staging_root") != expected_stage
            or launch["request"].get("run_root") != expected_run
            or launch["request"].get("submit_script") != expected_submit
            or launch["request"].get("job_name") != expected_job_name
            or launch["request"].get("submit_user") != compute.get("submit_user")):
        raise OperationError("derived run paths are invalid")
    if run_identity.get("id") != plan["run_id"] or run_identity.get("root") != {
            "site_id": plan["site_id"], "path": expected_run}:
        raise OperationError("derived run identity payload is invalid")
    if launch.get("identity") != run_identity:
        raise OperationError("prepare and launch run identities differ")
    expected_manifest_payload = {
        "schema_version": 3, "case_uid": plan["case_uid"], "run_id": plan["run_id"],
        "source_id": plan["source_id"], "build_id": build_id,
        "site_id": plan["site_id"], "input_sha256": input_sha256,
        "executable": run_spec.get("executable"), "compute": compute,
        "created_by_operation": plan["operation_id"],
    }
    if prepare["request"].get("manifest_payload") != expected_manifest_payload:
        raise OperationError("derived run manifest is invalid")


def _validate_asset_derivations(goal, plan, profile):
    """Recompute and check every derived value for build/data Plans."""
    case_spec = plan["case"]
    if set(case_spec) != {"case_uid", "case_id", "project_root", "source", "current"}:
        raise OperationError("Plan Case keys differ from schema")
    if case_spec["case_uid"] != plan["case_uid"]:
        raise OperationError("Plan Case does not match the project")
    roots = profile.get("roots", {})
    staging = os.path.join(
        roots.get("staging_root", ""), plan["case_uid"], plan["operation_id"])
    step = plan["steps"][0]
    kind = plan["goal_kind"]
    if kind == "build":
        seed = {"case_uid": plan["case_uid"],
                "checkpoint_sha256": plan["checkpoint_sha256"],
                "executable": plan["executable"], "site_id": plan["site_id"]}
        digest = canonical_hash(seed).split(":", 1)[1][:16]
        if (plan["build_id"] != "build-" + digest
                or plan["operation_id"] != "op-" + digest):
            raise OperationError("derived Operation or build identity is invalid")
        checkpoint_path = absolute(plan["checkpoint"])
        if (not os.path.isfile(checkpoint_path)
                or sha256_file(checkpoint_path) != plan["checkpoint_sha256"]):
            raise OperationError("build checkpoint changed after planning; create a new plan")
        try:
            with open(checkpoint_path, "r") as handle:
                checkpoint = json.load(handle)
        except (IOError, OSError, ValueError) as exc:
            raise OperationError("cannot read build checkpoint: %s" % exc)
        require_verified_checkpoint(checkpoint)
        build_root = os.path.normpath(roots.get("build_root", ""))
        try:
            inside = os.path.commonpath(
                [os.path.normpath(plan["executable"]), build_root]) == build_root
        except ValueError:
            inside = False
        if not inside:
            raise OperationError("Plan executable is outside the Site build_root")
        expected_receipt = os.path.join(staging, "receipts", "build-register.json")
        expected_allowed = [staging, roots.get("build_root", "")]
        if step["request"].get("executable") != plan["executable"]:
            raise OperationError("derived build executable is invalid")
    else:
        seed = {"case_uid": plan["case_uid"], "run_id": plan["run_id"]}
        digest = canonical_hash(seed).split(":", 1)[1][:16]
        if (plan["data_id"] != "data-" + digest
                or plan["operation_id"] != "op-" + digest):
            raise OperationError("derived Operation or data identity is invalid")
        run_root = step["request"].get("run_root", "")
        manifest = step["request"].get("manifest", "")
        if (not run_root
                or manifest != os.path.join(run_root, "data-inventory.json")):
            raise OperationError("derived data inventory paths are invalid")
        expected_receipt = os.path.join(staging, "receipts", "data-inventory.json")
        expected_allowed = [staging, run_root]
    if (step.get("site_id") != plan["site_id"]
            or step.get("receipt") != expected_receipt
            or step.get("allowed_roots") != expected_allowed
            or step.get("identity", {}).get("id") != plan.get(
                "build_id" if kind == "build" else "data_id")):
        raise OperationError("derived Step is invalid")


def _ensure_case(store, plan, actor):
    try:
        case = store.get_case(plan["case_uid"])
    except StoreError:
        if not plan.get("create_case"):
            raise
        case_spec = plan["case"]
        with store.transaction() as connection:
            store.upsert_case(
                case_spec["case_uid"], case_spec["case_id"], case_spec["project_root"],
                case_spec["source"], case_spec["current"], {}, connection=connection,
            )
            identity = plan.get("source_identity")
            if identity:
                store.add_identity(
                    plan["case_uid"], "source", identity["id"], identity, True, connection,
                )
            store._event(connection, plan["case_uid"], None, "case.created", {}, actor)
        case = store.get_case(plan["case_uid"])
    return case


def _identity_projection(step, effect):
    identity = dict(step.get("identity") or {})
    if not identity:
        return []
    if step["kind"] in {"run.prepare.v2", "run.launch.v2"}:
        dimension = "run"
        if step["kind"] == "run.prepare.v2":
            identity["status"] = "prepared"
        else:
            identity["status"] = "submitted"
            identity["scheduler"] = effect
    elif step["kind"] == "build.register.v1":
        dimension = "build"
        identity["status"] = "verified"
        identity["outputs"] = [{
            "kind": "file",
            "locator": {"site_id": step["site_id"],
                        "path": step["request"]["executable"]},
        }]
    elif step["kind"] == "data.inventory.v1":
        dimension = "data"
        identity["status"] = "inventoried"
        identity["files"] = effect.get("files", 0)
    else:
        return []
    return [{"dimension": dimension, "identity_id": identity["id"],
             "payload": identity, "current": True}]


def apply_plan(store, goal, plan, actor, claim_ttl=90, plan_path=None, refresh=False):
    goal = validate_goal(goal)
    plan = validate_plan(plan)
    if canonical_hash(goal) != plan["goal_hash"]:
        raise OperationError("GoalSpec does not match Operation Plan")
    profile = store.get_site(plan["site_id"])
    if canonical_hash(profile) != plan["site_profile_hash"]:
        raise OperationError("Site profile changed after planning; create a new plan")
    kind = plan.get("goal_kind") or "run"
    if kind == "run":
        source_profile = store.get_site(plan["source_identity"]["root"]["site_id"])
        if canonical_hash(source_profile) != plan["source_site_profile_hash"]:
            raise OperationError("source Site profile changed after planning; create a new plan")
        _validate_derivations(goal, plan, profile, source_profile, plan_path)
        _verify_source(plan)
    else:
        _validate_asset_derivations(goal, plan, profile)
    _ensure_case(store, plan, actor)
    if kind == "run":
        source_identity = plan["source_identity"]
        store.add_identity(
            plan["case_uid"], "source", source_identity["id"], source_identity, True
        )
    operation = store.create_operation(plan["case_uid"], goal, plan, actor)
    if operation["status"] == "completed":
        if not refresh:
            return operation
        if kind != "data":
            raise OperationError(
                "--refresh only re-executes data Goal plans (inventory refresh "
                "after run artifacts changed); create a new plan for other Goals"
            )
        store.refresh_operation(operation["operation_id"], actor)
        operation = store.get_operation(operation["operation_id"])
    if operation["status"] not in {"pending", "running"}:
        store.reopen_operation(operation["operation_id"], actor)
    token = store.claim_operation(operation["operation_id"], actor, claim_ttl)
    if not token:
        return store.get_operation(operation["operation_id"])
    heartbeat = ClaimHeartbeat(store, operation["operation_id"], token, claim_ttl)
    heartbeat.start()
    client = ExecutorClient(profile)
    active_index = -1
    try:
        for index, step in enumerate(plan["steps"]):
            active_index = index
            heartbeat.check()
            current_operation = store.get_operation(operation["operation_id"])
            if current_operation["steps"][index]["status"] == "committed":
                continue
            store.update_step(
                operation["operation_id"], index, "intent_written", actor=actor
            )
            for payload in step.get("payloads", []):
                client.stage_payload(payload)
            envelope = {
                "schema_version": 1,
                "operation_id": operation["operation_id"],
                "plan_hash": plan["plan_hash"],
                "step_index": index,
                "step_id": step["step_id"],
                "kind": step["kind"],
                "site_id": step["site_id"],
                "receipt": step["receipt"],
                "allowed_roots": step["allowed_roots"],
                "request": step["request"],
            }
            executed = client.invoke("execute", envelope)
            heartbeat.check()
            verified = client.invoke("verify", envelope)
            receipt = verified.get("receipt", {})
            for key in ["operation_id", "plan_hash", "step_index", "step_id", "kind"]:
                if receipt.get(key) != envelope.get(key):
                    raise OperationError("verified receipt identity differs from Step")
            case = store.get_case(plan["case_uid"])
            current = dict(case["current"])
            identities = _identity_projection(step, verified.get("effect", {}))
            for item in identities:
                dimension = item["dimension"]
                readiness = dict(current.get("readiness", {}))
                if dimension == "run":
                    current["source_id"] = plan["source_id"]
                    current["run_id"] = plan["run_id"]
                    current["active_run"] = step["identity"]["root"]
                    readiness["run"] = ("ready" if step["kind"] == "run.prepare.v2"
                                        else "submitted")
                else:
                    current[dimension + "_id"] = item["identity_id"]
                    readiness[dimension] = item["payload"].get("status", "ready")
                current["readiness"] = readiness
            store.commit_step(
                operation["operation_id"], index, verified.get("effect", {}),
                verified.get("outputs", []), identities, current, actor,
            )
        result = {
            "site_id": plan["site_id"],
            "completed_at": now_utc(), "steps": len(plan["steps"]),
        }
        for key in ["run_id", "build_id", "data_id"]:
            if plan.get(key):
                result[key] = plan[key]
        store.finish_operation(operation["operation_id"], "completed", result, actor)
        return store.get_operation(operation["operation_id"])
    except Exception as exc:
        error = {"message": str(exc), "observed_at": now_utc()}
        if active_index >= 0:
            try:
                store.update_step(
                    operation["operation_id"], active_index, "anomaly",
                    error=error, actor=actor,
                )
            except Exception:
                pass
        # Never leak an active Operation: finish it so the Case is released
        # and a new Plan can proceed; re-applying this Plan resumes it.
        try:
            store.finish_operation(operation["operation_id"], "anomaly", error, actor)
        except Exception:
            pass
        raise
    finally:
        heartbeat.stop()
        store.release_claim(operation["operation_id"], token, actor)


def _same_path(left, right):
    """Path comparison that also works for remote paths on ssh Sites."""
    try:
        return os.path.realpath(left) == os.path.realpath(right)
    except OSError:
        return left == right


def _reconcile_job(profile, scheduler, job_id, live_state, observed_at):
    """Classify divergence between the recorded job and scheduler reality.

    Returns (divergences, extra_remote_calls). Only Slurm facts are used;
    every classification is reproducible from the same scheduler answers.
    """
    divergences = []
    remote_calls = 0
    ssh = profile.get("transport", {}).get("kind") == "ssh"
    if live_state == "NOT_FOUND":
        try:
            code, stdout, stderr = run_on_site(
                profile, ["sacct", "-n", "-X", "-j", job_id, "--format=State"]
            )
        except OSError as exc:
            code, stdout, stderr = 127, "", str(exc)
        if ssh:
            remote_calls += 1
        terminal = ""
        if code == 0 and stdout.strip():
            terminal = stdout.strip().splitlines()[0].split()[0].upper()
        if terminal:
            divergences.append({
                "kind": "state_mismatch", "job_id": job_id,
                "recorded": "submitted", "observed": terminal,
                "detail": "recorded job reached terminal scheduler state %s "
                          "without the router observing it" % terminal,
                "observed_at": observed_at,
            })
        else:
            detail = "recorded job is absent from squeue"
            if code == 0:
                detail += " and sacct has no record of it"
            else:
                detail += "; sacct unavailable (%s)" % (
                    stderr.strip() or stdout.strip() or "exit %d" % code)
            divergences.append({
                "kind": "job_gone", "job_id": job_id, "confirmed": code == 0,
                "detail": detail, "observed_at": observed_at,
            })
    run_root = scheduler.get("run_root", "")
    submit_user = scheduler.get("submit_user", "")
    if run_root and submit_user:
        try:
            code, stdout, stderr = run_on_site(
                profile, ["squeue", "-h", "--user", submit_user, "--format", "%i|%Z"]
            )
        except OSError:
            code, stdout = 127, ""
        if ssh:
            remote_calls += 1
        if code == 0:
            for line in stdout.splitlines():
                fields = line.strip().split("|", 1)
                if len(fields) != 2 or not fields[0] or fields[0] == job_id:
                    continue
                if _same_path(fields[1], run_root):
                    divergences.append({
                        "kind": "untracked_job", "job_id": fields[0],
                        "run_root": fields[1],
                        "detail": "scheduler job %s runs in the Case run root "
                                  "but is not the recorded job %s"
                                  % (fields[0], job_id),
                        "observed_at": observed_at,
                    })
    return divergences, remote_calls


def status_for_project(store, project_root, live=False):
    case = store.resolve_project(project_root)
    current = case["current"]
    run_id = current.get("run_id", "")
    run_identity = None
    for item in case.get("identities", {}).get("run", {}).get("items", []):
        if item.get("id") == run_id or item.get("identity_id") == run_id:
            run_identity = item
            break
    result = {
        "schema_version": 1, "kind": "entity-router.status", "ok": True,
        "state_mutated": False, "remote_calls": 0,
        "project_root": case.get("project_root"), "case_uid": case["case_uid"],
        "active_operation": case.get("active_operation"), "current": current,
        "run": run_identity, "live": None, "divergences": [],
    }
    if not live or not run_identity:
        return result
    scheduler = run_identity.get("scheduler", {})
    job_id = scheduler.get("job_id", "")
    if not job_id:
        return result
    profile = store.get_site(run_identity["site_id"])
    if profile.get("scheduler", {}).get("kind") != "slurm":
        raise OperationError("live status currently supports Slurm only")
    ssh = profile.get("transport", {}).get("kind") == "ssh"
    code, stdout, stderr = run_on_site(
        profile, ["squeue", "-h", "-j", job_id, "-o", "%T"]
    )
    if ssh:
        result["remote_calls"] = 1
    if code != 0:
        detail = (stderr.strip() or stdout.strip() or "exit %d" % code)
        result["live"] = {
            "scheduler": "slurm", "job_id": job_id, "state": "UNKNOWN",
            "warning": "scheduler query failed (%s); showing cached controller "
                       "state" % detail,
            "observed_at": now_utc(),
        }
        return result
    state = stdout.strip().splitlines()[0] if stdout.strip() else "NOT_FOUND"
    observed_at = now_utc()
    result["live"] = {"scheduler": "slurm", "job_id": job_id,
                      "state": state, "observed_at": observed_at}
    divergences, extra_calls = _reconcile_job(
        profile, scheduler, job_id, state, observed_at
    )
    result["divergences"] = divergences
    result["remote_calls"] += extra_calls
    return result
