from __future__ import annotations

import time
import unittest
from pathlib import Path

from entity.build import prepare_build, run_build, site_build_root
from entity.errors import EntityError
from entity.objects import add_run
from entity.run import attempt_status, data_summary, prepare_attempt, site_run_root, submit_attempt
from entity.site import SiteOps

from .support import Fixture


class BuildRunTest(unittest.TestCase):
    def make_run(self, fixture: Fixture, run_id: str = "run-a") -> None:
        toml = fixture.root / f"{run_id}.toml"
        toml.write_text("[simulation]\nsteps = 2\n", encoding="utf-8")
        add_run(
            fixture.workspace,
            "project-a",
            run_id,
            "build-a",
            toml,
            {"tasks": 4, "nodes": 1, "cpus_per_task": 2},
            {"OMP_NUM_THREADS": "2"},
        )

    def test_build_preparation_materializes_source_and_pgen(self) -> None:
        fixture = Fixture()
        try:
            prepared = prepare_build(fixture.workspace, "project-a", "build-a")
            root = Path(prepared["root"])
            self.assertTrue((root / "pgen" / "pgen.hpp").is_file())
            self.assertTrue((fixture.site_root / "checkouts" / "source-a" / ".git").exists())
            self.assertTrue((root / "scripts" / "build.sh").is_file())
        finally:
            fixture.close()

    def test_build_script_loads_site_and_deps_environments(self) -> None:
        fixture = Fixture()
        try:
            prepared = prepare_build(fixture.workspace, "project-a", "build-a")
            script = (Path(prepared["root"]) / "scripts" / "build.sh").read_text()
            self.assertIn("site-env.sh", script)
            self.assertIn("deps-a/env.sh", script)
        finally:
            fixture.close()

    def test_build_execution_writes_result_and_executable(self) -> None:
        fixture = Fixture()
        try:
            fixture.build()
            result = fixture.site_root / "projects/project-a/builds/build-a/build-result.json"
            self.assertEqual(__import__("json").loads(result.read_text())["status"], "completed")
            self.assertTrue((result.parent / "bin" / "entity").is_file())
        finally:
            fixture.close()

    def test_build_cannot_prepare_twice(self) -> None:
        fixture = Fixture()
        try:
            prepare_build(fixture.workspace, "project-a", "build-a")
            with self.assertRaises(EntityError):
                prepare_build(fixture.workspace, "project-a", "build-a")
        finally:
            fixture.close()

    def test_run_requires_completed_build(self) -> None:
        fixture = Fixture()
        try:
            self.make_run(fixture)
            with self.assertRaisesRegex(EntityError, "not completed"):
                prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
        finally:
            fixture.close()

    def test_direct_non_mpi_script_is_bare(self) -> None:
        fixture = Fixture()
        try:
            fixture.build()
            self.make_run(fixture)
            prepared = prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
            root = Path(prepared["root"])
            script = (root / "run.sh").read_text()
            self.assertNotIn("ENTITY_MPI_TASKS", script)
            self.assertFalse((root / "job.slurm").exists())
        finally:
            fixture.close()

    def test_direct_mpi_uses_site_launcher(self) -> None:
        fixture = Fixture(mpi=True)
        try:
            fixture.build()
            self.make_run(fixture)
            prepared = prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
            script = (Path(prepared["root"]) / "run.sh").read_text()
            self.assertIn("ENTITY_MPI_TASKS=4", script)
            self.assertNotIn("srun", script)
        finally:
            fixture.close()

    def test_slurm_non_mpi_generates_job_without_launcher(self) -> None:
        fixture = Fixture(scheduler="slurm")
        try:
            fixture.build()
            self.make_run(fixture)
            prepared = prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
            root = Path(prepared["root"])
            self.assertTrue((root / "job.slurm").is_file())
            self.assertNotIn("ENTITY_MPI_TASKS", (root / "run.sh").read_text())
            slurm = (root / "job.slurm").read_text()
            self.assertIn("#SBATCH --ntasks=4", slurm)
            self.assertIn("exec bash run.sh", slurm)
        finally:
            fixture.close()

    def test_slurm_mpi_uses_explicit_site_launcher(self) -> None:
        fixture = Fixture(scheduler="slurm", mpi=True)
        try:
            fixture.build()
            self.make_run(fixture)
            prepared = prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
            script = (Path(prepared["root"]) / "run.sh").read_text()
            self.assertIn("ENTITY_MPI_TASKS=4", script)
            self.assertNotIn("srun", script)
        finally:
            fixture.close()

    def test_slurm_submit_records_job_id_and_status(self) -> None:
        fixture = Fixture(scheduler="slurm")
        try:
            fixture.build()
            self.make_run(fixture)
            prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
            result = submit_attempt(fixture.workspace, "project-a", "run-a", "attempt-001")
            self.assertEqual(result["job_id"], "12345")
            status = attempt_status(fixture.workspace, "project-a", "run-a", "attempt-001")
            self.assertEqual(status["state"], "RUNNING")
        finally:
            fixture.close()

    def test_submit_is_idempotent_when_result_exists(self) -> None:
        fixture = Fixture(scheduler="slurm")
        try:
            fixture.build()
            self.make_run(fixture)
            prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
            first = submit_attempt(fixture.workspace, "project-a", "run-a", "attempt-001")
            fixture.sbatch.write_text("#!/usr/bin/env bash\nexit 9\n", encoding="utf-8")
            fixture.sbatch.chmod(0o755)
            second = submit_attempt(fixture.workspace, "project-a", "run-a", "attempt-001")
            self.assertEqual(first, second)
        finally:
            fixture.close()

    def test_unknown_slurm_result_is_recorded_before_retry(self) -> None:
        fixture = Fixture(scheduler="slurm")
        try:
            fixture.build()
            self.make_run(fixture)
            prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
            fixture.sbatch.write_text("#!/usr/bin/env bash\necho submitted-but-no-id\n", encoding="utf-8")
            fixture.sbatch.chmod(0o755)
            with self.assertRaisesRegex(EntityError, "cannot parse"):
                submit_attempt(fixture.workspace, "project-a", "run-a", "attempt-001")
            second = submit_attempt(fixture.workspace, "project-a", "run-a", "attempt-001")
            self.assertEqual(second["status"], "unknown")
        finally:
            fixture.close()

    def test_direct_submit_executes_and_data_is_bound_to_run(self) -> None:
        fixture = Fixture()
        try:
            fixture.build()
            self.make_run(fixture)
            prepared = prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
            submit_attempt(fixture.workspace, "project-a", "run-a", "attempt-001")
            status = {}
            for _ in range(50):
                status = attempt_status(fixture.workspace, "project-a", "run-a", "attempt-001")
                if status["state"] != "RUNNING":
                    break
                time.sleep(0.02)
            self.assertEqual(status["state"], "COMPLETED")
            summary = data_summary(fixture.workspace, "project-a", "run-a")
            self.assertGreaterEqual(summary["files"], 2)
            self.assertTrue(Path(summary["path"]).is_relative_to(Path(prepared["root"]).parents[1]))
        finally:
            fixture.close()

    def test_new_attempt_preserves_previous_attempt(self) -> None:
        fixture = Fixture()
        try:
            fixture.build()
            self.make_run(fixture)
            first = prepare_attempt(fixture.workspace, "project-a", "run-a", attempt_id="attempt-001")
            second = prepare_attempt(
                fixture.workspace,
                "project-a",
                "run-a",
                attempt_id="attempt-002",
                resource_override={"tasks": 2},
            )
            self.assertTrue(Path(first["root"]).exists())
            self.assertEqual(second["resources"]["tasks"], 2)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
