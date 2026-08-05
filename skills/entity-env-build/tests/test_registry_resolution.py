#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


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


def base_requirements(tmp: Path) -> dict:
    source = tmp / "entity"
    build = tmp / "build"
    deps = tmp / "deps"
    artifacts = tmp / "artifacts"
    for path in (source, build, deps, artifacts):
        path.mkdir(parents=True, exist_ok=True)
    return {
        "schema_version": 2,
        "entity": {
            "site_id": "cluster-a",
            "source_checkout": str(source),
            "source_revision": {"kind": "git", "commit": "abc", "tree": "def"},
            "build_root": str(build),
            "deps_root": str(deps),
            "artifacts_root": str(artifacts),
            "version_bucket": "1.4.3",
            "dependency_profile": "modern",
        },
        "environment": {
            "backend": "cpu",
            "output": True,
            "mpi": False,
            "dependency_policy": "reuse-existing",
        },
        "compile": {
            "pgen": "smoke",
            "cxx_standard": "20",
        },
    }


def registry_json(signature_overrides=None, status="verified") -> dict:
    signature = {
        "backend": "cpu", "mpi": False, "gpu_aware_mpi": False,
        "output": True, "cxx_standard": "20", "dependency_profile": "modern",
    }
    signature.update(signature_overrides or {})
    return {
        "site_id": "cluster-a",
        "stacks": [
            {
                "stack_id": "gcc12.3.0-kokkos5.1.0-1a2b3c4d",
                "status": status,
                "signature": signature,
                "packages": [
                    {"name": "kokkos", "version": "5.1.0",
                     "prefix": "/site/deps/stack/kokkos", "provider": "module"},
                    {"name": "hdf5", "version": "1.14.5",
                     "prefix": "/site/deps/stack/hdf5", "provider": "system"},
                ],
                "recipe": {"providers": {"kokkos": "module"}},
                "env_sh": "/site/deps/stack/env.sh",
            }
        ],
    }


class SignatureVectorsTests(unittest.TestCase):
    """env-build side of the shared signature contract; the same vectors
    are consumed by tests/test_ledger_site_deps.py (ledger side)."""

    def test_shared_vectors(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from entity_checkpoint import registry_signature
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        vectors = json.loads(
            (REPO / "tests" / "vectors" / "stack-signature.json").read_text(
                encoding="utf-8"))["vectors"]
        for vector in vectors:
            self.assertEqual(registry_signature(vector["requirements"]),
                             vector["expected"], vector["name"])


class RegistryResolutionTests(unittest.TestCase):
    def write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def create(self, tmp: Path, req: dict, registry: dict) -> Path:
        req_path = tmp / "requirements.json"
        registry_path = tmp / "registry.json"
        checkpoint = tmp / "entity-deps.local.json"
        self.write_json(req_path, req)
        self.write_json(registry_path, registry)
        proc = run_cmd(
            "scripts/entity_checkpoint.py", "create", str(req_path),
            "--from-registry", str(registry_path),
            "--output", str(checkpoint),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return checkpoint

    def test_verified_matching_stack_prefills_selected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            checkpoint = self.create(tmp, base_requirements(tmp), registry_json())
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(data["stack_id"], "gcc12.3.0-kokkos5.1.0-1a2b3c4d")
            kokkos = data["selected"]["kokkos"]
            # the original provider is a fact and is preserved; the origin
            # is carried by validation.source
            self.assertEqual(kokkos["provider"], "module")
            self.assertEqual(kokkos["version"], "5.1.0")
            self.assertEqual(kokkos["prefix"], "/site/deps/stack/kokkos")
            self.assertEqual(kokkos["validation"]["source"], "site-registry")
            self.assertEqual(data["selected"]["hdf5"]["version"], "1.14.5")
            self.assertTrue(any("site registry stack" in note
                                for note in data["status"]["reuse_notes"]))

    def test_signature_mismatch_falls_back_to_probe(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            checkpoint = self.create(
                tmp, base_requirements(tmp),
                registry_json(signature_overrides={"mpi": True}))
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertNotIn("stack_id", data)
            self.assertEqual(data["selected"], {})

    def test_unverified_stack_never_matches(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            checkpoint = self.create(
                tmp, base_requirements(tmp), registry_json(status="suspect"))
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertNotIn("stack_id", data)
            self.assertEqual(data["selected"], {})

    def test_probe_candidates_fill_registry_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = base_requirements(tmp)
            req_path = tmp / "requirements.json"
            registry_path = tmp / "registry.json"
            discovery_path = tmp / "discovery.json"
            checkpoint = tmp / "entity-deps.local.json"
            self.write_json(req_path, req)
            # the registry stack only carries kokkos this time
            registry = registry_json()
            registry["stacks"][0]["packages"] = [
                package for package in registry["stacks"][0]["packages"]
                if package["name"] == "kokkos"
            ]
            self.write_json(registry_path, registry)
            self.write_json(discovery_path, {
                "adios2": {"name": "adios2", "version": "2.11.0",
                           "prefix": "/probed/adios2", "provider": "system"},
                "kokkos": {"name": "kokkos", "version": "9.9.9",
                           "prefix": "/probed/kokkos", "provider": "system"},
            })
            proc = run_cmd(
                "scripts/entity_checkpoint.py", "create", str(req_path),
                "--from-registry", str(registry_path),
                "--from-discovery", str(discovery_path),
                "--output", str(checkpoint),
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            # registry wins per dependency; the probe only fills the gaps
            self.assertEqual(data["selected"]["kokkos"]["version"], "5.1.0")
            self.assertEqual(data["selected"]["kokkos"]["provider"], "module")
            self.assertEqual(data["selected"]["adios2"]["prefix"], "/probed/adios2")
            # gap-filling changed selected beyond the stack's packages, so
            # the stack_id reference is downgraded to a note
            self.assertNotIn("stack_id", data)
            self.assertTrue(any("stack_id unset" in note
                                for note in data["status"]["reuse_notes"]))

    def test_handwritten_archive_with_int_scalars_still_matches(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # a hand-maintained archive may carry e.g. an integer
            # cxx_standard; normalization must still hit the stack
            registry = registry_json()
            registry["stacks"][0]["signature"]["cxx_standard"] = 20
            checkpoint = self.create(tmp, base_requirements(tmp), registry)
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(data["stack_id"],
                             "gcc12.3.0-kokkos5.1.0-1a2b3c4d")

    def test_record_install_invalidates_stack_id(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            checkpoint = self.create(tmp, base_requirements(tmp),
                                     registry_json())
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertIn("stack_id", data)
            prefix = tmp / "new-dep"
            prefix.mkdir()
            proc = run_cmd(
                "scripts/entity_checkpoint.py", "record-install",
                "--checkpoint", str(checkpoint),
                "--dep", "mpi", "--provider", "module",
                "--prefix", str(prefix),
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertNotIn("stack_id", data)
            self.assertTrue(any("record-install" in note
                                for note in data["status"]["reuse_notes"]))


if __name__ == "__main__":
    unittest.main()
