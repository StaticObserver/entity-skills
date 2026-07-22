#!/usr/bin/env python3

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import shlex


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_router_operation import ExecutorClient, OperationError, apply_plan, status_for_project
from entity_router_planner import PlanError, plan_goal, validate_goal
from entity_router_common import atomic_write_json
import entity_router_common
from entity_router_store import OperationStore, canonical_hash


class RouterV5Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-router-v5-")
        self.home = os.path.join(self.temp, "controller")
        self.project = os.path.join(self.temp, "project")
        self.run_root = os.path.join(self.temp, "runs")
        self.staging_root = os.path.join(self.temp, "staging")
        self.bin_root = os.path.join(self.temp, "bin")
        for path in [self.project, self.run_root, self.staging_root, self.bin_root]:
            os.makedirs(path)
        self.input = os.path.join(self.project, "input.toml")
        self.build_root = os.path.join(self.temp, "build")
        os.makedirs(self.build_root)
        self.executable = os.path.join(self.build_root, "entity.xc")
        with open(self.input, "w") as handle:
            handle.write("[simulation]\nsteps = 2\n")
        self._confirm_input()
        with open(os.path.join(self.project, "pgen.hpp"), "w") as handle:
            handle.write("// source\n")
        with open(self.executable, "w") as handle:
            handle.write("binary-placeholder\n")
        os.chmod(self.executable, 0o755)
        self.record = os.path.join(self.temp, "slurm.json")
        self.count = os.path.join(self.temp, "submits.txt")
        self._write_fake_slurm()
        self.environment = mock.patch.dict(os.environ, {
            "PATH": self.bin_root + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_SLURM_RECORD": self.record,
            "FAKE_SUBMIT_COUNT": self.count,
        })
        self.environment.start()
        self.store = OperationStore(self.home)
        self.profile = {
            "schema_version": 1, "site_id": "local-slurm", "display_name": "local",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "slurm"},
            "roots": {"source_root": self.temp, "build_root": self.build_root,
                      "run_root": self.run_root,
                      "staging_root": self.staging_root},
            "policy": {"default_cpus_per_gpu": 2, "default_partition": "test"},
            "shared_mappings": [],
        }
        self.store.upsert_site(self.profile)
        self.goal = {
            "schema_version": 1, "kind": "run", "input": "input.toml",
            "site": "local-slurm", "executable": self.executable,
            "compute": {"gpus": 1, "walltime": "00:10:00", "precision": "double",
                        "submit_user": "tester"},
        }
        self.plan_file = os.path.join(self.project, "operation-plan.json")

    def tearDown(self):
        self.environment.stop()
        shutil.rmtree(self.temp)

    def _write_executable(self, name, text):
        path = os.path.join(self.bin_root, name)
        with open(path, "w") as handle:
            handle.write("#!%s\n%s" % (sys.executable, text))
        os.chmod(path, 0o755)

    def _write_fake_slurm(self):
        self._write_executable("sbatch", """import datetime,json,os,sys
args=sys.argv[1:]
if '--test-only' in args:
    print('accepted')
    raise SystemExit(0)
def value(flag):
    return args[args.index(flag)+1]
count_path=os.environ['FAKE_SUBMIT_COUNT']
count=int(open(count_path).read()) if os.path.isfile(count_path) else 0
open(count_path,'w').write(str(count+1))
record={'job_id':'42','job_name':value('--job-name'),'user':'tester',
        'submitted_at':datetime.datetime.now().replace(microsecond=0).isoformat(),
        'state':'RUNNING','run_root':value('--chdir'),'comment':value('--comment')}
json.dump(record,open(os.environ['FAKE_SLURM_RECORD'],'w'))
print('42')
""")
        self._write_executable("squeue", """import json,os,sys
path=os.environ['FAKE_SLURM_RECORD']
if not os.path.isfile(path):
    raise SystemExit(0)
r=json.load(open(path))
if '--format' in sys.argv:
    print('{job_id}|{job_name}|{user}|{submitted_at}|{state}|{run_root}|{comment}'.format(**r))
else:
    print(r['state'])
""")

    def _confirm_input(self, path=None, sha256=None):
        import hashlib
        path = path or self.input
        if sha256 is None:
            with open(path, "rb") as handle:
                sha256 = hashlib.sha256(handle.read()).hexdigest()
        record = {
            "schema_version": 1,
            "kind": "entity-pgen.simulation-confirmation",
            "input_sha256": sha256,
            "card": {},
            "confirmed_by": "test",
            "confirmed_at": "2026-07-22T00:00:00",
            "defaults": False,
        }
        with open(path + ".decisions.json", "w") as handle:
            json.dump(record, handle)

    def make_plan(self):
        envelope = plan_goal(self.store, self.project, self.goal, [self.plan_file])
        with open(self.plan_file, "w") as handle:
            json.dump(envelope, handle)
        return envelope

    def submit_count(self):
        if not os.path.isfile(self.count):
            return 0
        with open(self.count) as handle:
            return int(handle.read())

    def cli(self, *args):
        process = __import__("subprocess").Popen(
            [sys.executable, ENTITYCTL, "--router-home", self.home] + list(args),
            stdout=__import__("subprocess").PIPE,
            stderr=__import__("subprocess").PIPE,
            universal_newlines=True,
        )
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), stderr)
        return process.returncode, json.loads(stdout)

    def test_site_add_and_list_via_cli(self):
        profile = dict(self.profile, site_id="cli-site")
        profile_path = os.path.join(self.temp, "cli-site.json")
        atomic_write_json(profile_path, profile)
        code, payload = self.cli("site", "add", "--profile", profile_path)
        self.assertEqual(code, 0)
        self.assertEqual(payload["site_id"], "cli-site")

        code, listing = self.cli("site", "list")
        self.assertEqual(code, 0)
        site_ids = [site["site_id"] for site in listing["sites"]]
        self.assertIn("cli-site", site_ids)
        self.assertIn("local-slurm", site_ids)

        goal = dict(self.goal, site="cli-site")
        goal_path = os.path.join(self.temp, "goal.json")
        atomic_write_json(goal_path, goal)
        code, planned = self.cli(
            "plan", "--project-root", self.project,
            "--goal", goal_path, "--output", self.plan_file,
        )
        self.assertEqual(code, 0)
        self.assertEqual(planned["plan"]["site_id"], "cli-site")

    def test_site_add_rejects_invalid_profile(self):
        profile = dict(self.profile, site_id="bad site!")
        profile_path = os.path.join(self.temp, "bad-site.json")
        atomic_write_json(profile_path, profile)
        code, payload = self.cli("site", "add", "--profile", profile_path)
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["state_mutated"])

    def test_goal_rejects_controller_fields_and_reports_decisions(self):
        invalid = dict(self.goal, operation_id="chosen-by-user")
        with self.assertRaises(PlanError):
            validate_goal(invalid)
        incomplete = {"schema_version": 1, "kind": "run"}
        with self.assertRaises(PlanError) as caught:
            validate_goal(incomplete)
        self.assertEqual(caught.exception.status, "needs_decision")
        self.assertTrue(caught.exception.decisions)

    def test_site_policy_gaps_become_plan_decisions(self):
        profile = dict(self.profile)
        profile["policy"] = {"default_cpus_per_gpu": 2}
        self.store.upsert_site(profile)
        with self.assertRaises(PlanError) as partition:
            plan_goal(self.store, self.project, self.goal, [self.plan_file])
        self.assertEqual(partition.exception.status, "needs_decision")
        self.assertEqual(partition.exception.decisions[0]["field"], "compute.partition")

        remote = dict(profile, site_id="ssh-no-user")
        remote["transport"] = {"kind": "ssh", "ssh_alias": "fake"}
        remote["policy"] = {"default_cpus_per_gpu": 2, "default_partition": "dgx2"}
        self.store.upsert_site(remote)
        goal = dict(self.goal, site="ssh-no-user")
        goal["compute"] = dict(goal["compute"])
        goal["compute"].pop("submit_user")
        with mock.patch("entity_router_planner.run_on_site",
                        side_effect=lambda unused, argv: entity_router_common.run_command(argv)):
            with self.assertRaises(PlanError) as submit_user:
                plan_goal(self.store, self.project, goal, [self.plan_file])
        self.assertEqual(submit_user.exception.status, "needs_decision")
        self.assertEqual(submit_user.exception.decisions[0]["field"], "compute.submit_user")

    def test_plan_hash_is_stable_and_plan_artifact_is_not_source(self):
        first = self.make_plan()
        second = plan_goal(self.store, self.project, self.goal, [self.plan_file])
        self.assertEqual(first["plan"]["plan_hash"], second["plan"]["plan_hash"])
        self.assertEqual(first["plan"]["controller_artifacts"], ["operation-plan.json"])

    def test_project_root_and_source_authority_are_distinct(self):
        source_root = os.path.join(self.project, "entity-source")
        os.makedirs(source_root)
        with open(os.path.join(source_root, "pgen.hpp"), "w") as handle:
            handle.write("// authoritative source\n")
        case_uid = "case-distinct-roots"
        self.store.upsert_case(
            case_uid, "distinct-roots", self.project,
            {"authority": {"site_id": "local-slurm", "path": source_root},
             "transfer_policy": "snapshot"},
            {"source_id": "", "build_id": "", "run_id": "", "active_run": None,
             "data_id": "", "analysis_id": ""},
        )
        first = plan_goal(self.store, self.project, self.goal, [self.plan_file])
        self.assertEqual(first["plan"]["source_identity"]["root"]["path"], source_root)
        self.assertEqual(first["plan"]["controller_artifacts"], [])
        with open(os.path.join(self.project, "project-note.md"), "w") as handle:
            handle.write("not source\n")
        second = plan_goal(self.store, self.project, self.goal, [self.plan_file])
        self.assertEqual(first["plan"]["plan_hash"], second["plan"]["plan_hash"])

    def test_apply_is_idempotent_and_status_defaults_to_controller_only(self):
        envelope = self.make_plan()
        actor = {"run_id": "test", "provider": "unittest"}
        first = apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                           plan_path=self.plan_file)
        second = apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                            plan_path=self.plan_file)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        self.assertEqual(self.submit_count(), 1)
        status = status_for_project(self.store, self.project)
        self.assertEqual(status["remote_calls"], 0)
        self.assertEqual(status["current"]["run_id"], envelope["plan"]["run_id"])
        self.assertEqual(status["run"]["scheduler"]["job_id"], "42")

    def test_public_cli_is_plan_apply_status(self):
        goal_path = os.path.join(self.project, "goal.json")
        with open(goal_path, "w") as handle:
            json.dump(self.goal, handle)
        code, planned = self.cli(
            "plan", "--project-root", self.project, "--goal", goal_path,
            "--output", self.plan_file,
        )
        self.assertEqual(code, 0, planned)
        self.assertTrue(os.path.isfile(self.plan_file))
        code, applied = self.cli("--actor-run-id", "cli-test", "apply", "--plan", self.plan_file)
        self.assertEqual(code, 0, applied)
        code, status = self.cli("status", "--project-root", self.project)
        self.assertEqual(code, 0, status)
        self.assertEqual(status["current"]["run_id"], planned["plan"]["run_id"])
        self.assertEqual(self.submit_count(), 1)

    def _assert_recovers_after_effect(self, kind):
        envelope = self.make_plan()
        actor = {"run_id": "crash-test", "provider": "unittest"}
        original = ExecutorClient.invoke
        crashed = {"value": False}

        def crash_after_launch(client, command, request):
            result = original(client, command, request)
            if not crashed["value"] and command == "execute" and request["kind"] == kind:
                crashed["value"] = True
                raise SystemExit("simulated controller crash")
            return result

        with mock.patch.object(ExecutorClient, "invoke", crash_after_launch):
            with self.assertRaises(SystemExit):
                apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                           plan_path=self.plan_file)
        self.assertEqual(self.submit_count(), 1 if kind == "run.launch.v2" else 0)
        recovered = apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                               plan_path=self.plan_file)
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(self.submit_count(), 1)

    def test_reapply_recovers_preflight_effect_not_committed(self):
        self._assert_recovers_after_effect("run.preflight.v1")

    def test_reapply_recovers_prepare_effect_not_committed(self):
        self._assert_recovers_after_effect("run.prepare.v2")

    def test_reapply_recovers_launch_effect_not_committed(self):
        self._assert_recovers_after_effect("run.launch.v2")

    def test_reapply_recovers_transient_controller_commit_failure(self):
        envelope = self.make_plan()
        actor = {"run_id": "controller-failure", "provider": "unittest"}
        original = self.store.commit_step
        failed = {"value": False}

        def fail_once(*args, **kwargs):
            if not failed["value"] and args[1] == 2:
                failed["value"] = True
                raise RuntimeError("transient sqlite failure")
            return original(*args, **kwargs)

        with mock.patch.object(self.store, "commit_step", side_effect=fail_once):
            with self.assertRaises(RuntimeError):
                apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                           plan_path=self.plan_file)
        self.assertEqual(self.store.get_operation(envelope["plan"]["operation_id"])["status"],
                         "anomaly")
        recovered = apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                               plan_path=self.plan_file)
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(self.submit_count(), 1)

    def test_apply_rejects_source_drift(self):
        envelope = self.make_plan()
        with open(os.path.join(self.project, "pgen.hpp"), "a") as handle:
            handle.write("// changed\n")
        with self.assertRaises(OperationError):
            apply_plan(self.store, envelope["goal"], envelope["plan"], {"run_id": "test"},
                       plan_path=self.plan_file)

    def test_apply_rejects_rehashed_plan_with_widened_write_root(self):
        from entity_router_planner import _stable_plan
        envelope = self.make_plan()
        plan = envelope["plan"]
        plan["steps"][1]["allowed_roots"].append(self.temp)
        unsigned = dict(plan)
        unsigned.pop("plan_hash")
        plan["plan_hash"] = canonical_hash(_stable_plan(unsigned))
        with self.assertRaises(OperationError):
            apply_plan(self.store, envelope["goal"], plan, {"run_id": "tamper"},
                       plan_path=self.plan_file)
        self.assertEqual(self.submit_count(), 0)

    def test_store_step_commit_rolls_back_as_one_transaction(self):
        envelope = self.make_plan()
        plan = envelope["plan"]
        actor = {"run_id": "test"}
        from entity_router_operation import _ensure_case
        _ensure_case(self.store, plan, actor)
        operation = self.store.create_operation(plan["case_uid"], envelope["goal"], plan, actor)
        before = self.store.get_case(plan["case_uid"])["current"]
        with self.assertRaises(Exception):
            self.store.commit_step(
                operation["operation_id"], 0, {}, [],
                [{"dimension": "invalid", "identity_id": "bad", "payload": {}}],
                dict(before, run_id="must-not-commit"), actor,
            )
        after = self.store.get_case(plan["case_uid"])["current"]
        self.assertEqual(before, after)
        self.assertEqual(self.store.get_operation(operation["operation_id"])["steps"][0]["status"],
                         "pending")

    def test_ssh_uses_the_same_steps_and_live_status_reconciles_remotely(self):
        local_plan = self.make_plan()["plan"]
        remote_profile = dict(self.profile)
        remote_profile["site_id"] = "fake-ssh"
        remote_profile["transport"] = {"kind": "ssh", "ssh_alias": "fake"}
        self.store.upsert_site(remote_profile)
        remote_goal = dict(self.goal, site="fake-ssh")

        def local_site(unused_profile, argv):
            return entity_router_common.run_command(argv)

        def scp_or_local(argv, cwd=None):
            if argv and argv[0] == "scp":
                source = argv[-2]
                encoded = argv[-1].split(":", 1)[1]
                target = shlex.split(encoded)[0]
                parent = os.path.dirname(target)
                if not os.path.isdir(parent):
                    os.makedirs(parent)
                shutil.copy2(source, target)
                return 0, "", ""
            return entity_router_common.run_command(argv, cwd)

        with mock.patch("entity_router_planner.run_on_site", local_site):
            remote_envelope = plan_goal(
                self.store, self.project, remote_goal,
                [os.path.join(self.project, "remote-plan.json")],
            )
        remote_plan = remote_envelope["plan"]
        self.assertEqual([step["kind"] for step in local_plan["steps"]],
                         [step["kind"] for step in remote_plan["steps"]])
        self.assertEqual([set(step["request"]) for step in local_plan["steps"]],
                         [set(step["request"]) for step in remote_plan["steps"]])
        with mock.patch("entity_router_operation.run_on_site", side_effect=local_site) as remote_calls:
            with mock.patch("entity_router_operation.run_command", side_effect=scp_or_local):
                applied = apply_plan(
                    self.store, remote_envelope["goal"], remote_plan,
                    {"run_id": "ssh-test"},
                    plan_path=os.path.join(self.project, "remote-plan.json"),
                )
                calls_before_status = remote_calls.call_count
                status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(applied["status"], "completed")
        # live status = squeue job query + untracked-job scan (job is active,
        # so no sacct fallback); reconciliation stays read-only and bounded
        self.assertEqual(status["remote_calls"], 2)
        self.assertEqual(remote_calls.call_count - calls_before_status, 2)
        self.assertEqual(status["divergences"], [])

    def test_sbatch_invokes_entity_with_dash_input(self):
        from entity_router_executor import render_sbatch
        script = render_sbatch({
            "executable": self.executable,
            "input_name": "input.toml",
            "compute": {"nodes": 1, "tasks": 1, "gpus": 1, "cpus_per_task": 2,
                        "walltime": "00:10:00", "partition": "test", "qos": "",
                        "submit_user": "tester", "precision": "double"},
        })
        self.assertIn("srun %s -input input.toml" % self.executable, script)
        self.assertNotIn("srun %s input.toml" % self.executable, script)

    def _fail_first_preflight(self):
        original = ExecutorClient.invoke
        def boom(client, command, request):
            if command == "execute" and request["kind"] == "run.preflight.v1":
                raise OperationError("simulated preflight failure")
            return original(client, command, request)
        return mock.patch.object(ExecutorClient, "invoke", boom)

    def test_failed_apply_releases_case_and_reapply_resumes(self):
        envelope = self.make_plan()
        actor = {"run_id": "fail-test", "provider": "unittest"}
        with self._fail_first_preflight():
            with self.assertRaises(OperationError):
                apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                           plan_path=self.plan_file)
        operation = self.store.get_operation(envelope["plan"]["operation_id"])
        self.assertEqual(operation["status"], "anomaly")
        self.assertIsNone(
            self.store.get_case(envelope["plan"]["case_uid"])["active_operation"])
        recovered = apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                               plan_path=self.plan_file)
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(self.submit_count(), 1)

    def test_failed_apply_allows_a_new_plan(self):
        envelope = self.make_plan()
        actor = {"run_id": "fail-new-plan", "provider": "unittest"}
        with self._fail_first_preflight():
            with self.assertRaises(OperationError):
                apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                           plan_path=self.plan_file)
        new_goal = dict(self.goal)
        new_goal["compute"] = dict(self.goal["compute"], walltime="00:20:00")
        second = plan_goal(self.store, self.project, new_goal, [self.plan_file])
        with open(self.plan_file, "w") as handle:
            json.dump(second, handle)
        applied = apply_plan(self.store, second["goal"], second["plan"], actor,
                             plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")
        self.assertEqual(self.submit_count(), 1)

    def test_operation_cancel_releases_case_via_cli(self):
        envelope = self.make_plan()
        actor = {"run_id": "cancel-test", "provider": "unittest"}
        from entity_router_operation import _ensure_case
        _ensure_case(self.store, envelope["plan"], actor)
        operation = self.store.create_operation(
            envelope["plan"]["case_uid"], envelope["goal"], envelope["plan"], actor)
        code, payload = self.cli("--actor-run-id", "cancel-test",
                                 "operation", "cancel", operation["operation_id"])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["operation_status"], "cancelled")
        self.assertIsNone(
            self.store.get_case(envelope["plan"]["case_uid"])["active_operation"])
        new_goal = dict(self.goal)
        new_goal["compute"] = dict(self.goal["compute"], walltime="00:20:00")
        second = plan_goal(self.store, self.project, new_goal, [self.plan_file])
        with open(self.plan_file, "w") as handle:
            json.dump(second, handle)
        applied = apply_plan(self.store, second["goal"], second["plan"], actor,
                             plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")

    def test_missing_store_error_points_to_site_add(self):
        empty_home = os.path.join(self.temp, "empty-controller")
        with self.assertRaises(Exception) as caught:
            OperationStore(empty_home, create=False)
        self.assertIn("site add", str(caught.exception))
        self.assertNotIn("migrate", str(caught.exception))

    def test_doctor_reports_bundle_version_and_store_schema(self):
        fake_home = os.path.join(self.temp, "no-clients")
        os.makedirs(fake_home)
        with mock.patch.dict(os.environ, {"HOME": fake_home}):
            code, payload = self.cli("doctor")
        self.assertEqual(code, 0, payload)
        version_file = os.path.join(ROOT, "skills", "entity-router", "VERSION")
        with open(version_file, "r") as handle:
            self.assertEqual(payload["runtime_bundle"]["version"], handle.read().strip())
        self.assertEqual(payload["controller"]["store_schema_version"], 1)
        self.assertEqual(payload["failures"], [])

    def test_doctor_fails_on_client_bundle_drift(self):
        fake_home = os.path.join(self.temp, "drifted-clients")
        drifted = os.path.join(fake_home, ".claude", "skills", "entity-router")
        os.makedirs(drifted)
        with open(os.path.join(drifted, "VERSION"), "w") as handle:
            handle.write("0.0.0-drifted\n")
        with mock.patch.dict(os.environ, {"HOME": fake_home}):
            code, payload = self.cli("doctor")
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("drifted" in failure for failure in payload["failures"]))

    def test_doctor_warns_on_leaked_active_operation(self):
        envelope = self.make_plan()
        actor = {"run_id": "leak-test", "provider": "unittest"}
        from entity_router_operation import _ensure_case
        _ensure_case(self.store, envelope["plan"], actor)
        operation = self.store.create_operation(
            envelope["plan"]["case_uid"], envelope["goal"], envelope["plan"], actor)
        fake_home = os.path.join(self.temp, "leak-clients")
        os.makedirs(fake_home)
        with mock.patch.dict(os.environ, {"HOME": fake_home}):
            code, payload = self.cli("doctor")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["failures"], [])
        hint = "operation cancel %s" % operation["operation_id"]
        self.assertTrue(any(hint in warning for warning in payload["warnings"]),
                        payload["warnings"])

    def test_store_migrate_shell_reports_current_schema(self):
        code, payload = self.cli("store", "migrate")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["store_schema_version"], 1)
        self.assertFalse(payload["state_mutated"])
        empty_home = os.path.join(self.temp, "empty-controller")
        process = __import__("subprocess").Popen(
            [sys.executable, ENTITYCTL, "--router-home", empty_home,
             "store", "migrate"],
            stdout=__import__("subprocess").PIPE,
            stderr=__import__("subprocess").PIPE, universal_newlines=True,
        )
        stdout, _ = process.communicate()
        self.assertEqual(process.returncode, 2)
        self.assertIn("nothing to migrate", stdout)

    def test_live_status_degrades_when_scheduler_query_fails(self):
        envelope = self.make_plan()
        applied = apply_plan(self.store, envelope["goal"], envelope["plan"],
                             {"run_id": "live-test"}, plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")
        self._write_executable("squeue", """import sys
sys.stderr.write('slurm_load_jobs error: Invalid job id\\n')
raise SystemExit(1)
""")
        status = status_for_project(self.store, self.project, live=True)
        self.assertTrue(status["ok"])
        self.assertEqual(status["live"]["state"], "UNKNOWN")
        self.assertIn("warning", status["live"])
        self.assertEqual(status["current"]["run_id"], envelope["plan"]["run_id"])

    def test_plan_requires_simulation_confirmation(self):
        os.unlink(self.input + ".decisions.json")
        with self.assertRaises(PlanError) as caught:
            plan_goal(self.store, self.project, self.goal, [self.plan_file])
        self.assertEqual(caught.exception.status, "needs_decision")
        self.assertIn("confirm", caught.exception.decisions[0]["question"])

    def test_plan_rejects_stale_simulation_confirmation(self):
        self._confirm_input(sha256="0" * 64)
        with self.assertRaises(PlanError) as caught:
            plan_goal(self.store, self.project, self.goal, [self.plan_file])
        self.assertEqual(caught.exception.status, "needs_decision")
        self._confirm_input()
        envelope = plan_goal(self.store, self.project, self.goal, [self.plan_file])
        self.assertEqual(
            envelope["summary"]["simulation_confirmation"]["confirmed_by"], "test")

    def test_site_discover_enumerates_partitions_and_qos(self):
        self._write_executable("sinfo", """print('debug*|up|00:30:00|gpu:4|8|64')
print('normal|up|1-00:00:00|gpu:4|32|64')
""")
        self._write_executable("sacctmgr", """print('debug')
print('normal')
""")
        code, payload = self.cli("site", "discover", "local-slurm")
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["state_mutated"])
        names = [item["name"] for item in payload["partitions"]]
        self.assertEqual(names, ["debug", "normal"])
        self.assertEqual(payload["qos"], ["debug", "normal"])
        self.assertEqual(payload["suggested_policy"]["default_partition"], "debug")
        self.assertTrue(payload["warnings"])

    def test_preflight_qos_rejection_includes_remediation(self):
        self._write_executable("sbatch", """import sys
if '--test-only' in sys.argv:
    sys.stderr.write('sbatch: error: Invalid qos specification\\n')
    raise SystemExit(1)
print('42')
""")
        envelope = self.make_plan()
        with self.assertRaises(OperationError) as caught:
            apply_plan(self.store, envelope["goal"], envelope["plan"],
                       {"run_id": "qos-test"}, plan_path=self.plan_file)
        self.assertIn("Invalid qos specification", str(caught.exception))
        self.assertIn("site discover", str(caught.exception))

    def test_submission_create_and_verify_detects_drift(self):
        envelope = self.make_plan()
        applied = apply_plan(self.store, envelope["goal"], envelope["plan"],
                             {"run_id": "sub-test"}, plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")
        artifact = os.path.join(self.project, "report.md")
        with open(artifact, "w") as handle:
            handle.write("# final report\n")
        submission = os.path.join(self.temp, "submission.json")
        code, created = self.cli("--actor-run-id", "sub-test", "submission", "create",
                                 "--project-root", self.project, "--output", submission,
                                 "--artifact", artifact)
        self.assertEqual(code, 0, created)
        self.assertEqual(created["identities"]["run_id"], envelope["plan"]["run_id"])
        self.assertEqual(created["artifacts"][0]["path"], os.path.realpath(artifact))
        code, verified = self.cli("submission", "verify", "--submission", submission)
        self.assertEqual(code, 0, verified)
        self.assertTrue(verified["ok"])
        with open(artifact, "a") as handle:
            handle.write("late edit\n")
        code, drifted = self.cli("submission", "verify", "--submission", submission)
        self.assertEqual(code, 2, drifted)
        self.assertFalse(drifted["ok"])
        self.assertEqual(drifted["stale"], [os.path.realpath(artifact)])

    def _write_checkpoint(self, confirmed=True, compat="pass"):
        checkpoint = {"schema_version": 2, "compatibility": {"status": compat}}
        if confirmed:
            checkpoint["decisions"] = {"parameters": {
                "digest": "sha256:" + "1" * 64, "confirmed_by": "tester"}}
        path = os.path.join(self.temp, "entity-deps.local.json")
        with open(path, "w") as handle:
            json.dump(checkpoint, handle)
        return path

    def test_build_goal_requires_verified_confirmed_checkpoint(self):
        unconfirmed = self._write_checkpoint(confirmed=False)
        goal = {"schema_version": 1, "kind": "build", "site": "local-slurm",
                "checkpoint": unconfirmed, "executable": self.executable}
        with self.assertRaises(PlanError) as caught:
            plan_goal(self.store, self.project, goal)
        self.assertEqual(caught.exception.status, "needs_decision")
        failing = self._write_checkpoint(compat="fail")
        with self.assertRaises(PlanError):
            plan_goal(self.store, self.project, dict(goal, checkpoint=failing))

    def test_build_goal_registers_build_and_feeds_run_goal(self):
        checkpoint = self._write_checkpoint()
        goal = {"schema_version": 1, "kind": "build", "site": "local-slurm",
                "checkpoint": checkpoint, "executable": self.executable}
        envelope = plan_goal(self.store, self.project, goal)
        with open(self.plan_file, "w") as handle:
            json.dump(envelope, handle)
        applied = apply_plan(self.store, envelope["goal"], envelope["plan"],
                             {"run_id": "build-test"}, plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")
        case = self.store.get_case(envelope["plan"]["case_uid"])
        self.assertEqual(case["current"]["build_id"], envelope["plan"]["build_id"])
        self.assertEqual(case["current"]["readiness"]["build"], "verified")
        # the registered build now feeds a run Goal without an explicit executable
        run_goal = dict(self.goal)
        run_goal.pop("executable")
        run_envelope = plan_goal(self.store, self.project, run_goal, [self.plan_file])
        self.assertEqual(run_envelope["plan"]["steps"][0]["request"]["run_spec"]["executable"],
                         self.executable)

    def test_data_goal_inventories_run_outputs(self):
        envelope = self.make_plan()
        applied = apply_plan(self.store, envelope["goal"], envelope["plan"],
                             {"run_id": "data-test"}, plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")
        data_goal = {"schema_version": 1, "kind": "data", "run": "current"}
        data_envelope = plan_goal(self.store, self.project, data_goal)
        with open(self.plan_file, "w") as handle:
            json.dump(data_envelope, handle)
        inventoried = apply_plan(self.store, data_envelope["goal"],
                                 data_envelope["plan"], {"run_id": "data-test"},
                                 plan_path=self.plan_file)
        self.assertEqual(inventoried["status"], "completed")
        case = self.store.get_case(envelope["plan"]["case_uid"])
        self.assertEqual(case["current"]["data_id"], data_envelope["plan"]["data_id"])
        self.assertEqual(case["current"]["readiness"]["data"], "inventoried")
        run_root = envelope["plan"]["steps"][1]["request"]["run_root"]
        manifest = os.path.join(run_root, "data-inventory.json")
        with open(manifest, "r") as handle:
            inventory = json.load(handle)
        names = [item["path"] for item in inventory["files"]]
        self.assertIn("input.toml", names)
        self.assertIn("run.sbatch", names)

    def test_data_goal_requires_existing_case_and_run(self):
        data_goal = {"schema_version": 1, "kind": "data", "run": "current"}
        with self.assertRaises(PlanError) as caught:
            plan_goal(self.store, self.project, data_goal)
        self.assertEqual(caught.exception.status, "needs_decision")

    def _applied_run(self, run_id="divergence-test"):
        envelope = self.make_plan()
        applied = apply_plan(self.store, envelope["goal"], envelope["plan"],
                             {"run_id": run_id}, plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")
        return envelope

    def test_live_status_flags_job_gone(self):
        self._applied_run()
        os.unlink(self.record)  # job vanished from the scheduler out-of-band
        status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(status["live"]["state"], "NOT_FOUND")
        self.assertEqual(len(status["divergences"]), 1)
        divergence = status["divergences"][0]
        self.assertEqual(divergence["kind"], "job_gone")
        self.assertEqual(divergence["job_id"], "42")
        self.assertFalse(divergence["confirmed"])  # sacct unavailable locally

    def test_live_status_flags_terminal_state_mismatch(self):
        self._applied_run()
        os.unlink(self.record)
        self._write_executable("sacct", """import sys
print('FAILED')
""")
        status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(status["live"]["state"], "NOT_FOUND")
        kinds = [item["kind"] for item in status["divergences"]]
        self.assertEqual(kinds, ["state_mismatch"])
        self.assertEqual(status["divergences"][0]["observed"], "FAILED")
        self.assertEqual(status["divergences"][0]["recorded"], "submitted")

    def test_live_status_flags_untracked_job_in_run_root(self):
        envelope = self._applied_run()
        run_root = envelope["plan"]["steps"][1]["request"]["run_root"]
        self._write_executable("squeue", """import json,os,sys
r=json.load(open(os.environ['FAKE_SLURM_RECORD']))
if '-j' in sys.argv:
    print(r['state'])
else:
    print('%s|%s' % (r['job_id'], r['run_root']))
    print('99|%s' % r['run_root'])
""")
        status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(status["live"]["state"], "RUNNING")
        kinds = [item["kind"] for item in status["divergences"]]
        self.assertEqual(kinds, ["untracked_job"])
        divergence = status["divergences"][0]
        self.assertEqual(divergence["job_id"], "99")
        self.assertEqual(os.path.realpath(divergence["run_root"]),
                         os.path.realpath(run_root))

    def _applied_data_goal(self):
        envelope = self.make_plan()
        apply_plan(self.store, envelope["goal"], envelope["plan"],
                   {"run_id": "refresh-test"}, plan_path=self.plan_file)
        data_goal = {"schema_version": 1, "kind": "data", "run": "current"}
        data_envelope = plan_goal(self.store, self.project, data_goal)
        with open(self.plan_file, "w") as handle:
            json.dump(data_envelope, handle)
        inventoried = apply_plan(self.store, data_envelope["goal"],
                                 data_envelope["plan"], {"run_id": "refresh-test"},
                                 plan_path=self.plan_file)
        self.assertEqual(inventoried["status"], "completed")
        run_root = envelope["plan"]["steps"][1]["request"]["run_root"]
        return data_envelope, os.path.join(run_root, "data-inventory.json"), run_root

    def test_data_inventory_refresh_replaces_stale_manifest(self):
        data_envelope, manifest, run_root = self._applied_data_goal()
        with open(os.path.join(run_root, "extra.out"), "w") as handle:
            handle.write("late artifact\n")
        # without --refresh the completed operation is returned untouched
        skipped = apply_plan(self.store, data_envelope["goal"],
                             data_envelope["plan"], {"run_id": "refresh-test"},
                             plan_path=self.plan_file)
        self.assertEqual(skipped["status"], "completed")
        with open(manifest, "r") as handle:
            self.assertNotIn("extra.out",
                             [item["path"] for item in json.load(handle)["files"]])
        refreshed = apply_plan(self.store, data_envelope["goal"],
                               data_envelope["plan"], {"run_id": "refresh-test"},
                               plan_path=self.plan_file, refresh=True)
        self.assertEqual(refreshed["status"], "completed")
        with open(manifest, "r") as handle:
            self.assertIn("extra.out",
                          [item["path"] for item in json.load(handle)["files"]])

    def test_refresh_rejects_non_data_goals(self):
        envelope = self._applied_run()
        with self.assertRaises(OperationError) as caught:
            apply_plan(self.store, envelope["goal"], envelope["plan"],
                       {"run_id": "refresh-test"}, plan_path=self.plan_file,
                       refresh=True)
        self.assertIn("data Goal", str(caught.exception))

    def test_replan_after_successful_apply_is_idempotent(self):
        envelope = self.make_plan()
        actor = {"run_id": "replan-test", "provider": "unittest"}
        applied = apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                             plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")
        # a successful run mutates case.current; re-planning the same Goal must
        # still reproduce the same Plan identity and apply idempotently
        replanned = self.make_plan()
        self.assertEqual(replanned["plan"]["plan_hash"], envelope["plan"]["plan_hash"])
        self.assertEqual(replanned["plan"]["operation_id"],
                         envelope["plan"]["operation_id"])
        reapplied = apply_plan(self.store, replanned["goal"], replanned["plan"], actor,
                               plan_path=self.plan_file)
        self.assertEqual(reapplied["status"], "completed")
        self.assertEqual(self.submit_count(), 1)

    def _launch_intent(self, comment_hash="0" * 16):
        """Fabricate a launch intent receipt as if the controller crashed
        after sbatch accepted the job but before the effect receipt landed."""
        import entity_router_executor
        run_root = os.path.join(self.run_root, "case-x", "run-x")
        os.makedirs(run_root)
        submit = os.path.join(run_root, "run.sbatch")
        with open(submit, "w") as handle:
            handle.write("#!/bin/bash\n")
        receipt = os.path.join(self.staging_root, "case-x", "op-tz", "receipts",
                               "run-launch.json")
        envelope = {
            "schema_version": 1,
            "operation_id": "op-tz",
            "plan_hash": "sha256:" + comment_hash,
            "step_index": 2,
            "step_id": "launch",
            "kind": "run.launch.v2",
            "site_id": "local-slurm",
            "receipt": receipt,
            "allowed_roots": [os.path.join(self.staging_root, "case-x", "op-tz"),
                              run_root],
            "request": {"run_root": run_root, "submit_script": submit,
                        "job_name": "entity-op-tz", "submit_user": "tester"},
        }
        entity_router_executor.receipt_base(envelope, "intent_written")
        comment = "entity-router:op-tz:%s" % comment_hash
        return entity_router_executor, envelope, run_root, comment

    def _write_slurm_record(self, run_root, comment, submitted_at):
        record = {"job_id": "42", "job_name": "entity-op-tz", "user": "tester",
                  "submitted_at": submitted_at, "state": "RUNNING",
                  "run_root": run_root, "comment": comment}
        with open(self.record, "w") as handle:
            json.dump(record, handle)
        return record

    def test_launch_recovery_matches_non_utc_squeue_time(self):
        import time
        executor, envelope, run_root, comment = self._launch_intent()
        with mock.patch.dict(os.environ, {"TZ": "Pacific/Kiritimati"}):
            time.tzset()
            try:
                # squeue %V reports site-local time; UTC+14 makes a naive
                # comparison with the UTC intent time miss the window
                import datetime
                self._write_slurm_record(
                    run_root, comment,
                    datetime.datetime.now().replace(microsecond=0).isoformat())
                result = executor.execute(envelope)
            finally:
                time.tzset()
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["effect"]["job_id"], "42")
        self.assertEqual(self.submit_count(), 0)

    def test_launch_recovery_finds_dequeued_job_via_sacct(self):
        executor, envelope, run_root, comment = self._launch_intent()
        # the job drained out of squeue before recovery, but sacct still
        # knows it by job name and comment
        sacct_record = os.path.join(self.temp, "sacct-record.json")
        record = self._write_slurm_record(
            run_root, comment, "2026-07-22T10:00:00")
        os.unlink(self.record)
        with open(sacct_record, "w") as handle:
            json.dump(record, handle)
        self._write_executable("sacct", """import json,os,sys
path=os.environ.get('FAKE_SACCT_RECORD','')
if not path or not os.path.isfile(path):
    raise SystemExit(0)
r=json.load(open(path))
print('|'.join([r['job_id'], r['job_name'], r['user'], r['run_root'],
                r['comment'], 'COMPLETED']))
""")
        with mock.patch.dict(os.environ, {"FAKE_SACCT_RECORD": sacct_record}):
            result = executor.execute(envelope)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["effect"]["job_id"], "42")
        self.assertEqual(result["effect"]["state"], "COMPLETED")
        self.assertEqual(self.submit_count(), 0)

    def test_cli_sqlite_error_returns_json_envelope(self):
        import subprocess
        with open(self.store.path, "wb") as handle:
            handle.write(b"definitely not a sqlite database")
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--router-home", self.home, "site", "list"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
        )
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 2, stderr)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)
        self.assertNotIn("Traceback", stdout)

    def test_site_add_rejects_ssh_alias_option_injection(self):
        profile = dict(self.profile, site_id="evil-ssh")
        profile["transport"] = {"kind": "ssh", "ssh_alias": "-oProxyCommand=/bin/evil"}
        profile_path = os.path.join(self.temp, "evil-site.json")
        atomic_write_json(profile_path, profile)
        code, payload = self.cli("site", "add", "--profile", profile_path)
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["state_mutated"])
        # a conventional user@host alias stays valid
        from entity_router_common import validate_site_profile
        valid = dict(self.profile, site_id="ok-ssh")
        valid["transport"] = {"kind": "ssh", "ssh_alias": "deploy@login-1.example"}
        self.assertEqual(validate_site_profile(valid)["site_id"], "ok-ssh")

    def test_build_identity_is_content_addressed(self):
        checkpoint = self._write_checkpoint()
        goal = {"schema_version": 1, "kind": "build", "site": "local-slurm",
                "checkpoint": checkpoint, "executable": self.executable}
        first = plan_goal(self.store, self.project, goal)
        with open(self.executable, "a") as handle:
            handle.write("rebuilt with different content\n")
        second = plan_goal(self.store, self.project, goal)
        self.assertNotEqual(first["plan"]["build_id"], second["plan"]["build_id"])
        # and the rebuilt binary still applies cleanly under its new identity
        with open(self.plan_file, "w") as handle:
            json.dump(second, handle)
        applied = apply_plan(self.store, second["goal"], second["plan"],
                             {"run_id": "build-content"}, plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")
        self.assertEqual(applied["result"]["build_id"], second["plan"]["build_id"])

    def test_cancel_completed_operation_fails_without_changing_state(self):
        from entity_router_store import StoreError
        envelope = self.make_plan()
        actor = {"run_id": "cancel-completed", "provider": "unittest"}
        applied = apply_plan(self.store, envelope["goal"], envelope["plan"], actor,
                             plan_path=self.plan_file)
        self.assertEqual(applied["status"], "completed")
        with self.assertRaises(StoreError):
            self.store.cancel_operation(envelope["plan"]["operation_id"], actor)
        operation = self.store.get_operation(envelope["plan"]["operation_id"])
        self.assertEqual(operation["status"], "completed")

    def test_write_paths_require_the_held_claim(self):
        from entity_router_store import StoreError
        envelope = self.make_plan()
        actor = {"run_id": "claim-test"}
        from entity_router_operation import _ensure_case
        _ensure_case(self.store, envelope["plan"], actor)
        operation = self.store.create_operation(
            envelope["plan"]["case_uid"], envelope["goal"], envelope["plan"], actor)
        token = self.store.claim_operation(operation["operation_id"], actor)
        self.assertTrue(token)
        with self.assertRaises(StoreError):
            self.store.commit_step(operation["operation_id"], 0, {}, [], [], {},
                                   actor, claim_token="stolen-token")
        with self.assertRaises(StoreError):
            self.store.finish_operation(operation["operation_id"], "completed", {},
                                        actor, claim_token="stolen-token")
        self.store.commit_step(operation["operation_id"], 0, {}, [], [], {},
                               actor, claim_token=token)
        self.store.finish_operation(operation["operation_id"], "completed", {},
                                    actor, claim_token=token)
        self.assertEqual(
            self.store.get_operation(operation["operation_id"])["status"], "completed")


if __name__ == "__main__":
    unittest.main()
