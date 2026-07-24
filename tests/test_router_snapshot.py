#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_router_record import snapshot_source
from entity_router_store import OperationStore


class SnapshotSourceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-router-snapshot-")
        self.home = os.path.join(self.temp, "controller")
        self.project = os.path.join(self.temp, "project")
        os.makedirs(self.project)
        with open(os.path.join(self.project, "pgen.hpp"), "w") as handle:
            handle.write("// pgen\n")
        with open(os.path.join(self.project, "input.toml"), "w") as handle:
            handle.write("[simulation]\nsteps = 2\n")
        self.store = OperationStore(self.home)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def _make_case(self):
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local", "display_name": "local",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "none"},
            "roots": {"source_root": self.temp, "build_root": self.temp,
                      "run_root": self.temp, "staging_root": self.temp},
            "policy": {}, "shared_mappings": [],
        })
        self.store.upsert_case(
            "case-demo", "demo", self.project,
            {"authority": {"site_id": "local", "path": self.project},
             "revision": {"kind": "path", "root": self.project}},
            {"source_id": "", "build_id": "", "run_id": "", "active_run": None,
             "data_id": "", "analysis_id": ""})

    def test_snapshot_archive_is_content_addressed_and_idempotent(self):
        result = snapshot_source(self.store, self.project, {})
        self.assertFalse(result["recorded"])
        self.assertFalse(result["state_mutated"])
        self.assertTrue(result["archived"])
        self.assertTrue(os.path.isfile(result["archive"]))
        with tarfile.open(result["archive"], "r") as bundle:
            names = bundle.getnames()
        self.assertIn("snapshot-manifest.json", names)
        self.assertIn("pgen.hpp", names)
        second = snapshot_source(self.store, self.project, {})
        self.assertEqual(result["snapshot_id"], second["snapshot_id"])
        self.assertFalse(second["archived"])

    def test_snapshot_records_source_identity_when_case_exists(self):
        self._make_case()
        result = snapshot_source(self.store, self.project, {})
        self.assertTrue(result["recorded"])
        self.assertTrue(result["state_mutated"])
        case = self.store.resolve_project(self.project)
        identity_id = "src-" + result["snapshot_id"][:16]
        self.assertEqual(case["current"]["source_id"], identity_id)
        self.assertEqual(case["current"]["readiness"]["source"], "established")
        identity = case["identities"]["source"]["items"][0]
        self.assertEqual(identity["fingerprint"], result["snapshot_id"])
        self.assertEqual(identity["status"], "snapshotted")

    def test_missing_project_root_fails(self):
        from entity_router_facts import PlanError
        with self.assertRaises(PlanError):
            snapshot_source(self.store, os.path.join(self.temp, "nope"), {})

    def test_cli_snapshot_source(self):
        self._make_case()
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--router-home", self.home,
             "--actor-run-id", "test", "--actor-provider", "test",
             "snapshot-source", "--project-root", self.project],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["kind"], "entity-router.snapshot-source")
        self.assertTrue(payload["recorded"])
        self.assertTrue(os.path.isfile(payload["archive"]))


if __name__ == "__main__":
    unittest.main()
