from __future__ import print_function

import json
import os
import re
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTER_ROOT = os.path.join(ROOT, "skills", "entity-router")
sys.path.insert(0, os.path.join(ROUTER_ROOT, "scripts"))


class RouterContractTest(unittest.TestCase):
    def read_json(self, relative):
        with open(os.path.join(ROUTER_ROOT, relative), "r") as handle:
            return json.load(handle)

    def test_runtime_entrypoints_exist(self):
        required = [
            "SKILL.md",
            "scripts/entity_router_common.py",
            "scripts/entity_router_purge.py",
            "scripts/entity_router_remote.py",
            "scripts/entity_router_store.py",
            "scripts/entity_router_planner.py",
            "scripts/entity_router_operation.py",
            "scripts/entity_router_executor.py",
            "scripts/entityctl.py",
            "templates/goal.schema.json",
            "templates/operation-plan.schema.json",
            "references/workspace-layout.md",
            "references/router-runtime.md",
            "../entity-pgen/SKILL.md",
            "../entity-pgen/scripts/pgen_preflight.py",
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
            os.path.join("scripts", "entity_router_store.py"),
        ]
        for relative in forbidden:
            self.assertFalse(os.path.exists(os.path.join(ROOT, relative)), relative)

    def test_v5_goal_schema_excludes_controller_mechanics(self):
        goal = self.read_json("templates/goal.schema.json")
        plan = self.read_json("templates/operation-plan.schema.json")
        self.assertFalse(goal["additionalProperties"])
        self.assertEqual(goal["properties"]["kind"]["enum"], ["run", "build", "data"])
        for field in ["operation_id", "case_uid", "locator", "owner", "lease", "plan_hash"]:
            self.assertNotIn(field, goal["properties"])
        self.assertEqual(plan["properties"]["kind"]["const"], "entity-router.plan")

    def test_goal_schema_declares_kind_specific_requirements(self):
        goal = self.read_json("templates/goal.schema.json")
        requirements = {}
        for clause in goal.get("allOf", []):
            kind = clause.get("if", {}).get("properties", {}).get("kind", {}).get("const")
            if kind:
                requirements[kind] = clause.get("then", {}).get("required", [])
        # mirrors validate_goal in entity_router_planner.py
        self.assertEqual(requirements.get("run"), ["input", "site", "compute"])
        self.assertEqual(requirements.get("build"), ["site", "checkpoint", "executable"])
        # data Goals take an optional run reference and no required fields
        self.assertNotIn("data", requirements)
        self.assertIn("run", goal["properties"])
        self.assertIn("checkpoint", goal["properties"])

    def test_router_declares_all_execution_domains(self):
        with open(os.path.join(ROUTER_ROOT, "SKILL.md"), "r") as handle:
            skill = handle.read()
        for value in ["entity-pgen", "entity-env-build", "entity-nt2py"]:
            self.assertIn(value, skill)

    def test_status_is_controller_local_by_default(self):
        with open(os.path.join(ROUTER_ROOT, "SKILL.md"), "r") as handle:
            skill = handle.read()
        self.assertIn("status", skill)
        self.assertIn("controller-local", skill)
        self.assertIn("at most three bounded scheduler queries", skill)


if __name__ == "__main__":
    unittest.main()
