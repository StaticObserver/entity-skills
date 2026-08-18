#!/usr/bin/env python3

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-ledger", "scripts")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_ledger_dashboard import build_dashboard
from entity_ledger_store import OperationStore, canonical_hash


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-record-")
        self.home = os.path.join(self.temp, "controller")
        self.project = os.path.join(self.temp, "project")
        self.run_root = os.path.join(self.temp, "runs")
        self.staging_root = os.path.join(self.temp, "staging")
        self.build_root = os.path.join(self.temp, "build")
        for path in [self.project, self.run_root, self.staging_root, self.build_root]:
            os.makedirs(path)
        self.store = OperationStore(self.home)
        self.profile = {
            "schema_version": 1, "site_id": "local", "display_name": "local",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "none"},
            "roots": {"source_root": self.temp, "build_root": self.build_root,
                      "run_root": self.run_root, "staging_root": self.staging_root},
            "policy": {}, "shared_mappings": [],
        }
        self.store.upsert_site(self.profile)
        self.case_uid = "case-record"
        self.current = {"source_id": "", "build_id": "", "run_id": "",
                        "active_run": None, "data_id": "", "analysis_id": ""}
        self.store.upsert_case(
            self.case_uid, "record-demo", self.project,
            {"authority": {"site_id": "local", "path": self.project},
             "transfer_policy": "snapshot",
             "revision": {"kind": "path", "root": self.project}},
            dict(self.current),
        )

    def tearDown(self):
        shutil.rmtree(self.temp)

    def cli(self, *args):
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--ledger-home", self.home] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), stderr)
        return process.returncode, json.loads(stdout)

    def _write_checkpoint(self, confirmed=True, compat="pass"):
        checkpoint = {"schema_version": 2, "compatibility": {"status": compat}}
        if confirmed:
            checkpoint["decisions"] = {"parameters": {
                "digest": "sha256:" + "1" * 64, "confirmed_by": "tester"}}
        path = os.path.join(self.temp, "entity-deps.local.json")
        with open(path, "w") as handle:
            json.dump(checkpoint, handle)
        return path

    def _write_executable(self, name="entity.xc", mode=0o755):
        path = os.path.join(self.build_root, name)
        with open(path, "w") as handle:
            handle.write("binary-placeholder\n")
        os.chmod(path, mode)
        return path

    def _register_run(self, run_id="run-1", files=None):
        run_root = os.path.join(self.run_root, self.case_uid, run_id)
        if not os.path.isdir(run_root):
            os.makedirs(run_root)
        for name in files or ["output-000.bp", "output-001.bp", "stdout.log"]:
            path = os.path.join(run_root, name)
            with open(path, "w") as handle:
                handle.write("payload of %s\n" % name)
        self.store.add_identity(
            self.case_uid, "run", run_id,
            {"id": run_id, "kind": "run", "site_id": "local",
             "root": {"site_id": "local", "path": run_root},
             "status": "submitted",
             "scheduler": {"pid": 4321, "run_root": run_root}}, True)
        current = dict(self.store.get_case(self.case_uid)["current"])
        current["run_id"] = run_id
        current["active_run"] = {"site_id": "local", "path": run_root}
        self.store.upsert_case(
            self.case_uid, "record-demo", self.project,
            {"authority": {"site_id": "local", "path": self.project},
             "transfer_policy": "snapshot",
             "revision": {"kind": "path", "root": self.project}},
            current,
        )
        return run_root

    def test_show_reports_case_facts_and_never_mutates(self):
        self._register_run()
        code, payload = self.cli("show", "--project-root", self.project)
        self.assertEqual(code, 0)
        self.assertEqual(payload["kind"], "entity-ledger.show")
        self.assertFalse(payload["state_mutated"])
        self.assertEqual(payload["case_uid"], self.case_uid)
        self.assertEqual(payload["case_id"], "record-demo")
        self.assertEqual(payload["current"]["run_id"], "run-1")
        run_dimension = payload["identities"]["run"]
        self.assertEqual(run_dimension["current_id"], "run-1")
        self.assertEqual(run_dimension["items"][0]["id"], "run-1")
        self.assertIn("created_at", payload)
        self.assertIn("updated_at", payload)
        self.assertNotIn("active_operation", payload)

    def test_show_requires_existing_case(self):
        code, payload = self.cli("show", "--project-root",
                                 os.path.join(self.temp, "nowhere"))
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["state_mutated"])

    def test_record_build_registers_verified_identity(self):
        checkpoint = self._write_checkpoint()
        executable = self._write_executable()
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "build",
            "--project-root", self.project, "--site", "local",
            "--checkpoint", checkpoint, "--executable", executable)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["kind"], "entity-ledger.record.build")
        self.assertTrue(payload["state_mutated"])
        self.assertTrue(payload["build_id"].startswith("build-"))
        case = self.store.get_case(self.case_uid)
        self.assertEqual(case["current"]["build_id"], payload["build_id"])
        self.assertEqual(case["current"]["readiness"]["build"], "verified")
        identity = case["identities"]["build"]["items"][0]
        self.assertEqual(identity["status"], "verified")
        self.assertEqual(identity["outputs"], [{
            "kind": "file",
            "locator": {"site_id": "local", "path": executable},
        }])
        with open(executable, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(identity["executable_sha256"], digest)
        self.assertEqual(identity["checkpoint"], os.path.realpath(checkpoint))
        seed = {"case_uid": self.case_uid,
                "checkpoint_sha256": identity["checkpoint_sha256"],
                "executable": executable, "executable_sha256": digest,
                "site_id": "local"}
        expected = "build-" + canonical_hash(seed).split(":", 1)[1][:16]
        self.assertEqual(payload["build_id"], expected)
        events = self.store.export()["events"]
        self.assertEqual([item["event_type"] for item in events], ["record.build"])
        self.assertEqual(events[0]["actor"]["run_id"], "record-test")
        code, again = self.cli(
            "--actor-run-id", "record-test", "record", "build",
            "--project-root", self.project, "--site", "local",
            "--checkpoint", checkpoint, "--executable", executable)
        self.assertEqual(code, 0, again)
        self.assertEqual(again["build_id"], payload["build_id"])

    def test_record_build_rejects_unverified_checkpoint(self):
        executable = self._write_executable()
        for checkpoint in [self._write_checkpoint(compat="fail"),
                           self._write_checkpoint(confirmed=False)]:
            code, payload = self.cli(
                "--actor-run-id", "record-test", "record", "build",
                "--project-root", self.project, "--site", "local",
                "--checkpoint", checkpoint, "--executable", executable)
            self.assertEqual(code, 2, payload)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "needs_decision")
            self.assertTrue(payload["decisions"])
        case = self.store.get_case(self.case_uid)
        self.assertEqual(case["current"].get("build_id", ""), "")
        self.assertEqual(case["identities"], {})

    def test_record_build_rejects_missing_or_non_executable_file(self):
        checkpoint = self._write_checkpoint()
        missing = os.path.join(self.build_root, "not-there.xc")
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "build",
            "--project-root", self.project, "--site", "local",
            "--checkpoint", checkpoint, "--executable", missing)
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        not_executable = self._write_executable(name="entity-plain.xc", mode=0o644)
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "build",
            "--project-root", self.project, "--site", "local",
            "--checkpoint", checkpoint, "--executable", not_executable)
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        case = self.store.get_case(self.case_uid)
        self.assertEqual(case["current"].get("build_id", ""), "")

    def test_record_build_requires_existing_case(self):
        checkpoint = self._write_checkpoint()
        executable = self._write_executable()
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "build",
            "--project-root", os.path.join(self.temp, "nowhere"),
            "--site", "local", "--checkpoint", checkpoint,
            "--executable", executable)
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "needs_decision")

    def test_record_data_inventories_run_outputs(self):
        run_root = self._register_run()
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "data",
            "--project-root", self.project)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["kind"], "entity-ledger.record.data")
        self.assertTrue(payload["state_mutated"])
        self.assertTrue(payload["data_id"].startswith("data-"))
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["files"], 3)
        self.assertFalse(payload["refreshed"])
        manifest = os.path.join(run_root, "data-inventory.json")
        self.assertTrue(os.path.isfile(manifest))
        with open(manifest, "r") as handle:
            inventory = json.load(handle)
        names = [item["path"] for item in inventory["files"]]
        self.assertEqual(names, ["output-000.bp", "output-001.bp", "stdout.log"])
        digest = canonical_hash({"case_uid": self.case_uid, "run_id": "run-1"})
        expected = "data-" + digest.split(":", 1)[1][:16]
        self.assertEqual(payload["data_id"], expected)
        case = self.store.get_case(self.case_uid)
        self.assertEqual(case["current"]["data_id"], payload["data_id"])
        self.assertEqual(case["current"]["readiness"]["data"], "inventoried")
        identity = case["identities"]["data"]["items"][0]
        self.assertEqual(identity["status"], "inventoried")
        self.assertEqual(identity["files"], 3)
        self.assertEqual(identity["parents"], {"run_id": "run-1"})
        events = self.store.export()["events"]
        self.assertEqual([item["event_type"] for item in events], ["record.data"])

    def test_record_data_is_idempotent_and_refreshes(self):
        run_root = self._register_run()
        argv = ["--actor-run-id", "record-test", "record", "data",
                "--project-root", self.project]
        code, first = self.cli(*argv)
        self.assertEqual(code, 0, first)
        code, second = self.cli(*argv)
        self.assertEqual(code, 0, second)
        self.assertEqual(second["data_id"], first["data_id"])
        self.assertTrue(second["refreshed"])
        self.assertEqual(second["files"], 3)
        with open(os.path.join(run_root, "output-002.bp"), "w") as handle:
            handle.write("late output\n")
        code, third = self.cli(*argv)
        self.assertEqual(code, 0, third)
        self.assertEqual(third["data_id"], first["data_id"])
        self.assertEqual(third["files"], 4)
        self.assertTrue(third["refreshed"])
        case = self.store.get_case(self.case_uid)
        self.assertEqual(case["identities"]["data"]["items"][0]["files"], 4)

    def test_record_data_explicit_run_id(self):
        self._register_run("run-1", files=["a.bp"])
        self._register_run("run-2", files=["b.bp", "c.bp"])
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "data",
            "--project-root", self.project, "--run-id", "run-1")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["files"], 1)

    def test_record_data_requires_run(self):
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "data",
            "--project-root", self.project)
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        self._register_run()
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "data",
            "--project-root", self.project, "--run-id", "run-9")
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        case = self.store.get_case(self.case_uid)
        self.assertEqual(case["current"].get("data_id", ""), "")

    def test_dashboard_reflects_recorded_build_and_data(self):
        checkpoint = self._write_checkpoint()
        executable = self._write_executable()
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "build",
            "--project-root", self.project, "--site", "local",
            "--checkpoint", checkpoint, "--executable", executable)
        self.assertEqual(code, 0, payload)
        self._register_run()
        code, payload = self.cli(
            "--actor-run-id", "record-test", "record", "data",
            "--project-root", self.project)
        self.assertEqual(code, 0, payload)
        dashboard = build_dashboard(self.store, self.project)
        board = dashboard["board"]
        self.assertEqual(board["build"]["state"], "verified")
        self.assertIn("entity.xc @ local", board["build"]["detail"])
        self.assertEqual(board["data"]["state"], "inventoried")
        self.assertEqual(board["data"]["detail"], "3 个文件")

    # B2: record run-correct rewrites a booked terminal state by human
    # declaration (the counterpart of --reclassify's evidence re-judgment)

    def _terminal_run(self, status):
        self._register_run()
        case = self.store.get_case(self.case_uid)
        identity = dict(case["identities"]["run"]["items"][0])
        identity["status"] = status
        self.store.add_identity(self.case_uid, "run", identity["id"],
                                identity, True)
        return identity["id"]

    def _correct(self, status, reason="更正"):
        return self.cli(
            "--actor-run-id", "correct-test", "record", "run-correct",
            "--project-root", self.project, "--status", status,
            "--reason", reason)

    def test_run_correct_rewrites_state_and_books_event(self):
        self._terminal_run("completed")
        code, payload = self._correct(
            "failed", "sacct 实为 CANCELLED 0:0,迁移周误记 completed")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["state_mutated"])
        self.assertEqual(payload["state"], "failed")
        self.assertEqual(payload["previous_status"], "completed")
        case = self.store.get_case(self.case_uid)
        identity = case["identities"]["run"]["items"][0]
        self.assertEqual(identity["status"], "failed")
        correction = identity["correction"]
        self.assertEqual(correction["from"], "completed")
        self.assertEqual(correction["to"], "failed")
        self.assertIn("CANCELLED", correction["reason"])
        self.assertEqual(correction["corrected_by"], "correct-test")
        self.assertEqual(case["current"]["readiness"]["run"], "failed")
        events = self.store.export()["events"]
        self.assertEqual(events[-1]["event_type"], "record.run-correct")
        self.assertEqual(events[-1]["payload"]["from"], "completed")
        self.assertEqual(events[-1]["payload"]["to"], "failed")
        self.assertIn("CANCELLED", events[-1]["payload"]["reason"])
        self.assertEqual(events[-1]["actor"]["run_id"], "correct-test")

    def test_run_correct_to_same_state_is_a_noop(self):
        self._terminal_run("failed")
        events_before = len(self.store.export()["events"])
        code, payload = self._correct("failed")
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["state_mutated"])
        self.assertIn("nothing to correct", payload["detail"])
        case = self.store.get_case(self.case_uid)
        identity = case["identities"]["run"]["items"][0]
        self.assertNotIn("correction", identity)
        self.assertEqual(len(self.store.export()["events"]), events_before)

    def test_run_correct_refuses_inflight_run_with_zero_writes(self):
        self._register_run()  # status submitted
        events_before = len(self.store.export()["events"])
        code, payload = self._correct("failed")
        self.assertEqual(code, 2)
        self.assertIn("run-exit", payload["error"])
        case = self.store.get_case(self.case_uid)
        identity = case["identities"]["run"]["items"][0]
        self.assertEqual(identity["status"], "submitted")
        self.assertEqual(len(self.store.export()["events"]), events_before)


if __name__ == "__main__":
    unittest.main()
