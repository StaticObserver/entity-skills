from __future__ import print_function

import os
import re
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_ROOT = os.path.join(ROOT, "skills", "entity-ledger")
sys.path.insert(0, os.path.join(LEDGER_ROOT, "scripts"))


class LedgerContractTest(unittest.TestCase):
    def test_runtime_entrypoints_exist(self):
        required = [
            "SKILL.md",
            "scripts/entity_ledger_common.py",
            "scripts/entity_ledger_purge.py",
            "scripts/entity_ledger_remote.py",
            "scripts/entity_ledger_store.py",
            "scripts/entity_ledger_facts.py",
            "scripts/entity_ledger_record.py",
            "scripts/entity_ledger_dashboard.py",
            "scripts/entity_ledger_operation.py",
            "scripts/entity_ledger_executor.py",
            "scripts/entityctl.py",
            "templates/site-profile.schema.json",
            "references/workspace-layout.md",
            "references/ledger-runtime.md",
            "../entity-pgen/SKILL.md",
            "../entity-pgen/scripts/pgen_preflight.py",
            "../entity-env-build/SKILL.md",
            "../entity-nt2py/SKILL.md",
        ]
        for relative in required:
            self.assertTrue(os.path.isfile(os.path.join(LEDGER_ROOT, relative)), relative)

    def test_skill_name_matches_directory(self):
        with open(os.path.join(LEDGER_ROOT, "SKILL.md"), "r") as handle:
            skill = handle.read()
        match = re.search(r"^name:\s*(\S+)\s*$", skill, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(os.path.basename(LEDGER_ROOT), match.group(1))

    def test_ledger_runtime_is_not_scattered_at_project_root(self):
        forbidden = [
            "SKILL.md",
            "agents",
            "playbooks",
            "references",
            "templates",
            os.path.join("scripts", "entity_ledger_store.py"),
        ]
        for relative in forbidden:
            self.assertFalse(os.path.exists(os.path.join(ROOT, relative)), relative)

    def test_ledger_declares_all_execution_domains(self):
        with open(os.path.join(LEDGER_ROOT, "SKILL.md"), "r") as handle:
            skill = handle.read()
        for value in ["entity-pgen", "entity-env-build", "entity-nt2py"]:
            self.assertIn(value, skill)

    def test_status_is_controller_local_by_default(self):
        with open(os.path.join(LEDGER_ROOT, "SKILL.md"), "r") as handle:
            skill = handle.read()
        self.assertIn("status", skill)
        self.assertIn("read-only", skill)
        with open(os.path.join(LEDGER_ROOT, "references",
                               "ledger-runtime.md"), "r") as handle:
            runtime = handle.read()
        self.assertIn("controller-local", runtime)
        self.assertIn("at most three bounded", runtime)


if __name__ == "__main__":
    unittest.main()
