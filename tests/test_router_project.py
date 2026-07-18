from __future__ import print_function

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
STATE = os.path.join(SCRIPTS, "entity_router_state.py")
SITE = os.path.join(SCRIPTS, "entity_router_site.py")
PROJECT = os.path.join(SCRIPTS, "entity_router_project.py")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")


class RouterProjectBindingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-router-project-")
        self.home = os.path.join(self.temp, "control")
        self.source = os.path.join(self.temp, "project")
        os.makedirs(os.path.join(self.source, "docs"))
        self.write(os.path.join(self.source, "pgen.hpp"), "// pgen\n")
        self.write(os.path.join(self.source, "input.toml"), "[simulation]\n")
        self.write(os.path.join(self.source, "docs", "design.md"), "# Design\n")
        self.cli(
            SITE, "add", "--site-id", "local", "--transport", "local",
            "--source-root", self.source, "--build-root", self.temp,
            "--run-root", self.temp, "--deps-root", self.temp,
            "--staging-root", self.temp, "--analysis-root", self.temp,
        )
        created = self.cli(
            STATE, "create", "--case-id", "shared-project",
            "--source-authority", "local:%s" % self.source,
            "--pgen-locator", "local:%s" % os.path.join(self.source, "pgen.hpp"),
            "--toml-locator", "local:%s" % os.path.join(self.source, "input.toml"),
            "--design-locator", "local:%s" % os.path.join(self.source, "docs", "design.md"),
            "--goal", "shared state", "--done-when", "binding works",
        )
        self.case_uid = created["case_uid"]

    def tearDown(self):
        shutil.rmtree(self.temp)

    def write(self, path, value):
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w") as handle:
            handle.write(value)

    def cli(self, script, *args, **kwargs):
        environment = os.environ.copy()
        environment.update(kwargs.get("environment", {}))
        command = [sys.executable, script, "--router-home", self.home] + list(args)
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, env=environment,
        )
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), "no JSON output; stderr=%s" % stderr)
        payload = json.loads(stdout)
        if kwargs.get("expect", 0) != process.returncode:
            self.fail("unexpected exit %s: %s\n%s" % (process.returncode, payload, stderr))
        return payload

    def actor_environment(self, run_id="agent-run-1"):
        return {
            "ENTITY_AGENT_RUN_ID": run_id,
            "ENTITY_AGENT_PROVIDER": "test-provider",
            "ENTITY_AGENT_CLIENT": "test-cli",
            "ENTITY_AGENT_SESSION_ID": "session-1",
            "ENTITY_AGENT_MODEL": "test-model",
            "ENTITY_SKILLS_BUNDLE_HASH": "sha256:" + "a" * 64,
        }

    def test_binding_is_shared_and_resolves_from_project_subdirectory(self):
        bound = self.cli(
            PROJECT, "bind", "--project-root", self.source, "--case", self.case_uid,
            environment=self.actor_environment(),
        )
        self.assertEqual(bound["case_uid"], self.case_uid)
        self.assertFalse(bound["case_state_mutated"])
        registry = os.path.join(self.home, "project-bindings.json")
        with open(registry, "r") as handle:
            record = json.load(handle)["projects"][os.path.realpath(self.source)]
        self.assertEqual(record["updated_by"]["run_id"], "agent-run-1")

        nested = os.path.join(self.source, "docs")
        resolved = self.cli(PROJECT, "resolve", "--project-root", nested)
        self.assertEqual(resolved["project_root"], os.path.realpath(self.source))
        self.assertEqual(resolved["case_uid"], self.case_uid)
        self.assertFalse(resolved["state_mutated"])
        self.assertFalse(os.path.exists(os.path.join(self.source, "_case")))
        self.assertFalse(os.path.exists(os.path.join(self.source, ".entity-router")))

    def test_entityctl_inspect_is_compact_and_does_not_mutate_case(self):
        self.cli(
            PROJECT, "bind", "--project-root", self.source, "--case", self.case_uid,
            environment=self.actor_environment(),
        )
        case_path = self.cli(STATE, "show", "--case", self.case_uid)["case_dir"]
        state_path = os.path.join(case_path, "case.json")
        before = (os.stat(state_path).st_mtime_ns, os.path.getsize(state_path))
        inspected = self.cli(
            ENTITYCTL, "inspect", "--project-root", os.path.join(self.source, "docs")
        )
        after = (os.stat(state_path).st_mtime_ns, os.path.getsize(state_path))
        self.assertEqual(before, after)
        self.assertFalse(inspected["state_mutated"])
        self.assertLessEqual(inspected["summary_bytes"], 4096)
        self.assertEqual(inspected["case"]["case_uid"], self.case_uid)

    def test_entityctl_exposes_deterministic_flow_as_default_public_transaction(self):
        inspected = self.cli(
            ENTITYCTL, "flow", "inspect", "--case", self.case_uid, expect=10,
        )
        self.assertEqual(inspected["status"], "needs_decision")
        self.assertEqual(inspected["case_uid"], self.case_uid)
        self.assertLessEqual(inspected["metrics"]["output_bytes"], 4096)

    def test_entityctl_exposes_writer_lease_lifecycle(self):
        actor = [
            "--actor-run-id", "public-writer", "--actor-provider", "codex",
            "--actor-client", "test",
        ]
        acquired = self.cli(
            ENTITYCTL, *(actor + [
                "writer", "acquire", "--case", self.case_uid,
                "--expected-revision", "0", "--lease-id", "public-lease",
                "--ttl-seconds", "300",
            ])
        )
        self.assertEqual(acquired["writer_lease"]["holder"]["run_id"], "public-writer")
        status = self.cli(ENTITYCTL, "writer", "status", "--case", self.case_uid)
        self.assertTrue(status["active"])
        released = self.cli(
            ENTITYCTL, *(actor + [
                "--writer-lease-id", "public-lease", "writer", "release",
                "--case", self.case_uid, "--expected-revision", "1",
            ])
        )
        self.assertIsNone(released["writer_lease"])

    def test_action_request_result_and_events_record_distinct_actors(self):
        start_env = self.actor_environment("agent-start")
        finish_env = self.actor_environment("agent-finish")
        started = self.cli(
            STATE, "start-action", "--case", self.case_uid,
            "--expected-revision", "0", "--action-id", "pgen-actor",
            "--action-type", "pgen.verify", "--owner", "entity-pgen",
            "--execution-domain", "entity-pgen", "--execution-site", "local",
            "--goal", "verify provenance", "--read-root", "local:%s" % self.source,
            "--write-root", "local:%s" % os.path.join(self.source, "docs"),
            "--expected-output", "local:%s" % os.path.join(self.source, "docs", "design.md"),
            environment=start_env,
        )
        finished = self.cli(
            STATE, "finish-action", "--case", self.case_uid,
            "--expected-revision", "1", "--action-id", "pgen-actor",
            "--status", "completed", "--output",
            "local:%s" % os.path.join(self.source, "docs", "design.md"),
            "--verification", "design inspected", "--readiness", "pgen=verified",
            environment=finish_env,
        )
        with open(started["request"], "r") as handle:
            request = json.load(handle)
        with open(finished["result"], "r") as handle:
            result = json.load(handle)
        self.assertEqual(request["actor"]["run_id"], "agent-start")
        self.assertEqual(result["actor"]["run_id"], "agent-finish")
        case_dir = os.path.dirname(os.path.dirname(os.path.dirname(started["request"])))
        with open(os.path.join(case_dir, "events.jsonl"), "r") as handle:
            events = [json.loads(line) for line in handle]
        self.assertEqual(events[-2]["actor"]["run_id"], "agent-start")
        self.assertEqual(events[-1]["actor"]["run_id"], "agent-finish")

    def test_require_actor_gate_rejects_unattributed_mutation(self):
        environment = {"ENTITY_ROUTER_REQUIRE_ACTOR": "1"}
        rejected = self.cli(
            PROJECT, "bind", "--project-root", self.source, "--case", self.case_uid,
            environment=environment, expect=2,
        )
        self.assertIn("requires ENTITY_AGENT_RUN_ID", rejected["error"])

    def test_bundle_install_projects_one_content_addressed_bundle(self):
        fake_home = os.path.join(self.temp, "agent-home")
        source_root = os.path.join(ROOT, "skills")
        environment = self.actor_environment("bundle-publisher")
        environment["HOME"] = fake_home
        environment["ENTITY_SKILLS_HOME"] = os.path.join(fake_home, ".entity-skills")
        installed = self.cli(
            ENTITYCTL, "bundle", "install", "--source-root", source_root,
            environment=environment,
        )
        self.assertTrue(installed["bundle_hash"].startswith("sha256:"))
        self.assertFalse(installed["project_state_mutated"])
        self.assertFalse(installed["case_state_mutated"])
        self.assertTrue(os.path.islink(installed["current"]))
        for provider_root in (
            os.path.join(fake_home, ".codex", "skills"),
            os.path.join(fake_home, ".claude", "skills"),
            os.path.join(fake_home, ".kimi-code", "skills"),
        ):
            for skill in ("entity-router", "entity-pgen", "entity-env-build", "entity-nt2py"):
                target = os.path.join(provider_root, skill)
                self.assertTrue(os.path.islink(target))
                self.assertEqual(
                    os.path.realpath(target),
                    os.path.join(installed["bundle_root"], skill),
                )


if __name__ == "__main__":
    unittest.main()
