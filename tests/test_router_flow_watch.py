from __future__ import print_function

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
STATE = os.path.join(SCRIPTS, "entity_router_state.py")
SITE = os.path.join(SCRIPTS, "entity_router_site.py")
FLOW = os.path.join(SCRIPTS, "entity_router_flow.py")

class RouterFlowWatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-flow-watch-")
        self.home = os.path.join(self.temp, "control")
        self.site = os.path.join(self.temp, "site")
        self.source = os.path.join(self.site, "source")
        self.bin = os.path.join(self.temp, "bin")
        os.makedirs(os.path.join(self.source, "docs"))
        os.makedirs(self.bin)
        self.write(os.path.join(self.source, "pgen.hpp"), "// pgen\n")
        self.write(os.path.join(self.source, "input.toml"), "[simulation]\n")
        self.write(os.path.join(self.source, "docs", "design.md"), "# Design\n")
        subprocess.check_call(["git", "init", "-q", self.source])
        subprocess.check_call(["git", "-C", self.source, "config", "user.email", "test@example.invalid"])
        subprocess.check_call(["git", "-C", self.source, "config", "user.name", "Watch Test"])
        subprocess.check_call(["git", "-C", self.source, "add", "."])
        subprocess.check_call(["git", "-C", self.source, "commit", "-qm", "fixture"])
        self.add_site("local", self.temp, "none")
        self.add_site("slurm", self.site, "slurm")
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin + os.pathsep + self.old_path
        self.write(os.path.join(self.bin, "sbatch"), "#!/bin/sh\nprintf '42\\n'\n", True)
        self.case, self.target_hash, self.run_root = self.prepare_run()

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        shutil.rmtree(self.temp)

    def write(self, path, value, executable=False):
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w") as handle:
            handle.write(value)
        if executable:
            os.chmod(path, 0o755)

    def cli(self, script, *args):
        process = subprocess.run(
            [sys.executable, script, "--router-home", self.home] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertTrue(process.stdout.strip(), process.stderr)
        return process.returncode, json.loads(process.stdout)

    def add_site(self, site_id, root, scheduler):
        args = ["add", "--site-id", site_id, "--transport", "local", "--scheduler", scheduler]
        for name in ["source", "build", "run", "deps", "staging", "analysis"]:
            path = os.path.join(root, name)
            os.makedirs(path, exist_ok=True)
            args.extend(["--%s-root" % name, path])
        code, payload = self.cli(SITE, *args)
        self.assertEqual(code, 0, payload)

    def prepare_run(self):
        build_base = os.path.join(self.site, "build")
        run_base = os.path.join(self.site, "run")
        analysis_base = os.path.join(self.site, "analysis")
        code, case = self.cli(
            STATE, "create", "--case-id", "watch",
            "--source-authority", "slurm:%s" % self.source,
            "--pgen-locator", "slurm:%s" % os.path.join(self.source, "pgen.hpp"),
            "--toml-locator", "slurm:%s" % os.path.join(self.source, "input.toml"),
            "--design-locator", "slurm:%s" % os.path.join(self.source, "docs", "design.md"),
            "--build-root", "slurm:%s" % build_base,
            "--run-root", "slurm:%s" % run_base,
            "--data-root", "slurm:%s" % run_base,
            "--analysis-root", "slurm:%s" % analysis_base,
            "--goal", "watch a prepared run",
        )
        self.assertEqual(code, 0, case)
        code, unused = self.cli(
            STATE, "reconcile", "--case", case["case_uid"], "--expected-revision", "0",
            "--readiness", "pgen=verified",
            "--evidence", "pgen=slurm:%s" % os.path.join(self.source, "pgen.hpp"),
        )
        self.assertEqual(code, 0, unused)
        target_path = os.path.join(self.temp, "target.json")
        self.write(target_path, json.dumps({
            "schema_version": 1, "target_id": "watch-target", "source_revision_hash": "",
            "build_id": "build-watch", "build_spec_hash": "", "run_id": "run-watch",
            "run_spec_hash": "", "data_id": "", "analysis_id": "", "criteria": [],
        }))
        code, targeted = self.cli(
            STATE, "set-workflow-target", "--case", case["case_uid"],
            "--expected-revision", "1", "--target", target_path,
        )
        self.assertEqual(code, 0, targeted)
        build_root = os.path.join(build_base, "build-watch")
        code, started = self.cli(
            STATE, "start-action", "--case", case["case_uid"], "--expected-revision", "2",
            "--action-id", "build-watch", "--action-type", "build.compile",
            "--owner", "entity-env-build", "--execution-domain", "entity-env-build",
            "--execution-site", "slurm", "--identity-id", "build-watch",
            "--goal", "fixture build", "--write-root", "slurm:%s" % build_root,
        )
        self.assertEqual(code, 0, started)
        executable = os.path.join(build_root, "entity.xc")
        self.write(executable, "binary\n")
        code, finished = self.cli(
            STATE, "finish-action", "--case", case["case_uid"], "--expected-revision", "3",
            "--action-id", "build-watch", "--status", "completed",
            "--output", "slurm:%s" % executable, "--readiness", "build=pass",
        )
        self.assertEqual(code, 0, finished)
        run_root = os.path.join(run_base, "run-watch")
        data_root = os.path.join(run_root, "data")
        analysis_root = os.path.join(analysis_base, "run-watch")
        code, started = self.cli(
            STATE, "start-action", "--case", case["case_uid"], "--expected-revision", "4",
            "--action-id", "prepare-watch", "--action-type", "run.prepare",
            "--owner", "playbook-run", "--execution-domain", "playbook-run",
            "--execution-site", "slurm", "--identity-id", "run-watch", "--goal", "prepare",
            "--write-root", "slurm:%s" % run_root,
            "--resource-binding", "run=slurm:%s" % run_root,
            "--resource-binding", "data=slurm:%s" % data_root,
            "--resource-binding", "analysis=slurm:%s" % analysis_root,
        )
        self.assertEqual(code, 0, started)
        manifest = os.path.join(run_root, "manifest.json")
        self.write(manifest, "{}\n")
        self.write(os.path.join(run_root, "submit.sh"), "#!/bin/sh\n", True)
        code, finished = self.cli(
            STATE, "finish-action", "--case", case["case_uid"], "--expected-revision", "5",
            "--action-id", "prepare-watch", "--status", "completed",
            "--output", "slurm:%s" % manifest, "--readiness", "run=prepared",
        )
        self.assertEqual(code, 0, finished)
        return case, targeted["target_hash"], run_root

    def save_flow(self, name, base_revision, step):
        value = {
            "schema_version": 1, "flow_id": name, "case_uid": self.case["case_uid"],
            "base_revision": base_revision, "workflow_id": "wf-initial",
            "target_hash": self.target_hash, "goal": name, "steps": [step],
            "stop_policy": {"on_completed": "continue", "on_needs_decision": "return",
                            "on_blocked": "return", "on_anomaly": "return"},
        }
        path = os.path.join(self.temp, name + ".json")
        self.write(path, json.dumps(value))
        return path

    def base_step(self, action_id, action_type, runner, write_path, runner_args):
        return {
            "index": 0, "action_id": action_id, "action_type": action_type,
            "owner": "playbook-run", "execution_domain": "playbook-run",
            "execution_site_id": "slurm", "runner": runner, "identity_id": "",
            "spec_hash": "", "parents": {}, "input_from": [], "inputs": [],
            "read_roots": [{"site_id": "slurm", "path": self.run_root}],
            "write_roots": [{"site_id": "slurm", "path": write_path}],
            "protected_paths": [], "resource_bindings": {}, "constraints": [],
            "expected_outputs": [{"site_id": "slurm", "path": write_path}],
            "acceptance_checks": ["terminal identity is verified"], "runner_args": runner_args,
        }

    def launch(self):
        receipt = os.path.join(self.run_root, "launch-receipt.json")
        step = self.base_step("launch-watch", "run.launch", "run.launch.v1", self.run_root, {
            "run_root": {"site_id": "slurm", "path": self.run_root},
            "submit_script": {"site_id": "slurm", "path": os.path.join(self.run_root, "submit.sh")},
            "job_name": "entity-watch", "submit_user": "tester",
            "receipt": {"site_id": "slurm", "path": receipt},
        })
        step["expected_outputs"] = [{"site_id": "slurm", "path": receipt}]
        code, payload = self.cli(FLOW, "execute", "--request", self.save_flow("launch-flow", 6, step))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["revision"], 8)

    def start_monitor(self):
        trace = os.path.join(self.run_root, "monitor.jsonl")
        step = self.base_step("monitor-watch", "run.monitor", "run.monitor.v1", trace, {
            "run_root": {"site_id": "slurm", "path": self.run_root},
            "trace": {"site_id": "slurm", "path": trace}, "job_id": "42",
        })
        path = self.save_flow("monitor-flow", 8, step)
        code, payload = self.cli(FLOW, "execute", "--request", path)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "observe_only")
        self.assertEqual(payload["revision"], 9)
        import hashlib
        with open(path, "r") as handle:
            request_value = json.load(handle)
        request_hash = "sha256:" + hashlib.sha256(
            json.dumps(request_value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return request_hash

    def test_terminal_watch_finishes_active_action(self):
        self.launch()
        self.write(os.path.join(self.bin, "squeue"), "#!/bin/sh\nexit 0\n", True)
        self.write(os.path.join(self.bin, "sacct"),
                   "#!/bin/sh\nprintf '42|COMPLETED|00:01|0:0\\n'\n", True)
        flow_hash = self.start_monitor()
        code, payload = self.cli(
            FLOW, "watch", "--case", self.case["case_uid"], "--action", "monitor-watch",
            "--flow-request-hash", flow_hash, "--interval-seconds", "0",
            "--timeout-seconds", "1",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["revision"], 10)

    def test_terminal_without_exit_code_is_blocked(self):
        self.launch()
        self.write(os.path.join(self.bin, "squeue"),
                   "#!/bin/sh\nprintf '42|COMPLETED|00:01|node\\n'\n", True)
        flow_hash = self.start_monitor()
        code, payload = self.cli(
            FLOW, "watch", "--case", self.case["case_uid"], "--action", "monitor-watch",
            "--flow-request-hash", flow_hash, "--interval-seconds", "0",
            "--timeout-seconds", "1",
        )
        self.assertEqual(code, 20, payload)
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("exit code", payload["issues"][0]["message"])

    def test_launch_receipt_supplies_monitor_job_identity(self):
        receipt = {"site_id": "slurm",
                   "path": os.path.join(self.run_root, "launch-receipt.json")}
        launch_step = self.base_step(
            "launch-watch", "run.launch", "run.launch.v1", self.run_root, {
                "run_root": {"site_id": "slurm", "path": self.run_root},
                "submit_script": {"site_id": "slurm", "path": os.path.join(
                    self.run_root, "submit.sh")},
                "job_name": "entity-watch", "submit_user": "tester", "receipt": receipt,
            })
        launch_step["expected_outputs"] = [receipt]
        step = self.base_step("monitor-derived", "run.monitor", "run.monitor.v1",
                              os.path.join(self.run_root, "derived-trace.jsonl"), {
                                  "run_root": {"site_id": "slurm", "path": self.run_root},
                                  "trace": {"site_id": "slurm", "path": os.path.join(
                                      self.run_root, "derived-trace.jsonl")},
                              })
        step["index"] = 1
        step["input_from"] = [{"step_index": 0, "role": "launch_receipt",
                               "expected_locator": receipt}]
        value = {
            "schema_version": 1, "flow_id": "launch-monitor-flow",
            "case_uid": self.case["case_uid"], "base_revision": 6,
            "workflow_id": "wf-initial", "target_hash": self.target_hash,
            "goal": "launch and monitor with derived identity", "steps": [launch_step, step],
            "stop_policy": {"on_completed": "continue", "on_needs_decision": "return",
                            "on_blocked": "return", "on_anomaly": "return"},
        }
        path = os.path.join(self.temp, "launch-monitor-flow.json")
        self.write(path, json.dumps(value))
        code, payload = self.cli(FLOW, "execute", "--request", path)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "observe_only")
        request_path = os.path.join(
            self.case["case_dir"], "actions", "monitor-derived", "request.json"
        )
        with open(request_path) as handle:
            monitor_request = json.load(handle)
        self.assertEqual(monitor_request["runner_args"]["job_id"], "42")

    def test_timeout_suppresses_unchanged_polls_and_closes_action(self):
        self.launch()
        self.write(os.path.join(self.bin, "squeue"),
                   "#!/bin/sh\nprintf '42|RUNNING|00:01|node\\n'\n", True)
        flow_hash = self.start_monitor()
        code, payload = self.cli(
            FLOW, "watch", "--case", self.case["case_uid"], "--action", "monitor-watch",
            "--flow-request-hash", flow_hash, "--interval-seconds", "0.001",
            "--timeout-seconds", "1",
        )
        self.assertEqual(code, 20, payload)
        self.assertEqual(payload["status"], "blocked")
        self.assertGreater(payload["result"]["unchanged_polls_suppressed"], 0)


if __name__ == "__main__":
    unittest.main()
