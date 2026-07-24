#!/usr/bin/env python3

import json
import os
import shutil
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock
import shlex


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_router_operation import status_for_project
from entity_router_record import record_run_launch, record_run_prepare
from entity_router_common import atomic_write_json
import entity_router_common
from entity_router_store import OperationStore


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
            "FAKE_SACCT_RECORD": "",
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
            "policy": {"default_cpus_per_gpu": 2, "default_partition": "test",
                       "default_submit_user": "tester"},
            "shared_mappings": [],
        }
        self.store.upsert_site(self.profile)
        self._pgids = []

    def tearDown(self):
        for pgid in self._pgids:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
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
args=sys.argv[1:]
path=os.environ['FAKE_SLURM_RECORD']
if not os.path.isfile(path):
    raise SystemExit(0)
r=json.load(open(path))
fmt=''
for flag in ('-o','--format'):
    if flag in args:
        fmt=args[args.index(flag)+1]
if '-j' in args:
    job=args[args.index('-j')+1]
    if job != r['job_id']:
        raise SystemExit(0)
if fmt == '%T':
    print(r['state'])
elif fmt == '%i|%T|%Z':
    print('%s|%s|%s' % (r['job_id'], r['state'], r['run_root']))
else:
    print('{job_id}|{job_name}|{user}|{submitted_at}|{state}|{run_root}|{comment}'.format(**r))
""")
        self._write_executable("sacct", """import json,os,sys
args=sys.argv[1:]
path=os.environ.get('FAKE_SACCT_RECORD','')
if not path or not os.path.isfile(path):
    raise SystemExit(0)
r=json.load(open(path))
if '-j' in args:
    job=args[args.index('-j')+1]
    if job != r.get('job_id', '42'):
        raise SystemExit(0)
fmt=''
for a in args:
    if a.startswith('--format='):
        fmt=a.split('=',1)[1]
if fmt == 'State,ExitCode':
    print('%s|%s' % (r.get('state','COMPLETED'), r.get('exit_code','0:0')))
else:
    print(r.get('state','COMPLETED'))
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

    def _record_run(self, site="local-slurm", executable=None,
                    walltime="00:10:00"):
        """Create a submitted run identity through the record primitives."""
        actor = {"run_id": "record-fixture", "provider": "unittest"}
        prepared = record_run_prepare(
            self.store, self.project, "input.toml", site, 1, walltime,
            "double", executable or self.executable, actor)
        launched = record_run_launch(
            self.store, self.project, prepared["run_id"], None, None, actor)
        return prepared, launched

    def _direct_executable(self, body, name="entity-direct.xc"):
        path = os.path.join(self.build_root, name)
        with open(path, "w") as handle:
            handle.write("#!/bin/bash\n%s\n" % body)
        os.chmod(path, 0o755)
        return path

    def _record_direct_run(self, body, walltime="00:10:00"):
        """Record a run on a scheduler-less local Site whose executable is a
        real script the direct backend actually launches."""
        self._write_executable("nvidia-smi", "print('fake gpu')")
        profile = dict(self.profile)
        profile["site_id"] = "local-direct"
        profile["scheduler"] = {"kind": "none"}
        self.store.upsert_site(profile)
        executable = self._direct_executable(body)
        return self._record_run(
            site="local-direct", executable=executable, walltime=walltime)

    def _run_identity(self):
        case = self.store.resolve_project(self.project)
        run_id = case.get("current", {}).get("run_id", "")
        for item in case.get("identities", {}).get("run", {}).get("items", []):
            if item.get("id") == run_id:
                return item
        return None

    def _track_process_group(self):
        scheduler = (self._run_identity() or {}).get("scheduler", {})
        if scheduler.get("pgid"):
            self._pgids.append(scheduler["pgid"])

    def _wait_exit_file(self, path, seconds=20):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if os.path.isfile(path):
                with open(path, "r") as handle:
                    return handle.read().strip()
            time.sleep(0.1)
        self.fail("exit file did not appear: %s" % path)

    def _wait_pid_gone(self, pid, seconds=20):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.1)
        self.fail("process %s is still running" % pid)

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

    def test_site_add_rejects_invalid_profile(self):
        profile = dict(self.profile, site_id="bad site!")
        profile_path = os.path.join(self.temp, "bad-site.json")
        atomic_write_json(profile_path, profile)
        code, payload = self.cli("site", "add", "--profile", profile_path)
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["state_mutated"])

    def test_executor_rejects_unsupported_scheduler_kind(self):
        executor, envelope, unused_root, unused_comment = self._launch_intent()
        envelope["request"]["scheduler"] = "pbs"
        with self.assertRaises(executor.ExecutorError) as caught:
            executor.execute(envelope)
        self.assertIn("scheduler kind is not supported: pbs", str(caught.exception))

    def test_site_discover_rejects_unregistered_scheduler_kind(self):
        profile = dict(self.profile, site_id="pbs-site")
        profile["scheduler"] = {"kind": "pbs"}
        profile_path = os.path.join(self.temp, "pbs-site.json")
        atomic_write_json(profile_path, profile)
        code, payload = self.cli("site", "add", "--profile", profile_path)
        self.assertEqual(code, 0, payload)
        code, payload = self.cli("site", "discover", "pbs-site")
        self.assertEqual(code, 2)
        self.assertIn("scheduler kinds: none, slurm", payload["error"])
        self.assertIn("'pbs'", payload["error"])

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
            "request": {"scheduler": "slurm", "run_root": run_root,
                        "submit_script": submit,
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

    def _direct_launch_intent(self):
        """Fabricate a direct launch intent receipt as if the controller
        crashed after the process started but before the effect receipt
        landed."""
        import entity_router_executor
        run_root = os.path.join(self.run_root, "case-d", "run-d")
        os.makedirs(run_root)
        submit = os.path.join(run_root, "run.sh")
        with open(submit, "w") as handle:
            handle.write("#!/bin/bash\nset -eu\nsleep 30\n")
        receipt = os.path.join(self.staging_root, "case-d", "op-d", "receipts",
                               "run-launch.json")
        envelope = {
            "schema_version": 1,
            "operation_id": "op-d",
            "plan_hash": "sha256:" + "1" * 16,
            "step_index": 2,
            "step_id": "launch",
            "kind": "run.launch.v2",
            "site_id": "local-direct",
            "receipt": receipt,
            "allowed_roots": [os.path.join(self.staging_root, "case-d", "op-d"),
                              run_root],
            "request": {"scheduler": "direct", "run_root": run_root,
                        "submit_script": submit,
                        "job_name": "entity-op-d", "submit_user": "tester"},
        }
        entity_router_executor.receipt_base(envelope, "intent_written")
        return entity_router_executor, envelope, run_root

    def test_direct_launch_recovery_claims_running_process(self):
        executor, envelope, unused_root = self._direct_launch_intent()
        first = executor.execute(envelope)
        self.assertEqual(first["status"], "completed", first)
        pid = first["effect"]["pid"]
        self.assertEqual(first["effect"]["pgid"], pid)
        try:
            # a controller crash lost the effect receipt; recovery must claim
            # the still-running process instead of launching a second one
            executor.receipt_base(envelope, "intent_written")
            recovered = executor.execute(envelope)
            self.assertEqual(recovered["status"], "completed", recovered)
            self.assertEqual(recovered["effect"]["pid"], pid)
            self.assertEqual(recovered["effect"]["comment"],
                             first["effect"]["comment"])
        finally:
            try:
                os.killpg(first["effect"]["pgid"], signal.SIGKILL)
            except OSError:
                pass

    def test_direct_run_script_is_deterministic(self):
        from entity_router_executor import RENDER_BACKENDS
        run_spec = {
            "executable": self.executable, "input_name": "input.toml",
            "compute": {"nodes": 1, "tasks": 1, "gpus": 1, "cpus_per_task": 2,
                        "walltime": "00:10:00", "partition": "", "qos": "",
                        "submit_user": "tester", "precision": "double"},
        }
        first = RENDER_BACKENDS["direct"](run_spec)
        self.assertEqual(first, RENDER_BACKENDS["direct"](run_spec))
        self.assertIn("set -eu", first)
        self.assertIn("timeout 600 ", first)
        self.assertIn("-input input.toml", first)
        self.assertIn(".entity-exit-code", first)

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
        # operations rows can only be leftovers of the retired plan/apply
        # protocol; doctor must surface them without pointing at commands
        # that no longer exist
        actor = {"run_id": "leak-test", "provider": "unittest"}
        case_uid = "case-leak"
        self.store.upsert_case(
            case_uid, "leak", self.project,
            {"authority": {"site_id": "local-slurm", "path": self.project},
             "transfer_policy": "snapshot"},
            {"source_id": "", "build_id": "", "run_id": "", "active_run": None,
             "data_id": "", "analysis_id": ""},
        )
        plan = {"operation_id": "op-leak", "plan_hash": "sha256:" + "0" * 64,
                "steps": [{"step_id": "s0", "kind": "run.preflight.v1"}]}
        self.store.create_operation(
            case_uid, {"schema_version": 1, "kind": "run"}, plan, actor)
        fake_home = os.path.join(self.temp, "leak-clients")
        os.makedirs(fake_home)
        with mock.patch.dict(os.environ, {"HOME": fake_home}):
            code, payload = self.cli("doctor")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["failures"], [])
        leaked = [warning for warning in payload["warnings"]
                  if "op-leak" in warning]
        self.assertTrue(leaked, payload["warnings"])
        self.assertIn("retired plan/apply protocol", leaked[0])

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

    def test_ssh_live_status_reconciles_remotely(self):
        remote_profile = dict(self.profile)
        remote_profile["site_id"] = "fake-ssh"
        remote_profile["transport"] = {"kind": "ssh", "ssh_alias": "fake"}
        self.store.upsert_site(remote_profile)

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

        with mock.patch("entity_router_facts.run_on_site", local_site):
            with mock.patch("entity_router_operation.run_on_site",
                            side_effect=local_site) as remote_calls:
                with mock.patch("entity_router_operation.run_command",
                                side_effect=scp_or_local):
                    prepared, launched = self._record_run(site="fake-ssh")
                    calls_before_status = remote_calls.call_count
                    status = status_for_project(self.store, self.project,
                                                live=True)
        self.assertEqual(launched["status"], "submitted")
        self.assertEqual(launched["scheduler"]["job_id"], "42")
        self.assertEqual(self.submit_count(), 1)
        # live status = squeue job query + untracked-job scan (job is active,
        # so no sacct fallback); reconciliation stays read-only and bounded
        self.assertEqual(status["live"]["state"], "RUNNING")
        self.assertEqual(status["remote_calls"], 2)
        self.assertEqual(remote_calls.call_count - calls_before_status, 2)
        self.assertEqual(status["divergences"], [])
        self.assertEqual(status["current"]["run_id"], prepared["run_id"])

    def test_live_status_degrades_when_scheduler_query_fails(self):
        prepared, unused_launched = self._record_run()
        self._write_executable("squeue", """import sys
sys.stderr.write('slurm_load_jobs error: Invalid job id\\n')
raise SystemExit(1)
""")
        status = status_for_project(self.store, self.project, live=True)
        self.assertTrue(status["ok"])
        self.assertEqual(status["live"]["state"], "UNKNOWN")
        self.assertIn("warning", status["live"])
        self.assertEqual(status["current"]["run_id"], prepared["run_id"])

    def test_live_status_flags_job_gone(self):
        self._record_run()
        os.unlink(self.record)  # job vanished from the scheduler out-of-band
        status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(status["live"]["state"], "NOT_FOUND")
        self.assertEqual(len(status["divergences"]), 1)
        divergence = status["divergences"][0]
        self.assertEqual(divergence["kind"], "job_gone")
        self.assertEqual(divergence["job_id"], "42")
        # sacct answers successfully but has no record of the job, which
        # confirms the job is gone rather than leaving the probe inconclusive
        self.assertTrue(divergence["confirmed"])

    def test_live_status_flags_terminal_state_mismatch(self):
        self._record_run()
        os.unlink(self.record)
        sacct_record = os.path.join(self.temp, "sacct-record.json")
        with open(sacct_record, "w") as handle:
            json.dump({"job_id": "42", "state": "FAILED"}, handle)
        with mock.patch.dict(os.environ, {"FAKE_SACCT_RECORD": sacct_record}):
            status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(status["live"]["state"], "NOT_FOUND")
        kinds = [item["kind"] for item in status["divergences"]]
        self.assertEqual(kinds, ["state_mismatch"])
        self.assertEqual(status["divergences"][0]["observed"], "FAILED")
        self.assertEqual(status["divergences"][0]["recorded"], "submitted")

    def test_live_status_flags_untracked_job_in_run_root(self):
        prepared, unused_launched = self._record_run()
        run_root = prepared["run_root"]
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

    def test_submission_create_and_verify_detects_drift(self):
        prepared, unused_launched = self._record_run()
        artifact = os.path.join(self.project, "report.md")
        with open(artifact, "w") as handle:
            handle.write("# final report\n")
        submission = os.path.join(self.temp, "submission.json")
        code, created = self.cli("--actor-run-id", "sub-test", "submission", "create",
                                 "--project-root", self.project, "--output", submission,
                                 "--artifact", artifact)
        self.assertEqual(code, 0, created)
        self.assertEqual(created["identities"]["run_id"], prepared["run_id"])
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

    def test_direct_backend_end_to_end(self):
        marker = os.path.join(self.temp, "direct-ran.txt")
        prepared, launched = self._record_direct_run(
            'echo ran >> "%s"\nsleep 0.2' % marker)
        self.assertEqual(launched["status"], "submitted")
        self.assertEqual(launched["scheduler"]["scheduler"], "direct")
        self._track_process_group()
        run_root = prepared["run_root"]
        submit = os.path.join(run_root, "run.sh")
        self.assertTrue(os.path.isfile(submit))
        with open(submit, "r") as handle:
            script = handle.read()
        self.assertIn("set -eu", script)
        self.assertIn("timeout 600 ", script)
        self.assertIn("-input input.toml", script)
        self.assertIn(".entity-exit-code", script)
        exit_code = self._wait_exit_file(
            os.path.join(run_root, ".entity-exit-code"))
        self.assertEqual(exit_code, "0")
        self.assertTrue(os.path.isfile(os.path.join(run_root, "run.log")))
        with open(marker, "r") as handle:
            self.assertEqual(handle.read().splitlines(), ["ran"])
        status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(status["live"]["scheduler"], "direct")
        self.assertEqual(status["live"]["state"], "EXITED")
        self.assertEqual(status["live"]["exit_code"], 0)
        kinds = [item["kind"] for item in status["divergences"]]
        self.assertEqual(kinds, ["state_mismatch"])
        self.assertEqual(status["divergences"][0]["recorded"], "submitted")
        self.assertEqual(status["divergences"][0]["observed"], "EXITED")
        self._wait_pid_gone(status["run"]["scheduler"]["pid"])

    def test_direct_live_status_running_then_job_gone(self):
        self._record_direct_run("sleep 30")
        self._track_process_group()
        status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(status["live"]["state"], "RUNNING")
        identity = status["run"]["scheduler"]
        self.assertEqual(status["live"]["pid"], identity["pid"])
        os.killpg(identity["pgid"], signal.SIGKILL)
        status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(status["live"]["state"], "NOT_FOUND")
        kinds = [item["kind"] for item in status["divergences"]]
        self.assertEqual(kinds, ["job_gone"])
        self.assertEqual(status["divergences"][0]["pid"], identity["pid"])
        self.assertTrue(status["divergences"][0]["confirmed"])

    def test_direct_walltime_enforced_with_exit_124(self):
        prepared, unused_launched = self._record_direct_run(
            "sleep 30", walltime="00:00:01")
        self._track_process_group()
        exit_code = self._wait_exit_file(
            os.path.join(prepared["run_root"], ".entity-exit-code"))
        self.assertEqual(exit_code, "124")
        status = status_for_project(self.store, self.project, live=True)
        self.assertEqual(status["live"]["state"], "EXITED")
        self.assertEqual(status["live"]["exit_code"], 124)
        self._wait_pid_gone(status["run"]["scheduler"]["pid"])

    def test_direct_live_status_flags_untracked_job_in_run_root(self):
        prepared, unused_launched = self._record_direct_run("sleep 30")
        self._track_process_group()
        run_root = prepared["run_root"]
        foreign = None
        try:
            foreign_dir = os.path.join(run_root, "foreign")
            os.makedirs(foreign_dir)
            foreign_script = os.path.join(foreign_dir, "run.sh")
            with open(foreign_script, "w") as handle:
                handle.write("#!/bin/bash\nsleep 30\n")
            subprocess = __import__("subprocess")
            foreign = subprocess.Popen(
                ["bash", foreign_script, "entity-router:op-foreign:0000000000000000"],
                cwd=run_root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
            deadline = time.time() + 10
            while True:
                status = status_for_project(self.store, self.project, live=True)
                self.assertEqual(status["live"]["state"], "RUNNING")
                untracked = [item for item in status["divergences"]
                             if item["kind"] == "untracked_job"]
                if untracked:
                    break
                if time.time() > deadline:
                    self.fail("foreign process was never scanned")
                time.sleep(0.2)
            self.assertEqual(len(untracked), 1)
            self.assertEqual(untracked[0]["pid"], foreign.pid)
            self.assertNotIn("unknown", untracked[0])
            self.assertEqual(os.path.realpath(untracked[0]["run_root"]),
                             os.path.realpath(run_root))
        finally:
            if foreign is not None:
                try:
                    os.killpg(foreign.pid, signal.SIGKILL)
                except OSError:
                    pass
                foreign.wait()

    def test_direct_untracked_scan_degrades_to_unknown(self):
        self._record_direct_run("sleep 5")
        self._track_process_group()
        self._write_executable("pgrep", """import sys
sys.stderr.write('pgrep: permission denied\\n')
raise SystemExit(2)
""")
        status = status_for_project(self.store, self.project, live=True)
        self.assertTrue(status["ok"])  # unknown is not a failure
        self.assertEqual(status["live"]["state"], "RUNNING")
        untracked = [item for item in status["divergences"]
                     if item["kind"] == "untracked_job"]
        self.assertEqual(len(untracked), 1)
        self.assertTrue(untracked[0]["unknown"])
        self.assertTrue(untracked[0]["detail"])

    def test_site_discover_direct_reports_environment_and_gpus(self):
        self._write_executable("nvidia-smi", "print('FakeGPU A100')")
        profile = dict(self.profile, site_id="direct-site")
        profile["scheduler"] = {"kind": "none"}
        profile_path = os.path.join(self.temp, "direct-site.json")
        atomic_write_json(profile_path, profile)
        code, payload = self.cli("site", "add", "--profile", profile_path)
        self.assertEqual(code, 0, payload)
        code, payload = self.cli("site", "discover", "direct-site")
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["state_mutated"])
        self.assertEqual(payload["gpus"], ["FakeGPU A100"])
        self.assertIn("bash", payload["environment"]["bash"].lower())
        self.assertTrue(payload["environment"]["python3"].startswith("Python"))
        self.assertTrue(payload["roots"]["run_root"]["writable"])
        self.assertTrue(payload["roots"]["staging_root"]["writable"])
        self.assertEqual(payload["suggested_policy"], {})

    def test_site_discover_direct_warns_without_nvidia_smi(self):
        self._write_executable("nvidia-smi", """import sys
sys.stderr.write('no devices found\\n')
raise SystemExit(1)
""")
        profile = dict(self.profile, site_id="direct-bare")
        profile["scheduler"] = {"kind": "none"}
        profile_path = os.path.join(self.temp, "direct-bare.json")
        atomic_write_json(profile_path, profile)
        code, payload = self.cli("site", "add", "--profile", profile_path)
        self.assertEqual(code, 0, payload)
        code, payload = self.cli("site", "discover", "direct-bare")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["gpus"], [])
        self.assertTrue(any("nvidia-smi" in warning
                            for warning in payload["warnings"]))

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


if __name__ == "__main__":
    unittest.main()
