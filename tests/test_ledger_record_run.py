#!/usr/bin/env python3

import datetime
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-ledger", "scripts")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_ledger_dashboard import build_dashboard
from entity_ledger_store import OperationStore


class RecordRunTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-record-run-")
        self.home = os.path.join(self.temp, "controller")
        self.project = os.path.join(self.temp, "project")
        self.run_root = os.path.join(self.temp, "runs")
        self.staging_root = os.path.join(self.temp, "staging")
        self.build_root = os.path.join(self.temp, "build")
        self.bin_root = os.path.join(self.temp, "bin")
        for path in [self.project, self.run_root, self.staging_root,
                     self.build_root, self.bin_root]:
            os.makedirs(path)
        self.input = os.path.join(self.project, "input.toml")
        with open(self.input, "w") as handle:
            handle.write("[simulation]\nsteps = 2\n")
        self._confirm_input(self.input)
        with open(os.path.join(self.project, "pgen.hpp"), "w") as handle:
            handle.write("// source\n")
        self.executable = os.path.join(self.build_root, "entity.xc")
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
            "FAKE_SBATCH_REJECT": "",
        })
        self.environment.start()
        self.store = OperationStore(self.home)
        roots = {"source_root": self.temp, "build_root": self.build_root,
                 "run_root": self.run_root, "staging_root": self.staging_root}
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local-slurm",
            "display_name": "local slurm",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "slurm"}, "roots": roots,
            "policy": {"default_cpus_per_gpu": 2,
                       "default_partition": "test",
                       "default_submit_user": "tester"},
            "shared_mappings": [],
        })
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local-direct",
            "display_name": "local direct",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "none"}, "roots": roots,
            "policy": {}, "shared_mappings": [],
        })
        self._pgids = []

    def tearDown(self):
        for pgid in self._pgids:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
        self.environment.stop()
        shutil.rmtree(self.temp)

    def cli(self, *args):
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--ledger-home", self.home,
             "--actor-run-id", "record-run-test"] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), stderr)
        return process.returncode, json.loads(stdout)

    def _write_executable(self, name, text):
        path = os.path.join(self.bin_root, name)
        with open(path, "w") as handle:
            handle.write("#!%s\n%s" % (sys.executable, text))
        os.chmod(path, 0o755)

    def _write_fake_slurm(self):
        self._write_executable("sbatch", """import datetime,json,os,sys
args=sys.argv[1:]
if '--test-only' in args:
    reject=os.environ.get('FAKE_SBATCH_REJECT','')
    if reject:
        sys.stderr.write('sbatch: error: %s\\n' % reject)
        raise SystemExit(1)
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
    if job != r['job_id']:
        raise SystemExit(0)
fmt=''
for a in args:
    if a.startswith('--format='):
        fmt=a.split('=',1)[1]
# honest emulation: real sacct only pipe-separates with -P; without it the
# output is a whitespace-padded table
pipe='-P' in args
def emit(fields):
    print('|'.join(fields) if pipe else '  '.join(fields))
if fmt == 'State,ExitCode':
    emit([r.get('state','COMPLETED'), r.get('exit_code','0:0')])
elif fmt == 'JobID,State,WorkDir':
    emit([r['job_id'], r.get('state','COMPLETED'), r['run_root']])
else:
    print(r.get('state','COMPLETED'))
""")

    def _confirm_input(self, path):
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        record = {
            "schema_version": 1,
            "kind": "entity-pgen.simulation-confirmation",
            "input_sha256": digest,
            "card": {},
            "confirmed_by": "test",
            "confirmed_at": "2026-07-22T00:00:00",
            "defaults": False,
        }
        with open(path + ".decisions.json", "w") as handle:
            json.dump(record, handle)

    def _direct_executable(self, body, name="entity-direct.xc"):
        path = os.path.join(self.build_root, name)
        with open(path, "w") as handle:
            handle.write("#!/bin/bash\n%s\n" % body)
        os.chmod(path, 0o755)
        return path

    def _prepare(self, site, executable, toml=None, extra=None):
        argv = ["record", "run-prepare", "--project-root", self.project,
                "--toml", toml or "input.toml", "--site", site,
                "--executable", executable] + list(extra or [])
        code, payload = self.cli(*argv)
        self.assertEqual(code, 0, payload)
        return payload

    def _launch(self, extra=None):
        argv = ["record", "run-launch", "--project-root", self.project]
        argv += list(extra or [])
        return self.cli(*argv)

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

    def submit_count(self):
        if not os.path.isfile(self.count):
            return 0
        with open(self.count) as handle:
            return int(handle.read())

    def test_render_run_is_deterministic_and_pure(self):
        argv = ["render-run", "--project-root", self.project,
                "--toml", "input.toml", "--site", "local-slurm",
                "--executable", self.executable]
        code, first = self.cli(*argv)
        self.assertEqual(code, 0, first)
        self.assertEqual(first["kind"], "entity-ledger.render-run")
        self.assertFalse(first["state_mutated"])
        code, second = self.cli(*argv)
        self.assertEqual(code, 0, second)
        self.assertEqual(second["script"], first["script"])
        self.assertEqual(second["run_id"], first["run_id"])
        self.assertTrue(first["run_id"].startswith("run-"))
        script = first["script"]
        self.assertIn("#SBATCH --partition=test", script)
        self.assertIn("#SBATCH --gres=gpu:1", script)
        self.assertIn("#SBATCH --cpus-per-task=2", script)
        self.assertNotIn("#SBATCH --time", script)
        self.assertIn("srun %s -input input.toml" % self.executable, script)
        self.assertEqual(first["compute"]["partition"], "test")
        self.assertEqual(first["compute"]["submit_user"], "tester")
        self.assertTrue(first["submit_script"].endswith("run.sbatch"))
        self.assertEqual(self.store.export()["cases"], [])

    def test_render_run_needs_no_confirmation(self):
        os.unlink(self.input + ".decisions.json")
        code, payload = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable)
        self.assertEqual(code, 0, payload)

    def test_render_run_compute_overrides(self):
        code, payload = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable,
            "--gpus", "4", "--walltime", "02:00:00", "--precision", "single")
        self.assertEqual(code, 0, payload)
        self.assertIn("#SBATCH --gres=gpu:4", payload["script"])
        self.assertIn("#SBATCH --time=02:00:00", payload["script"])
        self.assertEqual(payload["compute"]["gpus"], 4)
        self.assertEqual(payload["compute"]["tasks"], 4)
        self.assertEqual(payload["compute"]["precision"], "single")

    def test_render_run_default_leaves_walltime_unset(self):
        code, payload = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["compute"]["walltime"], "")
        self.assertNotIn("#SBATCH --time", payload["script"])

    def _register_typed_gres_site(self):
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local-slurm-typed",
            "display_name": "local slurm typed",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "slurm"},
            "roots": {"source_root": self.temp, "build_root": self.build_root,
                      "run_root": self.run_root,
                      "staging_root": self.staging_root},
            "policy": {"default_cpus_per_gpu": 2,
                       "default_partition": "test",
                       "default_submit_user": "tester",
                       "default_gres": "gpu:V100:1"},
            "shared_mappings": [],
        })

    def test_render_run_typed_gres_from_policy(self):
        self._register_typed_gres_site()
        code, payload = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm-typed",
            "--executable", self.executable)
        self.assertEqual(code, 0, payload)
        self.assertIn("#SBATCH --gres=gpu:V100:1", payload["script"])
        self.assertEqual(payload["compute"]["gres"], "gpu:V100:1")

    def test_render_run_explicit_gres_overrides_policy(self):
        self._register_typed_gres_site()
        code, payload = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm-typed",
            "--executable", self.executable, "--gres", "gpu:A100:1")
        self.assertEqual(code, 0, payload)
        self.assertIn("#SBATCH --gres=gpu:A100:1", payload["script"])
        self.assertEqual(payload["compute"]["gres"], "gpu:A100:1")

    def test_render_run_gres_falls_back_to_generic(self):
        code, payload = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["compute"]["gres"], "gpu:1")
        self.assertIn("#SBATCH --gres=gpu:1", payload["script"])

    def test_render_run_rejects_an_invalid_gres(self):
        code, payload = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable, "--gres", "v100")
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["state_mutated"])
        self.assertIn("gres", payload["error"])

    def test_run_identity_records_resolved_gres(self):
        self._register_typed_gres_site()
        prepared = self._prepare("local-slurm-typed", self.executable)
        self.assertEqual(prepared["kind"], "entity-ledger.record.run-prepare")
        identity = self._run_identity()
        self.assertIsNotNone(identity)
        self.assertEqual(identity["compute"]["gres"], "gpu:V100:1")
        submit = os.path.join(prepared["run_root"], "run.sbatch")
        with open(submit) as handle:
            self.assertIn("#SBATCH --gres=gpu:V100:1", handle.read())

    def test_direct_backend_ignores_gres(self):
        code, payload = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-direct",
            "--executable", self.executable, "--gres", "gpu:V100:1")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["compute"]["gres"], "")
        self.assertNotIn("gres", payload["script"])

    def test_run_prepare_run_id_reuses_rendered_run(self):
        code, rendered = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable)
        self.assertEqual(code, 0, rendered)
        code, prepared = self.cli(
            "record", "run-prepare", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable,
            "--run-id", rendered["run_id"])
        self.assertEqual(code, 0, prepared)
        self.assertEqual(prepared["run_id"], rendered["run_id"])
        self.assertEqual(prepared["run_root"], rendered["run_root"])
        # the render previewed exactly what prepare materialized
        with open(os.path.join(prepared["run_root"], "run.sbatch")) as handle:
            self.assertEqual(handle.read(), rendered["script"])

    def test_run_prepare_run_id_mismatch_fails_closed(self):
        code, rendered = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable)
        self.assertEqual(code, 0, rendered)
        code, payload = self.cli(
            "record", "run-prepare", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable, "--gpus", "2",
            "--run-id", rendered["run_id"])
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["state_mutated"])
        self.assertIn("drifted", payload["error"])
        self.assertIn(rendered["run_id"], payload["error"])
        # zero writes: no run root materialized anywhere
        self.assertEqual(os.listdir(self.run_root), [])

    def test_site_tree_launch_uses_derived_staging_root(self):
        # regression: record run-launch must resolve execution roots from
        # site_root (site-tree layout), not only from explicit legacy roots
        site_root = os.path.join(self.temp, "compute")
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local-tree",
            "display_name": "local site-tree",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "slurm"},
            "site_root": site_root, "roots": {},
            "policy": {"default_cpus_per_gpu": 2,
                       "default_partition": "test",
                       "default_submit_user": "tester"},
            "shared_mappings": [],
        })
        # the executable must sit under the derived site-tree build root
        # (project entity unregistered here -> slug falls back to the
        # project directory basename)
        tree_executable = os.path.join(
            site_root, "projects", os.path.basename(self.project), "builds",
            "entity.xc")
        os.makedirs(os.path.dirname(tree_executable))
        shutil.copy2(self.executable, tree_executable)
        prepared = self._prepare("local-tree", tree_executable)
        self.assertIn(site_root, prepared["run_root"])
        code, launched = self._launch()
        self.assertEqual(code, 0, launched)
        self.assertEqual(launched["status"], "submitted")
        self.assertEqual(launched["scheduler"]["job_id"], "42")
        submit = os.path.join(prepared["run_root"], "run.sbatch")
        self.assertTrue(os.path.isfile(submit))

    def test_render_run_rejects_an_invalid_walltime(self):
        code, payload = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm",
            "--executable", self.executable, "--walltime", "soon")
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["state_mutated"])
        self.assertIn("walltime", payload["error"])

    def test_render_run_resolves_executable_from_build_identity(self):
        checkpoint = os.path.join(self.temp, "entity-deps.local.json")
        with open(checkpoint, "w") as handle:
            json.dump({"schema_version": 2,
                       "compatibility": {"status": "pass"},
                       "decisions": {"parameters": {
                           "digest": "sha256:" + "1" * 64,
                           "confirmed_by": "tester"}}}, handle)
        # record build requires an existing Case; prepare creates it with an
        # explicit executable first, then the build identity becomes the
        # default for later renders
        self._prepare("local-slurm", self.executable)
        code, payload = self.cli(
            "record", "build", "--project-root", self.project,
            "--site", "local-slurm", "--checkpoint", checkpoint,
            "--executable", self.executable)
        self.assertEqual(code, 0, payload)
        code, rendered = self.cli(
            "render-run", "--project-root", self.project,
            "--toml", "input.toml", "--site", "local-slurm")
        self.assertEqual(code, 0, rendered)
        self.assertEqual(rendered["executable"], self.executable)
        self.assertEqual(rendered["build_id"], payload["build_id"])
        self.assertIn("srun %s -input input.toml" % self.executable,
                      rendered["script"])

    def test_run_prepare_requires_confirmation(self):
        raw = os.path.join(self.project, "raw.toml")
        with open(raw, "w") as handle:
            handle.write("[simulation]\nsteps = 3\n")
        code, payload = self.cli(
            "record", "run-prepare", "--project-root", self.project,
            "--toml", "raw.toml", "--site", "local-slurm",
            "--executable", self.executable)
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "needs_decision")
        self.assertFalse(payload["state_mutated"])
        self.assertEqual(self.store.export()["cases"], [])
        self.assertEqual(os.listdir(self.run_root), [])

    def test_run_prepare_books_case_and_run_idempotently(self):
        payload = self._prepare("local-slurm", self.executable)
        self.assertEqual(payload["kind"], "entity-ledger.record.run-prepare")
        self.assertTrue(payload["state_mutated"])
        self.assertTrue(payload["created_case"])
        self.assertTrue(payload["run_id"].startswith("run-"))
        run_root = payload["run_root"]
        for name in ["input.toml", "run-manifest.json", "run.sbatch"]:
            self.assertTrue(os.path.isfile(os.path.join(run_root, name)), name)
        case = self.store.resolve_project(self.project)
        self.assertEqual(case["current"]["run_id"], payload["run_id"])
        self.assertEqual(case["current"]["readiness"]["run"], "ready")
        self.assertTrue(case["current"]["source_id"].startswith("source-"))
        identity = self._run_identity()
        self.assertEqual(identity["status"], "prepared")
        self.assertEqual(identity["root"],
                         {"site_id": "local-slurm", "path": run_root})
        self.assertEqual(identity["operation_id"], "op-" + payload["run_id"][4:])
        events = self.store.export()["events"]
        self.assertEqual([item["event_type"] for item in events],
                         ["case.created", "record.run-prepare"])
        again = self._prepare("local-slurm", self.executable)
        self.assertEqual(again["run_id"], payload["run_id"])
        self.assertFalse(again["created_case"])

    def test_run_launch_submits_exactly_once(self):
        self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["kind"], "entity-ledger.record.run-launch")
        self.assertEqual(payload["status"], "submitted")
        self.assertFalse(payload["adopted"])
        self.assertEqual(payload["scheduler"]["job_id"], "42")
        self.assertEqual(payload["scheduler"]["scheduler"], "slurm")
        self.assertEqual(self.submit_count(), 1)
        identity = self._run_identity()
        self.assertEqual(identity["status"], "submitted")
        self.assertEqual(identity["scheduler"]["job_id"], "42")
        case = self.store.resolve_project(self.project)
        self.assertEqual(case["current"]["readiness"]["run"], "submitted")
        code, again = self._launch()
        self.assertEqual(code, 0, again)
        self.assertEqual(again["scheduler"]["job_id"], "42")
        self.assertEqual(self.submit_count(), 1)

    def test_run_launch_slurm_preflight_rejection_blocks_without_writes(self):
        prepared = self._prepare("local-slurm", self.executable)
        os.environ["FAKE_SBATCH_REJECT"] = "Invalid qos specification"
        try:
            code, payload = self._launch()
        finally:
            os.environ["FAKE_SBATCH_REJECT"] = ""
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["state_mutated"])
        self.assertIn("invalid qos", payload["error"].lower())
        # the executor's remediation hint is passed through
        self.assertIn("entityctl site discover", payload["error"])
        self.assertEqual(self.submit_count(), 0)
        identity = self._run_identity()
        self.assertEqual(identity["status"], "prepared")
        self.assertNotIn("scheduler", identity)
        events = [item["event_type"] for item in self.store.export()["events"]]
        self.assertNotIn("record.run-launch", events)
        # fixing the scheduler-side problem lets the same run launch
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["scheduler"]["job_id"], "42")
        self.assertEqual(self.submit_count(), 1)
        receipts = os.listdir(os.path.join(
            self.staging_root, self.store.resolve_project(self.project)["case_uid"],
            "op-" + prepared["run_id"][4:], "receipts"))
        self.assertIn("run-preflight.json", receipts)

    def test_run_launch_direct_skips_preflight(self):
        prepared = self._prepare(
            "local-direct", self._direct_executable("sleep 30"))
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["scheduler"]["scheduler"], "direct")
        self._track_process_group()
        receipts = os.listdir(os.path.join(
            self.staging_root, self.store.resolve_project(self.project)["case_uid"],
            "op-" + prepared["run_id"][4:], "receipts"))
        self.assertNotIn("run-preflight.json", receipts)

    def test_run_launch_requires_a_known_run(self):
        code, payload = self._launch()
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["status"], "needs_decision")
        self.assertEqual(self.submit_count(), 0)

    def test_run_launch_adopt_slurm_job(self):
        prepared = self._prepare("local-slurm", self.executable)
        with open(self.record, "w") as handle:
            json.dump({"job_id": "42", "job_name": "entity-manual",
                       "user": "tester", "submitted_at": "2026-07-23T00:00:00",
                       "state": "RUNNING", "run_root": prepared["run_root"],
                       "comment": "manual"}, handle)
        code, payload = self._launch(["--adopt-job", "42"])
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["adopted"])
        self.assertEqual(payload["scheduler"]["job_id"], "42")
        self.assertEqual(self.submit_count(), 0)
        identity = self._run_identity()
        self.assertEqual(identity["status"], "submitted")
        self.assertTrue(identity["scheduler"]["adopted"])
        self.assertEqual(identity["scheduler"]["job_id"], "42")

    def test_run_launch_adopt_rejects_unknown_job(self):
        self._prepare("local-slurm", self.executable)
        code, payload = self._launch(["--adopt-job", "99"])
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["state_mutated"])
        identity = self._run_identity()
        self.assertEqual(identity["status"], "prepared")
        self.assertNotIn("scheduler", identity)

    def test_run_launch_adopt_direct_process(self):
        prepared = self._prepare(
            "local-direct", self._direct_executable("sleep 30"))
        reaped = subprocess.Popen(["true"])
        reaped.wait()
        code, payload = self._launch(["--adopt-pid", str(reaped.pid)])
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["state_mutated"])
        process = subprocess.Popen(
            ["sleep", "30"], cwd=prepared["run_root"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        self._pgids.append(process.pid)
        try:
            code, payload = self._launch(["--adopt-pid", str(process.pid)])
            self.assertEqual(code, 0, payload)
            self.assertTrue(payload["adopted"])
            self.assertEqual(payload["scheduler"]["pid"], process.pid)
            self.assertEqual(payload["scheduler"]["scheduler"], "direct")
            identity = self._run_identity()
            self.assertEqual(identity["status"], "submitted")
            self.assertTrue(identity["scheduler"]["adopted"])
        finally:
            process.kill()
            process.wait()

    def test_run_launch_direct_books_pid_and_exit_reports_running(self):
        prepared = self._prepare(
            "local-direct", self._direct_executable("sleep 30"))
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["scheduler"]["scheduler"], "direct")
        self.assertIsInstance(payload["scheduler"]["pid"], int)
        self._track_process_group()
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "running")
        self.assertFalse(probed["state_mutated"])
        self.assertEqual(self._run_identity()["status"], "submitted")
        exit_file = os.path.join(prepared["run_root"], ".entity-exit-code")
        self.assertFalse(os.path.isfile(exit_file))

    def test_run_exit_direct_completed(self):
        prepared = self._prepare(
            "local-direct", self._direct_executable("exit 0"))
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._track_process_group()
        exit_file = os.path.join(prepared["run_root"], ".entity-exit-code")
        self.assertEqual(self._wait_exit_file(exit_file), "0")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "completed")
        self.assertEqual(probed["exit_code"], 0)
        self.assertTrue(probed["state_mutated"])
        identity = self._run_identity()
        self.assertEqual(identity["status"], "completed")
        self.assertEqual(identity["exit_code"], 0)
        self.assertTrue(identity["observed_at"])
        case = self.store.resolve_project(self.project)
        self.assertEqual(case["current"]["readiness"]["run"], "completed")
        code, again = self.cli("record", "run-exit",
                               "--project-root", self.project)
        self.assertEqual(code, 0, again)
        self.assertEqual(again["state"], "completed")
        self.assertFalse(again["state_mutated"])

    def test_run_exit_direct_failed(self):
        prepared = self._prepare(
            "local-direct", self._direct_executable("exit 124"))
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._track_process_group()
        exit_file = os.path.join(prepared["run_root"], ".entity-exit-code")
        self.assertEqual(self._wait_exit_file(exit_file), "124")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "failed")
        self.assertEqual(probed["exit_code"], 124)
        identity = self._run_identity()
        self.assertEqual(identity["status"], "failed")
        self.assertEqual(identity["exit_code"], 124)
        case = self.store.resolve_project(self.project)
        self.assertEqual(case["current"]["readiness"]["run"], "failed")

    def _sacct_terminal(self, state, exit_code):
        os.unlink(self.record)
        sacct_record = os.path.join(self.temp, "sacct.json")
        with open(sacct_record, "w") as handle:
            json.dump({"job_id": "42", "state": state,
                       "exit_code": exit_code,
                       "run_root": self._run_identity()["root"]["path"]},
                      handle)
        os.environ["FAKE_SACCT_RECORD"] = sacct_record

    def test_run_exit_slurm_completed_via_sacct(self):
        self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._sacct_terminal("COMPLETED", "0:0")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "completed")
        self.assertEqual(probed["exit_code"], 0)
        identity = self._run_identity()
        self.assertEqual(identity["status"], "completed")
        self.assertEqual(identity["scheduler"]["state"], "COMPLETED")

    def test_run_exit_slurm_failed_via_sacct(self):
        self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        code, running = self.cli("record", "run-exit",
                                 "--project-root", self.project)
        self.assertEqual(code, 0, running)
        self.assertEqual(running["state"], "running")
        self.assertFalse(running["state_mutated"])
        self._sacct_terminal("FAILED", "1:0")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "failed")
        self.assertEqual(probed["exit_code"], 1)
        self.assertTrue(probed["state_mutated"])
        identity = self._run_identity()
        self.assertEqual(identity["status"], "failed")
        self.assertEqual(identity["exit_code"], 1)
        self.assertEqual(identity["scheduler"]["state"], "FAILED")

    _TEARDOWN_ERR = (
        "Entity runtime shutdown\n"
        "malloc_consolidate(): invalid chunk size\n"
        "srun: error: gpu1: task 0: Aborted\n")
    _COMPLETE_OUT_ANSI = (
        "\x1b[0m\x1b[90m\x1b[0mStep:\x1b[0m\x1b[90m \x1b[92m7998\x1b[0m"
        "\x1b[90m .... \x1b[90m[of 8000]\x1b[0m\n"
        "\x1b[0m\x1b[90m\x1b[0mStep:\x1b[0m\x1b[90m \x1b[92m7999\x1b[0m"
        "\x1b[90m .... \x1b[90m[of 8000]\x1b[0m\n")
    _INCOMPLETE_OUT_ANSI = (
        "\x1b[0m\x1b[90m\x1b[0mStep:\x1b[0m\x1b[90m \x1b[92m50\x1b[0m"
        "\x1b[90m .... \x1b[90m[of 8000]\x1b[0m\n")

    def _write_log(self, run_root, name, text):
        with open(os.path.join(run_root, name), "w") as handle:
            handle.write(text)

    def test_run_exit_slurm_teardown_abort_books_completed_with_anomaly(self):
        prepared = self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._sacct_terminal("FAILED", "6:0")
        self._write_log(prepared["run_root"], "simulation.err",
                        self._TEARDOWN_ERR)
        self._write_log(prepared["run_root"], "simulation.out",
                        self._COMPLETE_OUT_ANSI)
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "completed")
        self.assertEqual(probed["exit_code"], 6)
        self.assertTrue(probed["state_mutated"])
        anomaly = probed["exit_anomaly"]
        self.assertEqual(anomaly["kind"], "exit-teardown-abort")
        self.assertEqual(anomaly["signature"], "malloc_consolidate()")
        self.assertEqual(anomaly["last_step"], 7999)
        self.assertEqual(anomaly["total_steps"], 8000)
        identity = self._run_identity()
        self.assertEqual(identity["status"], "completed")
        self.assertEqual(identity["exit_code"], 6)
        self.assertEqual(identity["exit_anomaly"], anomaly)
        case = self.store.resolve_project(self.project)
        self.assertEqual(case["current"]["readiness"]["run"], "completed")
        board = build_dashboard(self.store, self.project)["board"]
        self.assertEqual(board["run"]["state"], "completed")
        self.assertIn("退出阶段已知无害 abort", board["run"]["detail"])

    def test_run_exit_teardown_evidence_from_merged_slurm_out(self):
        # regression: slurm merges stderr into the out file by default, and
        # Entity names its logs after simulation.name inside the output
        # subdirectory — both must count as teardown evidence
        prepared = self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._sacct_terminal("FAILED", "6:0")
        self._write_log(prepared["run_root"], "slurm-42.out",
                        self._COMPLETE_OUT_ANSI + self._TEARDOWN_ERR)
        subdir = os.path.join(prepared["run_root"], "twostream-gold")
        os.makedirs(subdir)
        self._write_log(subdir, "twostream-gold.err", self._TEARDOWN_ERR)
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "completed")
        self.assertEqual(probed["exit_anomaly"]["kind"], "exit-teardown-abort")

    def test_run_exit_slurm_teardown_signature_without_completion_stays_failed(self):
        prepared = self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._sacct_terminal("FAILED", "6:0")
        self._write_log(prepared["run_root"], "simulation.err",
                        self._TEARDOWN_ERR)
        self._write_log(prepared["run_root"], "simulation.out",
                        self._INCOMPLETE_OUT_ANSI)
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "failed")
        self.assertEqual(probed["exit_code"], 6)
        self.assertIsNone(probed["exit_anomaly"])
        identity = self._run_identity()
        self.assertEqual(identity["status"], "failed")
        self.assertNotIn("exit_anomaly", identity)

    def test_run_exit_slurm_completion_without_teardown_signature_stays_failed(self):
        prepared = self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._sacct_terminal("FAILED", "6:0")
        self._write_log(prepared["run_root"], "simulation.err",
                        "Segmentation fault (core dumped)\n")
        self._write_log(prepared["run_root"], "simulation.out",
                        self._COMPLETE_OUT_ANSI)
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "failed")
        self.assertIsNone(probed["exit_anomaly"])
        self.assertEqual(self._run_identity()["status"], "failed")

    def test_run_exit_slurm_missing_logs_stays_failed(self):
        self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._sacct_terminal("FAILED", "6:0")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "failed")
        self.assertEqual(probed["exit_code"], 6)
        self.assertIsNone(probed["exit_anomaly"])
        self.assertEqual(self._run_identity()["status"], "failed")

    def test_run_exit_direct_teardown_abort_books_completed_with_anomaly(self):
        prepared = self._prepare(
            "local-direct", self._direct_executable("exit 134"))
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._track_process_group()
        exit_file = os.path.join(prepared["run_root"], ".entity-exit-code")
        self.assertEqual(self._wait_exit_file(exit_file), "134")
        self._write_log(
            prepared["run_root"], "run.log",
            self._COMPLETE_OUT_ANSI +
            "malloc_consolidate(): unaligned fastbin chunk detected\n"
            "Aborted\n")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "completed")
        self.assertEqual(probed["exit_code"], 134)
        anomaly = probed["exit_anomaly"]
        self.assertEqual(anomaly["kind"], "exit-teardown-abort")
        self.assertEqual(anomaly["last_step"], 7999)
        self.assertEqual(anomaly["total_steps"], 8000)
        self.assertEqual(self._run_identity()["status"], "completed")

    def test_run_exit_reclassify_failed_run_with_late_log_evidence(self):
        prepared = self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._sacct_terminal("FAILED", "6:0")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "failed")
        self.assertIsNone(probed["exit_anomaly"])
        # the logs are inspected only later (e.g. fetched by hand)
        self._write_log(prepared["run_root"], "simulation.err",
                        self._TEARDOWN_ERR)
        self._write_log(prepared["run_root"], "simulation.out",
                        self._COMPLETE_OUT_ANSI)
        code, again = self.cli("record", "run-exit",
                               "--project-root", self.project)
        self.assertEqual(code, 0, again)
        self.assertEqual(again["state"], "failed")
        self.assertFalse(again["state_mutated"])
        code, fixed = self.cli("record", "run-exit",
                               "--project-root", self.project, "--reclassify")
        self.assertEqual(code, 0, fixed)
        self.assertEqual(fixed["state"], "completed")
        self.assertTrue(fixed["state_mutated"])
        self.assertTrue(fixed["reclassified"])
        self.assertEqual(fixed["exit_code"], 6)
        self.assertEqual(fixed["exit_anomaly"]["last_step"], 7999)
        identity = self._run_identity()
        self.assertEqual(identity["status"], "completed")
        self.assertEqual(identity["exit_code"], 6)
        self.assertEqual(identity["exit_anomaly"]["kind"],
                         "exit-teardown-abort")
        case = self.store.resolve_project(self.project)
        self.assertEqual(case["current"]["readiness"]["run"], "completed")

    def test_run_exit_reclassify_true_failure_leaves_state_untouched(self):
        self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._sacct_terminal("FAILED", "1:0")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "failed")
        events_before = len(self.store.export()["events"])
        code, again = self.cli("record", "run-exit",
                               "--project-root", self.project, "--reclassify")
        self.assertEqual(code, 0, again)
        self.assertEqual(again["state"], "failed")
        self.assertFalse(again["state_mutated"])
        self.assertIn("detail", again)
        self.assertEqual(self._run_identity()["status"], "failed")
        self.assertEqual(len(self.store.export()["events"]), events_before)

    def test_run_exit_reclassify_completed_run_errors_without_writes(self):
        self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._sacct_terminal("COMPLETED", "0:0")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "completed")
        events_before = len(self.store.export()["events"])
        code, refused = self.cli("record", "run-exit",
                                 "--project-root", self.project,
                                 "--reclassify")
        self.assertEqual(code, 2, refused)
        self.assertFalse(refused["ok"])
        self.assertFalse(refused["state_mutated"])
        self.assertEqual(self._run_identity()["status"], "completed")
        self.assertEqual(len(self.store.export()["events"]), events_before)

    def test_run_launch_after_adopt_does_not_resubmit(self):
        prepared = self._prepare("local-slurm", self.executable)
        with open(self.record, "w") as handle:
            json.dump({"job_id": "42", "job_name": "entity-manual",
                       "user": "tester", "submitted_at": "2026-07-23T00:00:00",
                       "state": "RUNNING", "run_root": prepared["run_root"],
                       "comment": "manual"}, handle)
        code, payload = self._launch(["--adopt-job", "42"])
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["adopted"])
        # an adopted run leaves no executor receipt; a plain re-launch must
        # claim the recorded scheduler identity, not submit a second job
        code, again = self._launch()
        self.assertEqual(code, 0, again)
        self.assertFalse(again["state_mutated"])
        self.assertTrue(again["adopted"])
        self.assertEqual(again["scheduler"]["job_id"], "42")
        self.assertEqual(self.submit_count(), 0)

    def test_launch_recovery_claims_pre_rename_comment(self):
        prepared = self._prepare("local-slurm", self.executable)
        identity = self._run_identity()
        operation_id = identity["operation_id"]
        plan_hash = identity["plan_hash"]
        receipt = os.path.join(
            identity["staging_root"], "receipts", "run-launch.json")
        now = datetime.datetime.utcnow().replace(microsecond=0)
        with open(receipt, "w") as handle:
            json.dump({
                "schema_version": 1, "operation_id": operation_id,
                "plan_hash": plan_hash, "step_index": 2, "step_id": "launch",
                "kind": "run.launch.v2", "state": "intent_written",
                "attempt": 1, "intent_written_at": now.isoformat() + "Z",
                "effect_identity": {}, "outputs": [],
                "stdout": {}, "stderr": {},
                "updated_at": now.isoformat() + "Z"}, handle)
        # the in-flight job was submitted before the router -> ledger rename
        # and carries the old comment prefix; recovery must claim it
        legacy_comment = "entity-router:%s:%s" % (
            operation_id, plan_hash.split(":", 1)[-1][:16])
        with open(self.record, "w") as handle:
            json.dump({"job_id": "42", "job_name": "entity-" + operation_id,
                       "user": "tester",
                       "submitted_at": datetime.datetime.now().replace(
                           microsecond=0).isoformat(),
                       "state": "RUNNING", "run_root": prepared["run_root"],
                       "comment": legacy_comment}, handle)
        code, claimed = self._launch()
        self.assertEqual(code, 0, claimed)
        self.assertEqual(claimed["scheduler"]["job_id"], "42")
        self.assertEqual(self.submit_count(), 0)
        scheduler = self._run_identity()["scheduler"]
        self.assertEqual(scheduler["comment"], legacy_comment)

    def test_run_prepare_refuses_an_advanced_run(self):
        self._prepare("local-slurm", self.executable)
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        argv = ["record", "run-prepare", "--project-root", self.project,
                "--toml", "input.toml", "--site", "local-slurm",
                "--executable", self.executable]
        code, refused = self.cli(*argv)
        self.assertEqual(code, 2, refused)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["status"], "needs_decision")
        self.assertFalse(refused["state_mutated"])
        self.assertEqual(self._run_identity()["status"], "submitted")
        self._sacct_terminal("COMPLETED", "0:0")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(probed["state"], "completed")
        code, refused = self.cli(*argv)
        self.assertEqual(code, 2, refused)
        self.assertFalse(refused["ok"])
        self.assertIn("derive a new run", refused["error"])
        identity = self._run_identity()
        self.assertEqual(identity["status"], "completed")

    def test_run_prepare_executor_failure_leaves_store_untouched(self):
        import entity_ledger_record
        from entity_ledger_operation import OperationError
        with mock.patch.object(entity_ledger_record, "ExecutorClient") as client:
            client.return_value.invoke.side_effect = OperationError("boom")
            with self.assertRaises(OperationError):
                entity_ledger_record.record_run_prepare(
                    self.store, self.project, "input.toml", "local-slurm",
                    1, "01:00:00", "double", self.executable, {"run_id": "t"})
        exported = self.store.export()
        self.assertEqual(exported["cases"], [])
        self.assertEqual(exported["projects"], [])
        self.assertEqual(exported["events"], [])

    def test_run_exit_direct_unknown_on_partial_exit_file(self):
        prepared = self._prepare(
            "local-direct", self._direct_executable("sleep 30"))
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._track_process_group()
        scheduler = self._run_identity()["scheduler"]
        os.killpg(scheduler["pgid"], signal.SIGKILL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(scheduler["pid"], 0)
            except OSError:
                break
            time.sleep(0.1)
        # a half-written exit file plus a dead process is not enough
        # evidence for a terminal state
        exit_file = os.path.join(prepared["run_root"], ".entity-exit-code")
        with open(exit_file, "w") as handle:
            handle.write("par")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "unknown")
        self.assertFalse(probed["state_mutated"])
        self.assertEqual(self._run_identity()["status"], "submitted")

    def test_dashboard_follows_run_lifecycle(self):
        prepared = self._prepare(
            "local-direct", self._direct_executable("exit 0"))
        board = build_dashboard(self.store, self.project)["board"]
        self.assertEqual(board["run"]["state"], "prepared")
        code, payload = self._launch()
        self.assertEqual(code, 0, payload)
        self._track_process_group()
        board = build_dashboard(self.store, self.project)["board"]
        self.assertEqual(board["run"]["state"], "submitted")
        exit_file = os.path.join(prepared["run_root"], ".entity-exit-code")
        self.assertEqual(self._wait_exit_file(exit_file), "0")
        code, probed = self.cli("record", "run-exit",
                                "--project-root", self.project)
        self.assertEqual(code, 0, probed)
        self.assertEqual(probed["state"], "completed")
        case = self.store.resolve_project(self.project)
        self.assertEqual(case["current"]["readiness"]["run"], "completed")
        board = build_dashboard(self.store, self.project)["board"]
        self.assertEqual(board["run"]["state"], "completed")


if __name__ == "__main__":
    unittest.main()
