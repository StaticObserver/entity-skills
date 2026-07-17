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
STATE = os.path.join(SCRIPTS, "entity_router_state.py")
SITE = os.path.join(SCRIPTS, "entity_router_site.py")
FLOW = os.path.join(SCRIPTS, "entity_router_flow.py")


class RouterFlowWorkerResumeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-worker-resume-")
        self.home = os.path.join(self.temp, "control")
        self.source = os.path.join(self.temp, "source")
        self.data = os.path.join(self.temp, "run", "data")
        self.analysis = os.path.join(self.temp, "analysis")
        os.makedirs(os.path.join(self.source, "docs"))
        os.makedirs(self.data)
        os.makedirs(self.analysis)
        for path, value in [
                (os.path.join(self.source, "pgen.hpp"), "// pgen\n"),
                (os.path.join(self.source, "input.toml"), "[simulation]\n"),
                (os.path.join(self.source, "docs", "design.md"), "# Design\n")]:
            self.write(path, value)
        subprocess.check_call(["git", "init", "-q", self.source])
        subprocess.check_call(["git", "-C", self.source, "config", "user.email", "test@example.invalid"])
        subprocess.check_call(["git", "-C", self.source, "config", "user.name", "Worker Test"])
        subprocess.check_call(["git", "-C", self.source, "add", "."])
        subprocess.check_call(["git", "-C", self.source, "commit", "-qm", "fixture"])
        self.add_site()
        self.case = self.create_case()
        self.target_hash = self.set_target()
        self.seed_ready_data()
        self.request = self.write_flow()

    def tearDown(self):
        shutil.rmtree(self.temp)

    def write(self, path, value):
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w") as handle:
            handle.write(value)

    def cli(self, script, *args):
        process = subprocess.run(
            [sys.executable, script, "--router-home", self.home] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertTrue(process.stdout.strip(), process.stderr)
        return process.returncode, json.loads(process.stdout)

    def add_site(self):
        code, payload = self.cli(
            SITE, "add", "--site-id", "local", "--transport", "local",
            "--source-root", self.source, "--run-root", os.path.dirname(self.data),
            "--analysis-root", self.analysis, "--build-root", os.path.join(self.temp, "build"),
            "--staging-root", self.analysis,
        )
        self.assertEqual(code, 0, payload)

    def create_case(self):
        code, payload = self.cli(
            STATE, "create", "--case-id", "worker",
            "--source-authority", "local:%s" % self.source,
            "--pgen-locator", "local:%s" % os.path.join(self.source, "pgen.hpp"),
            "--toml-locator", "local:%s" % os.path.join(self.source, "input.toml"),
            "--design-locator", "local:%s" % os.path.join(self.source, "docs", "design.md"),
            "--run-root", "local:%s" % os.path.dirname(self.data),
            "--data-root", "local:%s" % self.data,
            "--analysis-root", "local:%s" % self.analysis,
            "--goal", "resume a model Worker",
        )
        self.assertEqual(code, 0, payload)
        return payload

    def set_target(self):
        path = os.path.join(self.temp, "target.json")
        self.write(path, json.dumps({
            "schema_version": 1, "target_id": "worker-target", "source_revision_hash": "",
            "build_id": "", "build_spec_hash": "", "run_id": "",
            "run_spec_hash": "", "data_id": "", "analysis_id": "", "criteria": [],
        }))
        code, payload = self.cli(
            STATE, "set-workflow-target", "--case", self.case["case_uid"],
            "--expected-revision", "0", "--target", path,
        )
        self.assertEqual(code, 0, payload)
        return payload["target_hash"]

    def seed_ready_data(self):
        path = os.path.join(self.case["case_dir"], "case.json")
        with open(path) as handle:
            state = json.load(handle)
        state["resources"]["run"]["current_id"] = "run-1"
        state["resources"]["run"]["active"] = {"site_id": "local", "path": os.path.dirname(self.data)}
        state["resources"]["data"]["current_id"] = "data-1"
        state["resources"]["data"]["identities"] = [{
            "id": "data-1", "kind": "data", "site_id": "local",
            "root": {"site_id": "local", "path": self.data}, "spec_hash": "",
            "parents": {"run_id": "run-1"}, "evidence": [],
        }]
        state["readiness"]["run"] = {"status": "completed", "evidence": []}
        state["readiness"]["data"] = {"status": "ready", "evidence": [{
            "kind": "observation", "value": "fixture", "observed_at": state["updated_at"],
            "observer_site": "controller",
        }]}
        state["workflow"]["allowed_actions"] = [
            "analysis.run", "data.inspect", "data.purge", "run.resume",
        ]
        state["workflow"]["next_action"] = "analysis.run"
        with open(path, "w") as handle:
            json.dump(state, handle)

    def write_flow(self):
        envelope = os.path.join(self.analysis, "worker-envelope.json")
        result = os.path.join(self.analysis, "worker-result.json")
        report = os.path.join(self.analysis, "report.md")
        step = {
            "index": 0, "action_id": "analysis-worker", "action_type": "analysis.run",
            "owner": "playbook-analysis", "execution_domain": "playbook-analysis",
            "execution_site_id": "local", "runner": "model.worker.v1",
            "identity_id": "", "spec_hash": "sha256:" + "c" * 64,
            "parents": {"data_id": "data-1"}, "input_from": [],
            "inputs": [{"site_id": "local", "path": self.data}],
            "read_roots": [{"site_id": "local", "path": self.data}],
            "write_roots": [{"site_id": "local", "path": self.analysis}],
            "protected_paths": [{"site_id": "local", "path": self.data}],
            "resource_bindings": {"analysis": {"site_id": "local", "path": self.analysis}},
            "constraints": ["raw data is read-only"],
            "expected_outputs": [{"site_id": "local", "path": report}],
            "acceptance_checks": ["report exists"],
            "runner_args": {
                "skill": "entity-nt2py", "playbook": "analyze-run",
                "worker_envelope": {"site_id": "local", "path": envelope},
                "worker_result": {"site_id": "local", "path": result},
            },
        }
        flow = {
            "schema_version": 1, "flow_id": "worker-flow", "case_uid": self.case["case_uid"],
            "base_revision": 1, "workflow_id": "wf-initial", "target_hash": self.target_hash,
            "goal": "produce a scientific report", "steps": [step],
            "stop_policy": {"on_completed": "continue", "on_needs_decision": "return",
                            "on_blocked": "return", "on_anomaly": "return"},
        }
        path = os.path.join(self.temp, "flow.json")
        self.write(path, json.dumps(flow))
        return path

    def test_prepare_resume_requires_structured_verified_outputs(self):
        code, normal = self.cli(FLOW, "execute", "--request", self.request)
        self.assertEqual(code, 10, normal)
        code, prepared = self.cli(
            FLOW, "execute", "--request", self.request, "--prepare", "--step", "0",
        )
        self.assertEqual(code, 0, prepared)
        self.assertEqual(prepared["revision"], 2)
        request_hash = prepared["result"]["steps"][0]["request_hash"]
        result_path = os.path.join(self.analysis, "worker-result.json")
        self.write(result_path, json.dumps({
            "schema_version": 1, "case_uid": self.case["case_uid"],
            "action_id": "analysis-worker", "request_hash": request_hash,
            "status": "completed", "outputs": [], "verification": ["narrative only"],
            "message": "claims success without an artifact",
        }))
        code, rejected = self.cli(
            FLOW, "execute", "--request", self.request, "--resume", "--step", "0",
        )
        self.assertEqual(code, 30, rejected)
        code, shown = self.cli(STATE, "show", "--case", self.case["case_uid"])
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["state"]["revision"], 2)
        report = os.path.join(self.analysis, "report.md")
        self.write(report, "# Result\n")
        self.write(result_path, json.dumps({
            "schema_version": 1, "case_uid": self.case["case_uid"],
            "action_id": "analysis-worker", "request_hash": request_hash,
            "status": "completed", "outputs": [{"site_id": "local", "path": report}],
            "verification": ["report inspected"], "message": "complete",
        }))
        code, resumed = self.cli(
            FLOW, "execute", "--request", self.request, "--resume", "--step", "0",
        )
        self.assertEqual(code, 0, resumed)
        self.assertEqual(resumed["revision"], 3)
        code, shown = self.cli(STATE, "show", "--case", self.case["case_uid"])
        self.assertEqual(code, 0, shown)
        identity = shown["state"]["resources"]["analysis"]["identities"][0]
        self.assertEqual(identity["parents"]["data_id"], "data-1")


if __name__ == "__main__":
    unittest.main()
