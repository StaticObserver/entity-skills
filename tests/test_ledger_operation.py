#!/usr/bin/env python3

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-ledger", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_ledger_operation import ExecutorClient, OperationError


class ExecutorInvokeTest(unittest.TestCase):
    """B1: a crashed remote executor must surface its stderr, and a clean
    exit with garbage stdout must report invalid JSON with the stdout head."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-operation-")
        profile = {
            "schema_version": 1, "site_id": "fake-ssh",
            "transport": {"kind": "ssh", "ssh_alias": "fake"},
            "scheduler": {"kind": "none"},
            "roots": {"staging_root": os.path.join(self.temp, "staging")},
            "policy": {}, "shared_mappings": [],
        }
        self.client = ExecutorClient(profile)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def _invoke(self, code, stdout, stderr):
        envelope = {"step_id": "s1", "receipt": "/r/receipt.json"}
        with mock.patch.object(
                self.client, "ensure_executor", return_value="/r/executor.py"):
            with mock.patch.object(
                    self.client, "_stage_envelope", return_value="/r/req.json"):
                with mock.patch("entity_ledger_operation.run_on_site",
                                return_value=(code, stdout, stderr)):
                    return self.client.invoke("execute", envelope)

    def test_nonzero_exit_surfaces_stderr_tail(self):
        traceback = ("Traceback (most recent call last):\n"
                     "  File \"entity_ledger_executor.py\", line 9, in <module>\n"
                     "AttributeError: module 'contextlib' has no attribute "
                     "'nullcontext'")
        stderr = "x" * 1000 + "\n" + traceback + "\n"
        with self.assertRaises(OperationError) as caught:
            self._invoke(1, "", stderr)
        message = str(caught.exception)
        self.assertIn("Site executor exited 1", message)
        self.assertIn("AttributeError", message)
        # only the tail (~500 chars) is carried, not the whole stderr
        self.assertNotIn("x" * 1000, message)
        self.assertNotIn("invalid JSON", message)

    def test_clean_exit_with_bad_json_reports_stdout_head(self):
        stdout = "some login-shell banner noise\nnot json at all\n"
        with self.assertRaises(OperationError) as caught:
            self._invoke(0, stdout, "")
        message = str(caught.exception)
        self.assertIn("invalid JSON", message)
        self.assertIn("login-shell banner", message)

    def test_clean_exit_with_valid_result_passes(self):
        result = self._invoke(0, '{"status": "completed", "ok": true}\n', "")
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
