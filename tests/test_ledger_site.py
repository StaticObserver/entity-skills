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
from entity_ledger_facts import execution_roots
from entity_ledger_store import OperationStore
from entity_ledger_workspace import (
    WorkspaceError,
    init_workspace,
    list_site_archives,
    load_flat_yaml,
    load_site_yaml,
    profile_from_archive,
    site_yaml_path,
    write_site_yaml,
)


class SiteTestBase(unittest.TestCase):
    """Isolate HOME and the controller-location variables; each test gets a
    fresh adopted workspace."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-site-")
        self._env = mock.patch.dict(os.environ, {"HOME": self.temp})
        self._env.start()
        for key in ("ENTITY_LEDGER_HOME", "ENTITY_ROUTER_HOME",
                    "ENTITY_WORKSPACE"):
            os.environ.pop(key, None)
        self.workspace = init_workspace(os.path.join(self.temp, "ws"))["workspace"]
        write_active_workspace(self.workspace)
        self.home = os.path.join(self.workspace, ".ledger")
        self.store = OperationStore(self.home)

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

    def write_archive(self, site_id, **fields):
        record = {"site_id": site_id}
        record.update(fields)
        if record.get("site_root"):
            record["site_root"] = absolute(record["site_root"])
        return write_site_yaml(self.workspace, record)


class SiteArchiveTest(SiteTestBase):
    def test_nested_archive_roundtrip(self):
        self.write_archive(
            "m87",
            transport={"kind": "ssh", "alias": "m87"},
            scheduler={"kind": "slurm", "default_partition": "fat"},
            machine={"os": "Linux", "arch": "x86_64", "gpus": ["RTX 4070 Ti"]},
            site_root="/home/staticobserver/entity-compute",
            projects=["bh-reconnection"],
            deps=[{"stack_id": "gcc11-openmpi4.1-hdf5.14",
                   "status": "verified",
                   "packages": [{"name": "hdf5", "version": "1.14.5",
                                 "prefix": "/deps/hdf5"}]}],
            notes="first line\nsecond line: with colon and # hash")
        path = site_yaml_path(self.workspace, "m87")
        with open(path, "r") as handle:
            text = handle.read()
        self.assertIn("notes: |", text)
        record = load_site_yaml(path)
        self.assertEqual(record["transport"], {"kind": "ssh", "alias": "m87"})
        self.assertEqual(record["scheduler"]["default_partition"], "fat")
        self.assertEqual(record["machine"]["gpus"], ["RTX 4070 Ti"])
        self.assertEqual(record["projects"], ["bh-reconnection"])
        self.assertEqual(record["deps"][0]["packages"][0]["name"], "hdf5")
        self.assertEqual(record["notes"], "first line\nsecond line: with colon and # hash")
        archives = list_site_archives(self.workspace)
        self.assertEqual(sorted(archives), ["m87"])

    def test_invalid_archive_is_refused(self):
        with self.assertRaises(WorkspaceError):
            write_site_yaml(self.workspace,
                            {"site_id": "m87", "site_root": "relative/root"})
        path = site_yaml_path(self.workspace, "bad")
        with open(path, "w") as handle:
            handle.write("site_id: bad\nschema_version: 1\n"
                         "transport: {\"kind\": \"nfs\"}\n")
        with self.assertRaises(WorkspaceError):
            load_site_yaml(path)

    def test_bracket_prefixed_scalars_roundtrip_quoted(self):
        # a scalar starting with [ or { would parse as a flow collection;
        # the writer must quote it
        record = self.write_archive("m87", site_root="/[bracket]/compute",
                                    notes="single-line notes")
        loaded = load_site_yaml(site_yaml_path(self.workspace, "m87"))
        self.assertEqual(loaded["site_root"], "/[bracket]/compute")
        self.assertEqual(loaded["notes"], "single-line notes")

    def test_profile_from_archive_maps_to_db_shape(self):
        record = self.write_archive(
            "m87", transport={"kind": "ssh", "alias": "m87"},
            scheduler={"kind": "slurm"}, site_root="/opt/compute",
            machine={"os": "Linux"}, deps=[{"stack_id": "s1"}])
        profile = profile_from_archive(record)
        self.assertEqual(profile["transport"],
                         {"kind": "ssh", "ssh_alias": "m87"})
        self.assertEqual(profile["site_root"], "/opt/compute")
        self.assertEqual(profile["machine"], {"os": "Linux"})
        self.assertEqual(profile["deps"], [{"stack_id": "s1"}])
        self.assertEqual(profile["roots"], {})
        self.assertEqual(profile["schema_version"], 1)


class SiteSyncTest(SiteTestBase):
    def test_sync_refreshes_db_and_reports_db_only(self):
        self.write_archive("m87", transport={"kind": "local"},
                           site_root=self.temp)
        self.write_archive("astro", transport={"kind": "ssh", "alias": "astro"})
        self.store.upsert_site({"schema_version": 1, "site_id": "legacy",
                                "transport": {"kind": "local"},
                                "scheduler": {"kind": "none"}, "roots": {}})
        code, payload = self.cli("site", "sync")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["synced"], ["astro", "m87"])
        self.assertEqual(payload["db_only"], ["legacy"])
        self.assertTrue(payload["state_mutated"])
        profile = self.store.get_site("m87")
        self.assertEqual(profile["site_root"], os.path.realpath(self.temp))
        self.assertEqual(profile["transport"], {"kind": "local"})
        # the db-only site stays untouched
        self.assertEqual(self.store.get_site("legacy")["site_id"], "legacy")
        # syncing a single archive works; unknown archive is an error
        code, payload = self.cli("site", "sync", "astro")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["synced"], ["astro"])
        code, payload = self.cli("site", "sync", "ghost")
        self.assertEqual(code, 2)
        self.assertIn("no site archive", payload["error"])

    def test_sync_notes_only_archive_defaults_local_transport(self):
        self.write_archive("m87", notes="prose-only archive")
        code, payload = self.cli("site", "sync")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["synced"], ["m87"])
        profile = self.store.get_site("m87")
        self.assertEqual(profile["transport"], {"kind": "local"})
        self.assertEqual(profile["notes"], "prose-only archive")

    def test_list_and_show_merge_archive_and_db(self):
        self.write_archive("m87", transport={"kind": "local"},
                           site_root=self.temp, projects=["demo"])
        self.store.upsert_site({"schema_version": 1, "site_id": "legacy",
                                "transport": {"kind": "local"},
                                "scheduler": {"kind": "none"}, "roots": {}})
        code, payload = self.cli("site", "list")
        self.assertEqual(code, 0, payload)
        by_id = dict((entry["site_id"], entry) for entry in payload["sites"])
        self.assertEqual(by_id["m87"]["origin"], "archive")
        self.assertEqual(by_id["m87"]["projects"], ["demo"])
        self.assertEqual(by_id["legacy"]["origin"], "db-only")
        code, payload = self.cli("site", "show", "m87")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["origin"], "archive")
        self.assertEqual(payload["effective_profile"]["site_root"],
                         os.path.realpath(self.temp))
        code, payload = self.cli("site", "show", "legacy")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["origin"], "db-only")
        self.assertIsNone(payload["archive"])
        code, payload = self.cli("site", "show", "ghost")
        self.assertEqual(code, 2)


class SiteInitTest(SiteTestBase):
    def test_site_init_creates_tree_and_marker_idempotently(self):
        site_root = os.path.join(self.temp, "compute")
        self.write_archive("m87", transport={"kind": "local"},
                           site_root=site_root)
        code, payload = self.cli("site", "init", "m87")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["marker_created"])
        for name in ("deps", "checkouts", "projects"):
            self.assertTrue(os.path.isdir(os.path.join(site_root, name)))
        marker = load_flat_yaml(os.path.join(site_root, "entity-site.yaml"),
                                "site marker")
        self.assertEqual(marker["site_id"], "m87")
        self.assertEqual(marker["roots"]["deps"],
                         os.path.join(absolute(site_root), "deps"))
        # re-run validates the marker and creates nothing
        code, again = self.cli("site", "init", "m87")
        self.assertEqual(code, 0, again)
        self.assertFalse(again["marker_created"])
        self.assertFalse(again["state_mutated"])

    def test_site_init_refuses_foreign_marker_and_missing_root(self):
        site_root = os.path.join(self.temp, "compute")
        os.makedirs(site_root)
        with open(os.path.join(site_root, "entity-site.yaml"), "w") as handle:
            handle.write("site_id: other\nschema_version: 1\n")
        self.write_archive("m87", transport={"kind": "local"},
                           site_root=site_root)
        code, payload = self.cli("site", "init", "m87")
        self.assertEqual(code, 2)
        self.assertIn("other", payload["error"])
        self.write_archive("rootless", transport={"kind": "local"})
        code, payload = self.cli("site", "init", "rootless")
        self.assertEqual(code, 2)
        self.assertIn("site_root", payload["error"])

    def test_site_init_transport_failure_is_not_treated_as_absent(self):
        # an ssh failure must abort site init, never rewrite a live marker
        self.write_archive("m87",
                           transport={"kind": "ssh", "alias": "ghost-host"},
                           site_root="/remote/compute")
        import argparse
        import entityctl
        args = argparse.Namespace(site_id="m87", ledger_home=None,
                                  actor_run_id="t", actor_provider="",
                                  actor_client="", actor_session_id="",
                                  actor_model="", actor_bundle_hash="")
        with mock.patch("entityctl.run_on_site",
                        return_value=(255, "", "ssh: connect to host failed")):
            with self.assertRaises(Exception) as raised:
                entityctl.site_init_command(args)
        self.assertIn("cannot read the site marker", str(raised.exception))


class SiteDiscoverTest(SiteTestBase):
    def test_discover_records_machine_and_claims_marker(self):
        site_root = os.path.join(self.temp, "compute")
        self.write_archive("m87", transport={"kind": "local"},
                           scheduler={"kind": "none"}, site_root=site_root)
        code, unused = self.cli("site", "sync")
        self.assertEqual(code, 0)
        code, unused = self.cli("site", "init", "m87")
        self.assertEqual(code, 0)
        code, payload = self.cli("site", "discover", "m87")
        self.assertEqual(code, 0, payload)
        machine = payload["machine"]
        self.assertTrue(machine["os"])
        self.assertTrue(machine["arch"])
        self.assertTrue(payload["archive"]["machine_updated"])
        self.assertTrue(payload["state_mutated"])
        self.assertTrue(payload["site_marker"]["marker_found"])
        self.assertEqual(payload["site_marker"]["site_id"], "m87")
        # the machine section landed in the archive; a second probe is a no-op
        record = load_site_yaml(site_yaml_path(self.workspace, "m87"))
        self.assertEqual(record["machine"]["os"], machine["os"])
        code, again = self.cli("site", "discover", "m87")
        self.assertEqual(code, 0, again)
        self.assertFalse(again["archive"]["machine_updated"])

    def test_unknown_site_lists_registered_candidates(self):
        # B3: a mistyped site id must name the registered sites (the
        # deps-add astro vs astro-axion incident)
        self.store.upsert_site({
            "schema_version": 1, "site_id": "astro-axion",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "roots": {}, "policy": {}})
        code, payload = self.cli("site", "discover", "astro")
        self.assertEqual(code, 2)
        self.assertIn("unknown site_id: astro", payload["error"])
        self.assertIn("registered sites: astro-axion", payload["error"])
        # I2: an anomaly (unexpected/store-level failure) is the retryable kind
        self.assertEqual(payload["status"], "anomaly")
        self.assertTrue(payload["retryable"])


class SiteImportNotesTest(SiteTestBase):
    def setUp(self):
        super(SiteImportNotesTest, self).setUp()
        self.notes = os.path.join(self.temp, "site-notes")
        os.makedirs(self.notes)
        with open(os.path.join(self.notes, "m87.md"), "w") as handle:
            handle.write("# machine: m87\n\nprose text, not parsed.\n")
        with open(os.path.join(self.notes, "m87-site-profile.json"), "w") as handle:
            json.dump({
                "schema_version": 1, "site_id": "m87",
                "transport": {"kind": "ssh", "ssh_alias": "m87"},
                "scheduler": {"kind": "slurm"},
                "roots": {"run_root": "/old/runs"},
                "policy": {"default_partition": "fat"},
                "site_root": "/home/staticobserver/entity-compute",
            }, handle)

    def test_import_notes_converts_prose_and_structured_profile(self):
        code, payload = self.cli("site", "import-notes",
                                 "--notes-dir", self.notes)
        self.assertEqual(code, 0, payload)
        self.assertEqual(len(payload["imported"]), 1)
        entry = payload["imported"][0]
        self.assertEqual(entry["site_id"], "m87")
        self.assertTrue(entry["created"])
        record = load_site_yaml(site_yaml_path(self.workspace, "m87"))
        self.assertEqual(record["notes"], "# machine: m87\n\nprose text, not parsed.")
        self.assertEqual(record["transport"], {"kind": "ssh", "alias": "m87"})
        self.assertEqual(record["scheduler"], {"kind": "slurm"})
        self.assertEqual(record["policy"], {"default_partition": "fat"})
        self.assertEqual(record["site_root"],
                         "/home/staticobserver/entity-compute")
        # re-import is deterministic (idempotent content)
        code, again = self.cli("site", "import-notes",
                               "--notes-dir", self.notes)
        self.assertEqual(code, 0, again)
        self.assertFalse(again["imported"][0]["created"])
        record2 = load_site_yaml(site_yaml_path(self.workspace, "m87"))
        self.assertEqual(record, record2)
        # a single site can be imported explicitly
        code, one = self.cli("site", "import-notes", "--site", "m87",
                             "--notes-dir", self.notes)
        self.assertEqual(code, 0, one)
        self.assertEqual(len(one["imported"]), 1)
        code, missing = self.cli("site", "import-notes", "--site", "ghost",
                                 "--notes-dir", self.notes)
        self.assertEqual(code, 2)
        self.assertIn("no site notes", missing["error"])
        code, invalid = self.cli("site", "import-notes", "--site", "bad/name",
                                 "--notes-dir", self.notes)
        self.assertEqual(code, 2)
        self.assertIn("invalid site_id", invalid["error"])


class SiteTreeDerivationTest(SiteTestBase):
    def setUp(self):
        super(SiteTreeDerivationTest, self).setUp()
        self.project_root = os.path.join(self.workspace, "projects", "demo")
        os.makedirs(self.project_root)
        with open(os.path.join(self.project_root, "input.toml"), "w") as handle:
            handle.write("[simulation]\nsteps = 2\n")
        self.site_root = os.path.join(self.temp, "compute")
        self.store.upsert_site({
            "schema_version": 1, "site_id": "new-site",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "site_root": self.site_root, "roots": {}, "policy": {}})
        self.legacy_roots = {
            "source_root": self.temp,
            "build_root": os.path.join(self.temp, "b"),
            "run_root": os.path.join(self.temp, "r"),
            "staging_root": os.path.join(self.temp, "s"),
        }
        self.store.upsert_site({
            "schema_version": 1, "site_id": "old-site",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "roots": self.legacy_roots, "policy": {}})
        self.store.upsert_project("project-1", "demo", self.project_root)
        self.store.upsert_case(
            "case-1", "alpha", self.project_root,
            {"authority": {"site_id": "old-site", "path": self.project_root},
             "transfer_policy": "snapshot",
             "revision": {"kind": "path", "root": self.project_root}},
            {"source_id": "", "build_id": "", "run_id": "",
             "active_run": None, "data_id": "", "analysis_id": ""},
            project_uid="project-1")
        self.case = self.store.get_case("case-1")

    def _executable(self, build_root):
        os.makedirs(build_root)
        path = os.path.join(build_root, "entity.xc")
        with open(path, "w") as handle:
            handle.write("binary\n")
        os.chmod(path, 0o755)
        return path

    def test_execution_roots_two_layouts(self):
        new_profile = self.store.get_site("new-site")
        roots, layout = execution_roots(self.store, new_profile, self.case)
        self.assertEqual(layout, "site-tree")
        base = os.path.join(self.site_root, "projects", "demo")
        self.assertEqual(roots["run_root"], os.path.join(base, "runs"))
        self.assertEqual(roots["staging_root"], os.path.join(base, "staging"))
        self.assertEqual(roots["build_root"], os.path.join(base, "builds"))
        old_profile = self.store.get_site("old-site")
        roots, layout = execution_roots(self.store, old_profile, self.case)
        self.assertEqual(layout, "legacy-roots")
        self.assertEqual(roots["run_root"], self.legacy_roots["run_root"])

    def test_render_run_lands_on_site_tree(self):
        build_root = os.path.join(self.site_root, "projects", "demo", "builds")
        executable = self._executable(build_root)
        code, payload = self.cli(
            "render-run", "--project-root", self.project_root,
            "--toml", "input.toml", "--site", "new-site",
            "--executable", executable)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["layout"], "site-tree")
        run_root = payload["run_root"]
        prefix = os.path.join(self.site_root, "projects", "demo",
                              "runs", "alpha")
        self.assertTrue(run_root.startswith(prefix + os.sep), run_root)

    def test_render_run_legacy_layout_is_annotated(self):
        executable = self._executable(self.legacy_roots["build_root"])
        code, payload = self.cli(
            "render-run", "--project-root", self.project_root,
            "--toml", "input.toml", "--site", "old-site",
            "--executable", executable)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["layout"], "legacy-roots")
        prefix = os.path.join(self.legacy_roots["run_root"], "case-1")
        self.assertTrue(payload["run_root"].startswith(prefix + os.sep),
                        payload["run_root"])


if __name__ == "__main__":
    unittest.main()
