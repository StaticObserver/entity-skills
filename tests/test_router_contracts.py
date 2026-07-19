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
            "scripts/entity_router_common.py",
            "scripts/entity_router_purge.py",
            "scripts/entity_router_remote.py",
            "scripts/entity_router_state.py",
            "scripts/entity_router_status.py",
            "scripts/entity_router_site.py",
            "scripts/entity_router_flow.py",
            "scripts/entity_router_flow_common.py",
            "scripts/entity_router_flow_runners.py",
            "scripts/entity_router_flow_metrics.py",
            "scripts/entity_router_project.py",
            "scripts/entity_router_store.py",
            "scripts/entity_router_planner.py",
            "scripts/entity_router_operation.py",
            "scripts/entity_router_executor.py",
            "scripts/entityctl.py",
            "templates/goal.schema.json",
            "templates/operation-plan.schema.json",
            "templates/flow-request.schema.json",
            "templates/flow-result.schema.json",
            "templates/flow-check.schema.json",
            "templates/worker-envelope.schema.json",
            "templates/dispatch-receipt.schema.json",
            "references/workspace-layout.md",
            "references/router-runtime.md",
            "playbooks/new-simulation.md",
            "playbooks/run-simulation.md",
            "playbooks/resume-simulation.md",
            "playbooks/analyze-run.md",
            "playbooks/purge-data.md",
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
        self.assertEqual(request["schema_version"], 2)
        self.assertEqual(result["schema_version"], 2)
        self.assertTrue({"case_uid", "execution_site_id", "workflow_id", "action_id", "action_type", "owner", "write_roots"}.issubset(request))
        self.assertTrue({"case_uid", "execution_site_id", "workflow_id", "action_id", "status", "verification"}.issubset(result))
        self.assertIn("target", case["workflow"])
        self.assertIn("target_hash", case["workflow"])
        self.assertIn("writer_lease", case["control"])
        self.assertIn("orchestration", request)
        self.assertIn("actor", request)
        self.assertIn("actor", result)
        self.assertEqual("unattributed", request["actor"]["run_id"])
        self.assertIn("runner_args", request)
        self.assertIn("identity", result)

    def test_flow_schemas_are_bounded_and_versioned(self):
        request = self.read_json("templates/flow-request.schema.json")
        result = self.read_json("templates/flow-result.schema.json")
        check = self.read_json("templates/flow-check.schema.json")
        envelope = self.read_json("templates/worker-envelope.schema.json")
        receipt = self.read_json("templates/dispatch-receipt.schema.json")
        self.assertEqual(request["properties"]["schema_version"]["const"], 1)
        self.assertEqual(request["properties"]["steps"]["maxItems"], 8)
        self.assertFalse(request["additionalProperties"])
        self.assertEqual(result["properties"]["schema_version"]["const"], 1)
        self.assertEqual(check["properties"]["schema_version"]["const"], 1)
        self.assertFalse(envelope["additionalProperties"])
        self.assertFalse(receipt["additionalProperties"])

    def test_v5_goal_schema_excludes_controller_mechanics(self):
        goal = self.read_json("templates/goal.schema.json")
        plan = self.read_json("templates/operation-plan.schema.json")
        self.assertFalse(goal["additionalProperties"])
        self.assertEqual(goal["properties"]["kind"]["const"], "run")
        for field in ["operation_id", "case_uid", "locator", "owner", "lease", "plan_hash"]:
            self.assertNotIn(field, goal["properties"])
        self.assertEqual(plan["properties"]["kind"]["const"], "entity-router.plan")

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
        self.assertIn("at most one remote call", skill)

    def test_action_prefixes_have_fixed_execution_contracts(self):
        expected = {
            "source": ("router", "playbook-sync"),
            "pgen": ("entity-pgen", "entity-pgen"),
            "build": ("entity-env-build", "entity-env-build"),
            "data": ("entity-nt2py", "entity-nt2py"),
            "run": ("playbook-run", "playbook-run"),
            "analysis": ("playbook-analysis", "playbook-analysis"),
            "failure": ("failure-triage", "failure-triage"),
        }
        for prefix, contract in expected.items():
            self.assertEqual(contract, router_state.ACTION_EXECUTION[prefix])
        self.assertEqual(("router", "router"), router_state.required_execution("data.purge"))

    def test_pgen_write_envelope_is_owner_specific(self):
        source = os.path.join(ROOT, "test-source")
        state = {
            "control": {"site_id": "controller", "root": os.path.join(ROOT, "control")},
            "source": {"authority": {"site_id": "source", "path": source}},
            "artifacts": {
                "pgen": {"site_id": "source", "path": os.path.join(source, "pgen.hpp")},
                "toml": {"site_id": "source", "path": os.path.join(source, "smoke.toml")},
                "design": {"site_id": "source", "path": os.path.join(source, "docs", "design.md")},
            },
            "resources": {},
        }
        allowed = [
            state["artifacts"]["pgen"],
            state["artifacts"]["toml"],
            {"site_id": "source", "path": os.path.join(source, "docs")},
        ]
        router_state.validate_action_write_envelope(state, "pgen.edit", "source", allowed, ROOT)
        with self.assertRaises(router_state.StateError):
            router_state.validate_action_write_envelope(
                state, "pgen.edit", "source",
                [{"site_id": "source", "path": os.path.join(source, "run-001")}], ROOT
            )
        with self.assertRaises(router_state.StateError):
            router_state.validate_action_write_envelope(
                state, "pgen.edit", "other", allowed, ROOT
            )

if __name__ == "__main__":
    unittest.main()
