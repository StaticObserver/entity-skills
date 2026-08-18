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

from entity_ledger_common import write_active_workspace
from entity_ledger_dashboard import build_dashboard
from entity_ledger_store import OperationStore, canonical_hash
from entity_ledger_workspace import init_workspace, write_site_yaml


class RecordAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-analysis-")
        self._env = mock.patch.dict(os.environ, {"HOME": self.temp})
        self._env.start()
        for key in ("ENTITY_LEDGER_HOME", "ENTITY_ROUTER_HOME",
                    "ENTITY_WORKSPACE"):
            os.environ.pop(key, None)
        self.workspace = init_workspace(os.path.join(self.temp, "ws"))["workspace"]
        write_active_workspace(self.workspace)
        self.home = os.path.join(self.workspace, ".ledger")
        self.store = OperationStore(self.home)
        self.site_root = os.path.join(self.temp, "compute")
        write_site_yaml(self.workspace, {
            "site_id": "local", "transport": {"kind": "local"},
            "scheduler": {"kind": "none"}, "site_root": self.site_root})
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "site_root": self.site_root, "roots": {}, "policy": {}})
        self.project_root = os.path.join(self.workspace, "projects", "demo")
        os.makedirs(self.project_root)
        self.store.upsert_project("project-1", "demo", self.project_root)
        self.store.upsert_case(
            "case-1", "alpha", self.project_root,
            {"authority": {"site_id": "local", "path": self.project_root}},
            {"source_id": "", "build_id": "", "run_id": "run-1",
             "active_run": None, "data_id": "data-1", "analysis_id": ""},
            project_uid="project-1")
        self.run_root = os.path.join(self.site_root, "projects", "demo",
                                     "runs", "alpha", "run-1")
        os.makedirs(self.run_root)
        self.store.add_identity(
            "case-1", "run", "run-1",
            {"id": "run-1", "kind": "run", "site_id": "local",
             "root": {"site_id": "local", "path": self.run_root},
             "status": "completed"}, True)
        self.store.add_identity(
            "case-1", "data", "data-1",
            {"id": "data-1", "kind": "data", "site_id": "local",
             "root": {"site_id": "local", "path": self.run_root},
             "parents": {"run_id": "run-1"}, "status": "inventoried"}, True)
        # the project script library
        self.scripts = os.path.join(self.project_root, "analysis", "scripts")
        os.makedirs(self.scripts)
        with open(os.path.join(self.scripts, "plot.py"), "w") as handle:
            handle.write("# generic plotting script\n")
        self.params = '{"bins": 32}'

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

    def analysis_id(self):
        from entity_ledger_common import sha256_file
        script_sha = sha256_file(os.path.join(self.scripts, "plot.py"))
        return "analysis-" + canonical_hash({
            "data_id": "data-1", "script_sha256": script_sha,
            "params": {"bins": 32},
        }).split(":", 1)[1][:16]

    def conventional_root(self):
        return os.path.join(self.site_root, "projects", "demo", "analysis",
                            "alpha", self.analysis_id())

    def write_manifest(self, output_root, data_id="data-1", **extra):
        os.makedirs(output_root, exist_ok=True)
        manifest = {"data_id": data_id, "script": "plot.py",
                    "generated_at": "2026-08-05T00:00:00Z"}
        manifest.update(extra)
        with open(os.path.join(output_root, "analysis-manifest.json"),
                  "w") as handle:
            json.dump(manifest, handle)

    def record(self, *extra):
        return self.cli("--actor-run-id", "analysis-test",
                        "record", "analysis",
                        "--project-root", self.project_root, *extra)

    def args_for(self, output_root):
        return ["--script", "plot.py", "--data", "data-1",
                "--params", self.params, "--output-root", output_root]

    def test_record_analysis_happy_path(self):
        output_root = self.conventional_root()
        self.write_manifest(output_root)
        code, payload = self.record(*self.args_for(output_root))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["analysis_id"], self.analysis_id())
        self.assertTrue(payload["at_conventional_root"])
        self.assertTrue(payload["parent_current"])
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["data_id"], "data-1")
        self.assertEqual(payload["run_id"], "run-1")
        case = self.store.get_case("case-1")
        self.assertEqual(case["current"]["analysis_id"], self.analysis_id())
        identity = case["identities"]["analysis"]["items"][0]
        self.assertEqual(identity["parents"], {"data_id": "data-1",
                                               "run_id": "run-1"})
        self.assertEqual(identity["params"], {"bins": 32})
        events = self.store.export()["events"]
        self.assertEqual(events[-1]["event_type"], "record.analysis")
        self.assertEqual(events[-1]["actor"]["run_id"], "analysis-test")
        # re-registering is idempotent, also with a differently formatted
        # but equivalent params JSON string
        args = self.args_for(output_root)
        args[args.index(self.params)] = '{"bins":32}'
        code, again = self.record(*args)
        self.assertEqual(code, 0, again)
        self.assertEqual(again["analysis_id"], payload["analysis_id"])
        self.assertEqual(len(self.store.get_case("case-1")
                             ["identities"]["analysis"]["items"]), 1)

    def test_non_current_parent_books_historical_entry(self):
        output_root = self.conventional_root()
        self.write_manifest(output_root)
        code, first = self.record(*self.args_for(output_root))
        self.assertEqual(code, 0, first)
        # data-2 becomes current; the first analysis goes stale
        self.store.add_identity(
            "case-1", "data", "data-2",
            {"id": "data-2", "kind": "data", "site_id": "local",
             "root": {"site_id": "local", "path": self.run_root},
             "parents": {"run_id": "run-1"}, "status": "inventoried"}, True)
        case = self.store.get_case("case-1")
        current = dict(case["current"])
        current["data_id"] = "data-2"
        self.store.upsert_case(
            "case-1", "alpha", self.project_root, case["source"], current,
            project_uid="project-1")
        # registering another analysis against the old data is allowed but
        # stays a historical entry: current is not rolled back to it
        old_root = os.path.join(self.temp, "historical-out")
        self.write_manifest(old_root, data_id="data-1")
        code, second = self.record(
            "--script", "plot.py", "--data", "data-1",
            "--params", '{"bins": 64}', "--output-root", old_root)
        self.assertEqual(code, 0, second)
        self.assertFalse(second["parent_current"])
        self.assertTrue(second["warnings"])
        self.assertIn("historical entry", second["warnings"][0])
        self.assertNotEqual(second["analysis_id"], first["analysis_id"])
        case = self.store.get_case("case-1")
        self.assertEqual(case["current"]["analysis_id"], first["analysis_id"])
        analyses = case["identities"]["analysis"]
        self.assertEqual(analyses["current_id"], first["analysis_id"])
        self.assertEqual(len(analyses["items"]), 2)

    def test_manifest_cross_checks_fail_with_zero_writes(self):
        script_sha = None
        from entity_ledger_common import sha256_file
        script_sha = sha256_file(os.path.join(self.scripts, "plot.py"))
        for extra in ({"script": "other.py"},
                      {"script_sha256": "0" * 64},
                      {"params": {"bins": 64}}):
            output_root = os.path.join(self.temp, "cross-out")
            if os.path.isdir(output_root):
                shutil.rmtree(output_root)
            self.write_manifest(output_root, **extra)
            code, payload = self.record(*self.args_for(output_root))
            self.assertEqual(code, 2, extra)
            case = self.store.get_case("case-1")
            self.assertNotIn("analysis", case["identities"])
            self.assertEqual(case["current"]["analysis_id"], "")
            self.assertEqual(self.store.export()["events"], [])

    def test_env_stack_is_presented(self):
        output_root = self.conventional_root()
        self.write_manifest(output_root)
        code, payload = self.record(
            *(self.args_for(output_root) + ["--env-stack", "py311-nt2py"]))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["env_stack"], "py311-nt2py")
        case = self.store.get_case("case-1")
        identity = case["identities"]["analysis"]["items"][0]
        self.assertEqual(identity["env_stack"], "py311-nt2py")
        dashboard = build_dashboard(self.store, self.project_root)
        self.assertIn("env py311-nt2py",
                      dashboard["board"]["analysis"]["detail"])
        code, show = self.cli("show", "--project-root", self.project_root)
        self.assertEqual(show["analyses"][0]["env_stack"], "py311-nt2py")

    def test_legacy_subdirectory_script_and_dot_prefix(self):
        legacy = os.path.join(self.scripts, "legacy")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "foo.py"), "w") as handle:
            handle.write("# hardcoded legacy script\n")
        output_root = os.path.join(self.temp, "legacy-out")
        self.write_manifest(output_root, script="legacy/foo.py")
        code, payload = self.record(
            "--script", "legacy/foo.py", "--data", "data-1",
            "--params", self.params, "--output-root", output_root,
            "--hardcoded-paths")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["script"], "legacy/foo.py")
        # ./plot.py normalizes to plot.py (same analysis_id as the plain form)
        self.write_manifest(output_root, script="plot.py")
        code, dotted = self.record(
            "--script", "./plot.py", "--data", "data-1",
            "--params", self.params, "--output-root", output_root)
        self.assertEqual(code, 0, dotted)
        self.assertEqual(dotted["script"], "plot.py")
        self.assertEqual(dotted["analysis_id"], self.analysis_id())

    def test_zero_write_gates(self):
        output_root = os.path.join(self.temp, "out")
        # manifest missing
        os.makedirs(output_root)
        code, payload = self.record(*self.args_for(output_root))
        self.assertEqual(code, 2)
        self.assertIn("analysis manifest", payload["error"])
        # manifest names another data identity
        self.write_manifest(output_root, data_id="data-9")
        code, payload = self.record(*self.args_for(output_root))
        self.assertEqual(code, 2)
        self.assertIn("data-9", payload["error"])
        # script missing from the library
        self.write_manifest(output_root)
        code, payload = self.record(
            "--script", "nope.py", "--data", "data-1",
            "--params", self.params, "--output-root", output_root)
        self.assertEqual(code, 2)
        self.assertIn("script library", payload["error"])
        # script must stay inside the library
        code, payload = self.record(
            "--script", "../outside.py", "--data", "data-1",
            "--params", self.params, "--output-root", output_root)
        self.assertEqual(code, 2)
        # params must be a JSON object
        code, payload = self.record(
            "--script", "plot.py", "--data", "data-1",
            "--params", "[1,2]", "--output-root", output_root)
        self.assertEqual(code, 2)
        # nothing was booked through any of the failures
        case = self.store.get_case("case-1")
        self.assertNotIn("analysis", case["identities"])
        self.assertEqual(case["current"]["analysis_id"], "")
        self.assertEqual(self.store.export()["events"], [])

    def test_data_accepts_run_id_and_requires_recorded_data(self):
        self.store.add_identity(
            "case-1", "run", "run-2",
            {"id": "run-2", "kind": "run", "site_id": "local",
             "root": {"site_id": "local",
                      "path": os.path.join(self.temp, "run-2")},
             "status": "completed"}, False)
        output_root = self.conventional_root()
        self.write_manifest(output_root)
        code, payload = self.record("--script", "plot.py", "--data", "run-1",
                                    "--params", self.params,
                                    "--output-root", output_root)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["data_id"], "data-1")
        self.assertEqual(payload["run_id"], "run-1")
        code, payload = self.record("--script", "plot.py", "--data", "run-2",
                                    "--params", self.params,
                                    "--output-root", output_root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        self.assertIn("record data", payload["decisions"][0]["question"])

    def test_stale_when_parent_data_leaves_current(self):
        # Note: this test pokes current data directly via
        # add_identity/upsert_case, deliberately bypassing record data —
        # staleness is a read-time derivation unit test (stale is derived
        # by the dashboard at read time from parents.data_id vs
        # current.data_id, not a stored field).
        output_root = self.conventional_root()
        self.write_manifest(output_root)
        code, payload = self.record(*self.args_for(output_root))
        self.assertEqual(code, 0, payload)
        dashboard = build_dashboard(self.store, self.project_root)
        self.assertEqual(dashboard["board"]["analysis"]["state"],
                         "established")
        self.assertIn("plot.py", dashboard["board"]["analysis"]["detail"])
        # a new data identity becomes current -> the analysis goes stale
        self.store.add_identity(
            "case-1", "data", "data-2",
            {"id": "data-2", "kind": "data", "site_id": "local",
             "root": {"site_id": "local", "path": self.run_root},
             "parents": {"run_id": "run-1"}, "status": "inventoried"}, True)
        case = self.store.get_case("case-1")
        current = dict(case["current"])
        current["data_id"] = "data-2"
        self.store.upsert_case(
            "case-1", "alpha", self.project_root, case["source"], current,
            project_uid="project-1")
        dashboard = build_dashboard(self.store, self.project_root)
        cell = dashboard["board"]["analysis"]
        self.assertEqual(cell["state"], "stale")
        self.assertIn("parent data is no longer current", cell["detail"])
        code, show = self.cli("show", "--project-root", self.project_root)
        self.assertEqual(code, 0, show)
        self.assertEqual(len(show["analyses"]), 1)
        entry = show["analyses"][0]
        self.assertEqual(entry["analysis_id"], self.analysis_id())
        self.assertEqual(entry["script"], "plot.py")
        self.assertEqual(entry["params"], {"bins": 32})
        self.assertEqual(entry["data_id"], "data-1")
        self.assertTrue(entry["stale"])
        # recovery case: re-registering against the new current data
        # returns to established
        new_root = os.path.join(self.temp, "out-data-2")
        self.write_manifest(new_root, data_id="data-2")
        code, refreshed = self.record("--script", "plot.py", "--data", "data-2",
                                      "--params", self.params,
                                      "--output-root", new_root)
        self.assertEqual(code, 0, refreshed)
        self.assertTrue(refreshed["parent_current"])
        dashboard = build_dashboard(self.store, self.project_root)
        self.assertEqual(dashboard["board"]["analysis"]["state"],
                         "established")

    def test_hardcoded_paths_flag_shows_on_dashboard(self):
        output_root = self.conventional_root()
        self.write_manifest(output_root)
        code, payload = self.record(
            *(self.args_for(output_root) + ["--hardcoded-paths"]))
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["hardcoded_paths"])
        dashboard = build_dashboard(self.store, self.project_root)
        self.assertIn("hardcoded", dashboard["board"]["analysis"]["detail"])

    def test_analysis_cell_none_without_recording(self):
        dashboard = build_dashboard(self.store, self.project_root)
        self.assertEqual(dashboard["board"]["analysis"]["state"], "none")


if __name__ == "__main__":
    unittest.main()
