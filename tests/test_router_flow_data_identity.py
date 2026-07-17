from __future__ import print_function

import json
import os
import shutil
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_router_common import RouterError, ensure_home, now_utc, save_site_profile  # noqa: E402
from entity_router_flow_runners import run_step  # noqa: E402
from entity_router_state import data_identity_id  # noqa: E402


class RouterDataIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-data-identity-")
        self.home = ensure_home(os.path.join(self.temp, "control"))
        self.data = os.path.join(self.temp, "data")
        self.analysis = os.path.join(self.temp, "analysis")
        os.makedirs(self.data)
        os.makedirs(self.analysis)
        save_site_profile(self.home, {
            "schema_version": 1, "site_id": "local", "display_name": "local",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "none"},
            "roots": {"run_root": self.data, "analysis_root": self.analysis},
            "shared_mappings": [], "created_at": now_utc(), "updated_at": now_utc(),
        })
        self.inventory = os.path.join(self.analysis, "inventory.json")
        with open(self.inventory, "w") as handle:
            json.dump({"schema_version": 1, "status": "ok", "nt2py_version": "1.5.3"}, handle)
        self.state = {"resources": {"data": {"root": {"site_id": "local", "path": self.data}}}}
        self.request = {
            "parents": {"run_id": "run-1"}, "resource_bindings": {},
            "runner_args": {"inventory": {"site_id": "local", "path": self.inventory}},
        }

    def tearDown(self):
        shutil.rmtree(self.temp)

    def evidence(self, digest, receipt_digest):
        return [
            {"locator": {"site_id": "local", "path": self.inventory},
             "kind": "file", "fingerprint": {"sha256": digest}},
            {"locator": {"site_id": "local", "path": os.path.join(self.analysis, "receipt.json")},
             "kind": "file", "fingerprint": {"sha256": receipt_digest}},
        ]

    def test_identity_uses_run_root_inventory_hash_and_nt2_version_only(self):
        first, seed = data_identity_id(self.home, self.state, self.request,
                                       self.evidence("inventory-a", "receipt-a"))
        replay, unused = data_identity_id(self.home, self.state, self.request,
                                          self.evidence("inventory-a", "receipt-b"))
        changed, unused = data_identity_id(self.home, self.state, self.request,
                                           self.evidence("inventory-b", "receipt-c"))
        self.assertEqual(first, replay)
        self.assertNotEqual(first, changed)
        self.assertEqual(seed["run_id"], "run-1")
        self.assertEqual(seed["nt2py_version"], "1.5.3")

    def test_inventory_inside_raw_data_root_is_rejected_before_probe(self):
        unsafe = os.path.join(self.data, "inventory.json")
        step = {
            "case_uid": "case", "action_id": "inspect", "action_type": "data.inspect",
            "execution_site_id": "local", "runner": "data.inspect.v1",
            "read_roots": [{"site_id": "local", "path": self.data}],
            "write_roots": [{"site_id": "local", "path": self.data}],
            "protected_paths": [],
            "runner_args": {
                "data_root": {"site_id": "local", "path": self.data},
                "inventory": {"site_id": "local", "path": unsafe},
                "receipt": {"site_id": "local", "path": os.path.join(self.data, "receipt.json")},
            },
        }
        with self.assertRaises(RouterError):
            run_step(self.home, step, "sha256:" + "a" * 64)
        self.assertFalse(os.path.exists(unsafe))


if __name__ == "__main__":
    unittest.main()
