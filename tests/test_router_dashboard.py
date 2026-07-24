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
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_router_dashboard import build_dashboard, render_text
from entity_router_store import OperationStore


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-router-dashboard-")
        self.home = os.path.join(self.temp, "controller")
        self.project = os.path.join(self.temp, "project")
        os.makedirs(self.project)
        self.store = OperationStore(self.home)
        self.profile = {
            "schema_version": 1, "site_id": "local", "display_name": "local",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "none"},
            "roots": {"source_root": self.temp, "build_root": self.temp,
                      "run_root": self.temp, "staging_root": self.temp},
            "policy": {}, "shared_mappings": [],
        }
        self.store.upsert_site(self.profile)
        self.case_uid = "case-demo"
        self.store.upsert_case(
            self.case_uid, "demo", self.project,
            {"authority": {"site_id": "local", "path": self.project},
             "transfer_policy": "snapshot",
             "revision": {"kind": "path", "root": self.project}},
            {"source_id": "", "build_id": "", "run_id": "", "active_run": None,
             "data_id": "", "analysis_id": ""},
        )

    def tearDown(self):
        shutil.rmtree(self.temp)

    def _write_toml(self, name="input.toml", body="[simulation]\nsteps = 2\n"):
        path = os.path.join(self.project, name)
        with open(path, "w") as handle:
            handle.write(body)
        return path

    def _confirm(self, path):
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        record = {"schema_version": 1,
                  "kind": "entity-pgen.simulation-confirmation",
                  "input_sha256": digest, "card": {}, "confirmed_by": "test",
                  "confirmed_at": "2026-07-22T00:00:00", "defaults": False}
        with open(path + ".decisions.json", "w") as handle:
            json.dump(record, handle)

    def _dashboard(self, status=None):
        return build_dashboard(self.store, self.project, status)

    def test_empty_case_board_and_intent(self):
        dashboard = self._dashboard()
        board = dashboard["board"]
        self.assertEqual(board["source"]["state"], "established")
        self.assertEqual(board["pgen"]["state"], "unknown")
        self.assertEqual(board["build"]["state"], "missing")
        self.assertEqual(board["run"]["state"], "none")
        self.assertEqual(board["data"]["state"], "missing")
        self.assertEqual(dashboard["intent"], "未记录")
        self.assertFalse(dashboard["state_mutated"])
        self.assertEqual(dashboard["remote_calls"], 0)
        steps = " ".join(dashboard["next_steps"])
        self.assertIn("构建", steps)

    def test_pgen_cell_tracks_confirmation_bytes(self):
        path = self._write_toml()
        self.assertEqual(self._dashboard()["board"]["pgen"]["state"], "unconfirmed")
        self._confirm(path)
        self.assertEqual(self._dashboard()["board"]["pgen"]["state"], "confirmed")
        self._write_toml(body="[simulation]\nsteps = 3\n")
        dashboard = self._dashboard()
        self.assertEqual(dashboard["board"]["pgen"]["state"], "unconfirmed")
        self.assertTrue(any("未确认" in item for item in dashboard["pending"]))

    def test_run_ledger_and_deriver(self):
        self.store.add_identity(
            self.case_uid, "run", "run-1",
            {"id": "run-1", "site_id": "local", "status": "submitted",
             "scheduler": {"pid": 4321}}, True)
        current = {"source_id": "", "build_id": "", "run_id": "run-1",
                   "active_run": None, "data_id": "", "analysis_id": ""}
        self.store.upsert_case(
            self.case_uid, "demo", self.project,
            {"authority": {"site_id": "local", "path": self.project},
             "revision": {"kind": "path", "root": self.project}}, current)
        dashboard = self._dashboard()
        self.assertEqual(dashboard["board"]["run"]["state"], "submitted")
        self.assertIn("pid 4321", dashboard["board"]["run"]["detail"])
        self.assertEqual(dashboard["runs"][0]["run_id"], "run-1")
        self.assertTrue(any("--live" in step for step in dashboard["next_steps"]))
        live_status = {"live": {"scheduler": "direct", "pid": 4321,
                                "state": "EXITED", "exit_code": 0,
                                "observed_at": "2026-07-23T00:00:00Z"},
                       "divergences": [{"kind": "state_mismatch", "detail": "x"}],
                       "remote_calls": 2}
        dashboard = self._dashboard(live_status)
        self.assertEqual(dashboard["board"]["run"]["state"], "exited")
        self.assertIn("exit 0", dashboard["board"]["run"]["detail"])
        self.assertTrue(any("盘点" in step for step in dashboard["next_steps"]))
        self.assertEqual(dashboard["remote_calls"], 2)
        self.assertTrue(any("带外变更" in item for item in dashboard["pending"]))

    def test_record_intent_shows_on_dashboard(self):
        from entity_router_record import record_intent
        from entity_router_facts import PlanError
        result = record_intent(
            self.store, self.project, "验证极冠重联的加热率", {"run_id": "t"})
        self.assertTrue(result["state_mutated"])
        dashboard = self._dashboard()
        self.assertIn("验证极冠重联的加热率", dashboard["intent"])
        self.assertIn("记录于", dashboard["intent"])
        with self.assertRaises(PlanError):
            record_intent(self.store, self.project, "  ", {})

    def test_render_is_compact_and_human_readable(self):
        self._write_toml()
        self.store.add_identity(
            self.case_uid, "run", "run-1",
            {"id": "run-1", "site_id": "local", "status": "prepared",
             "scheduler": {}}, True)
        text = render_text(self._dashboard())
        self.assertLess(len(text.encode("utf-8")), 4096)
        for marker in ["就绪板", "Run 台账", "建议下一步", "source", "pgen"]:
            self.assertIn(marker, text)

    def test_cli_status_defaults_to_text_and_json_is_preserved(self):
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--router-home", self.home,
             "status", "--project-root", self.project],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 0, stderr)
        self.assertIn("就绪板", stdout)
        self.assertRaises(ValueError, json.loads, stdout)
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--router-home", self.home,
             "status", "--project-root", self.project, "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["kind"], "entity-router.status")
        self.assertEqual(payload["case_uid"], self.case_uid)


if __name__ == "__main__":
    unittest.main()
