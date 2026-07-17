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


class RouterFlowInspectTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-flow-inspect-")
        self.home = os.path.join(self.temp, "control")
        self.source = os.path.join(self.temp, "source")
        self.remote = os.path.join(self.temp, "remote")
        os.makedirs(os.path.join(self.source, "docs"))
        os.makedirs(self.remote)
        subprocess.check_call(["git", "init", "-q", self.source])
        subprocess.check_call(["git", "-C", self.source, "config", "user.email", "test@example.invalid"])
        subprocess.check_call(["git", "-C", self.source, "config", "user.name", "Flow Test"])
        self.write(os.path.join(self.source, "README.md"), "source\n")
        subprocess.check_call(["git", "-C", self.source, "add", "."])
        subprocess.check_call(["git", "-C", self.source, "commit", "-qm", "base"])
        self.add_site("local", self.temp)
        self.add_site("remote", self.remote)

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
        return process.returncode, json.loads(process.stdout), len(process.stdout.encode("utf-8"))

    def add_site(self, site_id, root):
        args = ["add", "--site-id", site_id, "--transport", "local"]
        for name in ["source", "build", "run", "deps", "staging", "analysis"]:
            path = os.path.join(root, name)
            os.makedirs(path, exist_ok=True)
            args.extend(["--%s-root" % name, path])
        code, payload, unused = self.cli(SITE, *args)
        self.assertEqual(code, 0, payload)

    def create_case(self, label):
        code, payload, unused = self.cli(
            STATE, "create", "--case-id", label,
            "--source-authority", "local:%s" % self.source,
            "--pgen-locator", "local:%s" % os.path.join(self.source, "pgen.hpp"),
            "--toml-locator", "local:%s" % os.path.join(self.source, "case.toml"),
            "--design-locator", "local:%s" % os.path.join(self.source, "docs", "design.md"),
            "--build-root", "remote:%s" % os.path.join(self.remote, "build"),
            "--run-root", "remote:%s" % os.path.join(self.remote, "run"),
            "--data-root", "remote:%s" % os.path.join(self.remote, "run"),
            "--analysis-root", "remote:%s" % os.path.join(self.remote, "analysis"),
            "--goal", "flow inspect fixture",
        )
        self.assertEqual(code, 0, payload)
        return payload

    def set_target(self, case, revision=0):
        path = os.path.join(self.temp, "%s-target.json" % case["case_uid"])
        target = {
            "schema_version": 1,
            "target_id": "target-" + case["case_uid"][:8],
            "source_revision_hash": "",
            "build_id": "",
            "build_spec_hash": "",
            "run_id": "",
            "run_spec_hash": "",
            "data_id": "",
            "analysis_id": "",
            "criteria": [],
        }
        self.write(path, json.dumps(target))
        code, payload, unused = self.cli(
            STATE, "set-workflow-target", "--case", case["case_uid"],
            "--expected-revision", str(revision), "--target", path,
        )
        self.assertEqual(code, 0, payload)
        return payload

    def test_inspect_requires_target_then_returns_compact_live_summary(self):
        case = self.create_case("one")
        code, payload, size = self.cli(FLOW, "inspect", "--case", case["case_uid"])
        self.assertEqual(code, 10, payload)
        self.assertEqual(payload["issues"][0]["code"], "WF_TARGET_MISSING")
        self.set_target(case)
        code, payload, size = self.cli(
            FLOW, "inspect", "--case", case["case_uid"], "--live", "--phase", "source",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["case_uid"], case["case_uid"])
        self.assertEqual(payload["metrics"]["remote_calls"], 0)
        self.assertLessEqual(size, 4096)

    def test_cwd_ambiguity_returns_candidates_without_guessing(self):
        first = self.create_case("first")
        second = self.create_case("second")
        self.set_target(first)
        self.set_target(second)
        code, payload, unused = self.cli(FLOW, "inspect", "--cwd", self.source)
        self.assertEqual(code, 10, payload)
        self.assertEqual(payload["issues"][0]["code"], "CASE_AMBIGUOUS")
        self.assertEqual(len(payload["result"]["candidates"]), 2)

    def test_check_detects_data_parent_mismatch(self):
        case = self.create_case("broken")
        self.set_target(case)
        state_path = os.path.join(case["case_dir"], "case.json")
        with open(state_path) as handle:
            state = json.load(handle)
        state["resources"]["run"]["current_id"] = "run-current"
        state["resources"]["data"]["current_id"] = "data-current"
        state["resources"]["data"]["identities"].append({
            "id": "data-current",
            "kind": "data",
            "site_id": "remote",
            "root": state["resources"]["data"]["root"],
            "spec_hash": "",
            "parents": {"run_id": "run-other"},
            "evidence": [],
        })
        with open(state_path, "w") as handle:
            json.dump(state, handle)
        code, payload, unused = self.cli(FLOW, "check", "--case", case["case_uid"])
        self.assertEqual(code, 30, payload)
        self.assertIn("ID_DATA_RUN_MISMATCH", [item["code"] for item in payload["issues"]])


if __name__ == "__main__":
    unittest.main()
