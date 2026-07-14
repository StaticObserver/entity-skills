from __future__ import print_function

import json
import os
import re
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTER_ROOT = os.path.join(ROOT, "skills", "entity-router")
sys.path.insert(0, os.path.join(ROUTER_ROOT, "scripts"))

import entity_router_state as router_state


class RouterContractTest(unittest.TestCase):
    def read_json(self, relative):
        with open(os.path.join(ROUTER_ROOT, relative), "r") as handle:
            return json.load(handle)

    def test_runtime_entrypoints_exist(self):
        required = [
            "SKILL.md",
            "scripts/entity_router_state.py",
            "references/workspace-layout.md",
            "references/router-runtime.md",
            "playbooks/new-simulation.md",
            "playbooks/run-simulation.md",
            "playbooks/resume-simulation.md",
            "playbooks/analyze-run.md",
            "../entity-pgen/SKILL.md",
            "../entity-env-build/SKILL.md",
            "../entity-nt2py/SKILL.md",
        ]
        for relative in required:
            self.assertTrue(os.path.isfile(os.path.join(ROUTER_ROOT, relative)), relative)

    def test_skill_name_matches_directory(self):
        with open(os.path.join(ROUTER_ROOT, "SKILL.md"), "r") as handle:
            skill = handle.read()
        match = re.search(r"^name:\s*(\S+)\s*$", skill, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(os.path.basename(ROUTER_ROOT), match.group(1))

    def test_router_runtime_is_not_scattered_at_project_root(self):
        forbidden = [
            "SKILL.md",
            "agents",
            "playbooks",
            "references",
            "templates",
            os.path.join("scripts", "entity_router_state.py"),
        ]
        for relative in forbidden:
            self.assertFalse(os.path.exists(os.path.join(ROOT, relative)), relative)

    def test_templates_match_runtime_schema(self):
        case = self.read_json("templates/case-state.json")
        request = self.read_json("templates/action-request.json")
        result = self.read_json("templates/action-result.json")
        self.assertEqual(case["schema_version"], router_state.SCHEMA_VERSION)
        self.assertEqual(set(case["readiness"]), set(router_state.READINESS_STATUSES))
        self.assertTrue({"case_id", "workflow_id", "action_id", "action_type", "owner", "write_roots"}.issubset(request))
        self.assertTrue({"case_id", "workflow_id", "action_id", "status", "verification"}.issubset(result))

    def test_router_declares_all_execution_domains(self):
        with open(os.path.join(ROUTER_ROOT, "SKILL.md"), "r") as handle:
            skill = handle.read()
        for value in [
            "entity-pgen",
            "entity-env-build",
            "entity-nt2py",
            "playbook-run",
            "playbook-analysis",
            "failure-triage",
        ]:
            self.assertIn(value, skill)


if __name__ == "__main__":
    unittest.main()
