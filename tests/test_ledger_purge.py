from __future__ import print_function

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PURGE = os.path.join(ROOT, "skills", "entity-ledger", "scripts", "entity_ledger_purge.py")


class LedgerPurgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-purge-")
        self.target = os.path.join(self.temp, "run", "test.log")
        self.receipt_root = os.path.join(self.temp, "staging", "receipts")
        self.receipt = os.path.join(self.receipt_root, "receipt.json")
        self.protected = os.path.join(self.temp, "source")
        os.makedirs(os.path.dirname(self.target))
        os.makedirs(self.protected)
        with open(self.target, "w") as handle:
            handle.write("runtime log\n")
        self.size = os.path.getsize(self.target)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def request(self, include_fingerprint=True):
        request = {
            "action_type": "data.purge",
            "owner": "ledger",
            "execution_domain": "ledger",
            "execution_site_id": "test-site",
            "authorization": "explicit unit-test authorization",
            "case_uid": "case",
            "workflow_id": "workflow",
            "action_id": "action",
            "started_at": "2026-01-01T00:00:00Z",
            "write_roots": [
                {"site_id": "test-site", "path": self.target},
                {"site_id": "test-site", "path": self.receipt_root},
            ],
            "expected_outputs": [{"site_id": "test-site", "path": self.receipt}],
            "protected_paths": [{"site_id": "test-site", "path": self.protected}],
            "inputs": [{
                "locator": {"site_id": "test-site", "path": self.target},
                "fingerprint": {"size": self.size} if include_fingerprint else {},
            }],
        }
        path = os.path.join(self.temp, "request.json")
        with open(path, "w") as handle:
            json.dump(request, handle)
        return path

    def test_single_file_purge_writes_receipt(self):
        request = self.request()
        subprocess.check_call([sys.executable, PURGE, "--request", request, "--receipt", self.receipt])
        self.assertFalse(os.path.exists(self.target))
        with open(self.receipt, "r") as handle:
            receipt = json.load(handle)
        self.assertEqual("completed", receipt["status"])
        self.assertFalse(receipt["recovered_after_executor_failure"])

    def test_single_directory_purge_writes_receipt(self):
        target_dir = os.path.join(self.temp, "run-dir")
        os.makedirs(target_dir)
        with open(os.path.join(target_dir, "out.dat"), "w") as handle:
            handle.write("payload\n")
        request_path = self.request()
        with open(request_path, "r") as handle:
            payload = json.load(handle)
        payload["write_roots"][0]["path"] = target_dir
        payload["inputs"][0]["locator"]["path"] = target_dir
        payload["inputs"][0]["fingerprint"] = {}
        with open(request_path, "w") as handle:
            json.dump(payload, handle)
        subprocess.check_call([sys.executable, PURGE, "--request", request_path, "--receipt", self.receipt])
        self.assertFalse(os.path.exists(target_dir))
        with open(self.receipt, "r") as handle:
            receipt = json.load(handle)
        self.assertEqual("completed", receipt["status"])
        # the deletion removed the original probe directory itself; the
        # receipt must fall back to the nearest surviving parent
        self.assertTrue(os.path.isdir(receipt["filesystem"]["probe_path"]))

    def test_recover_after_file_was_deleted(self):
        request = self.request()
        os.unlink(self.target)
        subprocess.check_call([
            sys.executable, PURGE, "--request", request, "--receipt", self.receipt,
            "--recover-after-delete",
        ])
        with open(self.receipt, "r") as handle:
            receipt = json.load(handle)
        self.assertEqual("completed", receipt["status"])
        self.assertTrue(receipt["recovered_after_executor_failure"])
        self.assertEqual(self.size, receipt["manifest_bytes"])

    def test_rejects_target_missing_from_action_inputs(self):
        request = self.request()
        with open(request, "r") as handle:
            payload = json.load(handle)
        payload["inputs"] = []
        with open(request, "w") as handle:
            json.dump(payload, handle)
        process = subprocess.run(
            [sys.executable, PURGE, "--request", request, "--receipt", self.receipt],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("exactly match", process.stderr)
        self.assertTrue(os.path.exists(self.target))

    def test_rejects_symlink_escape_into_protected_path(self):
        request = self.request()
        protected_target = os.path.join(self.protected, "secret.log")
        with open(protected_target, "w") as handle:
            handle.write("protected\n")
        linked_run = os.path.join(self.temp, "linked-run")
        os.symlink(self.protected, linked_run)
        linked_target = os.path.join(linked_run, os.path.basename(protected_target))
        with open(request, "r") as handle:
            payload = json.load(handle)
        payload["write_roots"][0]["path"] = linked_target
        payload["inputs"][0]["locator"]["path"] = linked_target
        with open(request, "w") as handle:
            json.dump(payload, handle)
        process = subprocess.run(
            [sys.executable, PURGE, "--request", request, "--receipt", self.receipt],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("protected path", process.stderr)
        self.assertTrue(os.path.exists(protected_target))


if __name__ == "__main__":
    unittest.main()
