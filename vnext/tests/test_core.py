from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from entity.errors import EntityError
from entity.objects import add_build, add_pgen, add_run, add_source, load_build, load_pgen, load_source
from entity.paths import Workspace, init_project
from entity.records import load_json, require_id, write_json
from entity.site import add_site, init_site, load_site

from .support import Fixture


class CoreTest(unittest.TestCase):
    def test_workspace_and_project_are_plain_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace.init(Path(temp) / "ws", "workspace-a")
            project = init_project(workspace, "project-a")
            self.assertTrue((workspace.root / "workspace.json").is_file())
            self.assertTrue((project / "project.json").is_file())
            self.assertFalse((workspace.root / ".ledger").exists())

    def test_workspace_discovery_from_environment(self) -> None:
        fixture = Fixture()
        try:
            with mock.patch.dict("os.environ", {"ENTITY_WORKSPACE": str(fixture.workspace.root)}):
                self.assertEqual(Workspace.discover().root, fixture.workspace.root)
        finally:
            fixture.close()

    def test_identifier_rejects_path_segments(self) -> None:
        with self.assertRaises(EntityError):
            require_id("../bad")

    def test_json_write_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "record.json"
            write_json(path, {"id": "a"})
            self.assertEqual(load_json(path), {"id": "a"})

    def test_invalid_json_is_reported_with_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "record.json"
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaisesRegex(EntityError, "line 1"):
                load_json(path)

    def test_source_records_git_commit(self) -> None:
        fixture = Fixture()
        try:
            source = load_source(fixture.workspace, "project-a", "source-a")
            self.assertEqual(source["git_commit"], fixture.commit)
        finally:
            fixture.close()

    def test_source_rejects_mutable_ref_without_checkout(self) -> None:
        fixture = Fixture()
        try:
            with self.assertRaises(EntityError) as raised:
                add_source(
                    fixture.workspace,
                    "project-a",
                    "source-b",
                    "https://example.test/entity.git",
                    "main",
                )
            self.assertEqual(raised.exception.code, "invalid_record")
        finally:
            fixture.close()

    def test_pgen_is_independent_from_source(self) -> None:
        fixture = Fixture()
        try:
            pgen = load_pgen(fixture.workspace, "project-a", "pgen-a")
            self.assertNotIn("source", pgen)
        finally:
            fixture.close()

    def test_pgen_cannot_be_replaced_in_place(self) -> None:
        fixture = Fixture()
        try:
            with self.assertRaises(EntityError):
                add_pgen(
                    fixture.workspace,
                    "project-a",
                    "pgen-a",
                    fixture.root / "pgen-source",
                    "pgen.hpp",
                )
        finally:
            fixture.close()

    def test_pgen_entry_must_be_inside_snapshot(self) -> None:
        fixture = Fixture()
        try:
            outside = fixture.root / "outside.hpp"
            outside.write_text("// outside\n", encoding="utf-8")
            with self.assertRaises(EntityError) as raised:
                add_pgen(
                    fixture.workspace,
                    "project-a",
                    "pgen-b",
                    fixture.root / "pgen-source",
                    str(outside),
                )
            self.assertEqual(raised.exception.code, "invalid_record")
            self.assertFalse(fixture.workspace.pgen_dir("project-a", "pgen-b").exists())
        finally:
            fixture.close()

    def test_build_records_source_and_pgen(self) -> None:
        fixture = Fixture()
        try:
            build = load_build(fixture.workspace, "project-a", "build-a")
            self.assertEqual((build["source"], build["pgen"]), ("source-a", "pgen-a"))
        finally:
            fixture.close()

    def test_same_pgen_can_be_used_by_another_build(self) -> None:
        fixture = Fixture()
        try:
            add_build(
                fixture.workspace,
                "project-a",
                "build-b",
                "source-a",
                "pgen-a",
                "site-a",
                "deps-a",
            )
            self.assertEqual(load_build(fixture.workspace, "project-a", "build-b")["pgen"], "pgen-a")
        finally:
            fixture.close()

    def test_same_pgen_can_build_against_two_source_commits(self) -> None:
        fixture = Fixture()
        try:
            (fixture.repo / "README").write_text("second version\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(fixture.repo), "add", "README"], check=True)
            subprocess.run(["git", "-C", str(fixture.repo), "commit", "-qm", "second"], check=True)
            second = subprocess.check_output(
                ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"], text=True
            ).strip()
            add_source(
                fixture.workspace,
                "project-a",
                "source-b",
                str(fixture.repo),
                second,
                fixture.repo,
            )
            add_build(
                fixture.workspace,
                "project-a",
                "build-b",
                "source-b",
                "pgen-a",
                "site-a",
                "deps-a",
            )
            build = load_build(fixture.workspace, "project-a", "build-b")
            self.assertEqual((build["source"], build["pgen"]), ("source-b", "pgen-a"))
        finally:
            fixture.close()

    def test_run_copies_toml_under_build(self) -> None:
        fixture = Fixture()
        try:
            toml = fixture.root / "input.toml"
            toml.write_text("[simulation]\nsteps = 10\n", encoding="utf-8")
            add_run(fixture.workspace, "project-a", "run-a", "build-a", toml)
            root = fixture.workspace.run_dir("project-a", "build-a", "run-a")
            self.assertEqual((root / "input.toml").read_text(), toml.read_text())
            self.assertEqual(load_json(root / "run.json")["build"], "build-a")
        finally:
            fixture.close()

    def test_site_credentials_are_not_required(self) -> None:
        fixture = Fixture()
        try:
            site = load_site(fixture.workspace, "site-a")
            self.assertNotIn("password", json.dumps(site).lower())
        finally:
            fixture.close()

    def test_site_init_explains_registration_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace.init(Path(temp) / "workspace", "workspace-a")
            with self.assertRaisesRegex(EntityError, "site add --config"):
                init_site(workspace, "missing-site")

    def test_site_init_does_not_overwrite_conflicting_site_record(self) -> None:
        fixture = Fixture()
        try:
            site_record = fixture.site_root / "site.json"
            changed = load_json(site_record)
            changed["manual_note"] = "keep"
            write_json(site_record, changed)
            with self.assertRaises(EntityError) as raised:
                init_site(fixture.workspace, "site-a")
            self.assertEqual(raised.exception.code, "site_config_conflict")
            self.assertEqual(load_json(site_record), changed)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
