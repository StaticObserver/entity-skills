from __future__ import print_function

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTER_ROOT = os.path.join(ROOT, "skills", "entity-router")
SCRIPT = os.path.join(ROUTER_ROOT, "scripts", "entity_router_state.py")


class RouterStateCLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-router-test-")
        self.workdir = os.path.join(self.temp, "work")
        self.checkout = os.path.join(self.workdir, "entity-test")
        os.makedirs(self.checkout)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def run_cli(self, *args):
        command = [sys.executable, SCRIPT] + list(args)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        stdout, stderr = process.communicate()
        payload = json.loads(stdout if stdout.strip() else stderr)
        return process.returncode, payload

    def create_case(self, case_id="smoke"):
        code, payload = self.run_cli(
            "create",
            "--workdir", self.workdir,
            "--case-id", case_id,
            "--entity-checkout", self.checkout,
            "--pgen", case_id,
            "--goal", "exercise router state transitions",
            "--done-when", "pgen and build evidence are verified",
        )
        self.assertEqual(code, 0, payload)
        return payload["case_dir"], payload["state"]

    def test_action_lifecycle_revision_and_stale_propagation(self):
        case_dir, state = self.create_case()
        self.assertEqual(state["revision"], 0)
        self.assertEqual(state["readiness"]["orientation"]["status"], "ready")
        self.assertIn("pgen.design", state["workflow"]["allowed_actions"])

        code, error = self.run_cli(
            "start-action",
            "--case", case_dir,
            "--expected-revision", "0",
            "--action-id", "pgen-001",
            "--action-type", "pgen.design",
            "--owner", "entity-pgen",
            "--execution-domain", "entity-pgen",
            "--goal", "create the smoke PGen",
            "--write-root", self.workdir,
        )
        self.assertEqual(code, 2)
        self.assertIn("outside case", error["error"])

        code, started = self.run_cli(
            "start-action",
            "--case", case_dir,
            "--expected-revision", "0",
            "--action-id", "pgen-001",
            "--action-type", "pgen.design",
            "--owner", "entity-pgen",
            "--execution-domain", "entity-pgen",
            "--goal", "create the smoke PGen",
            "--read-root", self.checkout,
            "--write-root", case_dir,
            "--expected-output", "pgen.hpp",
            "--acceptance-check", "PGen evidence exists",
        )
        self.assertEqual(code, 0, started)
        self.assertEqual(started["revision"], 1)
        request_path = started["request"]
        with open(request_path, "rb") as handle:
            request_hash = hashlib.sha256(handle.read()).hexdigest()

        pgen = os.path.join(case_dir, "pgen.hpp")
        with open(pgen, "w") as handle:
            handle.write("// router smoke PGen\n")

        code, conflict = self.run_cli(
            "finish-action",
            "--case", case_dir,
            "--expected-revision", "0",
            "--action-id", "pgen-001",
            "--status", "completed",
        )
        self.assertEqual(code, 2)
        self.assertIn("revision conflict", conflict["error"])

        code, unverified = self.run_cli(
            "finish-action",
            "--case", case_dir,
            "--expected-revision", "1",
            "--action-id", "pgen-001",
            "--status", "completed",
            "--output", pgen,
            "--readiness", "pgen=verified",
        )
        self.assertEqual(code, 2)
        self.assertIn("one verification per acceptance check", unverified["error"])

        code, finished = self.run_cli(
            "finish-action",
            "--case", case_dir,
            "--expected-revision", "1",
            "--action-id", "pgen-001",
            "--status", "completed",
            "--output", pgen,
            "--verification", "smoke PGen exists",
            "--readiness", "pgen=verified",
            "--next-action", "build.compile",
        )
        self.assertEqual(code, 0, finished)
        self.assertEqual(finished["revision"], 2)
        self.assertIn("build.compile", finished["allowed_actions"])
        with open(request_path, "rb") as handle:
            self.assertEqual(request_hash, hashlib.sha256(handle.read()).hexdigest())

        build_dir = os.path.join(case_dir, "build")
        os.makedirs(build_dir)
        code, started = self.run_cli(
            "start-action",
            "--case", case_dir,
            "--expected-revision", "2",
            "--action-id", "build-001",
            "--action-type", "build.compile",
            "--owner", "entity-env-build",
            "--execution-domain", "entity-env-build",
            "--goal", "compile the smoke PGen",
            "--input", pgen,
            "--read-root", self.checkout,
            "--read-root", case_dir,
            "--write-root", build_dir,
            "--expected-output", "entity executable",
        )
        self.assertEqual(code, 0, started)
        executable = os.path.join(build_dir, "entity")
        with open(executable, "w") as handle:
            handle.write("smoke executable\n")

        code, finished = self.run_cli(
            "finish-action",
            "--case", case_dir,
            "--expected-revision", "3",
            "--action-id", "build-001",
            "--status", "completed",
            "--output", executable,
            "--verification", "executable evidence exists",
            "--readiness", "build=pass",
        )
        self.assertEqual(code, 0, finished)
        self.assertEqual(finished["revision"], 4)

        with open(pgen, "a") as handle:
            handle.write("// changed after build\n")
        code, refreshed = self.run_cli(
            "refresh",
            "--case", case_dir,
            "--expected-revision", "4",
        )
        self.assertEqual(code, 0, refreshed)
        self.assertEqual(refreshed["revision"], 5)
        self.assertIn("pgen", refreshed["changed_dimensions"])
        self.assertEqual(refreshed["state"]["readiness"]["pgen"]["status"], "stale")
        self.assertEqual(refreshed["state"]["readiness"]["build"]["status"], "stale")

        code, verified = self.run_cli("verify", "--case", case_dir)
        self.assertEqual(code, 0, verified)
        self.assertTrue(verified["ok"])

        with open(os.path.join(case_dir, "_case", "events.jsonl"), "r") as handle:
            events = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(events[0]["event"], "case.created")
        self.assertEqual(events[-1]["event"], "case.refreshed")

    def test_suspend_resume_and_list(self):
        case_dir, _ = self.create_case("resume-smoke")
        code, suspended = self.run_cli(
            "suspend",
            "--case", case_dir,
            "--expected-revision", "0",
            "--summary", "waiting for user input",
        )
        self.assertEqual(code, 0, suspended)
        self.assertEqual(suspended["revision"], 1)

        code, listed = self.run_cli("list", "--workdir", self.workdir)
        self.assertEqual(code, 0, listed)
        self.assertEqual(listed["cases"][0]["case_status"], "suspended")

        code, resumed = self.run_cli(
            "resume",
            "--case", case_dir,
            "--expected-revision", "1",
        )
        self.assertEqual(code, 0, resumed)
        self.assertEqual(resumed["revision"], 2)

        code, shown = self.run_cli("show", "--case", case_dir)
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["state"]["case_status"], "active")
        self.assertEqual(shown["state"]["workflow"]["status"], "active")

        evidence = os.path.join(case_dir, "completion.txt")
        with open(evidence, "w") as handle:
            handle.write("verified\n")
        code, incomplete = self.run_cli(
            "complete-workflow",
            "--case", case_dir,
            "--expected-revision", "2",
            "--summary", "workflow complete",
            "--evidence", evidence,
        )
        self.assertEqual(code, 2)
        self.assertIn("one verification per done_when", incomplete["error"])

        code, completed = self.run_cli(
            "complete-workflow",
            "--case", case_dir,
            "--expected-revision", "2",
            "--summary", "workflow complete",
            "--verification", "done_when checked",
            "--evidence", evidence,
        )
        self.assertEqual(code, 0, completed)
        self.assertTrue(os.path.isfile(completed["snapshot"]))

        code, new_workflow = self.run_cli(
            "new-workflow",
            "--case", case_dir,
            "--expected-revision", "3",
            "--workflow-id", "wf-analysis",
            "--workflow-type", "analyze-run",
            "--goal", "inspect output",
            "--done-when", "inventory recorded",
        )
        self.assertEqual(code, 0, new_workflow)
        self.assertEqual(new_workflow["revision"], 4)

    def test_reconcile_existing_artifacts_and_memory(self):
        case_id = "existing"
        case_dir = os.path.join(self.workdir, "problems", case_id)
        os.makedirs(os.path.join(case_dir, "docs"))
        pgen = os.path.join(case_dir, "pgen.hpp")
        build_result = os.path.join(case_dir, "build-result.json")
        with open(pgen, "w") as handle:
            handle.write("// existing PGen\n")
        with open(build_result, "w") as handle:
            handle.write("{}\n")

        case_dir, state = self.create_case(case_id)
        self.assertEqual(state["readiness"]["pgen"]["status"], "implemented")

        code, reconciled = self.run_cli(
            "reconcile",
            "--case", case_dir,
            "--expected-revision", "0",
            "--readiness", "pgen=verified",
            "--evidence", "pgen=" + pgen,
            "--readiness", "build=pass",
            "--evidence", "build=" + build_result,
            "--protect-path", build_result,
        )
        self.assertEqual(code, 0, reconciled)
        self.assertIn("run.prepare", reconciled["allowed_actions"])

        code, updated = self.run_cli(
            "update-memory",
            "--case", case_dir,
            "--expected-revision", "1",
            "--decision", "use the existing executable identity",
            "--open-question", "confirm scheduler partition",
            "--constraint", "do not overwrite historical runs",
        )
        self.assertEqual(code, 0, updated)
        self.assertEqual(updated["revision"], 2)

        code, shown = self.run_cli("show", "--case", case_dir)
        self.assertEqual(code, 0, shown)
        memory = shown["state"]["memory"]
        self.assertIn("use the existing executable identity", memory["confirmed_decisions"])
        self.assertIn("confirm scheduler partition", memory["open_questions"])
        self.assertIn("do not overwrite historical runs", memory["constraints"])


if __name__ == "__main__":
    unittest.main()
