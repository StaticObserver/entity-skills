#!/usr/bin/env python3

import glob
import json
import os
import re
import sys
import unittest


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-ledger", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_ledger_common import LedgerError, domain_digest
import entity_ledger_executor


REGISTRY_PATH = os.path.join(ROOT, "hash-registry.json")
PURPOSES = {"identity", "evidence", "transfer", "observation"}
COST_CLASSES = {"small", "bounded", "large"}
ENTRY_KEYS = {"id", "file", "function", "purpose", "schema", "scope",
              "cost_class", "gate", "remediation"}
DIGEST_TOKEN = re.compile(
    r"hashlib\.sha256|sha256_file|canonical_hash|domain_digest|site_file_sha256")


def _production_files():
    files = glob.glob(os.path.join(ROOT, "skills", "*", "scripts", "*.py"))
    files += glob.glob(os.path.join(ROOT, "tools", "**", "*.py"),
                       recursive=True)
    return sorted(files)


class HashRegistryTest(unittest.TestCase):
    def setUp(self):
        with open(REGISTRY_PATH, "r") as handle:
            self.registry = json.load(handle)
        self.entries = self.registry["entries"]

    def test_registry_schema(self):
        ids = set()
        for entry in self.entries:
            self.assertEqual(set(entry), ENTRY_KEYS, entry.get("id"))
            self.assertIn(entry["purpose"], PURPOSES, entry["id"])
            self.assertIn(entry["cost_class"], COST_CLASSES, entry["id"])
            self.assertIs(type(entry["gate"]), bool, entry["id"])
            self.assertTrue(entry["schema"], entry["id"])
            self.assertTrue(entry["remediation"], entry["id"])
            self.assertNotIn(entry["id"], ids)
            ids.add(entry["id"])
            path = os.path.join(ROOT, entry["file"])
            self.assertTrue(os.path.isfile(path),
                            "%s: missing file %s" % (entry["id"], entry["file"]))

    def test_v1_data_inventory_is_registered_as_large_evidence(self):
        entry = [item for item in self.entries
                 if item["id"] == "ledger-executor.data-inventory-v1"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0]["cost_class"], "large")
        self.assertEqual(entry[0]["purpose"], "evidence")

    def test_coverage_every_digest_file_is_registered(self):
        """File-level gate against NEW unregistered digest call sites (in
        particular new recursive content hashing): any production file that
        computes a digest must appear in the registry."""
        registered = {entry["file"] for entry in self.entries}
        for path in _production_files():
            with open(path, "r") as handle:
                text = handle.read()
            if not DIGEST_TOKEN.search(text):
                continue
            relative = os.path.relpath(path, ROOT)
            self.assertIn(
                relative, registered,
                "%s computes digests but has no hash-registry.json entry"
                % relative)


class DomainDigestTest(unittest.TestCase):
    def test_deterministic(self):
        payload = {"b": [1, 2], "a": {"x": "y"}}
        first = domain_digest("identity", "entity.test.v1", payload)
        second = domain_digest("identity", "entity.test.v1",
                               {"a": {"x": "y"}, "b": [1, 2]})
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("sha256:"))
        self.assertEqual(len(first), len("sha256:") + 64)

    def test_domain_separation_by_purpose(self):
        payload = {"files": []}
        digests = {purpose: domain_digest(purpose, "entity.test.v1", payload)
                   for purpose in sorted(PURPOSES)}
        self.assertEqual(len(set(digests.values())), len(PURPOSES))

    def test_domain_separation_by_schema(self):
        payload = {"files": []}
        self.assertNotEqual(
            domain_digest("evidence", "entity.test.v1", payload),
            domain_digest("evidence", "entity.test.v2", payload))

    def test_payload_changes_digest(self):
        self.assertNotEqual(
            domain_digest("evidence", "entity.test.v1", {"files": []}),
            domain_digest("evidence", "entity.test.v1", {"files": ["a"]}))

    def test_invalid_purpose_rejected(self):
        with self.assertRaises(LedgerError):
            domain_digest("whatever", "entity.test.v1", {})

    def test_executor_mirror_matches(self):
        """The standalone executor copy must produce identical digests."""
        payload = {"integrity": "metadata",
                   "files": [{"path": "a.bp", "bytes": 3, "type": "file"}]}
        self.assertEqual(
            domain_digest("evidence", "entity.data-inventory.v2", payload),
            entity_ledger_executor.domain_digest(
                "evidence", "entity.data-inventory.v2", payload))


if __name__ == "__main__":
    unittest.main()
