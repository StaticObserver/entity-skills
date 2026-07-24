from __future__ import print_function

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


PGEN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(PGEN_ROOT))
PREFLIGHT = os.path.join(PGEN_ROOT, "scripts", "pgen_preflight.py")
LEDGER_SCRIPTS = os.path.join(ROOT, "skills", "entity-ledger", "scripts")
if LEDGER_SCRIPTS not in sys.path:
    sys.path.insert(0, LEDGER_SCRIPTS)

from entity_ledger_store import OperationStore  # noqa: E402


class PGenPreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-pgen-preflight-")
        self.home = os.path.join(self.temp, "control")
        self.checkout = os.path.join(self.temp, "arbitrary", "entity")
        os.makedirs(os.path.join(self.checkout, "docs"))
        self.store = OperationStore(self.home)
        self.store.upsert_site({
            "schema_version": 1, "site_id": "laptop", "display_name": "laptop",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "none"},
            "roots": {"source_root": self.temp},
            "policy": {}, "shared_mappings": [],
        })

    def tearDown(self):
        shutil.rmtree(self.temp)

    def run_json(self, script, *args):
        process = subprocess.Popen([sys.executable, script] + list(args),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True)
        stdout, stderr = process.communicate()
        return process.returncode, json.loads(stdout), stderr

    def create_case(self):
        self.store.upsert_case(
            "case-smoke-uid", "smoke", self.checkout,
            {"authority": {"site_id": "laptop", "path": self.checkout},
             "transfer_policy": "snapshot"},
            {"source_id": "", "build_id": "", "run_id": "", "active_run": None,
             "data_id": "", "analysis_id": ""},
        )

    def preflight(self, operation, target, home=None):
        args = ["--ledger-home", home or self.home,
                "--operation", operation, "--target", target]
        return self.run_json(PREFLIGHT, *args)

    def test_standalone_operations_are_allowed(self):
        target = "laptop:%s" % os.path.join(self.temp, "standalone.hpp")
        for operation in ["read", "write"]:
            code, payload, error = self.preflight(operation, target)
            self.assertEqual(code, 0, error)
            self.assertTrue(payload["mode"].startswith("standalone-"))

    def test_standalone_when_store_is_missing(self):
        target = "laptop:%s" % os.path.join(self.temp, "standalone.hpp")
        empty_home = os.path.join(self.temp, "no-store")
        code, payload, error = self.preflight("write", target, home=empty_home)
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["mode"], "standalone-write")
        self.assertFalse(payload["store_present"])
        self.assertIn("could not be checked", payload["reason"])

    def test_confirmed_standalone_reports_store_present(self):
        target = "laptop:%s" % os.path.join(self.temp, "standalone.hpp")
        code, payload, error = self.preflight("write", target)
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["mode"], "standalone-write")
        self.assertTrue(payload["store_present"])

    def test_invalid_target_still_prints_json_and_exits_2(self):
        code, payload, error = self.preflight("write", "laptop:relative/path.hpp")
        self.assertEqual(code, 2, error)
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["mode"], "router-required")
        self.assertIn("laptop:relative/path.hpp", payload["reason"])

    def test_corrupt_store_still_prints_json_and_exits_2(self):
        corrupt_home = os.path.join(self.temp, "corrupt-store")
        os.makedirs(corrupt_home)
        with open(os.path.join(corrupt_home, "ledger.db"), "w") as handle:
            handle.write("not a sqlite database")
        target = "laptop:%s" % os.path.join(self.temp, "standalone.hpp")
        code, payload, error = self.preflight("write", target, home=corrupt_home)
        self.assertEqual(code, 2, error)
        self.assertFalse(payload["allowed"])

    def test_multiple_cases_covering_target_are_ambiguous(self):
        self.create_case()
        other = os.path.join(self.temp, "other-checkout")
        os.makedirs(other)
        self.store.upsert_case(
            "case-second-uid", "second", other,
            {"authority": {"site_id": "laptop", "path": self.temp},
             "transfer_policy": "snapshot"},
            {"source_id": "", "build_id": "", "run_id": "", "active_run": None,
             "data_id": "", "analysis_id": ""},
        )
        target = "laptop:%s" % os.path.join(self.checkout, "pgen.hpp")
        code, payload, error = self.preflight("write", target)
        self.assertEqual(code, 2, error)
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["mode"], "ambiguous")
        self.assertIn("multiple Cases", payload["reason"])

    def test_symlinked_target_matches_registered_real_path(self):
        self.create_case()
        link = os.path.join(self.temp, "checkout-link")
        os.symlink(self.checkout, link)
        target = "laptop:%s" % os.path.join(link, "pgen.hpp")
        code, payload, error = self.preflight("write", target)
        self.assertEqual(code, 2, error)
        self.assertEqual(payload["mode"], "router-required")
        self.assertEqual(payload["case_uid"], "case-smoke-uid")

    def test_registered_source_is_managed_and_write_fails_closed(self):
        self.create_case()
        target = "laptop:%s" % os.path.join(self.checkout, "pgen.hpp")
        code, payload, error = self.preflight("read", target)
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["mode"], "managed-readonly")
        self.assertEqual(payload["case_uid"], "case-smoke-uid")

        code, payload, unused = self.preflight("write", target)
        self.assertEqual(code, 2)
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["mode"], "router-required")
        self.assertIn("v5 pgen Goal", payload["reason"])

    def test_unregistered_site_and_path_are_not_managed(self):
        self.create_case()
        for target in [
            "laptop:%s" % os.path.join(self.temp, "other.hpp"),
            "other:%s" % os.path.join(self.checkout, "pgen.hpp"),
        ]:
            code, payload, unused = self.preflight("write", target)
            self.assertEqual(code, 0)
            self.assertEqual(payload["mode"], "standalone-write")


if __name__ == "__main__":
    unittest.main()
