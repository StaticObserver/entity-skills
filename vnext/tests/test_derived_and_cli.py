from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from entity.analysis import record_analysis
from entity.check import check_workspace
from entity.migrate import migrate_legacy
from entity.objects import add_run
from entity.records import load_json, write_json

from .support import Fixture


class DerivedAndCliTest(unittest.TestCase):
    def add_run(self, fixture: Fixture, run_id: str) -> None:
        toml = fixture.root / f"{run_id}.toml"
        toml.write_text(f"name = \"{run_id}\"\n", encoding="utf-8")
        add_run(fixture.workspace, "project-a", run_id, "build-a", toml)

    def add_script(self, fixture: Fixture) -> Path:
        script = fixture.workspace.require_project("project-a") / "scripts" / "analyze.py"
        script.write_text("print('analysis')\n", encoding="utf-8")
        return script

    def test_single_run_analysis_lives_under_run(self) -> None:
        fixture = Fixture()
        try:
            self.add_run(fixture, "run-a")
            self.add_script(fixture)
            record_analysis(
                fixture.workspace,
                "project-a",
                "analysis-a",
                ["run-a"],
                "scripts/analyze.py",
                {"time": 1},
                "outputs",
            )
            path = fixture.workspace.run_dir("project-a", "build-a", "run-a") / "analysis/analysis-a/analysis.json"
            self.assertTrue(path.is_file())
        finally:
            fixture.close()

    def test_multi_run_analysis_lives_under_project(self) -> None:
        fixture = Fixture()
        try:
            self.add_run(fixture, "run-a")
            self.add_run(fixture, "run-b")
            self.add_script(fixture)
            record = record_analysis(
                fixture.workspace,
                "project-a",
                "joint-a",
                ["run-a", "run-b"],
                "scripts/analyze.py",
                {},
                "outputs",
            )
            path = fixture.workspace.require_project("project-a") / "analysis/joint-a/analysis.json"
            self.assertEqual(load_json(path)["runs"], ["run-a", "run-b"])
            self.assertEqual(record["script"], "scripts/analyze.py")
        finally:
            fixture.close()

    def test_analysis_rejects_script_outside_project_library(self) -> None:
        fixture = Fixture()
        try:
            self.add_run(fixture, "run-a")
            outside = fixture.root / "outside.py"
            outside.write_text("pass\n", encoding="utf-8")
            with self.assertRaises(Exception):
                record_analysis(
                    fixture.workspace, "project-a", "analysis-a", ["run-a"], str(outside), {}, "outputs"
                )
        finally:
            fixture.close()

    def test_check_passes_valid_workspace(self) -> None:
        fixture = Fixture()
        try:
            result = check_workspace(fixture.workspace)
            self.assertTrue(result["ok"], result["issues"])
        finally:
            fixture.close()

    def test_check_reports_dangling_build_source(self) -> None:
        fixture = Fixture()
        try:
            path = fixture.workspace.build_dir("project-a", "build-a") / "build.json"
            build = load_json(path)
            build["source"] = "missing-source"
            write_json(path, build)
            result = check_workspace(fixture.workspace)
            self.assertFalse(result["ok"])
            self.assertIn("dangling_source", {item["code"] for item in result["issues"]})
        finally:
            fixture.close()

    def test_check_reports_dangling_analysis_run(self) -> None:
        fixture = Fixture()
        try:
            self.add_run(fixture, "run-a")
            self.add_script(fixture)
            record_analysis(
                fixture.workspace,
                "project-a",
                "analysis-a",
                ["run-a"],
                "scripts/analyze.py",
                {},
                "outputs",
            )
            path = fixture.workspace.run_dir("project-a", "build-a", "run-a") / "analysis/analysis-a/analysis.json"
            record = load_json(path)
            record["runs"] = ["missing-run"]
            write_json(path, record)
            result = check_workspace(fixture.workspace)
            self.assertIn("dangling_analysis_run", {item["code"] for item in result["issues"]})
        finally:
            fixture.close()

    def test_check_does_not_modify_workspace(self) -> None:
        fixture = Fixture()
        try:
            before = sorted(str(path.relative_to(fixture.workspace.root)) for path in fixture.workspace.root.rglob("*"))
            check_workspace(fixture.workspace)
            after = sorted(str(path.relative_to(fixture.workspace.root)) for path in fixture.workspace.root.rglob("*"))
            self.assertEqual(before, after)
        finally:
            fixture.close()

    def test_legacy_migration_retains_case_only_in_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="entity-migrate-test-") as temp:
            root = Path(temp)
            export = root / "export.json"
            export.write_text(
                json.dumps(
                    {
                        "projects": [{"project_uid": "p1", "slug": "project-a"}],
                        "cases": [
                            {
                                "project_uid": "p1",
                                "case_id": "old-case",
                                "identities": {
                                    "source": {
                                        "items": [
                                            {
                                                "source_id": "source-a",
                                                "repository": "https://example.test/entity.git",
                                                "git_commit": "abc123",
                                            }
                                        ]
                                    }
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = migrate_legacy(export, root / "new-workspace")
            self.assertEqual(report["imported"]["sources"], 1)
            self.assertIn("case", {item["kind"] for item in report["conflicts"]})
            self.assertFalse((root / "new-workspace" / "projects/project-a/cases").exists())

    def test_migration_refuses_nonempty_destination(self) -> None:
        with tempfile.TemporaryDirectory(prefix="entity-migrate-test-") as temp:
            root = Path(temp)
            export = root / "export.json"
            export.write_text('{"projects": [], "cases": []}', encoding="utf-8")
            destination = root / "destination"
            destination.mkdir()
            (destination / "keep").write_text("keep", encoding="utf-8")
            with self.assertRaises(Exception):
                migrate_legacy(export, destination)

    def test_cli_four_object_journey(self) -> None:
        fixture = Fixture()
        try:
            cli = Path(__file__).resolve().parents[1] / "bin" / "entity"
            environment = dict(os.environ)
            environment["ENTITY_WORKSPACE"] = str(fixture.workspace.root)
            command = [str(cli), "project", "show", "--project", "project-a"]
            result = subprocess.run(command, text=True, capture_output=True, env=environment, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["sources"], 1)
            self.assertEqual(payload["pgens"], 1)
            self.assertEqual(payload["builds"], 1)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
