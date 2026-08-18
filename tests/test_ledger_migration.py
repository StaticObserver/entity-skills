#!/usr/bin/env python3

import json
import os
import shutil
import sqlite3
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

from entity_ledger_common import sha256_file, write_active_workspace
from entity_ledger_store import (
    OperationStore,
    SCHEMA_V2,
    STORE_SCHEMA_VERSION,
)
from entity_ledger_workspace import (
    init_workspace,
    list_site_archives,
    load_project_yaml,
    site_yaml_path,
)


class MigrationTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-migration-")
        self._env = mock.patch.dict(os.environ, {"HOME": self.temp})
        self._env.start()
        for key in ("ENTITY_LEDGER_HOME", "ENTITY_ROUTER_HOME",
                    "ENTITY_WORKSPACE"):
            os.environ.pop(key, None)

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


class WorkspaceImportTest(MigrationTestBase):
    def setUp(self):
        super(WorkspaceImportTest, self).setUp()
        # old layout fixtures: projects, a v2 controller, site-notes
        self.old_projects = os.path.join(self.temp, "old-documents")
        demo = os.path.join(self.old_projects, "demo")
        os.makedirs(os.path.join(demo, "source"))
        with open(os.path.join(demo, "source", "input.toml"), "w") as handle:
            handle.write("[simulation]\nsteps = 2\n")
        with open(os.path.join(demo, "notes.md"), "w") as handle:
            handle.write("old project notes\n")
        self.old_home = os.path.join(self.temp, "old-controller")
        os.makedirs(os.path.join(self.old_home, "snapshots"))
        self._build_v2_store(demo)
        with open(os.path.join(self.old_home, "snapshots", "snap-1.tar"),
                  "w") as handle:
            handle.write("snapshot-bytes\n")
        self.notes = os.path.join(self.temp, "site-notes")
        os.makedirs(self.notes)
        with open(os.path.join(self.notes, "m87.md"), "w") as handle:
            handle.write("# m87 prose\n")
        self.workspace = init_workspace(os.path.join(self.temp, "ws"))["workspace"]
        write_active_workspace(self.workspace)
        self.ledger = os.path.join(self.workspace, ".ledger")

    def tearDown(self):
        super(WorkspaceImportTest, self).tearDown()

    def _build_v2_store(self, project_root):
        database = os.path.join(self.old_home, "ledger.db")
        connection = sqlite3.connect(database)
        try:
            connection.executescript(SCHEMA_V2)
            connection.execute(
                "INSERT INTO meta(key,value) VALUES('schema_version','2')")
            connection.execute(
                "INSERT INTO sites(site_id,profile_json,updated_at) VALUES(?,?,?)",
                ("local", json.dumps({"site_id": "local"}), "2026-08-01T00:00:00Z"))
            connection.execute(
                """INSERT INTO cases(case_uid,case_id,project_root,source_json,
                       current_json,legacy_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                ("case-1", "demo", project_root, "{}", "{}", "{}",
                 "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"))
            connection.execute(
                "INSERT INTO projects(project_root,case_uid,updated_at) "
                "VALUES(?,?,?)",
                (project_root, "case-1", "2026-08-02T00:00:00Z"))
            connection.commit()
        finally:
            connection.close()

    def import_args(self):
        return ["workspace", "import", self.workspace,
                "--projects-dir", self.old_projects,
                "--from-ledger-home", self.old_home,
                "--site-notes", self.notes]

    def test_dry_run_plans_without_touching(self):
        db_before = sha256_file(os.path.join(self.ledger, "ledger.db"))
        code, payload = self.cli(*self.import_args())
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["apply"])
        self.assertFalse(payload["state_mutated"])
        by_kind = {}
        for step in payload["steps"]:
            by_kind.setdefault(step["kind"], []).append(step)
        self.assertEqual(by_kind["project"][0]["action"], "copy")
        self.assertEqual(by_kind["project"][0]["slug"], "demo")
        # the initialized empty .ledger/ledger.db is replaceable
        self.assertEqual(by_kind["ledger.db"][0]["action"], "replace")
        self.assertEqual(by_kind["snapshot"][0]["action"], "copy")
        self.assertEqual(by_kind["site-notes"][0]["action"], "convert")
        self.assertEqual(payload["conflicts"], [])
        # nothing was written
        self.assertFalse(os.path.exists(
            os.path.join(self.workspace, "projects", "demo")))
        self.assertFalse(os.path.exists(
            site_yaml_path(self.workspace, "m87")))
        self.assertEqual(db_before,
                         sha256_file(os.path.join(self.ledger, "ledger.db")))

    def test_apply_consolidates_and_migrates(self):
        code, payload = self.cli(*(self.import_args() + ["--apply"]))
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["state_mutated"])
        # project directory copied verbatim and bound to the migrated entity
        copied = os.path.join(self.workspace, "projects", "demo")
        with open(os.path.join(copied, "source", "input.toml"), "r") as handle:
            self.assertIn("steps = 2", handle.read())
        store = OperationStore(self.ledger, create=False)
        exported = store.export()
        self.assertEqual(exported["schema_version"], STORE_SCHEMA_VERSION)
        self.assertEqual(len(exported["projects"]), 1)
        project = exported["projects"][0]
        self.assertEqual(project["slug"], "demo")
        case = exported["cases"][0]
        self.assertEqual(case["project_uid"], project["project_uid"])
        record = load_project_yaml(copied)
        self.assertEqual(record["project_uid"], project["project_uid"])
        # the binding is re-pointed at the workspace copy, not the old path
        self.assertEqual(project["project_root"], os.path.realpath(copied))
        self.assertEqual(case["project_root"], os.path.realpath(copied))
        # ...so the old Case resolves under the new workspace (no new Case)
        resolved = store.resolve_project(copied)
        self.assertEqual(resolved["case_uid"], "case-1")
        self.assertEqual(len(exported["cases"]), 1)
        # the old db file itself was migrated in place inside .ledger
        self.assertTrue(payload["store_migrations"])
        backup = os.path.join(self.ledger, "ledger.db.pre-import")
        self.assertTrue(os.path.isfile(backup))
        # snapshots and site-notes came along
        self.assertTrue(os.path.isfile(
            os.path.join(self.ledger, "snapshots", "snap-1.tar")))
        archives = list_site_archives(self.workspace)
        self.assertEqual(archives["m87"]["notes"], "# m87 prose")
        # a second apply is all skips and mutates nothing
        code, again = self.cli(*(self.import_args() + ["--apply"]))
        self.assertEqual(code, 0, again)
        self.assertFalse(again["state_mutated"], again["applied"])
        actions = set(step["action"] for step in again["steps"])
        self.assertNotIn("copy", actions)
        self.assertNotIn("replace", actions)

    def test_import_after_project_init_does_not_replace_store(self):
        # a project entity in the workspace store means it is NOT empty:
        # the foreign ledger.db must conflict, never replace
        code, unused = self.cli("project", "init", "demo")
        self.assertEqual(code, 0)
        code, payload = self.cli(*(self.import_args() + ["--apply"]))
        self.assertEqual(code, 0, payload)
        ledger_steps = [step for step in payload["steps"]
                        if step["kind"] == "ledger.db"]
        self.assertEqual(ledger_steps[0]["action"], "skip-conflict")
        store = OperationStore(self.ledger, create=False)
        self.assertEqual(
            [project["slug"] for project in store.find_projects()], ["demo"])
        self.assertEqual(
            [site["site_id"] for site in store.export()["sites"]], [])

    def test_conflicting_project_dir_is_skipped_never_overwritten(self):
        target = os.path.join(self.workspace, "projects", "demo")
        os.makedirs(target)
        marker = os.path.join(target, "mine.txt")
        with open(marker, "w") as handle:
            handle.write("existing local content\n")
        code, payload = self.cli(*(self.import_args() + ["--apply"]))
        self.assertEqual(code, 0, payload)
        conflicts = payload["conflicts"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["kind"], "project")
        with open(marker, "r") as handle:
            self.assertEqual(handle.read(), "existing local content\n")
        # the conflicting directory is not registered into project.yaml
        self.assertFalse(os.path.exists(os.path.join(target, "project.yaml")))
        # the remaining steps still executed
        self.assertTrue(os.path.isfile(
            site_yaml_path(self.workspace, "m87")))

    def test_non_empty_foreign_ledger_db_conflicts(self):
        # a workspace .ledger that already holds real data must not be
        # overwritten by the import
        store = OperationStore(self.ledger)
        store.upsert_site({"site_id": "keep", "transport": {"kind": "local"},
                           "scheduler": {"kind": "none"}, "roots": {}})
        code, payload = self.cli(*(self.import_args() + ["--apply"]))
        self.assertEqual(code, 0, payload)
        ledger_steps = [step for step in payload["steps"]
                        if step["kind"] == "ledger.db"]
        self.assertEqual(ledger_steps[0]["action"], "skip-conflict")
        # the foreign db was not imported; the existing data survives
        self.assertEqual(self.store_site_ids(self.ledger), ["keep"])
        # project registration into the existing store still works
        projects = OperationStore(self.ledger, create=False).find_projects()
        self.assertIn("demo", [project["slug"] for project in projects])

    def store_site_ids(self, home):
        return [site["site_id"]
                for site in OperationStore(home, create=False).export()["sites"]]

    def test_import_chains_v1_store_to_current(self):
        from test_ledger_migrate import V1_SCHEMA
        os.unlink(os.path.join(self.old_home, "ledger.db"))
        database = os.path.join(self.old_home, "ledger.db")
        demo = os.path.join(self.old_projects, "demo")
        connection = sqlite3.connect(database)
        try:
            connection.executescript(V1_SCHEMA)
            connection.execute(
                "INSERT INTO meta(key,value) VALUES('schema_version','1')")
            connection.execute(
                """INSERT INTO cases(case_uid,case_id,project_root,source_json,
                       current_json,legacy_json,active_operation_id,created_at,
                       updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                ("case-1", "demo", demo, "{}", "{}", "{}", None,
                 "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z"))
            connection.execute(
                "INSERT INTO projects(project_root,case_uid,updated_at) "
                "VALUES(?,?,?)", (demo, "case-1", "2026-07-21T00:00:00Z"))
            connection.commit()
        finally:
            connection.close()
        code, payload = self.cli(*(self.import_args() + ["--apply"]))
        self.assertEqual(code, 0, payload)
        # the copied store went through the whole v1 -> v2 -> v3 chain
        self.assertEqual(len(payload["store_migrations"]), 2)
        store = OperationStore(self.ledger, create=False)
        exported = store.export()
        self.assertEqual(exported["schema_version"], STORE_SCHEMA_VERSION)
        self.assertEqual(len(exported["cases"]), 1)
        resolved = store.resolve_project(
            os.path.join(self.workspace, "projects", "demo"))
        self.assertEqual(resolved["case_uid"], "case-1")


class PlanMigrationTest(MigrationTestBase):
    def setUp(self):
        super(PlanMigrationTest, self).setUp()
        self.home = os.path.join(self.temp, "controller")
        self.store = OperationStore(self.home)
        self.site_root = os.path.join(self.temp, "compute")
        self.build_root = os.path.join(self.temp, "old-build")
        self.run_root = os.path.join(self.temp, "old-runs")
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "site_root": self.site_root,
            "roots": {"build_root": self.build_root,
                      "run_root": self.run_root,
                      "staging_root": os.path.join(self.temp, "old-staging")},
            "policy": {}})
        self.project_root = os.path.join(self.temp, "project")
        os.makedirs(self.project_root)
        self.store.upsert_project("project-1", "demo", self.project_root)
        self.store.upsert_case(
            "case-1", "alpha", self.project_root,
            {"authority": {"site_id": "local", "path": self.project_root}},
            {"source_id": "", "build_id": "", "run_id": "",
             "active_run": None, "data_id": "", "analysis_id": ""},
            project_uid="project-1")
        self.old_build = os.path.join(self.build_root, "case-1", "build-1")
        self.old_run = os.path.join(self.run_root, "case-1", "run-1")
        self.inflight_run = os.path.join(self.run_root, "case-1", "run-2")
        for path in (self.old_build, self.old_run, self.inflight_run,
                     os.path.join(self.run_root, "case-1", "run-9")):
            os.makedirs(path)
        self.store.add_identity(
            "case-1", "build", "build-1",
            {"id": "build-1", "kind": "build", "site_id": "local",
             "root": {"site_id": "local", "path": self.old_build},
             "status": "verified"}, True)
        self.store.add_identity(
            "case-1", "run", "run-1",
            {"id": "run-1", "kind": "run", "site_id": "local",
             "root": {"site_id": "local", "path": self.old_run},
             "status": "completed"}, True)
        self.store.add_identity(
            "case-1", "run", "run-2",
            {"id": "run-2", "kind": "run", "site_id": "local",
             "root": {"site_id": "local", "path": self.inflight_run},
             "status": "submitted"}, False)
        self.store.add_identity(
            "case-1", "data", "data-1",
            {"id": "data-1", "kind": "data", "site_id": "local",
             "root": {"site_id": "local", "path": self.old_run},
             "parents": {"run_id": "run-1"},
             "status": "inventoried"}, True)

    def test_plan_maps_old_tree_to_new_tree(self):
        code, payload = self.cli("--ledger-home", self.home,
                                 "site", "plan-migration", "local")
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["state_mutated"])
        self.assertEqual(payload["site_root"],
                         os.path.normpath(self.site_root))
        by_id = dict((item["identity_id"], item)
                     for item in payload["items"])
        build = by_id["build-1"]
        self.assertEqual(build["action"], "move")
        self.assertTrue(build["exists_on_site"])
        self.assertEqual(build["new"]["path"], os.path.join(
            os.path.normpath(self.site_root),
            "projects", "demo", "builds", "alpha", "build-1"))
        run = by_id["run-1"]
        self.assertEqual(run["action"], "move")
        self.assertEqual(run["new"]["path"], os.path.join(
            os.path.normpath(self.site_root),
            "projects", "demo", "runs", "alpha", "run-1"))
        # the data identity moves with its parent run (data root == run root)
        data = by_id["data-1"]
        self.assertEqual(data["dimension"], "data")
        self.assertEqual(data["action"], "move")
        self.assertEqual(data["new"]["path"], run["new"]["path"])
        inflight = by_id["run-2"]
        self.assertEqual(inflight["action"], "skip")
        self.assertIn("in-flight", inflight["reason"])
        self.assertEqual(payload["moves"], 3)
        self.assertEqual(payload["skips"], 1)
        self.assertEqual(payload["untracked"],
                         [os.path.join(self.run_root, "case-1", "run-9")])


class RelocateTest(MigrationTestBase):
    def setUp(self):
        super(RelocateTest, self).setUp()
        self.home = os.path.join(self.temp, "controller")
        self.store = OperationStore(self.home)
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "roots": {}, "policy": {}})
        self.project_root = os.path.join(self.temp, "project")
        os.makedirs(self.project_root)
        self.store.upsert_project("project-1", "demo", self.project_root)
        self.old_run = os.path.join(self.temp, "old-runs", "case-1", "run-1")
        os.makedirs(self.old_run)
        with open(os.path.join(self.old_run, "run-manifest.json"), "w") as handle:
            json.dump({"run_id": "run-1", "case_uid": "case-1"}, handle)
        self.store.upsert_case(
            "case-1", "alpha", self.project_root,
            {"authority": {"site_id": "local", "path": self.project_root}},
            {"source_id": "", "build_id": "", "run_id": "run-1",
             "active_run": {"site_id": "local", "path": self.old_run},
             "data_id": "", "analysis_id": ""},
            project_uid="project-1")
        self.store.add_identity(
            "case-1", "run", "run-1",
            {"id": "run-1", "kind": "run", "site_id": "local",
             "root": {"site_id": "local", "path": self.old_run},
             "scheduler": {"run_root": self.old_run,
                           "log": os.path.join(self.old_run, "run.log")},
             "status": "completed"}, True)
        self.store.add_identity(
            "case-1", "run", "run-2",
            {"id": "run-2", "kind": "run", "site_id": "local",
             "root": {"site_id": "local", "path": self.old_run},
             "status": "submitted"}, False)
        # a build identity with a real executable fingerprint
        self.old_build = os.path.join(self.temp, "old-build", "case-1", "build-1")
        os.makedirs(self.old_build)
        self.executable = os.path.join(self.old_build, "entity.xc")
        with open(self.executable, "w") as handle:
            handle.write("binary-payload\n")
        os.chmod(self.executable, 0o755)
        self.store.add_identity(
            "case-1", "build", "build-1",
            {"id": "build-1", "kind": "build", "site_id": "local",
             "root": {"site_id": "local", "path": self.old_build},
             "outputs": [{"kind": "file", "locator": {
                 "site_id": "local", "path": self.executable}}],
             "executable_sha256": sha256_file(self.executable),
             "status": "verified"}, True)

    def relocate(self, dimension, identity_id, to):
        return self.cli("--ledger-home", self.home,
                        "record", "relocate",
                        "--project-root", self.project_root,
                        "--dimension", dimension,
                        "--identity-id", identity_id,
                        "--to", to)

    def test_relocate_run_updates_locator_and_current(self):
        new_root = os.path.join(self.temp, "compute", "projects", "demo",
                                "runs", "alpha", "run-1")
        os.makedirs(os.path.dirname(new_root))
        # the agent performs the move; relocate only re-probes and re-books
        shutil.move(self.old_run, new_root)
        code, payload = self.relocate("run", "run-1", new_root)
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["state_mutated"])
        self.assertEqual(payload["to"]["path"], os.path.normpath(new_root))
        case = self.store.get_case("case-1")
        identity = case["identities"]["run"]["items"][0]
        self.assertEqual(identity["root"]["path"], os.path.normpath(new_root))
        self.assertEqual(identity["scheduler"]["run_root"],
                         os.path.normpath(new_root))
        # the site has no site_root: the relocated path is outside the site
        # tree convention and stays legacy-roots
        self.assertEqual(identity["layout"], "legacy-roots")
        self.assertEqual(case["current"]["active_run"]["path"],
                         os.path.normpath(new_root))
        events = self.store.export()["events"]
        self.assertEqual(events[-1]["event_type"], "record.relocate")
        self.assertEqual(events[-1]["payload"]["from"],
                         os.path.normpath(self.old_run))

    def test_relocate_run_zero_write_on_evidence_mismatch(self):
        new_root = os.path.join(self.temp, "nowhere", "run-1")
        os.makedirs(new_root)  # moved dir without the run manifest
        code, payload = self.relocate("run", "run-1", new_root)
        self.assertEqual(code, 2)
        self.assertIn("run manifest", payload["error"])
        case = self.store.get_case("case-1")
        identity = case["identities"]["run"]["items"][0]
        self.assertEqual(identity["root"]["path"],
                         os.path.normpath(self.old_run))
        self.assertEqual(self.store.export()["events"], [])

    def test_relocate_refuses_inflight_run(self):
        code, payload = self.relocate("run", "run-2", self.old_run)
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        self.assertIn("in flight", payload["error"])
        case = self.store.get_case("case-1")
        runs = dict((item["id"], item)
                    for item in case["identities"]["run"]["items"])
        self.assertEqual(runs["run-2"]["root"]["path"],
                         os.path.normpath(self.old_run))

    def test_relocate_build_verifies_executable_fingerprint(self):
        new_root = os.path.join(self.temp, "compute", "projects", "demo",
                                "builds", "alpha", "build-1")
        os.makedirs(os.path.dirname(new_root))
        shutil.move(self.old_build, new_root)
        code, payload = self.relocate("build", "build-1", new_root)
        self.assertEqual(code, 0, payload)
        case = self.store.get_case("case-1")
        identity = case["identities"]["build"]["items"][0]
        self.assertEqual(identity["root"]["path"], os.path.normpath(new_root))
        self.assertEqual(identity["outputs"][0]["locator"]["path"],
                         os.path.join(os.path.normpath(new_root), "entity.xc"))
        # tampered evidence at another location is refused with zero writes
        bad_root = os.path.join(self.temp, "tampered")
        os.makedirs(bad_root)
        with open(os.path.join(bad_root, "entity.xc"), "w") as handle:
            handle.write("tampered\n")
        code, payload = self.relocate("build", "build-1", bad_root)
        self.assertEqual(code, 2)
        self.assertIn("fingerprint mismatch", payload["error"])
        identity = self.store.get_case("case-1")["identities"]["build"]["items"][0]
        self.assertEqual(identity["root"]["path"], os.path.normpath(new_root))

    def test_relocate_marks_site_tree_only_under_convention(self):
        # same move, but the site declares site_root and the target sits
        # under <site_root>/projects -> site-tree
        site_root = os.path.join(self.temp, "compute")
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "site_root": site_root, "roots": {}, "policy": {}})
        new_root = os.path.join(site_root, "projects", "demo",
                                "runs", "alpha", "run-1")
        os.makedirs(os.path.dirname(new_root))
        shutil.move(self.old_run, new_root)
        code, payload = self.relocate("run", "run-1", new_root)
        self.assertEqual(code, 0, payload)
        identity = self.store.get_case("case-1")["identities"]["run"]["items"][0]
        self.assertEqual(identity["layout"], "site-tree")

    def test_relocate_data_inventory_evidence(self):
        with open(os.path.join(self.old_run, "data-inventory.json"), "w") as handle:
            json.dump({"files": []}, handle)
        self.store.add_identity(
            "case-1", "data", "data-1",
            {"id": "data-1", "kind": "data", "site_id": "local",
             "root": {"site_id": "local", "path": self.old_run},
             "parents": {"run_id": "run-1"},
             "manifest": os.path.join(self.old_run, "data-inventory.json"),
             "status": "inventoried"}, True)
        new_root = os.path.join(self.temp, "moved", "run-1")
        os.makedirs(os.path.dirname(new_root))
        shutil.move(self.old_run, new_root)
        code, payload = self.relocate("data", "data-1", new_root)
        self.assertEqual(code, 0, payload)
        identity = self.store.get_case("case-1")["identities"]["data"]["items"][0]
        self.assertEqual(identity["root"]["path"], os.path.normpath(new_root))
        self.assertEqual(identity["manifest"], os.path.join(
            os.path.normpath(new_root), "data-inventory.json"))
        # missing inventory manifest -> zero writes
        empty = os.path.join(self.temp, "empty-data")
        os.makedirs(empty)
        code, payload = self.relocate("data", "data-1", empty)
        self.assertEqual(code, 2)
        self.assertIn("data inventory manifest", payload["error"])
        identity = self.store.get_case("case-1")["identities"]["data"]["items"][0]
        self.assertEqual(identity["root"]["path"], os.path.normpath(new_root))

    def test_relocate_error_paths(self):
        # unknown identity
        code, payload = self.relocate("run", "run-9", self.old_run)
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        self.assertIn("unknown run identity", payload["error"])
        # non-absolute target
        code, payload = self.relocate("run", "run-1", "relative/path")
        self.assertEqual(code, 2)
        self.assertIn("absolute", payload["error"])
        # unsupported dimension string is rejected by argparse choices
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--ledger-home", self.home,
             "record", "relocate", "--project-root", self.project_root,
             "--dimension", "source", "--identity-id", "x", "--to", "/tmp/x"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 2)
        identity = self.store.get_case("case-1")["identities"]["run"]["items"][0]
        self.assertEqual(identity["root"]["path"],
                         os.path.normpath(self.old_run))


class RunAbortTest(MigrationTestBase):
    def setUp(self):
        super(RunAbortTest, self).setUp()
        self.home = os.path.join(self.temp, "controller")
        self.store = OperationStore(self.home)
        self.site_root = os.path.join(self.temp, "compute")
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "site_root": self.site_root, "roots": {}, "policy": {}})
        self.project_root = os.path.join(self.temp, "project")
        os.makedirs(self.project_root)
        self.store.upsert_project("project-1", "demo", self.project_root)
        self.run_root = os.path.join(self.temp, "old-runs", "case-1", "run-1")
        os.makedirs(self.run_root)
        self.store.upsert_case(
            "case-1", "alpha", self.project_root,
            {"authority": {"site_id": "local", "path": self.project_root}},
            {"source_id": "", "build_id": "", "run_id": "run-1",
             "active_run": {"site_id": "local", "path": self.run_root},
             "data_id": "", "analysis_id": ""},
            project_uid="project-1")
        self.store.add_identity(
            "case-1", "run", "run-1",
            {"id": "run-1", "kind": "run", "site_id": "local",
             "root": {"site_id": "local", "path": self.run_root},
             "scheduler": {"pid": 4321, "run_root": self.run_root},
             "status": "submitted"}, True)

    def abort(self, *extra):
        return self.cli("--ledger-home", self.home,
                        "--actor-run-id", "abort-test",
                        "record", "run-abort",
                        "--project-root", self.project_root, *extra)

    def test_abort_inflight_run(self):
        code, payload = self.abort("--reason", "m87 decommissioned, site "
                                   "permanently unreachable")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "aborted")
        self.assertEqual(payload["previous_status"], "submitted")
        case = self.store.get_case("case-1")
        identity = case["identities"]["run"]["items"][0]
        self.assertEqual(identity["status"], "aborted")
        self.assertEqual(identity["abort"]["reason"],
                         "m87 decommissioned, site permanently unreachable")
        self.assertEqual(identity["abort"]["aborted_by"], "abort-test")
        self.assertIsNone(case["current"]["active_run"])
        self.assertEqual(case["current"]["readiness"]["run"], "aborted")
        events = self.store.export()["events"]
        self.assertEqual(events[-1]["event_type"], "record.run-abort")
        self.assertEqual(events[-1]["payload"]["reason"],
                         "m87 decommissioned, site permanently unreachable")
        self.assertEqual(events[-1]["actor"]["run_id"], "abort-test")

    def test_abort_terminal_run_is_refused_with_zero_writes(self):
        code, payload = self.abort("--reason", "first abort")
        self.assertEqual(code, 0, payload)
        events_before = len(self.store.export()["events"])
        code, again = self.abort("--reason", "duplicate abort")
        self.assertEqual(code, 2)
        self.assertIn("already terminal", again["error"])
        case = self.store.get_case("case-1")
        identity = case["identities"]["run"]["items"][0]
        self.assertEqual(identity["abort"]["reason"], "first abort")
        self.assertEqual(len(self.store.export()["events"]), events_before)

    def test_abort_unknown_run_and_missing_reason(self):
        code, payload = self.abort("--run-id", "run-9", "--reason", "x")
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "needs_decision")
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--ledger-home", self.home,
             "record", "run-abort", "--project-root", self.project_root],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 2)
        self.assertIn("--reason", stderr)
        identity = self.store.get_case("case-1")["identities"]["run"]["items"][0]
        self.assertEqual(identity["status"], "submitted")

    def test_abort_unblocks_plan_migration_and_relocate(self):
        code, plan = self.cli("--ledger-home", self.home,
                              "site", "plan-migration", "local")
        self.assertEqual(code, 0, plan)
        self.assertEqual(plan["items"][0]["action"], "skip")
        self.assertIn("in-flight", plan["items"][0]["reason"])
        code, payload = self.cli(
            "--ledger-home", self.home, "record", "relocate",
            "--project-root", self.project_root, "--dimension", "run",
            "--identity-id", "run-1", "--to", "/tmp/nowhere")
        self.assertEqual(code, 2)
        self.assertIn("in flight", payload["error"])
        code, unused = self.abort("--reason", "site retired")
        self.assertEqual(code, 0)
        code, plan = self.cli("--ledger-home", self.home,
                              "site", "plan-migration", "local")
        self.assertEqual(code, 0, plan)
        self.assertEqual(plan["items"][0]["action"], "move")
        # relocate is allowed once the manifest evidence is in place
        with open(os.path.join(self.run_root, "run-manifest.json"),
                  "w") as handle:
            json.dump({"run_id": "run-1"}, handle)
        new_root = os.path.join(self.site_root, "projects", "demo",
                                "runs", "alpha", "run-1")
        os.makedirs(os.path.dirname(new_root))
        shutil.move(self.run_root, new_root)
        code, payload = self.cli(
            "--ledger-home", self.home, "record", "relocate",
            "--project-root", self.project_root, "--dimension", "run",
            "--identity-id", "run-1", "--to", new_root)
        self.assertEqual(code, 0, payload)

    def test_dashboard_and_live_status_treat_aborted_as_terminal(self):
        code, unused = self.abort("--reason", "confirmed dead")
        self.assertEqual(code, 0)
        from entity_ledger_dashboard import build_dashboard
        dashboard = build_dashboard(
            OperationStore(self.home, create=False), self.project_root)
        self.assertEqual(dashboard["board"]["run"]["state"], "aborted")
        self.assertIn("aborted manually", dashboard["board"]["run"]["detail"])
        self.assertTrue(any("aborted manually" in step
                            for step in dashboard["next_steps"]))
        from entity_ledger_operation import status_for_project
        status = status_for_project(
            OperationStore(self.home, create=False), self.project_root,
            live=True)
        self.assertIsNone(status["live"])
        self.assertEqual(status["remote_calls"], 0)
        self.assertEqual(status["divergences"], [])


class LegacyStoreSchemaTest(MigrationTestBase):
    """A v3 bundle reading a pre-workspace (v2) store must get a clean
    migration-path error (or a doctor finding) — never an IndexError
    traceback from a raw row[...] access."""

    def setUp(self):
        super(LegacyStoreSchemaTest, self).setUp()
        self.home = os.path.join(self.temp, "legacy-home")
        os.makedirs(self.home)
        connection = sqlite3.connect(os.path.join(self.home, "ledger.db"))
        try:
            connection.executescript(SCHEMA_V2)
            connection.execute(
                "INSERT INTO meta(key,value) VALUES('schema_version','2')")
            connection.execute(
                "INSERT INTO sites(site_id,profile_json,updated_at) VALUES(?,?,?)",
                ("local", json.dumps({"site_id": "local"}), "2026-08-01T00:00:00Z"))
            # a v2 case row (no project_uid) is what crashed export before
            connection.execute(
                """INSERT INTO cases(case_uid,case_id,project_root,source_json,
                       current_json,legacy_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                ("case-1", "demo", os.path.join(self.temp, "demo"),
                 "{}", "{}", "{}", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"))
            connection.commit()
        finally:
            connection.close()

    def test_store_read_fails_with_migration_guidance(self):
        code, payload = self.cli("--ledger-home", self.home, "site", "list")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("store migrate", payload["error"])
        self.assertIn("pre-workspace schema", payload["error"])
        self.assertNotIn("IndexError", payload["error"])
        self.assertNotIn("Traceback", payload["error"])

    def test_store_class_raises_store_error_not_index_error(self):
        from entity_ledger_store import StoreError
        with self.assertRaises(StoreError) as caught:
            OperationStore(self.home, create=False)
        self.assertIn("entityctl store migrate", str(caught.exception))

    def test_doctor_reports_unmigrated_store_as_finding(self):
        code, payload = self.cli("--ledger-home", self.home, "doctor")
        self.assertEqual(code, 0, payload)
        self.assertTrue(any(
            "store migrate" in warning for warning in payload["warnings"]))
        # and the migration path actually clears the finding
        code, migrated = self.cli("--ledger-home", self.home, "store", "migrate")
        self.assertEqual(code, 0, migrated)
        code, payload = self.cli("--ledger-home", self.home, "site", "list")
        self.assertEqual(code, 0, payload)


if __name__ == "__main__":
    unittest.main()
