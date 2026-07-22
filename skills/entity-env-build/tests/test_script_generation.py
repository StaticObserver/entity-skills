"""Regression tests for entity_generate.py security and path handling.

Covers:
- command injection / path traversal via environment.dependency_versions
- gpu_arch token validation
- extra_env variable-name validation
- ENTITY_DEPS_ROOT derivation in env.sh
- cmake_cxx_flags quoting
- unknown Kokkos arch handling
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


class GenerationSecurityTests(unittest.TestCase):
    def write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def base_requirements(self, tmp: Path) -> dict:
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

    def run_deps(self, tmp: Path, req: dict, checkpoint: dict = None, *extra: str):
        req_path = tmp / "requirements.json"
        checkpoint_path = tmp / "entity-deps.local.json"
        self.write_json(req_path, req)
        self.write_json(checkpoint_path, checkpoint or {"schema_version": 1, "selected": {}})
        return run_cmd(
            "scripts/entity_generate.py",
            "deps",
            str(req_path),
            "--checkpoint",
            str(checkpoint_path),
            "--output-dir",
            str(tmp / "scripts"),
            "--no-update-json",
            *extra,
        )

    def test_dependency_version_command_injection_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            probe = "/tmp/eeb_inject_probe"
            req = self.base_requirements(tmp)
            req["environment"]["dependency_versions"] = {"kokkos": f"$(touch {probe})"}

            proc = self.run_deps(tmp, req)

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "scripts" / "build-kokkos.sh").exists())
            self.assertFalse(Path(probe).exists())

    def test_dependency_version_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["environment"]["dependency_versions"] = {"kokkos": "../../escaped"}

            proc = self.run_deps(tmp, req)

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "scripts" / "build-kokkos.sh").exists())

    def test_gpu_arch_shell_metacharacters_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["environment"]["gpu_arch"] = "AMPERE80;$(touch /tmp/eeb_arch_probe)"

            proc = self.run_deps(tmp, req)

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "scripts" / "build-kokkos.sh").exists())

    def test_valid_dependency_version_still_generates(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["environment"]["dependency_versions"] = {"kokkos": "5.0.1"}

            proc = self.run_deps(tmp, req)

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            script = (tmp / "scripts" / "build-kokkos.sh").read_text(encoding="utf-8")
            self.assertIn('VERSION="${KOKKOS_VERSION:-5.0.1}"', script)


class EnvGenerationTests(unittest.TestCase):
    def write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def run_env(self, tmp: Path, checkpoint: dict):
        checkpoint_path = tmp / "entity-deps.local.json"
        self.write_json(checkpoint_path, checkpoint)
        return run_cmd(
            "scripts/entity_generate.py",
            "env",
            str(checkpoint_path),
            "--output",
            str(tmp / "env.sh"),
            "--no-update-json",
        )

    def read_deps_root(self, tmp: Path) -> str:
        for line in (tmp / "env.sh").read_text(encoding="utf-8").splitlines():
            if line.startswith("export ENTITY_DEPS_ROOT="):
                return line.split("=", 1)[1].strip("'\"")
        raise AssertionError("ENTITY_DEPS_ROOT not exported")

    def test_deps_root_single_dependency(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            deps = tmp / "deps"
            checkpoint = {
                "schema_version": 2,
                "compatibility": {"status": "pass"},
                "selected": {"kokkos": {"prefix": str(deps / "kokkos" / "5.0.1")}},
            }

            proc = self.run_env(tmp, checkpoint)

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.read_deps_root(tmp), str(deps))

    def test_deps_root_multiple_dependencies(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            deps = tmp / "deps"
            checkpoint = {
                "schema_version": 2,
                "compatibility": {"status": "pass"},
                "selected": {
                    "kokkos": {"prefix": str(deps / "kokkos" / "5.0.1")},
                    "hdf5": {"prefix": str(deps / "hdf5" / "1.14.6")},
                },
            }

            proc = self.run_env(tmp, checkpoint)

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.read_deps_root(tmp), str(deps))

    def test_deps_root_prefers_recorded_entity_deps_root(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            recorded = tmp / "recorded-root"
            checkpoint = {
                "schema_version": 2,
                "compatibility": {"status": "pass"},
                "entity": {"deps_root": str(recorded)},
                "selected": {"kokkos": {"prefix": str(tmp / "elsewhere" / "kokkos" / "5.0.1")}},
            }

            proc = self.run_env(tmp, checkpoint)

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self.read_deps_root(tmp), str(recorded))

    def test_extra_env_invalid_key_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            checkpoint = {
                "schema_version": 2,
                "compatibility": {"status": "pass"},
                "selected": {},
                "paths": {"extra_env": {"A=1; touch /tmp/eeb_env_probe": "x"}},
            }

            proc = self.run_env(tmp, checkpoint)

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "env.sh").exists())

    def test_extra_env_valid_key_still_exported(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            checkpoint = {
                "schema_version": 2,
                "compatibility": {"status": "pass"},
                "selected": {},
                "paths": {"extra_env": {"SITE_FLAG": "1"}},
            }

            proc = self.run_env(tmp, checkpoint)

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            script = (tmp / "env.sh").read_text(encoding="utf-8")
            self.assertIn("export SITE_FLAG=1", script)


class BuildScriptQuotingTests(unittest.TestCase):
    def write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_cmake_cxx_flags_not_double_escaped(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            checkout = tmp / "entity"
            checkout.mkdir()
            req = {
                "schema_version": 1,
                "entity": {
                    "checkout_root": str(checkout),
                    "workdir": str(tmp),
                    "version_bucket": "1.4.0",
                    "dependency_profile": "modern",
                },
                "environment": {"backend": "cpu", "output": False, "mpi": False},
                "compile": {
                    "pgen": "smoke",
                    "cxx_standard": "20",
                    "cmake_cxx_flags": "-O2 -Wall",
                },
            }
            req_path = tmp / "requirements.json"
            env_path = tmp / "env.sh"
            self.write_json(req_path, req)
            env_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            proc = run_cmd(
                "scripts/entity_generate.py",
                "build",
                str(req_path),
                "--env",
                str(env_path),
                "--output",
                str(tmp / "entity-build.sh"),
                "--no-update-json",
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            script = (tmp / "entity-build.sh").read_text(encoding="utf-8")
            self.assertIn("'-DCMAKE_CXX_FLAGS=-O2 -Wall'", script)
            self.assertNotIn("'\"'\"'", script)


class UnknownGpuArchTests(unittest.TestCase):
    def write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def run_adios2_deps(self, tmp: Path, cuda_arch: str):
        checkout = tmp / "entity"
        checkout.mkdir(exist_ok=True)
        req = {
            "schema_version": 1,
            "entity": {
                "checkout_root": str(checkout),
                "workdir": str(tmp),
                "version_bucket": "1.4.3",
                "dependency_profile": "modern",
            },
            "environment": {
                "backend": "cuda",
                "gpu_arch": "AMPERE80",
                "output": True,
                "mpi": False,
                "dependency_policy": "reuse-existing",
            },
            "compile": {"pgen": "smoke", "cxx_standard": "20"},
        }
        checkpoint = {
            "schema_version": 1,
            "selected": {
                "gpu_toolkit": {"prefix": "/opt/cuda"},
                "kokkos": {"cuda_arch": cuda_arch},
            },
        }
        req_path = tmp / "requirements.json"
        checkpoint_path = tmp / "entity-deps.local.json"
        self.write_json(req_path, req)
        self.write_json(checkpoint_path, checkpoint)
        return run_cmd(
            "scripts/entity_generate.py",
            "deps",
            str(req_path),
            "--checkpoint",
            str(checkpoint_path),
            "--deps",
            "adios2",
            "--output-dir",
            str(tmp / "scripts"),
            "--no-update-json",
        )

    def test_unknown_kokkos_arch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            proc = self.run_adios2_deps(tmp, "FOO99")

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "scripts" / "build-adios2.sh").exists())

    def test_known_kokkos_arch_maps_to_cuda_capability(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            proc = self.run_adios2_deps(tmp, "AMPERE80")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            script = (tmp / "scripts" / "build-adios2.sh").read_text(encoding="utf-8")
            self.assertIn("CMAKE_CUDA_ARCHITECTURES=80", script)


if __name__ == "__main__":
    unittest.main()
