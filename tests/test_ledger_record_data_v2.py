#!/usr/bin/env python3
"""WP1 data path: v2 data revisions (metadata/strong), seal, verify, and the
ENTITY_LEDGER_DATA_IDENTITY=v1 rollback flag."""

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

from entity_ledger_common import domain_digest
from entity_ledger_dashboard import build_dashboard
from entity_ledger_store import OperationStore, canonical_hash


class RecordDataV2Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-data-v2-")
        self.home = os.path.join(self.temp, "controller")
        self.project = os.path.join(self.temp, "project")
        self.run_root = os.path.join(self.temp, "runs")
        self.staging_root = os.path.join(self.temp, "staging")
        self.build_root = os.path.join(self.temp, "build")
        for path in [self.project, self.run_root, self.staging_root,
                     self.build_root]:
            os.makedirs(path)
        self.store = OperationStore(self.home)
        self.profile = {
            "schema_version": 1, "site_id": "local", "display_name": "local",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "none"},
            "roots": {"source_root": self.temp, "build_root": self.build_root,
                      "run_root": self.run_root,
                      "staging_root": self.staging_root},
            "policy": {}, "shared_mappings": [],
        }
        self.store.upsert_site(self.profile)
        self.case_uid = "case-data-v2"
        self.store.upsert_case(
            self.case_uid, "data-v2-demo", self.project,
            {"authority": {"site_id": "local", "path": self.project},
             "transfer_policy": "snapshot",
             "revision": {"kind": "path", "root": self.project}},
            {"source_id": "", "build_id": "", "run_id": "",
             "active_run": None, "data_id": "", "analysis_id": ""},
        )

    def tearDown(self):
        shutil.rmtree(self.temp)

    def cli(self, *args, **kwargs):
        env = kwargs.pop("env", None)
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--ledger-home", self.home]
            + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, env=env)
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), stderr)
        return process.returncode, json.loads(stdout)

    def _register_run(self, run_id="run-1", files=None):
        run_root = os.path.join(self.run_root, self.case_uid, run_id)
        if not os.path.isdir(run_root):
            os.makedirs(run_root)
        for name, content in (files or {"output-000.bp": "payload zero\n",
                                        "output-001.bp": "payload one\n"}
                              ).items():
            with open(os.path.join(run_root, name), "w") as handle:
                handle.write(content)
        self.store.add_identity(
            self.case_uid, "run", run_id,
            {"id": run_id, "kind": "run", "site_id": "local",
             "root": {"site_id": "local", "path": run_root},
             "status": "exited"}, True)
        current = dict(self.store.get_case(self.case_uid)["current"])
        current["run_id"] = run_id
        current["active_run"] = {"site_id": "local", "path": run_root}
        self.store.upsert_case(
            self.case_uid, "data-v2-demo", self.project,
            {"authority": {"site_id": "local", "path": self.project},
             "transfer_policy": "snapshot",
             "revision": {"kind": "path", "root": self.project}},
            current,
        )
        return run_root

    def _record(self, *extra):
        return self.cli("--actor-run-id", "data-v2-test", "record", "data",
                        "--project-root", self.project, *extra)

    def _seal(self, data_id):
        return self.cli("--actor-run-id", "data-v2-test", "data", "seal",
                        "--project-root", self.project, "--data-id", data_id)

    def _verify(self, data_id):
        return self.cli("data", "verify", "--project-root", self.project,
                        "--data-id", data_id)

    def _v1_env(self):
        env = dict(os.environ)
        env["ENTITY_LEDGER_DATA_IDENTITY"] = "v1"
        return env

    def test_metadata_inventory_and_revision_identity(self):
        run_root = self._register_run()
        code, payload = self._record()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["integrity"], "metadata")
        self.assertTrue(payload["inventory_digest"].startswith("sha256:"))
        manifest = os.path.join(run_root, "data-inventory.json")
        with open(manifest, "r") as handle:
            inventory = json.load(handle)
        self.assertEqual(inventory["schema_version"], 2)
        self.assertEqual(inventory["integrity"], "metadata")
        self.assertEqual(inventory["probe"],
                         {"tool": "entity_ledger_executor",
                          "schema": "data.inventory.v2"})
        self.assertTrue(inventory["inventory_digest"])
        self.assertTrue(inventory["bytes_total"] > 0)
        for entry in inventory["files"]:
            self.assertEqual(set(entry), {"path", "bytes", "type"})
            self.assertEqual(entry["type"], "file")
        # the manifest itself is evidence about the tree, not data
        self.assertNotIn("data-inventory.json",
                         [entry["path"] for entry in inventory["files"]])
        expected = "data-" + domain_digest(
            "identity", "entity.data-revision.v2",
            {"run_id": "run-1", "integrity": "metadata",
             "inventory_digest": inventory["inventory_digest"]}
        ).split(":", 1)[1][:16]
        self.assertEqual(payload["data_id"], expected)
        identity = self.store.get_case(
            self.case_uid)["identities"]["data"]["items"][0]
        self.assertEqual(identity["identity_schema"], 2)
        self.assertEqual(identity["integrity"], "metadata")
        self.assertEqual(len(identity["entries"]), 2)

    def test_rerecord_unchanged_is_idempotent_growth_books_new_revision(self):
        run_root = self._register_run()
        code, first = self._record()
        self.assertEqual(code, 0, first)
        # An analysis bound to the first revision.
        self.store.add_identity(
            self.case_uid, "analysis", "analysis-1",
            {"id": "analysis-1", "kind": "analysis", "site_id": "local",
             "parents": {"data_id": first["data_id"]}, "script": "plot.py",
             "params": {}, "status": "recorded"}, True)
        code, second = self._record()
        self.assertEqual(code, 0, second)
        self.assertEqual(second["data_id"], first["data_id"])
        self.assertTrue(second["refreshed"])
        code, shown = self.cli("show", "--project-root", self.project)
        self.assertEqual(code, 0, shown)
        self.assertFalse(shown["analyses"][0]["stale"])
        with open(os.path.join(run_root, "output-002.bp"), "w") as handle:
            handle.write("late output\n")
        code, third = self._record()
        self.assertEqual(code, 0, third)
        self.assertNotEqual(third["data_id"], first["data_id"])
        self.assertFalse(third["refreshed"])
        case = self.store.get_case(self.case_uid)
        self.assertEqual(case["current"]["data_id"], third["data_id"])
        code, shown = self.cli("show", "--project-root", self.project)
        self.assertTrue(shown["analyses"][0]["stale"])
        dashboard = build_dashboard(self.store, self.project)
        self.assertEqual(dashboard["board"]["data"]["detail"],
                         "3 files, integrity metadata")

    def test_same_size_content_change_keeps_metadata_revision(self):
        """Documented semantics: metadata is NOT a content checksum — a
        same-size content change keeps the revision; strong seal/verify is
        what catches it."""
        run_root = self._register_run(files={"output.bp": "aaaaaaaa\n"})
        code, first = self._record()
        self.assertEqual(code, 0, first)
        with open(os.path.join(run_root, "output.bp"), "w") as handle:
            handle.write("bbbbbbbb\n")
        code, second = self._record()
        self.assertEqual(second["data_id"], first["data_id"])
        self.assertTrue(second["refreshed"])

    def test_seal_metadata_revision_and_idempotence(self):
        self._register_run()
        code, recorded = self._record()
        self.assertEqual(code, 0, recorded)
        code, sealed = self._seal(recorded["data_id"])
        self.assertEqual(code, 0, sealed)
        self.assertEqual(sealed["kind"], "entity-ledger.data.seal")
        self.assertTrue(sealed["state_mutated"])
        self.assertTrue(sealed["release_id"].startswith("data-"))
        self.assertEqual(sealed["integrity"], "strong")
        self.assertIn("bytes_planned_read", sealed)
        expected_release = "data-" + domain_digest(
            "identity", "entity.data-release.v2",
            {"data_revision_id": recorded["data_id"],
             "strong_inventory_digest": sealed["inventory_digest"]}
        ).split(":", 1)[1][:16]
        self.assertEqual(sealed["release_id"], expected_release)
        case = self.store.get_case(self.case_uid)
        # the release certifies the same bytes: current stays on the revision
        self.assertEqual(case["current"]["data_id"], recorded["data_id"])
        release = None
        for item in case["identities"]["data"]["items"]:
            if item.get("id") == sealed["release_id"]:
                release = item
        self.assertIsNotNone(release)
        self.assertTrue(release["sealed"])
        self.assertEqual(release["status"], "sealed")
        self.assertEqual(release["parents"],
                         {"run_id": "run-1",
                          "data_revision_id": recorded["data_id"]})
        events = [item["event_type"] for item in self.store.export()["events"]]
        self.assertEqual(events, ["record.data", "record.data-seal"])
        # sealing again is idempotent
        code, again = self._seal(recorded["data_id"])
        self.assertEqual(code, 0, again)
        self.assertEqual(again["release_id"], sealed["release_id"])
        self.assertTrue(again["refreshed"])
        # sealing the release itself is an idempotent ok with zero writes
        code, third = self._seal(sealed["release_id"])
        self.assertEqual(code, 0, third)
        self.assertFalse(third["state_mutated"])

    def test_tamper_after_seal_fails_verify_and_reseal(self):
        run_root = self._register_run()
        code, recorded = self._record()
        code, sealed = self._seal(recorded["data_id"])
        self.assertEqual(code, 0, sealed)
        code, verified = self._verify(sealed["release_id"])
        self.assertEqual(code, 0, verified)
        self.assertTrue(verified["ok"])
        self.assertFalse(verified["state_mutated"])
        with open(os.path.join(run_root, "output-000.bp"), "a") as handle:
            handle.write("tampered\n")
        # a failed verification is a result (ok=False), not a CLI error,
        # but the exit code is still non-zero like any checker
        code, verified = self._verify(sealed["release_id"])
        self.assertEqual(code, 2, verified)
        self.assertFalse(verified["ok"])
        self.assertNotEqual(verified["observed_digest"],
                            verified["expected_digest"])
        code, reseal = self._seal(sealed["release_id"])
        self.assertEqual(code, 2, reseal)
        self.assertFalse(reseal["ok"])
        self.assertFalse(reseal["state_mutated"])

    def test_seal_refuses_v1_identity(self):
        self._register_run()
        code, recorded = self.cli(
            "--actor-run-id", "data-v2-test", "record", "data",
            "--project-root", self.project, env=self._v1_env())
        self.assertEqual(code, 0, recorded)
        code, sealed = self._seal(recorded["data_id"])
        self.assertEqual(code, 2, sealed)
        self.assertEqual(sealed["status"], "needs_decision")
        self.assertIn("record data", sealed["error"])

    def test_strong_record_and_verify(self):
        self._register_run()
        code, recorded = self._record("--integrity", "strong")
        self.assertEqual(code, 0, recorded)
        self.assertEqual(recorded["integrity"], "strong")
        self.assertIn("bytes_planned_read", recorded)
        with open(recorded["manifest"], "r") as handle:
            inventory = json.load(handle)
        for entry in inventory["files"]:
            self.assertIn("sha256", entry)
        code, verified = self._verify(recorded["data_id"])
        self.assertEqual(code, 0, verified)
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["integrity"], "strong")

    def test_verify_v1_legacy_identity(self):
        run_root = self._register_run()
        code, recorded = self.cli(
            "--actor-run-id", "data-v2-test", "record", "data",
            "--project-root", self.project, env=self._v1_env())
        self.assertEqual(code, 0, recorded)
        code, verified = self._verify(recorded["data_id"])
        self.assertEqual(code, 0, verified)
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["integrity"], "legacy-unknown")
        with open(os.path.join(run_root, "output-000.bp"), "r+b") as handle:
            handle.write(b"X")
        code, verified = self._verify(recorded["data_id"])
        self.assertEqual(code, 2, verified)
        self.assertFalse(verified["ok"])
        self.assertIn("output-000.bp", verified["mismatches"])

    def test_feature_flag_v1_reproduces_legacy_identity(self):
        run_root = self._register_run()
        code, payload = self.cli(
            "--actor-run-id", "data-v2-test", "record", "data",
            "--project-root", self.project, env=self._v1_env())
        self.assertEqual(code, 0, payload)
        digest = canonical_hash({"case_uid": self.case_uid, "run_id": "run-1"})
        expected = "data-" + digest.split(":", 1)[1][:16]
        self.assertEqual(payload["data_id"], expected)
        with open(os.path.join(run_root, "data-inventory.json"), "r") as handle:
            inventory = json.load(handle)
        self.assertEqual(inventory["schema_version"], 1)
        for entry in inventory["files"]:
            self.assertIn("sha256", entry)
        identity = self.store.get_case(
            self.case_uid)["identities"]["data"]["items"][0]
        self.assertNotIn("identity_schema", identity)
        dashboard = build_dashboard(self.store, self.project)
        self.assertEqual(dashboard["board"]["data"]["detail"],
                         "2 files, integrity legacy-unknown")


if __name__ == "__main__":
    unittest.main()
