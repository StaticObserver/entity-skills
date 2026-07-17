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


class RouterFlowExecuteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-flow-execute-")
        self.home = os.path.join(self.temp, "control")
        self.source = os.path.join(self.temp, "source")
        self.build = os.path.join(self.temp, "build-site")
        os.makedirs(os.path.join(self.source, "docs"))
        os.makedirs(self.build)
        self.write(os.path.join(self.source, "pgen.hpp"), "// pgen\n")
        self.write(os.path.join(self.source, "input.toml"), "[simulation]\n")
        self.write(os.path.join(self.source, "docs", "design.md"), "# Design\n")
        subprocess.check_call(["git", "init", "-q", self.source])
        subprocess.check_call(["git", "-C", self.source, "config", "user.email", "test@example.invalid"])
        subprocess.check_call(["git", "-C", self.source, "config", "user.name", "Flow Execute Test"])
        subprocess.check_call(["git", "-C", self.source, "add", "."])
        subprocess.check_call(["git", "-C", self.source, "commit", "-qm", "fixture"])
        self.add_site("local", self.temp)
        self.add_site("source", self.source)
        self.add_site("build", self.build)
        self.case = self.create_case()
        code, reconciled = self.cli(
            STATE, "reconcile", "--case", self.case["case_uid"],
            "--expected-revision", "0", "--readiness", "pgen=verified",
            "--evidence", "pgen=source:%s" % os.path.join(self.source, "pgen.hpp"),
        )
        self.assertEqual(code, 0, reconciled)
        target_path = os.path.join(self.temp, "target.json")
        self.write(target_path, json.dumps({
            "schema_version": 1, "target_id": "materialized-source",
            "source_revision_hash": "", "build_id": "", "build_spec_hash": "",
            "run_id": "", "run_spec_hash": "", "data_id": "", "analysis_id": "",
            "criteria": [],
        }))
        code, targeted = self.cli(
            STATE, "set-workflow-target", "--case", self.case["case_uid"],
            "--expected-revision", "1", "--target", target_path,
        )
        self.assertEqual(code, 0, targeted)
        self.target_hash = targeted["target_hash"]

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

    def add_site(self, site_id, root):
        arguments = ["add", "--site-id", site_id, "--transport", "local"]
        for name in ["source", "build", "run", "deps", "staging", "analysis"]:
            path = os.path.join(root, name)
            os.makedirs(path, exist_ok=True)
            arguments.extend(["--%s-root" % name, path])
        code, payload = self.cli(SITE, *arguments)
        self.assertEqual(code, 0, payload)

    def create_case(self):
        code, payload = self.cli(
            STATE, "create", "--case-id", "flow-execute",
            "--source-authority", "source:%s" % self.source,
            "--pgen-locator", "source:%s" % os.path.join(self.source, "pgen.hpp"),
            "--toml-locator", "source:%s" % os.path.join(self.source, "input.toml"),
            "--design-locator", "source:%s" % os.path.join(self.source, "docs", "design.md"),
            "--build-root", "build:%s" % os.path.join(self.build, "build"),
            "--run-root", "build:%s" % os.path.join(self.build, "run"),
            "--data-root", "build:%s" % os.path.join(self.build, "run"),
            "--analysis-root", "build:%s" % os.path.join(self.build, "analysis"),
            "--goal", "execute a deterministic flow",
        )
        self.assertEqual(code, 0, payload)
        return payload

    def flow_request(self, runner_args=None):
        target = os.path.join(self.build, "staging", self.case["case_uid"])
        receipt = os.path.join(target, "dispatch-receipt.json")
        step = {
            "index": 0, "action_id": "flow-source-1",
            "action_type": "source.materialize", "owner": "router",
            "execution_domain": "playbook-sync", "execution_site_id": "build",
            "runner": "source.materialize.v1", "identity_id": "", "spec_hash": "",
            "parents": {}, "input_from": [],
            "inputs": [{"site_id": "source", "path": self.source}],
            "read_roots": [{"site_id": "source", "path": self.source}],
            "write_roots": [{"site_id": "build", "path": target}],
            "protected_paths": [], "resource_bindings": {},
            "constraints": ["preserve the authoritative checkout"],
            "expected_outputs": [{"site_id": "build", "path": target}],
            "acceptance_checks": ["snapshot manifest verifies"],
            "runner_args": runner_args or {
                "mode": "snapshot",
                "source": {"site_id": "source", "path": self.source},
                "target": {"site_id": "build", "path": target},
                "receipt": {"site_id": "build", "path": receipt},
            },
        }
        return {
            "schema_version": 1, "flow_id": "flow-source-materialize",
            "case_uid": self.case["case_uid"], "base_revision": 2,
            "workflow_id": "wf-initial", "target_hash": self.target_hash,
            "goal": "materialize source once", "steps": [step],
            "stop_policy": {
                "on_completed": "continue", "on_needs_decision": "return",
                "on_blocked": "return", "on_anomaly": "return",
            },
        }

    def save_request(self, value, name="flow.json"):
        path = os.path.join(self.temp, name)
        self.write(path, json.dumps(value))
        return path

    def test_execute_completes_and_replay_is_cached(self):
        request = self.save_request(self.flow_request())
        code, payload = self.cli(FLOW, "execute", "--request", request)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["revision"], 4)
        self.assertFalse(payload["result"]["steps"][0]["cached"])
        receipt = payload["result"]["steps"][0]["receipt"]["path"]
        self.assertTrue(os.path.isfile(receipt))
        code, replay = self.cli(FLOW, "execute", "--request", request)
        self.assertEqual(code, 0, replay)
        self.assertEqual(replay["revision"], 4)
        self.assertTrue(replay["result"]["steps"][0]["cached"])

    def test_arbitrary_shell_field_is_rejected_before_action_start(self):
        request = self.flow_request()
        request["steps"][0]["runner_args"]["command"] = "touch forbidden"
        code, payload = self.cli(FLOW, "execute", "--request", self.save_request(request))
        self.assertEqual(code, 40, payload)
        self.assertEqual(payload["issues"][0]["code"], "FLOW_ARBITRARY_SHELL")
        code, shown = self.cli(STATE, "show", "--case", self.case["case_uid"])
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["state"]["revision"], 2)

    def test_runner_target_outside_write_root_is_rejected_before_action_start(self):
        request = self.flow_request()
        outside = os.path.join(self.build, "source", "outside-snapshot")
        request["steps"][0]["runner_args"]["target"] = {
            "site_id": "build", "path": outside,
        }
        code, payload = self.cli(FLOW, "execute", "--request", self.save_request(request))
        self.assertEqual(code, 40, payload)
        self.assertEqual(payload["issues"][0]["code"], "FLOW_RUNNER_PREFLIGHT")
        code, shown = self.cli(STATE, "show", "--case", self.case["case_uid"])
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["state"]["revision"], 2)
        self.assertFalse(os.path.exists(outside))

    def test_missing_acceptance_evidence_closes_action_as_failed(self):
        request = self.flow_request()
        request["steps"][0]["acceptance_checks"].append("source tree hash verified")
        code, payload = self.cli(FLOW, "execute", "--request", self.save_request(request))
        self.assertEqual(code, 30, payload)
        self.assertEqual(payload["status"], "anomaly")
        code, shown = self.cli(STATE, "show", "--case", self.case["case_uid"])
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["state"]["revision"], 4)
        self.assertEqual(shown["state"]["workflow"]["active_action_id"], "")

    def test_revision_drift_prevents_side_effect(self):
        request = self.save_request(self.flow_request())
        code, updated = self.cli(
            STATE, "update-memory", "--case", self.case["case_uid"],
            "--expected-revision", "2", "--summary", "external update",
        )
        self.assertEqual(code, 0, updated)
        code, payload = self.cli(FLOW, "execute", "--request", request)
        self.assertEqual(code, 50, payload)
        self.assertEqual(payload["issues"][0]["code"], "FLOW_REVISION_CONFLICT")
        target = self.flow_request()["steps"][0]["runner_args"]["target"]["path"]
        self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
