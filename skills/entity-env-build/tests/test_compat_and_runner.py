"""Regression tests for entity_compat.py / entity_run.py / entity_checkpoint.py.

Covers:
- override downgrade must remove only the overridden check's issues
- snapshot manifest I/O errors must produce structured failures
- run_id validation and runner-crash exit-code mapping
- pgen/pgens mutual exclusion with empty-string pgen
- version family prefix boundary matching
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_cmd(*args, env=None):
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env=proc_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def base_requirements(tmp: Path) -> dict:
    checkout = tmp / "entity"
    checkout.mkdir(exist_ok=True)
    return {
        "schema_version": 1,
        "entity": {
            "checkout_root": str(checkout),
            "workdir": str(tmp),
            "version_bucket": "1.4.0",
            "dependency_profile": "modern",
        },
        "environment": {
            "backend": "cpu",
            "output": False,
            "mpi": False,
            "dependency_policy": "reuse-existing",
        },
        "compile": {
            "pgen": "smoke",
            "cxx_standard": "20",
        },
    }


def create_confirmed_checkpoint(tmp: Path, req: dict) -> Path:
    req_path = tmp / "requirements.json"
    checkpoint_path = tmp / "entity-deps.local.json"
    write_json(req_path, req)
    created = run_cmd(
        "scripts/entity_checkpoint.py", "create", str(req_path),
        "--output", str(checkpoint_path),
    )
    assert created.returncode == 0, created.stdout + created.stderr
    confirmed = run_cmd(
        "scripts/entity_checkpoint.py", "confirm", str(req_path),
        "--checkpoint", str(checkpoint_path), "--by", "test",
    )
    assert confirmed.returncode == 0, confirmed.stdout + confirmed.stderr
    return checkpoint_path


def run_compat(tmp: Path, checkpoint_path: Path):
    return run_cmd(
        "scripts/entity_compat.py",
        str(tmp / "requirements.json"),
        "--checkpoint",
        str(checkpoint_path),
        "--no-update-json",
    )


class OverridePreciseRemovalTests(unittest.TestCase):
    def test_nvcc_override_keeps_unrelated_nvcc_issues(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = base_requirements(tmp)
            req["entity"]["version_bucket"] = "1.4.3"
            req["environment"]["backend"] = "cuda"
            req["environment"]["gpu_arch"] = "AMPERE80"
            checkpoint_path = create_confirmed_checkpoint(tmp, req)

            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["selected"] = {
                # Not nvcc_wrapper: backend.cuda.compiler must keep failing.
                "compiler": {"cxx": sys.executable},
                "kokkos": {"prefix": str(tmp), "version": "5.0.0"},
                "adios2": {
                    "prefix": str(tmp),
                    "version": "2.11.0",
                    "compile_config": {"ADIOS2_USE_Kokkos": True},
                },
                # NVCC 11.0 < required 12.2: compiler.version.nvcc fails,
                # but the user override downgrades exactly that check.
                "gpu_toolkit": {"version": "11.0", "prefix": str(tmp)},
            }
            checkpoint["decisions"]["nvcc_version_override"] = True
            write_json(checkpoint_path, checkpoint)

            proc = run_compat(tmp, checkpoint_path)

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            compat = json.loads(proc.stdout)
            by_id = {check["id"]: check["status"] for check in compat["checks"]}
            self.assertEqual(by_id.get("compiler.version.nvcc"), "warn")
            self.assertEqual(by_id.get("backend.cuda.compiler"), "fail")
            self.assertTrue(
                any("nvcc_wrapper" in issue for issue in compat["issues"]),
                compat["issues"],
            )
            self.assertFalse(
                any("below minimum" in issue and "NVCC" in issue for issue in compat["issues"]),
                compat["issues"],
            )


class SnapshotManifestTests(unittest.TestCase):
    def test_corrupt_snapshot_manifest_yields_structured_fail(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import entity_compat
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            checkout = tmp / "checkout"
            checkout.mkdir()
            (checkout / "snapshot-manifest.json").write_text("{not valid json", encoding="utf-8")
            req = {
                "schema_version": 2,
                "entity": {
                    "source_checkout": str(checkout),
                    "source_revision": {"kind": "snapshot", "snapshot_id": "abc"},
                },
            }
            checks, issues = [], []

            entity_compat.check_source_revision(req, checks, issues)

            by_id = {check["id"]: check for check in checks}
            self.assertEqual(by_id["source.revision"]["status"], "fail")
            self.assertTrue(issues)


class RunnerTests(unittest.TestCase):
    def make_run_fixture(self, tmp: Path, script_body: str):
        req = base_requirements(tmp)
        req["artifacts"] = {"logs_dir": str(tmp / "logs")}
        req_path = tmp / "requirements.json"
        script = tmp / "entity-build.sh"
        write_json(req_path, req)
        script.write_text(script_body, encoding="utf-8")
        script.chmod(0o755)
        return req_path, script

    def test_invalid_run_id_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req_path, script = self.make_run_fixture(tmp, "#!/usr/bin/env bash\nexit 0\n")

            proc = run_cmd(
                "scripts/entity_run.py",
                "build",
                str(req_path),
                "--script",
                str(script),
                "--run-id",
                "bad id;evil",
                "--quiet",
                env={"HOME": str(tmp / "home")},
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "logs" / "entity-run-bad id;evil.log").exists())

    def test_runner_crash_maps_to_fixed_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req_path, script = self.make_run_fixture(tmp, "#!/usr/bin/env bash\nexit 0\n")
            # Force run_log.open("w") to fail: a directory occupies the log path.
            (tmp / "logs").mkdir()
            (tmp / "logs" / "entity-run-crashrun.log").mkdir()

            proc = run_cmd(
                "scripts/entity_run.py",
                "build",
                str(req_path),
                "--script",
                str(script),
                "--run-id",
                "crashrun",
                "--quiet",
                env={"HOME": str(tmp / "home")},
            )

            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            data = json.loads(req_path.read_text(encoding="utf-8"))
            self.assertEqual(data["build_result"]["status"], "fail")
            self.assertEqual(data["build_result"]["exit_code"], -1)


class PgenMutexTests(unittest.TestCase):
    def test_empty_pgen_string_does_not_conflict_with_pgens(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = base_requirements(tmp)
            req["compile"]["pgen"] = ""
            req["compile"]["pgens"] = ["x"]
            req_path = tmp / "requirements.json"
            write_json(req_path, req)

            proc = run_cmd("scripts/entity_checkpoint.py", "validate", str(req_path))

            result = json.loads(proc.stdout)
            rules = [issue["rule"] for issue in result["consistency_issues"]]
            self.assertNotIn("pgen.mutex", rules, result)


class VersionFamilyBoundaryTests(unittest.TestCase):
    def check_kokkos_version(self, tmp: Path, version: str) -> dict:
        req = base_requirements(tmp)
        checkpoint_path = create_confirmed_checkpoint(tmp, req)
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["selected"] = {
            "compiler": {"cxx": sys.executable},
            "kokkos": {"prefix": str(tmp), "version": version},
            "adios2": {
                "prefix": str(tmp),
                "version": "2.11.0",
                "compile_config": {"ADIOS2_USE_Kokkos": True},
            },
        }
        write_json(checkpoint_path, checkpoint)
        proc = run_compat(tmp, checkpoint_path)
        compat = json.loads(proc.stdout)
        return {check["id"]: check["status"] for check in compat["checks"]}

    def test_version_family_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "a").mkdir()
            by_id = self.check_kokkos_version(tmp / "a", "5")
            self.assertEqual(by_id.get("profile.kokkos_version"), "pass")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "b").mkdir()
            by_id = self.check_kokkos_version(tmp / "b", "55.0.0")
            self.assertEqual(by_id.get("profile.kokkos_version"), "fail")


if __name__ == "__main__":
    unittest.main()
