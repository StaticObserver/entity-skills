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
from entity_router_common import atomic_write_json, save_site_profile
import entity_router_common
from entity_router_store import OperationStore, canonical_hash, migrate_v3


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
        'submitted_at':datetime.datetime.utcnow().replace(microsecond=0).isoformat(),
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
                         "running")
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
        envelope = self.make_plan()
        plan = envelope["plan"]
        plan["steps"][1]["allowed_roots"].append(self.temp)
        unsigned = dict(plan)
        unsigned.pop("plan_hash")
        unsigned.pop("generated_at")
        plan["plan_hash"] = canonical_hash(unsigned)
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

    def test_v3_migration_is_one_time_and_does_not_dual_write(self):
        legacy_home = os.path.join(self.temp, "legacy-controller")
        case_uid = "legacy-case"
        case_dir = os.path.join(legacy_home, "cases", case_uid)
        os.makedirs(os.path.join(case_dir, "actions", "active"))
        legacy_profile = dict(self.profile, site_id="legacy-local")
        save_site_profile(legacy_home, legacy_profile)
        state = {
            "schema_version": 3, "case_uid": case_uid, "case_id": "legacy",
            "created_at": "2026-01-01T00:00:00Z", "revision": 7,
            "source": {"authority": {"site_id": "legacy-local", "path": self.project},
                       "revision": {"kind": "git", "commit": "abc"}},
            "workflow": {"active_action_id": "active", "status": "active"},
            "readiness": {"run": {"status": "submitted"}},
            "resources": {
                "build": {"current_id": "", "identities": []},
                "run": {"current_id": "run-old", "active": {
                    "site_id": "legacy-local", "path": self.run_root},
                    "identities": [{"id": "run-old", "kind": "run"}]},
                "data": {"current_id": "", "identities": []},
                "analysis": {"current_id": "", "identities": []},
            },
        }
        atomic_write_json(os.path.join(case_dir, "case.json"), state)
        atomic_write_json(os.path.join(case_dir, "actions", "active", "result.json"),
                          {"status": "completed"})
        atomic_write_json(os.path.join(legacy_home, "registry.json"), {
            "schema_version": 1, "updated_at": "2026-01-01T00:00:00Z",
            "cases": {case_uid: {"case_uid": case_uid, "case_id": "legacy",
                                  "control_root": case_dir}},
        })
        atomic_write_json(os.path.join(legacy_home, "project-bindings.json"), {
            "schema_version": 1, "projects": {self.project: {"case_uid": case_uid}}
        })
        first = migrate_v3(legacy_home)
        self.assertTrue(first["state_mutated"])
        migrated = OperationStore(legacy_home, create=False)
        imported = migrated.resolve_project(self.project)
        self.assertEqual(imported["current"]["run_id"], "run-old")
        self.assertTrue(imported["legacy"]["result_on_active"])
        state["resources"]["run"]["current_id"] = "changed-only-in-v3"
        atomic_write_json(os.path.join(case_dir, "case.json"), state)
        second = migrate_v3(legacy_home)
        self.assertTrue(second["already_imported"])
        self.assertFalse(second["state_mutated"])
        self.assertEqual(migrated.resolve_project(self.project)["current"]["run_id"], "run-old")

    def test_ssh_uses_the_same_steps_and_live_status_has_one_remote_call(self):
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
        self.assertEqual(status["remote_calls"], 1)
        self.assertEqual(remote_calls.call_count - calls_before_status, 1)


if __name__ == "__main__":
    unittest.main()
