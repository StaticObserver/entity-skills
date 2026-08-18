#!/usr/bin/env python3

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-ledger", "scripts")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_ledger_store import OperationStore, SCHEMA_V2, STORE_SCHEMA_VERSION
from entity_ledger_common import LedgerError, ledger_home

from unittest import mock


# The retired v1 schema, inlined so the fixture does not depend on any
# runtime code that no longer exists.
V1_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sites (site_id TEXT PRIMARY KEY, profile_json TEXT NOT NULL,
    updated_at TEXT NOT NULL);
CREATE TABLE cases (case_uid TEXT PRIMARY KEY, case_id TEXT NOT NULL,
    project_root TEXT, source_json TEXT NOT NULL, current_json TEXT NOT NULL,
    legacy_json TEXT NOT NULL, active_operation_id TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE projects (project_root TEXT PRIMARY KEY,
    case_uid TEXT NOT NULL REFERENCES cases(case_uid), updated_at TEXT NOT NULL);
CREATE TABLE identities (case_uid TEXT NOT NULL REFERENCES cases(case_uid),
    dimension TEXT NOT NULL, identity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_uid, dimension, identity_id));
CREATE TABLE operations (operation_id TEXT PRIMARY KEY,
    case_uid TEXT NOT NULL REFERENCES cases(case_uid),
    goal_hash TEXT NOT NULL, plan_hash TEXT NOT NULL,
    goal_json TEXT NOT NULL, plan_json TEXT NOT NULL, status TEXT NOT NULL,
    result_json TEXT NOT NULL, actor_json TEXT NOT NULL,
    claim_token TEXT, claim_expires_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(case_uid, plan_hash));
CREATE TABLE steps (operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    step_index INTEGER NOT NULL, step_id TEXT NOT NULL, kind TEXT NOT NULL,
    spec_json TEXT NOT NULL, status TEXT NOT NULL, effect_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL, error_json TEXT NOT NULL,
    updated_at TEXT NOT NULL, PRIMARY KEY (operation_id, step_index));
CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_uid TEXT NOT NULL REFERENCES cases(case_uid), operation_id TEXT,
    event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
    actor_json TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class StoreMigrateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-migrate-")
        self.home = os.path.join(self.temp, "controller")
        os.makedirs(self.home)
        self.database = os.path.join(self.home, "ledger.db")
        self._build_v1_store()

    def tearDown(self):
        shutil.rmtree(self.temp)

    def _build_v1_store(self):
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(V1_SCHEMA)
            connection.execute(
                "INSERT INTO meta(key,value) VALUES('schema_version','1')")
            connection.execute(
                "INSERT INTO sites(site_id,profile_json,updated_at) VALUES(?,?,?)",
                ("local", json.dumps({"site_id": "local"}), "2026-07-20T00:00:00Z"))
            connection.execute(
                """INSERT INTO cases(case_uid,case_id,project_root,source_json,
                       current_json,legacy_json,active_operation_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                ("case-1", "demo", self.temp, "{}", '{"run_id": "run-1"}', "{}",
                 "op-1", "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z"))
            connection.execute(
                "INSERT INTO projects(project_root,case_uid,updated_at) VALUES(?,?,?)",
                (self.temp, "case-1", "2026-07-21T00:00:00Z"))
            connection.execute(
                """INSERT INTO identities(case_uid,dimension,identity_id,payload_json,
                       is_current,created_at) VALUES(?,?,?,?,?,?)""",
                ("case-1", "run", "run-1", '{"id": "run-1", "status": "submitted"}',
                 1, "2026-07-21T00:00:00Z"))
            connection.execute(
                """INSERT INTO operations(operation_id,case_uid,goal_hash,plan_hash,
                       goal_json,plan_json,status,result_json,actor_json,
                       created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                ("op-1", "case-1", "sha256:g", "sha256:p", '{"kind": "run"}',
                 '{"plan_hash": "sha256:p"}', "anomaly", '{"message": "boom"}',
                 '{"run_id": "legacy"}', "2026-07-21T00:00:00Z",
                 "2026-07-21T01:00:00Z"))
            connection.execute(
                """INSERT INTO steps(operation_id,step_index,step_id,kind,spec_json,
                       status,effect_json,evidence_json,error_json,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("op-1", 0, "preflight", "run.preflight.v1", '{}', "anomaly",
                 '{}', '[]', '{"message": "boom"}', "2026-07-21T01:00:00Z"))
            connection.execute(
                """INSERT INTO events(case_uid,operation_id,event_type,payload_json,
                       actor_json,created_at) VALUES(?,?,?,?,?,?)""",
                ("case-1", "op-1", "operation.created", '{"plan_hash": "sha256:p"}',
                 "{}", "2026-07-21T00:00:00Z"))
            connection.commit()
        finally:
            connection.close()

    def cli(self, *args):
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--ledger-home", self.home] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), stderr)
        return process.returncode, json.loads(stdout)

    def _tables(self):
        connection = sqlite3.connect(self.database)
        try:
            return sorted(row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"))
        finally:
            connection.close()

    def test_v1_store_migrates_to_v2_with_operations_archive(self):
        # a v1 store is rejected by the v2 runtime before migration
        with self.assertRaises(Exception) as caught:
            OperationStore(self.home, create=False)._initialize()
        self.assertIn("unsupported Ledger store schema", str(caught.exception))
        code, payload = self.cli("store", "migrate")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["state_mutated"])
        self.assertEqual(payload["store_schema_version"], STORE_SCHEMA_VERSION)
        self.assertEqual(payload["operations_archived"], 1)
        # the operations/steps history survives as a JSON archive and the
        # original database file is backed up next to it
        archive = payload["operations_archive"]
        self.assertTrue(os.path.isfile(archive))
        self.assertEqual(os.path.realpath(os.path.dirname(archive)),
                         os.path.realpath(os.path.join(self.home, "archive")))
        self.assertTrue(os.path.isfile(payload["database_backup"]))
        with open(archive, "r") as handle:
            archived = json.load(handle)
        self.assertEqual(archived["kind"], "entity-ledger.operations-archive")
        self.assertEqual(len(archived["operations"]), 1)
        operation = archived["operations"][0]
        self.assertEqual(operation["operation_id"], "op-1")
        self.assertEqual(operation["status"], "anomaly")
        self.assertEqual(operation["goal"], {"kind": "run"})
        self.assertEqual(operation["steps"][0]["step_id"], "preflight")
        self.assertEqual(operation["steps"][0]["error"], {"message": "boom"})
        # the rebuilt store has no protocol tables and no active_operation_id
        tables = self._tables()
        self.assertNotIn("operations", tables)
        self.assertNotIn("steps", tables)
        connection = sqlite3.connect(self.database)
        try:
            columns = [row[1] for row in connection.execute(
                "PRAGMA table_info(cases)")]
            self.assertNotIn("active_operation_id", columns)
            version = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()[0]
            self.assertEqual(int(version), STORE_SCHEMA_VERSION)
        finally:
            connection.close()
        # sites/cases/projects/identities/events are preserved
        exported = OperationStore(self.home, create=False).export()
        self.assertEqual(exported["schema_version"], STORE_SCHEMA_VERSION)
        self.assertEqual([site["site_id"] for site in exported["sites"]], ["local"])
        self.assertEqual(len(exported["cases"]), 1)
        case = exported["cases"][0]
        self.assertEqual(case["case_uid"], "case-1")
        self.assertEqual(case["current"], {"run_id": "run-1"})
        self.assertNotIn("active_operation", case)
        self.assertEqual(case["identities"]["run"]["current_id"], "run-1")
        self.assertEqual(len(exported["projects"]), 1)
        self.assertEqual([event["event_type"] for event in exported["events"]],
                         ["operation.created"])
        # re-running the migration is an idempotent no-op
        code, again = self.cli("store", "migrate")
        self.assertEqual(code, 0, again)
        self.assertFalse(again["state_mutated"])
        self.assertIn("already at the current schema", again["message"])

    def test_newer_schema_is_rejected(self):
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE meta SET value=? WHERE key='schema_version'",
                (str(STORE_SCHEMA_VERSION + 1),))
            connection.commit()
        finally:
            connection.close()
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--ledger-home", self.home,
             "store", "migrate"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, unused = process.communicate()
        self.assertEqual(process.returncode, 2)
        self.assertIn("newer than this bundle supports", stdout)


class V2ToV3MigrateTest(unittest.TestCase):
    """A v2 store (root->case 1:1 bindings) migrates to v3: every binding
    becomes a Project entity with its case attached."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-migrate-v3-")
        self.home = os.path.join(self.temp, "controller")
        os.makedirs(self.home)
        self.database = os.path.join(self.home, "ledger.db")
        self.project = os.path.join(self.temp, "project")
        self._build_v2_store()

    def tearDown(self):
        shutil.rmtree(self.temp)

    def _build_v2_store(self):
        connection = sqlite3.connect(self.database)
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
                ("case-1", "demo", self.project, "{}", '{"run_id": "run-1"}',
                 "{}", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"))
            connection.execute(
                "INSERT INTO projects(project_root,case_uid,updated_at) VALUES(?,?,?)",
                (self.project, "case-1", "2026-08-02T00:00:00Z"))
            connection.execute(
                """INSERT INTO identities(case_uid,dimension,identity_id,payload_json,
                       is_current,created_at) VALUES(?,?,?,?,?,?)""",
                ("case-1", "run", "run-1", '{"id": "run-1", "status": "submitted"}',
                 1, "2026-08-02T00:00:00Z"))
            connection.execute(
                """INSERT INTO events(case_uid,operation_id,event_type,payload_json,
                       actor_json,created_at) VALUES(?,?,?,?,?,?)""",
                ("case-1", None, "record.intent", '{"text": "x"}', "{}",
                 "2026-08-02T00:00:00Z"))
            connection.commit()
        finally:
            connection.close()

    def cli(self, *args):
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL, "--ledger-home", self.home] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), stderr)
        return process.returncode, json.loads(stdout)

    def test_trailing_slash_roots_merge_into_one_project(self):
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                """INSERT INTO cases(case_uid,case_id,project_root,source_json,
                       current_json,legacy_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                ("case-2", "demo-b", self.project + os.sep, "{}", "{}", "{}",
                 "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"))
            connection.execute(
                "INSERT INTO projects(project_root,case_uid,updated_at) "
                "VALUES(?,?,?)",
                (self.project + os.sep, "case-2", "2026-08-02T00:00:00Z"))
            connection.commit()
        finally:
            connection.close()
        code, payload = self.cli("store", "migrate")
        self.assertEqual(code, 0, payload)
        store = OperationStore(self.home, create=False)
        projects = store.find_projects()
        # normalized roots collide -> a single Project, both Cases attached
        self.assertEqual(len(projects), 1)
        project = projects[0]
        self.assertTrue(project["slug"])
        self.assertEqual(project["slug"], os.path.basename(self.project))
        cases = store.project_cases(project["project_uid"])
        self.assertEqual(sorted(case["case_uid"] for case in cases),
                         ["case-1", "case-2"])

    def test_v2_store_migrates_to_v3_project_entities(self):
        # the v3 runtime refuses the v2 store before migration
        with self.assertRaises(Exception) as caught:
            OperationStore(self.home, create=False)._initialize()
        self.assertIn("unsupported Ledger store schema", str(caught.exception))
        code, payload = self.cli("store", "migrate")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["state_mutated"])
        self.assertEqual(payload["store_schema_version"], STORE_SCHEMA_VERSION)
        self.assertEqual(payload["projects_created"], 1)
        self.assertEqual(payload["cases_linked"], 1)
        self.assertTrue(os.path.isfile(payload["database_backup"]))
        # the binding became a Project entity; the case is attached to it
        store = OperationStore(self.home, create=False)
        projects = store.find_projects()
        self.assertEqual(len(projects), 1)
        project = projects[0]
        self.assertTrue(project["project_uid"].startswith("project-"))
        self.assertEqual(project["slug"], os.path.basename(self.project))
        self.assertEqual(project["project_root"], os.path.realpath(self.project))
        case = store.get_case("case-1")
        self.assertEqual(case["project_uid"], project["project_uid"])
        self.assertEqual(case["identities"]["run"]["current_id"], "run-1")
        # the path-covering lookup semantics are unchanged
        resolved = store.resolve_project(self.project)
        self.assertEqual(resolved["case_uid"], "case-1")
        exported = store.export()
        self.assertEqual(exported["schema_version"], STORE_SCHEMA_VERSION)
        self.assertEqual(len(exported["cases"]), 1)
        self.assertEqual(len(exported["projects"]), 1)
        self.assertEqual([event["event_type"] for event in exported["events"]],
                         ["record.intent"])
        # re-running the migration is an idempotent no-op
        code, again = self.cli("store", "migrate")
        self.assertEqual(code, 0, again)
        self.assertFalse(again["state_mutated"])
        self.assertIn("already at the current schema", again["message"])


class LegacyStorageMigrationTest(unittest.TestCase):
    """Pre-rename Router storage is adopted automatically on first access."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-legacy-")
        self._env = mock.patch.dict(os.environ, {"HOME": self.temp})
        self._env.start()
        for key in ("ENTITY_LEDGER_HOME", "ENTITY_ROUTER_HOME",
                    "ENTITY_WORKSPACE"):
            os.environ.pop(key, None)

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.temp)

    def test_legacy_home_directory_is_adopted(self):
        legacy = os.path.join(self.temp, ".entity-router")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "marker"), "w") as handle:
            handle.write("x")
        home = ledger_home()
        self.assertEqual(
            home, os.path.join(os.path.realpath(self.temp), ".entity-ledger"))
        self.assertFalse(os.path.exists(legacy))
        self.assertTrue(os.path.isfile(os.path.join(home, "marker")))
        # a second call is a no-op now that the new home exists
        self.assertEqual(ledger_home(), home)

    def test_legacy_home_rename_race_with_completed_peer(self):
        legacy = os.path.join(self.temp, ".entity-router")
        os.makedirs(legacy)
        home = os.path.join(os.path.realpath(self.temp), ".entity-ledger")

        def peer_won(unused_source, unused_target):
            # another process finished the migration between our existence
            # check and the rename
            os.makedirs(home)
            raise FileNotFoundError("no such file or directory")

        with mock.patch("entity_ledger_common.os.rename",
                        side_effect=peer_won):
            self.assertEqual(ledger_home(), home)

    def test_legacy_home_rename_failure_is_a_ledger_error(self):
        legacy = os.path.join(self.temp, ".entity-router")
        os.makedirs(legacy)
        with mock.patch("entity_ledger_common.os.rename",
                        side_effect=OSError("permission denied")):
            with self.assertRaises(LedgerError) as raised:
                ledger_home()
        self.assertIn("cannot migrate", str(raised.exception))

    def test_legacy_home_environment_variable_is_honoured(self):
        legacy = os.path.join(self.temp, "legacy-controller")
        os.environ["ENTITY_ROUTER_HOME"] = legacy
        self.assertEqual(ledger_home(), os.path.realpath(legacy))
        os.environ["ENTITY_LEDGER_HOME"] = os.path.join(self.temp, "explicit")
        self.assertEqual(
            ledger_home(), os.path.realpath(os.environ["ENTITY_LEDGER_HOME"]))

    def test_legacy_router_db_is_renamed(self):
        home = os.path.join(self.temp, "controller")
        store = OperationStore(home)
        store.upsert_site({"site_id": "local", "transport": {"kind": "local"},
                           "scheduler": {"kind": "none"}, "roots": {}})
        os.rename(os.path.join(home, "ledger.db"),
                  os.path.join(home, "router.db"))
        reopened = OperationStore(home, create=False)
        self.assertTrue(os.path.isfile(os.path.join(home, "ledger.db")))
        self.assertFalse(os.path.exists(os.path.join(home, "router.db")))
        self.assertEqual(reopened.get_site("local")["site_id"], "local")


if __name__ == "__main__":
    unittest.main()
