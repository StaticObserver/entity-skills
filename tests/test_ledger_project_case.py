#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from unittest import mock


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-ledger", "scripts")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_ledger_common import absolute, write_active_workspace
from entity_ledger_store import OperationStore
from entity_ledger_workspace import init_workspace, load_project_yaml


class ProjectCaseTestBase(unittest.TestCase):
    """Isolate HOME and the controller-location variables; each test gets a
    fresh workspace (adopted via the pointer) with a local site registered."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-project-")
        self._env = mock.patch.dict(os.environ, {"HOME": self.temp})
        self._env.start()
        for key in ("ENTITY_LEDGER_HOME", "ENTITY_ROUTER_HOME",
                    "ENTITY_WORKSPACE"):
            os.environ.pop(key, None)
        self.workspace = init_workspace(os.path.join(self.temp, "ws"))["workspace"]
        write_active_workspace(self.workspace)
        self.home = os.path.join(self.workspace, ".ledger")
        self.store = OperationStore(self.home)
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "roots": {"source_root": self.temp,
                      "build_root": os.path.join(self.temp, "build"),
                      "run_root": os.path.join(self.temp, "runs"),
                      "staging_root": os.path.join(self.temp, "staging")},
        })

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.temp)

    def cli(self, *args):
        env = dict((key, value) for key, value in os.environ.items()
                   if not key.startswith("ENTITY_"))
        env["HOME"] = self.temp
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, env=env)
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), stderr)
        return process.returncode, json.loads(stdout)

    def project_dir(self, slug="demo"):
        return os.path.join(self.workspace, "projects", slug)

    def init_project(self, slug="demo"):
        code, payload = self.cli("project", "init", slug)
        self.assertEqual(code, 0, payload)
        return payload

    def init_case(self, project="demo", slug="alpha"):
        code, payload = self.cli("case", "init", project, slug)
        self.assertEqual(code, 0, payload)
        return payload


class ProjectInitTest(ProjectCaseTestBase):
    def test_project_init_creates_yaml_and_registers(self):
        payload = self.init_project()
        self.assertTrue(payload["created"])
        self.assertTrue(payload["state_mutated"])
        project = payload["project"]
        self.assertEqual(project["slug"], "demo")
        self.assertEqual(project["project_root"],
                         os.path.realpath(self.project_dir()))
        self.assertEqual(project["source"], "source")
        record = load_project_yaml(self.project_dir())
        self.assertEqual(record["project_uid"], project["project_uid"])
        self.assertEqual(record["schema_version"], 1)
        self.assertTrue(os.path.isdir(os.path.join(self.project_dir(), "cases")))
        # the Project entity is booked in the store
        stored = self.store.get_project(project["project_uid"])
        self.assertEqual(stored["slug"], "demo")
        self.assertEqual(stored["project_root"],
                         os.path.realpath(self.project_dir()))
        # re-running keeps the identity and reports no mutation
        code, again = self.cli("project", "init", "demo")
        self.assertEqual(code, 0, again)
        self.assertFalse(again["created"])
        self.assertFalse(again["state_mutated"])
        self.assertEqual(again["project"]["project_uid"],
                         project["project_uid"])

    def test_project_init_registers_custom_source(self):
        code, payload = self.cli("project", "init", "demo",
                                 "--source", "entity-src")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["project"]["source"], "entity-src")
        record = load_project_yaml(self.project_dir())
        self.assertEqual(record["source"], "entity-src")
        # the source directory is only registered, never created
        self.assertFalse(os.path.exists(
            os.path.join(self.project_dir(), "entity-src")))

    def test_project_init_requires_workspace(self):
        legacy_home = os.path.join(self.temp, "legacy-controller")
        process_env = dict((key, value) for key, value in os.environ.items()
                           if not key.startswith("ENTITY_"))
        process_env["HOME"] = self.temp
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--ledger-home", legacy_home,
             "project", "init", "demo"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, env=process_env)
        stdout, unused = process.communicate()
        self.assertEqual(process.returncode, 2)
        self.assertIn("workspace", json.loads(stdout)["error"])

    def test_project_init_refuses_occupied_directory(self):
        os.makedirs(self.project_dir())
        with open(os.path.join(self.project_dir(), "notes.md"), "w") as handle:
            handle.write("occupied")
        code, payload = self.cli("project", "init", "demo")
        self.assertEqual(code, 2)
        self.assertIn("not a project", payload["error"])

    def test_project_init_rejects_invalid_slug(self):
        code, payload = self.cli("project", "init", "bad/name")
        self.assertEqual(code, 2)
        self.assertIn("invalid project slug", payload["error"])


class CaseInitTest(ProjectCaseTestBase):
    def setUp(self):
        super(CaseInitTest, self).setUp()
        self.project = self.init_project()["project"]

    def test_case_init_skeleton_and_booking(self):
        payload = self.init_case()
        self.assertTrue(payload["created"])
        self.assertEqual(payload["project_uid"], self.project["project_uid"])
        case_dir = os.path.join(self.project_dir(), "cases", "alpha")
        self.assertEqual(payload["case_dir"], os.path.realpath(case_dir))
        with open(os.path.join(case_dir, "intent.md"), "r") as handle:
            self.assertIn("alpha", handle.read())
        with open(os.path.join(case_dir, "decisions.json"), "r") as handle:
            decisions = json.load(handle)
        self.assertEqual(decisions["kind"], "entity-pgen.decision-card")
        # the Case is booked under the Project with its source authority
        case = self.store.get_case(payload["case_uid"])
        self.assertEqual(case["case_id"], "alpha")
        self.assertEqual(case["project_uid"], self.project["project_uid"])
        self.assertEqual(case["project_root"],
                         os.path.realpath(self.project_dir()))
        authority = case["source"]["authority"]
        self.assertEqual(authority["site_id"], "local")
        self.assertEqual(authority["path"],
                         os.path.join(os.path.realpath(self.project_dir()),
                                      "source"))
        # the uid is content-addressed: a re-run is an idempotent no-op
        marker = os.path.join(case_dir, "intent.md")
        with open(marker, "w") as handle:
            handle.write("hand-written content")
        code, again = self.cli("case", "init", "demo", "alpha")
        self.assertEqual(code, 0, again)
        self.assertEqual(again["case_uid"], payload["case_uid"])
        self.assertFalse(again["created"])
        with open(marker, "r") as handle:
            self.assertEqual(handle.read(), "hand-written content")

    def test_case_init_unknown_project(self):
        code, payload = self.cli("case", "init", "ghost", "alpha")
        self.assertEqual(code, 2)
        self.assertIn("unknown project", payload["error"])

    def test_case_init_without_local_site_gets_actionable_hint(self):
        # a workspace with no local source Site: the error must point at the
        # fix (register a local site archive with a narrow source_root)
        bare = init_workspace(os.path.join(self.temp, "ws-bare"))["workspace"]
        write_active_workspace(bare)
        code, unused = self.cli("project", "init", "demo")
        self.assertEqual(code, 0)
        code, payload = self.cli("case", "init", "demo", "alpha")
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        question = payload["decisions"][0]["question"]
        self.assertIn("source_root", question)
        self.assertIn("site sync", question)
        self.assertIn("workspace root", question)


class CaseAddressingTest(ProjectCaseTestBase):
    def setUp(self):
        super(CaseAddressingTest, self).setUp()
        self.project = self.init_project()["project"]
        self.alpha = self.init_case(slug="alpha")
        self.beta = self.init_case(slug="beta")

    def test_multiple_cases_require_the_case_flag(self):
        code, payload = self.cli("status", "--project-root", self.project_dir(),
                                 "--json")
        self.assertEqual(code, 2)
        self.assertIn("multiple cases", payload["error"])
        self.assertIn("alpha", payload["error"])
        self.assertIn("beta", payload["error"])

    def test_case_flag_selects_within_project(self):
        code, payload = self.cli("status", "--project-root", self.project_dir(),
                                 "--case", "alpha", "--json")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["case_uid"], self.alpha["case_uid"])
        self.assertEqual(payload["case_id"], "alpha")
        self.assertEqual(payload["project_uid"], self.project["project_uid"])
        code, payload = self.cli("show", "--project-root", self.project_dir(),
                                 "--case", "beta")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["case_uid"], self.beta["case_uid"])
        self.assertEqual(payload["project"]["slug"], "demo")

    def test_unknown_case_lists_available(self):
        code, payload = self.cli("status", "--project-root", self.project_dir(),
                                 "--case", "gamma", "--json")
        self.assertEqual(code, 2)
        self.assertIn("gamma", payload["error"])
        self.assertIn("alpha, beta", payload["error"])

    def test_single_case_project_resolves_implicitly(self):
        self.init_project("solo")
        solo = self.init_case("solo", "only")
        code, payload = self.cli("status", "--project-root",
                                 self.project_dir("solo"), "--json")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["case_uid"], solo["case_uid"])

    def test_record_without_case_flag_is_a_decision(self):
        code, payload = self.cli(
            "record", "intent", "--project-root", self.project_dir(),
            "--text", "x")
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        self.assertTrue(payload["decisions"])

    def test_record_intent_syncs_intent_md_and_detects_drift(self):
        code, payload = self.cli(
            "record", "intent", "--project-root", self.project_dir(),
            "--case", "alpha", "--text", "verify the alpha heating rate")
        self.assertEqual(code, 0, payload)
        intent_md = os.path.join(self.project_dir(), "cases", "alpha",
                                 "intent.md")
        self.assertEqual(payload["intent_file"], os.path.realpath(intent_md))
        with open(intent_md, "r") as handle:
            self.assertEqual(handle.read().strip(), "verify the alpha heating rate")
        # db is the authority: a hand edit is flagged on the dashboard
        with open(intent_md, "w") as handle:
            handle.write("hand-edited intent\n")
        from entity_ledger_dashboard import build_dashboard
        store = OperationStore(self.home, create=False)
        dashboard = build_dashboard(store, self.project_dir(),
                                    case_slug="alpha")
        self.assertTrue(any("diverged" in item for item in dashboard["pending"]))
        self.assertIn("verify the alpha heating rate", dashboard["intent"])
        self.assertEqual(dashboard["project"]["slug"], "demo")
        # the beta case carries no drift
        dashboard = build_dashboard(store, self.project_dir(), case_slug="beta")
        self.assertEqual(dashboard["pending"], [])

    def test_case_init_rerun_preserves_booked_state(self):
        code, unused = self.cli(
            "record", "intent", "--project-root", self.project_dir(),
            "--case", "alpha", "--text", "keep this intent")
        self.assertEqual(code, 0)
        before = self.store.get_case(self.alpha["case_uid"])
        events_before = len(self.store.export()["events"])
        code, payload = self.cli("case", "init", "demo", "alpha")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["already_exists"])
        self.assertFalse(payload["created"])
        self.assertFalse(payload["state_mutated"])
        after = self.store.get_case(self.alpha["case_uid"])
        self.assertEqual(after["current"], before["current"])
        self.assertEqual(after["legacy"], before["legacy"])
        self.assertEqual(after["created_at"], before["created_at"])
        self.assertEqual(len(self.store.export()["events"]), events_before)

    def test_upsert_case_preserves_project_binding(self):
        # a context-less upsert (no project_root/project_uid) must keep the
        # existing project binding instead of silently unbinding the Case
        self.store.upsert_case(
            self.alpha["case_uid"], "alpha", None,
            {"authority": {"site_id": "local", "path": self.project_dir()}},
            {"source_id": "", "build_id": "", "run_id": "",
             "active_run": None, "data_id": "", "analysis_id": ""})
        case = self.store.get_case(self.alpha["case_uid"])
        self.assertEqual(case["project_uid"], self.project["project_uid"])

    def test_render_run_ambiguity_is_a_decision(self):
        build_root = os.path.join(self.temp, "build")
        os.makedirs(build_root)
        executable = os.path.join(build_root, "entity.xc")
        with open(executable, "w") as handle:
            handle.write("binary\n")
        os.chmod(executable, 0o755)
        with open(os.path.join(self.project_dir(), "input.toml"), "w") as handle:
            handle.write("[simulation]\nsteps = 2\n")
        code, payload = self.cli(
            "render-run", "--project-root", self.project_dir(),
            "--toml", "input.toml", "--site", "local",
            "--executable", executable)
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        self.assertTrue(payload["decisions"])
        self.assertIn("alpha", payload["error"])


class RequireCaseMessageTest(ProjectCaseTestBase):
    """B3: an unregistered --project-root must say so (never "no Case"), and
    a basename match over the registered projects lists the moved project."""

    def test_unregistered_path_is_not_a_case_problem(self):
        stray = os.path.join(self.temp, "stray")
        os.makedirs(stray)
        code, payload = self.cli(
            "record", "intent", "--project-root", stray, "--text", "x")
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        # I2: a deterministic error is never worth retrying unchanged
        self.assertFalse(payload["retryable"])
        self.assertIn("no project is registered", payload["error"])
        self.assertIn("workspace import", payload["error"])
        self.assertNotIn("run-prepare", payload["error"])
        self.assertNotIn("registered projects with the same name",
                         payload["error"])

    def test_moved_project_path_lists_registered_candidate(self):
        self.init_project("polar_cap")
        old_layout = os.path.join(self.temp, "old-layout", "polar_cap")
        os.makedirs(old_layout)
        code, payload = self.cli(
            "record", "intent", "--project-root", old_layout, "--text", "x")
        self.assertEqual(code, 2)
        self.assertIn("no project is registered", payload["error"])
        self.assertIn("registered projects with the same name", payload["error"])
        self.assertIn("polar_cap", payload["error"])
        self.assertIn(os.path.realpath(self.project_dir("polar_cap")),
                      payload["error"])


if __name__ == "__main__":
    unittest.main()
