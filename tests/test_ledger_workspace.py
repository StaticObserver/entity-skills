#!/usr/bin/env python3

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

from unittest import mock


ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "skills", "entity-ledger", "scripts")
ENTITYCTL = os.path.join(SCRIPTS, "entityctl.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import entity_ledger_store
from entity_ledger_common import (
    LedgerError,
    absolute,
    active_workspace_pointer,
    read_active_workspace,
    write_active_workspace,
)
from entity_ledger_store import OperationStore, resolve_ledger_home
from entity_ledger_workspace import (
    WorkspaceError,
    init_workspace,
    load_workspace_yaml,
)


class WorkspaceTestBase(unittest.TestCase):
    """Isolate HOME and every controller-location variable so tests never
    touch the real ~/.entity-ledger."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-workspace-")
        self._env = mock.patch.dict(os.environ, {"HOME": self.temp})
        self._env.start()
        for key in ("ENTITY_LEDGER_HOME", "ENTITY_ROUTER_HOME",
                    "ENTITY_WORKSPACE"):
            os.environ.pop(key, None)
        entity_ledger_store._legacy_fallback_warned = False

    def tearDown(self):
        self._env.stop()
        entity_ledger_store._legacy_fallback_warned = False
        shutil.rmtree(self.temp)

    def cli(self, *args, **kwargs):
        extra_env = kwargs.pop("env", {})
        env = dict((key, value) for key, value in os.environ.items()
                   if not key.startswith("ENTITY_"))
        env["HOME"] = self.temp
        env.update(extra_env)
        process = subprocess.Popen(
            [sys.executable, ENTITYCTL] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, env=env)
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), stderr)
        return process.returncode, json.loads(stdout), stderr


class WorkspaceInitTest(WorkspaceTestBase):
    def test_init_creates_skeleton(self):
        workspace = os.path.join(self.temp, "ws")
        code, payload, unused = self.cli("workspace", "init", workspace)
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["created"])
        self.assertTrue(payload["state_mutated"])
        # workspace.yaml schema: uuid workspace_id, integer schema_version,
        # ISO8601 UTC created_at
        record = load_workspace_yaml(workspace)
        self.assertEqual(record["schema_version"], 1)
        uuid.UUID(record["workspace_id"])
        self.assertTrue(record["created_at"].endswith("Z"))
        self.assertEqual(payload["workspace_id"], record["workspace_id"])
        for name in ("projects", "sites"):
            self.assertTrue(os.path.isdir(os.path.join(workspace, name)))
        ledger = os.path.join(workspace, ".ledger")
        self.assertTrue(os.path.isfile(os.path.join(ledger, "ledger.db")))
        self.assertTrue(os.path.isdir(os.path.join(ledger, "snapshots")))
        # the initialized ledger.db is a valid current-schema store
        exported = OperationStore(ledger, create=False).export()
        self.assertEqual(exported["schema_version"],
                         entity_ledger_store.STORE_SCHEMA_VERSION)

    def test_init_into_existing_empty_directory(self):
        workspace = os.path.join(self.temp, "ws")
        os.makedirs(workspace)
        code, payload, unused = self.cli("workspace", "init", workspace)
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["created"])
        self.assertTrue(os.path.isfile(
            os.path.join(workspace, "workspace.yaml")))

    def test_init_is_idempotent_and_keeps_content(self):
        workspace = os.path.join(self.temp, "ws")
        code, first, unused = self.cli("workspace", "init", workspace)
        self.assertEqual(code, 0, first)
        marker = os.path.join(workspace, "projects", "keep.txt")
        with open(marker, "w") as handle:
            handle.write("untouched")
        code, second, unused = self.cli("workspace", "init", workspace)
        self.assertEqual(code, 0, second)
        self.assertFalse(second["created"])
        self.assertFalse(second["state_mutated"])
        self.assertEqual(second["workspace_id"], first["workspace_id"])
        with open(marker, "r") as handle:
            self.assertEqual(handle.read(), "untouched")

    def test_init_refuses_non_workspace_directory(self):
        workspace = os.path.join(self.temp, "busy")
        os.makedirs(workspace)
        with open(os.path.join(workspace, "unrelated.txt"), "w") as handle:
            handle.write("x")
        code, payload, unused = self.cli("workspace", "init", workspace)
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("not a workspace", payload["error"])
        self.assertFalse(os.path.exists(
            os.path.join(workspace, "workspace.yaml")))

    def test_init_refuses_corrupt_workspace_yaml(self):
        workspace = os.path.join(self.temp, "ws")
        os.makedirs(workspace)
        with open(os.path.join(workspace, "workspace.yaml"), "w") as handle:
            handle.write("schema_version: nope\n")
        code, payload, unused = self.cli("workspace", "init", workspace)
        self.assertEqual(code, 2)
        self.assertIn("schema_version", payload["error"])


class WorkspaceAdoptTest(WorkspaceTestBase):
    def test_adopt_writes_pointer_and_where_resolves_it(self):
        workspace = os.path.join(self.temp, "ws")
        code, unused_payload, unused_err = self.cli("workspace", "init", workspace)
        self.assertEqual(code, 0)
        code, payload, unused_err = self.cli("workspace", "adopt", workspace)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["workspace"], absolute(workspace))
        self.assertEqual(payload["hint"], "")
        pointer = os.path.join(self.temp, ".entity-ledger", "active-workspace")
        self.assertEqual(payload["pointer"], os.path.realpath(pointer))
        with open(os.path.realpath(pointer), "r") as handle:
            record = json.load(handle)
        self.assertEqual(record["workspace"], absolute(workspace))
        self.assertTrue(record["adopted_at"].endswith("Z"))
        code, where, unused_err = self.cli("workspace", "where")
        self.assertEqual(code, 0, where)
        self.assertEqual(where["source"], "pointer")
        self.assertEqual(where["workspace"], absolute(workspace))
        self.assertTrue(where["workspace_valid"])
        self.assertEqual(where["ledger_db"], os.path.join(
            absolute(workspace), ".ledger", "ledger.db"))
        self.assertTrue(where["ledger_db_exists"])

    def test_adopt_rejects_non_workspace(self):
        target = os.path.join(self.temp, "not-a-workspace")
        os.makedirs(target)
        code, payload, unused = self.cli("workspace", "adopt", target)
        self.assertEqual(code, 2)
        self.assertIn("not a workspace", payload["error"])
        self.assertFalse(os.path.exists(active_workspace_pointer()))

    def test_adopt_rejects_corrupt_workspace_yaml(self):
        target = os.path.join(self.temp, "broken")
        os.makedirs(target)
        with open(os.path.join(target, "workspace.yaml"), "w") as handle:
            handle.write("workspace_id:\n")
        code, payload, unused = self.cli("workspace", "adopt", target)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(active_workspace_pointer()))

    def test_adopt_hints_when_legacy_db_not_yet_moved(self):
        # legacy controller data exists at ~/.entity-ledger/ledger.db
        legacy_home = absolute("~/.entity-ledger")
        OperationStore(legacy_home)
        workspace = os.path.join(self.temp, "ws")
        init_workspace(workspace)
        # ...but the workspace's own ledger.db has not been created/moved
        os.remove(os.path.join(workspace, ".ledger", "ledger.db"))
        code, payload, unused = self.cli("workspace", "adopt", workspace)
        self.assertEqual(code, 0, payload)
        self.assertIn("workspace import", payload["hint"])
        # the legacy database is left untouched (moving is a later stage)
        self.assertTrue(os.path.isfile(
            os.path.join(legacy_home, "ledger.db")))
        self.assertFalse(os.path.isfile(
            os.path.join(workspace, ".ledger", "ledger.db")))


class ResolutionOrderTest(WorkspaceTestBase):
    def _workspace(self, name="ws"):
        workspace = os.path.join(self.temp, name)
        init_workspace(workspace)
        return absolute(workspace)

    def test_explicit_argument_wins_over_everything(self):
        workspace = self._workspace()
        write_active_workspace(workspace)
        os.environ["ENTITY_WORKSPACE"] = workspace
        explicit = os.path.join(self.temp, "explicit-home")
        home, source = resolve_ledger_home(explicit)
        self.assertEqual(source, "explicit")
        self.assertEqual(home, absolute(explicit))
        # ENTITY_LEDGER_HOME counts as explicit too
        os.environ["ENTITY_LEDGER_HOME"] = explicit
        home, source = resolve_ledger_home()
        self.assertEqual(source, "explicit")
        self.assertEqual(home, absolute(explicit))

    def test_environment_variable_beats_pointer_and_legacy(self):
        workspace = self._workspace("env-ws")
        write_active_workspace(self._workspace("pointer-ws"))
        OperationStore(absolute("~/.entity-ledger"))
        os.environ["ENTITY_WORKSPACE"] = workspace
        home, source = resolve_ledger_home()
        self.assertEqual(source, "environment")
        self.assertEqual(home, os.path.join(workspace, ".ledger"))

    def test_pointer_beats_legacy_home(self):
        workspace = self._workspace()
        write_active_workspace(workspace)
        OperationStore(absolute("~/.entity-ledger"))
        home, source = resolve_ledger_home()
        self.assertEqual(source, "pointer")
        self.assertEqual(home, os.path.join(workspace, ".ledger"))

    def test_legacy_fallback_warns_once(self):
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            home, source = resolve_ledger_home()
            again, again_source = resolve_ledger_home()
        self.assertEqual(source, "legacy")
        self.assertEqual(again_source, "legacy")
        self.assertEqual(home, again)
        self.assertEqual(home, absolute("~/.entity-ledger"))
        self.assertEqual(captured.getvalue().count("deprecated"), 1)

    def test_corrupt_pointer_fails_loudly(self):
        pointer = active_workspace_pointer()
        os.makedirs(os.path.dirname(pointer))
        with open(pointer, "w") as handle:
            handle.write("not json")
        with self.assertRaises(LedgerError):
            resolve_ledger_home()

    def test_dangling_workspace_env_var_errors_without_creating(self):
        ghost = os.path.join(self.temp, "ghost-ws")
        os.environ["ENTITY_WORKSPACE"] = ghost
        with self.assertRaises(LedgerError) as raised:
            resolve_ledger_home()
        self.assertIn("workspace", str(raised.exception))
        # never silently makedirs a fresh empty store at a dangling path
        self.assertFalse(os.path.exists(ghost))

    def test_dangling_workspace_pointer_errors(self):
        ghost = os.path.join(self.temp, "ghost-ws")
        os.makedirs(ghost)
        init_workspace(ghost)
        write_active_workspace(ghost)
        shutil.rmtree(ghost)
        with self.assertRaises(LedgerError):
            resolve_ledger_home()
        self.assertFalse(os.path.exists(ghost))
        code, payload, unused = self.cli("workspace", "where")
        self.assertEqual(code, 2)
        self.assertIn("workspace", payload["error"])
        self.assertFalse(os.path.exists(ghost))

    def test_where_reports_environment_source(self):
        workspace = self._workspace()
        code, where, unused = self.cli(
            "workspace", "where", env={"ENTITY_WORKSPACE": workspace})
        self.assertEqual(code, 0, where)
        self.assertEqual(where["source"], "environment")
        self.assertEqual(where["workspace"], workspace)
        self.assertEqual(where["ledger_db"],
                         os.path.join(workspace, ".ledger", "ledger.db"))

    def test_where_reports_legacy_fallback(self):
        code, where, stderr = self.cli("workspace", "where")
        self.assertEqual(code, 0, where)
        self.assertEqual(where["source"], "legacy")
        self.assertIsNone(where["workspace"])
        self.assertEqual(where["ledger_db"], os.path.join(
            absolute("~/.entity-ledger"), "ledger.db"))
        self.assertIn("deprecated", stderr)

    def test_where_explicit_flag_beats_environment(self):
        workspace = self._workspace()
        explicit = os.path.join(self.temp, "explicit-home")
        code, where, unused = self.cli(
            "--ledger-home", explicit, "workspace", "where",
            env={"ENTITY_WORKSPACE": workspace})
        self.assertEqual(code, 0, where)
        self.assertEqual(where["source"], "explicit")
        self.assertEqual(where["ledger_home"], absolute(explicit))
        self.assertIsNone(where["workspace"])

    def test_record_command_uses_workspace_db_via_pointer(self):
        # an existing command run without --ledger-home lands on the adopted
        # workspace's store: the site registered there is visible
        workspace = self._workspace()
        store = OperationStore(os.path.join(workspace, ".ledger"))
        store.upsert_site({"site_id": "local", "transport": {"kind": "local"},
                           "scheduler": {"kind": "none"}, "roots": {}})
        write_active_workspace(workspace)
        code, payload, unused = self.cli("site", "list")
        self.assertEqual(code, 0, payload)
        self.assertEqual([site["site_id"] for site in payload["sites"]],
                         ["local"])


class WorkspaceYamlTest(WorkspaceTestBase):
    def test_migrated_from_roundtrip_with_special_characters(self):
        workspace = os.path.join(self.temp, "ws")
        source = os.path.join(self.temp, "old: path #1")
        result = init_workspace(workspace, migrated_from=source)
        record = load_workspace_yaml(workspace)
        self.assertEqual(record["migrated_from"], absolute(source))
        self.assertEqual(record["workspace_id"],
                         result["record"]["workspace_id"])

    def test_missing_fields_are_rejected(self):
        workspace = os.path.join(self.temp, "ws")
        os.makedirs(workspace)
        with open(os.path.join(workspace, "workspace.yaml"), "w") as handle:
            handle.write("schema_version: 1\nworkspace_id: abc\n")
        with self.assertRaises(WorkspaceError):
            load_workspace_yaml(workspace)


if __name__ == "__main__":
    unittest.main()
