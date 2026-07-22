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


class HardGateTests(unittest.TestCase):
    def write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def base_requirements(self, tmp: Path) -> dict:
        checkout = tmp / "entity"
        checkout.mkdir()
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

    def load_parameter_card(self, req: dict) -> dict:
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from entity_schema import parameter_card
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        return parameter_card(req)

    def confirmed_parameters(self, req: dict) -> dict:
        card = self.load_parameter_card(req)
        return {
            "digest": card["digest"],
            "confirmed_by": "test",
            "confirmed_at": "2026-01-01T00:00:00+00:00",
            "defaults": False,
            "card": card,
        }

    def compat_checkpoint_fixture(self, tmp: Path, req: dict) -> dict:
        return {
            "schema_version": 1,
            "requirements": {"embedded": {
                "entity": {
                    "checkout_root": req["entity"]["checkout_root"],
                    "workdir": req["entity"]["workdir"],
                    "version_bucket": req["entity"]["version_bucket"],
                    "dependency_profile": req["entity"]["dependency_profile"],
                },
                "environment": {
                    "backend": "cpu",
                    "output": False,
                    "mpi": False,
                    "gpu_aware_mpi": False,
                },
                "compile": {
                    "pgen": "smoke",
                    "pgens": "",
                    "cxx_standard": "20",
                    "precision": "",
                    "deposit": "",
                    "shape_order": "",
                    "debug": False,
                    "tests": False,
                    "build_intent": "",
                },
            }},
            "entity": {
                "checkout_root": req["entity"]["checkout_root"],
                "workdir": req["entity"]["workdir"],
                "version_bucket": req["entity"]["version_bucket"],
                "dependency_profile": req["entity"]["dependency_profile"],
            },
            "selected": {
                "compiler": {"cxx": sys.executable},
                "kokkos": {"prefix": str(tmp), "version": "5.0.0"},
                "adios2": {
                    "prefix": str(tmp),
                    "version": "2.11.0",
                    "compile_config": {"ADIOS2_USE_Kokkos": True},
                },
            },
            "decisions": {"parameters": self.confirmed_parameters(req)},
            "compatibility": {"status": "unknown"},
            "env_sh": {"status": "missing"},
        }

    def test_v2_uses_independent_site_paths_without_workdir(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            source = tmp / "source-checkout"
            build = tmp / "scratch" / "case" / "build-id"
            deps = tmp / "shared-deps"
            artifacts = tmp / "records" / "build-id"
            for path in [source, build, deps, artifacts]:
                path.mkdir(parents=True)
            req = self.base_requirements(tmp)
            req["schema_version"] = 2
            req["entity"] = {
                "site_id": "cluster-a",
                "source_checkout": str(source),
                "source_revision": {"kind": "git", "commit": "test", "tree": "test"},
                "build_root": str(build),
                "deps_root": str(deps),
                "artifacts_root": str(artifacts),
                "version_bucket": "1.4.0",
                "dependency_profile": "modern",
            }
            req_path = tmp / "requirements-v2.json"
            checkpoint = artifacts / "entity-deps.local.json"
            self.write_json(req_path, req)

            validated = run_cmd("scripts/entity_checkpoint.py", "validate", str(req_path))
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
            created = run_cmd(
                "scripts/entity_checkpoint.py", "create", str(req_path),
                "--output", str(checkpoint),
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 2)
            self.assertEqual(data["entity"]["site_id"], "cluster-a")
            self.assertEqual(data["entity"]["source_checkout"], str(source))
            self.assertEqual(data["entity"]["build_root"], str(build))
            self.assertEqual(data["entity"]["deps_root"], str(deps))
            self.assertEqual(data["env_sh"]["path"], str(artifacts / "env.sh"))

    def test_validate_blocks_partial_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["compile"]["pgens"] = ["other"]
            req_path = tmp / "requirements.json"
            self.write_json(req_path, req)

            proc = run_cmd("scripts/entity_checkpoint.py", "validate", str(req_path))

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn('"status": "partial"', proc.stdout)

    def test_validate_allow_partial_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["compile"]["pgens"] = ["other"]
            req_path = tmp / "requirements.json"
            self.write_json(req_path, req)

            proc = run_cmd(
                "scripts/entity_checkpoint.py",
                "validate",
                str(req_path),
                "--allow-partial",
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn('"status": "partial"', proc.stdout)

    def test_validate_rejects_unsupported_entity_versions_and_profiles(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cases = [
                ("1.3.3", "modern", "20", "minimum supported version is 1.4.0"),
                ("1.4.0", "legacy", "20", "only modern is supported"),
                ("1.4.0", "modern", "17", "Entity >=1.4.0 requires 20"),
            ]
            for index, (version, profile, cxx_standard, message) in enumerate(cases):
                with self.subTest(version=version, profile=profile, cxx_standard=cxx_standard):
                    case_dir = tmp / str(index)
                    case_dir.mkdir()
                    req = self.base_requirements(case_dir)
                    req["entity"]["version_bucket"] = version
                    req["entity"]["dependency_profile"] = profile
                    req["compile"]["cxx_standard"] = cxx_standard
                    req_path = case_dir / "requirements.json"
                    self.write_json(req_path, req)

                    proc = run_cmd("scripts/entity_checkpoint.py", "validate", str(req_path))

                    self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                    self.assertIn('"status": "fail"', proc.stdout)
                    self.assertIn(message, proc.stdout)

    def test_create_rejects_entity_1_3(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["entity"]["version_bucket"] = "1.3.3"
            req_path = tmp / "requirements.json"
            self.write_json(req_path, req)

            proc = run_cmd(
                "scripts/entity_checkpoint.py",
                "create",
                str(req_path),
                "--output",
                str(tmp / "entity-deps.local.json"),
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "entity-deps.local.json").exists())
            self.assertIn("minimum supported version is 1.4.0", proc.stderr)

    def test_validate_rejects_cuda_before_entity_1_4_3(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["entity"]["version_bucket"] = "1.4.2"
            req["environment"]["backend"] = "cuda"
            req["environment"]["gpu_arch"] = "AMPERE80"
            req_path = tmp / "requirements.json"
            self.write_json(req_path, req)

            proc = run_cmd("scripts/entity_checkpoint.py", "validate", str(req_path))

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn('"status": "fail"', proc.stdout)
            self.assertIn("CUDA requires Entity >=1.4.3", proc.stdout)

    def test_build_and_runner_reject_entity_1_3(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["entity"]["version_bucket"] = "1.3.3"
            req_path = tmp / "requirements.json"
            env_path = tmp / "env.sh"
            script_path = tmp / "entity-build.sh"
            self.write_json(req_path, req)
            env_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            script_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            script_path.chmod(0o755)

            generate_proc = run_cmd(
                "scripts/entity_generate.py",
                "build",
                str(req_path),
                "--env",
                str(env_path),
                "--output",
                str(tmp / "generated-build.sh"),
            )
            run_proc = run_cmd(
                "scripts/entity_run.py",
                "build",
                str(req_path),
                "--script",
                str(script_path),
                "--quiet",
                env={"HOME": str(tmp / "home")},
            )

            self.assertNotEqual(generate_proc.returncode, 0)
            self.assertNotEqual(run_proc.returncode, 0)
            self.assertIn("minimum supported version is 1.4.0", generate_proc.stderr)
            self.assertIn("minimum supported version is 1.4.0", run_proc.stderr)

    def test_env_blocks_warn_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(
                deps_path,
                {
                    "schema_version": 1,
                    "compatibility": {"status": "warn"},
                    "selected": {},
                    "env_sh": {"path": str(tmp / "env.sh")},
                },
            )

            proc = run_cmd(
                "scripts/entity_generate.py",
                "env",
                str(deps_path),
                "--output",
                str(tmp / "env.sh"),
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "env.sh").exists())
            self.assertIn("must be pass", proc.stderr)

    def test_env_allows_warn_only_with_recorded_decision(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(
                deps_path,
                {
                    "schema_version": 1,
                    "compatibility": {"status": "warn"},
                    "decisions": {
                        "compatibility_warnings_accepted": {
                            "value": True,
                            "source": "user",
                            "reason": "fixture",
                        }
                    },
                    "selected": {},
                    "env_sh": {"path": str(tmp / "env.sh")},
                },
            )

            proc = run_cmd(
                "scripts/entity_generate.py",
                "env",
                str(deps_path),
                "--output",
                str(tmp / "env.sh"),
                "--allow-warnings",
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue((tmp / "env.sh").exists())

    def test_build_blocks_warn_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req_path = tmp / "requirements.json"
            deps_path = tmp / "entity-deps.local.json"
            env_path = tmp / "env.sh"
            self.write_json(req_path, self.base_requirements(tmp))
            env_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            self.write_json(
                deps_path,
                {
                    "schema_version": 1,
                    "compatibility": {"status": "warn"},
                    "selected": {},
                    "env_sh": {"path": str(env_path)},
                },
            )

            proc = run_cmd(
                "scripts/entity_generate.py",
                "build",
                str(req_path),
                "--env",
                str(env_path),
                "--checkpoint",
                str(deps_path),
                "--output",
                str(tmp / "entity-build.sh"),
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "entity-build.sh").exists())
            self.assertIn("must be pass", proc.stderr)

    def test_build_blocks_stale_env_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req_path = tmp / "requirements.json"
            deps_path = tmp / "entity-deps.local.json"
            env_path = tmp / "env.sh"
            self.write_json(req_path, self.base_requirements(tmp))
            env_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            self.write_json(
                deps_path,
                {
                    "schema_version": 1,
                    "compatibility": {"status": "pass"},
                    "selected": {},
                    "env_sh": {"path": str(tmp / "old-env.sh")},
                },
            )

            proc = run_cmd(
                "scripts/entity_generate.py",
                "build",
                str(req_path),
                "--env",
                str(env_path),
                "--checkpoint",
                str(deps_path),
                "--output",
                str(tmp / "entity-build.sh"),
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((tmp / "entity-build.sh").exists())
            self.assertIn("may be stale", proc.stderr)

    def test_record_install_requires_real_paths(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(
                deps_path,
                {
                    "schema_version": 1,
                    "selected": {},
                    "paths": {},
                    "compatibility": {"status": "pass"},
                },
            )

            proc = run_cmd(
                "scripts/entity_checkpoint.py",
                "record-install",
                "--checkpoint",
                str(deps_path),
                "--dep",
                "kokkos",
                "--prefix",
                str(tmp / "missing"),
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads(deps_path.read_text(encoding="utf-8"))
            self.assertEqual(data["selected"], {})

    def test_record_install_updates_checkpoint_and_invalidates_compat(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            prefix = tmp / "kokkos"
            config = prefix / "lib64" / "cmake" / "Kokkos" / "KokkosConfig.cmake"
            config.parent.mkdir(parents=True)
            config.write_text("# fixture\n", encoding="utf-8")
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(
                deps_path,
                {
                    "schema_version": 1,
                    "selected": {},
                    "paths": {},
                    "compatibility": {"status": "pass"},
                    "status": {"checkpoint": "complete", "ready_for_entity_build": True},
                },
            )

            proc = run_cmd(
                "scripts/entity_checkpoint.py",
                "record-install",
                "--checkpoint",
                str(deps_path),
                "--dep",
                "kokkos",
                "--prefix",
                str(prefix),
                "--cmake-config",
                str(config),
                "--version",
                "5.0.1",
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads(deps_path.read_text(encoding="utf-8"))
            self.assertTrue(data["selected"]["kokkos"]["validation"]["installed"])
            self.assertEqual(data["compatibility"]["status"], "unknown")
            self.assertFalse(data["status"]["ready_for_entity_build"])

    def test_create_embeds_requirements_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req_path = tmp / "requirements.json"
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(req_path, self.base_requirements(tmp))

            proc = run_cmd(
                "scripts/entity_checkpoint.py",
                "create",
                str(req_path),
                "--output",
                str(deps_path),
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads(deps_path.read_text(encoding="utf-8"))
            embedded = data["requirements"]["embedded"]
            self.assertEqual(embedded["environment"]["backend"], "cpu")
            self.assertEqual(embedded["compile"]["pgen"], "smoke")

    def test_compat_fails_when_requirements_snapshot_drifts(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            deps_path = tmp / "entity-deps.local.json"
            req_path = tmp / "requirements.json"
            self.write_json(req_path, req)

            create_proc = run_cmd(
                "scripts/entity_checkpoint.py",
                "create",
                str(req_path),
                "--output",
                str(deps_path),
            )
            self.assertEqual(create_proc.returncode, 0, create_proc.stdout + create_proc.stderr)

            confirm_proc = run_cmd(
                "scripts/entity_checkpoint.py",
                "confirm",
                str(req_path),
                "--checkpoint",
                str(deps_path),
                "--by",
                "test",
            )
            self.assertEqual(confirm_proc.returncode, 0, confirm_proc.stdout + confirm_proc.stderr)

            req["environment"]["backend"] = "cuda"
            req["environment"]["gpu_arch"] = "AMPERE80"
            self.write_json(req_path, req)

            proc = run_cmd(
                "scripts/entity_compat.py",
                str(req_path),
                "--checkpoint",
                str(deps_path),
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("consistency.requirements_embedded", proc.stdout)
            self.assertIn("environment.backend", proc.stdout)

    def test_compat_result_includes_coverage_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req_path = tmp / "requirements.json"
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(req_path, req)
            self.write_json(deps_path, self.compat_checkpoint_fixture(tmp, req))

            proc = run_cmd(
                "scripts/entity_compat.py",
                str(req_path),
                "--checkpoint",
                str(deps_path),
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads(deps_path.read_text(encoding="utf-8"))
            compat = data["compatibility"]
            self.assertEqual(compat["checker_version"], 1)
            self.assertEqual(compat["coverage"]["requirements_checkpoint_match"], "implemented")
            self.assertIn("cmake_package_probe", compat["coverage"])

    def test_run_build_records_success(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["artifacts"] = {"logs_dir": str(tmp / "logs")}
            req_path = tmp / "requirements.json"
            script = tmp / "entity-build.sh"
            self.write_json(req_path, req)
            script.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
            script.chmod(0o755)

            proc = run_cmd(
                "scripts/entity_run.py",
                "build",
                str(req_path),
                "--script",
                str(script),
                "--run-id",
                "testrun",
                "--quiet",
                env={"HOME": str(tmp / "home")},
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads(req_path.read_text(encoding="utf-8"))
            self.assertEqual(data["build_result"]["status"], "pass")
            self.assertEqual(data["build_result"]["exit_code"], 0)
            self.assertTrue(Path(data["build_result"]["runner_log"]).is_file())
            state = json.loads((tmp / ".entity-session.json").read_text(encoding="utf-8"))
            self.assertEqual(state["steps"]["build_executed"]["status"], "pass")

    def test_run_build_records_failure(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req["artifacts"] = {"logs_dir": str(tmp / "logs")}
            req_path = tmp / "requirements.json"
            script = tmp / "entity-build.sh"
            self.write_json(req_path, req)
            script.write_text("#!/usr/bin/env bash\necho bad\nexit 3\n", encoding="utf-8")
            script.chmod(0o755)

            proc = run_cmd(
                "scripts/entity_run.py",
                "build",
                str(req_path),
                "--script",
                str(script),
                "--run-id",
                "testrun",
                "--quiet",
                env={"HOME": str(tmp / "home")},
            )

            self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
            data = json.loads(req_path.read_text(encoding="utf-8"))
            self.assertEqual(data["build_result"]["status"], "fail")
            self.assertEqual(data["build_result"]["exit_code"], 3)
            self.assertTrue(Path(data["build_result"]["runner_log"]).is_file())
            state = json.loads((tmp / ".entity-session.json").read_text(encoding="utf-8"))
            self.assertEqual(state["steps"]["build_executed"]["status"], "fail")

    def test_compat_fails_without_parameters_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req_path = tmp / "requirements.json"
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(req_path, req)
            checkpoint = self.compat_checkpoint_fixture(tmp, req)
            del checkpoint["decisions"]
            self.write_json(deps_path, checkpoint)

            proc = run_cmd(
                "scripts/entity_compat.py",
                str(req_path),
                "--checkpoint",
                str(deps_path),
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("parameters.confirmation", proc.stdout)

    def test_compat_fails_when_parameters_change_after_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req_path = tmp / "requirements.json"
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(req_path, req)

            create_proc = run_cmd(
                "scripts/entity_checkpoint.py", "create", str(req_path),
                "--output", str(deps_path),
            )
            self.assertEqual(create_proc.returncode, 0, create_proc.stdout + create_proc.stderr)
            confirm_proc = run_cmd(
                "scripts/entity_checkpoint.py", "confirm", str(req_path),
                "--checkpoint", str(deps_path), "--by", "test",
            )
            self.assertEqual(confirm_proc.returncode, 0, confirm_proc.stdout + confirm_proc.stderr)

            req["environment"]["backend"] = "cuda"
            req["environment"]["gpu_arch"] = "AMPERE80"
            self.write_json(req_path, req)

            proc = run_cmd(
                "scripts/entity_compat.py",
                str(req_path),
                "--checkpoint",
                str(deps_path),
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("parameters.confirmation", proc.stdout)
            self.assertIn("changed after confirmation", proc.stdout)

    def test_compat_passes_parameters_confirmation_after_confirm(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req_path = tmp / "requirements.json"
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(req_path, req)
            self.write_json(deps_path, self.compat_checkpoint_fixture(tmp, req))

            proc = run_cmd(
                "scripts/entity_compat.py",
                str(req_path),
                "--checkpoint",
                str(deps_path),
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            compat = json.loads(proc.stdout)
            by_id = {check["id"]: check["status"] for check in compat["checks"]}
            self.assertEqual(by_id.get("parameters.confirmation"), "pass")

    def test_confirm_requires_by_actor(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req_path = tmp / "requirements.json"
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(req_path, self.base_requirements(tmp))
            create_proc = run_cmd(
                "scripts/entity_checkpoint.py", "create", str(req_path),
                "--output", str(deps_path),
            )
            self.assertEqual(create_proc.returncode, 0, create_proc.stdout + create_proc.stderr)

            proc = run_cmd(
                "scripts/entity_checkpoint.py", "confirm", str(req_path),
                "--checkpoint", str(deps_path),
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads(deps_path.read_text(encoding="utf-8"))
            self.assertNotIn("parameters", data.get("decisions", {}))

    def test_confirm_records_defaults_flag(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            req = self.base_requirements(tmp)
            req_path = tmp / "requirements.json"
            deps_path = tmp / "entity-deps.local.json"
            self.write_json(req_path, req)
            create_proc = run_cmd(
                "scripts/entity_checkpoint.py", "create", str(req_path),
                "--output", str(deps_path),
            )
            self.assertEqual(create_proc.returncode, 0, create_proc.stdout + create_proc.stderr)

            plain = run_cmd(
                "scripts/entity_checkpoint.py", "confirm", str(req_path),
                "--checkpoint", str(deps_path), "--by", "tester",
            )
            self.assertEqual(plain.returncode, 0, plain.stdout + plain.stderr)
            data = json.loads(deps_path.read_text(encoding="utf-8"))
            record = data["decisions"]["parameters"]
            self.assertEqual(record["confirmed_by"], "tester")
            self.assertFalse(record["defaults"])
            self.assertEqual(record["digest"], self.load_parameter_card(req)["digest"])
            self.assertTrue(record["confirmed_at"])

            with_defaults = run_cmd(
                "scripts/entity_checkpoint.py", "confirm", str(req_path),
                "--checkpoint", str(deps_path), "--by", "tester",
                "--confirm-defaults",
            )
            self.assertEqual(with_defaults.returncode, 0, with_defaults.stdout + with_defaults.stderr)
            data = json.loads(deps_path.read_text(encoding="utf-8"))
            self.assertTrue(data["decisions"]["parameters"]["defaults"])

    def _openmpi_check(self, selected):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import entity_compat
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        checks, issues = [], []
        entity_compat.run_cross_checks(
            checks, issues, {"environment": {"mpi": True, "backend": "cpu"}},
            {"selected": selected},
        )
        by_id = {check["id"]: check["status"] for check in checks}
        return by_id.get("mpi.openmpi_min_version"), issues

    def test_openmpi_below_minimum_fails_compat(self):
        status, issues = self._openmpi_check(
            {"mpi": {"prefix": "/opt/openmpi", "version": "4.1.9", "flavor": "openmpi"}}
        )
        self.assertEqual(status, "fail")
        self.assertTrue(any("below minimum" in issue for issue in issues))

    def test_openmpi_at_minimum_passes_compat(self):
        status, issues = self._openmpi_check(
            {"mpi": {"prefix": "/opt/openmpi", "version": "5.0.7", "flavor": "OpenMPI"}}
        )
        self.assertEqual(status, "pass")

    def test_openmpi_selected_key_identifies_flavor(self):
        status, issues = self._openmpi_check({"openmpi": {"version": "4.1.1"}})
        self.assertEqual(status, "fail")

    def test_non_openmpi_mpi_is_not_constrained(self):
        status, issues = self._openmpi_check(
            {"mpi": {"prefix": "/opt/mpich", "version": "4.1", "flavor": "mpich"}}
        )
        self.assertIsNone(status)


if __name__ == "__main__":
    unittest.main()
