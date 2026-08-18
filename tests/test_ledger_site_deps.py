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
from entity_ledger_store import OperationStore
from entity_ledger_workspace import (
    derive_stack_id,
    init_workspace,
    list_site_archives,
    load_flat_yaml,
    site_yaml_path,
    stack_signature,
    write_site_yaml,
)


class SignatureVectorsTest(unittest.TestCase):
    """Ledger side of the shared signature contract; the same vectors are
    consumed by skills/entity-env-build/tests/test_registry_resolution.py."""

    def test_shared_vectors(self):
        vectors_path = os.path.join(ROOT, "tests", "vectors",
                                    "stack-signature.json")
        with open(vectors_path, "r") as handle:
            vectors = json.load(handle)["vectors"]
        for vector in vectors:
            req = vector["requirements"]
            signature = stack_signature(
                req.get("environment"), req.get("entity"), req.get("compile"))
            self.assertEqual(signature, vector["expected"], vector["name"])


class DepsTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-ledger-deps-")
        self._env = mock.patch.dict(os.environ, {"HOME": self.temp})
        self._env.start()
        for key in ("ENTITY_LEDGER_HOME", "ENTITY_ROUTER_HOME",
                    "ENTITY_WORKSPACE"):
            os.environ.pop(key, None)
        self.workspace = init_workspace(os.path.join(self.temp, "ws"))["workspace"]
        write_active_workspace(self.workspace)
        self.home = os.path.join(self.workspace, ".ledger")
        self.store = OperationStore(self.home)
        self.site_root = os.path.join(self.temp, "compute")
        write_site_yaml(self.workspace, {
            "site_id": "m87",
            "transport": {"kind": "local"},
            "scheduler": {"kind": "none"},
            "site_root": self.site_root,
        })

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
        return process.returncode, stdout, stderr

    def cli_json(self, *args):
        code, stdout, stderr = self.cli(*args)
        return code, json.loads(stdout)

    def selected(self):
        return {
            "compiler": {"name": "gcc", "version": "12.3.0",
                         "prefix": "/opt/gcc", "provider": "system"},
            "kokkos": {"name": "kokkos", "version": "5.1.0",
                       "prefix": "/deps/kokkos", "provider": "module"},
        }

    def stack_id(self):
        return derive_stack_id(self.selected(), self.signature())

    def signature(self):
        return stack_signature(
            {"backend": "cpu", "mpi": False, "gpu_aware_mpi": False,
             "output": True},
            {"site_id": "m87", "dependency_profile": "modern"},
            {"cxx_standard": "20"})

    def write_checkpoint(self, compatibility="pass", confirmed=True,
                         site_id="m87"):
        checkpoint = {
            "schema_version": 2,
            "requirements": {"path": "", "embedded": {
                "entity": {"site_id": site_id, "dependency_profile": "modern"},
                "environment": {"backend": "cpu", "mpi": False,
                                "gpu_aware_mpi": False, "output": True},
                "compile": {"cxx_standard": "20"},
            }},
            "entity": {"site_id": site_id},
            "selected": self.selected(),
            "compatibility": {"status": compatibility},
            "decisions": {},
        }
        if confirmed:
            checkpoint["decisions"]["parameters"] = {"digest": "sha256:" + "1" * 64}
        path = os.path.join(self.temp, "entity-deps.local.json")
        with open(path, "w") as handle:
            json.dump(checkpoint, handle)
        return path

    def write_env_sh(self):
        env_sh = os.path.join(self.site_root, "deps", self.stack_id(), "env.sh")
        os.makedirs(os.path.dirname(env_sh))
        with open(env_sh, "w") as handle:
            handle.write("export ENTITY_DEPS_ROOT=x\n")
        return env_sh


class SiteDepsAddTest(DepsTestBase):
    def test_deps_add_registers_verified_stack(self):
        env_sh = self.write_env_sh()
        checkpoint = self.write_checkpoint()
        code, payload = self.cli_json(
            "site", "deps-add", "m87", "--from-checkpoint", checkpoint)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["stack_id"], self.stack_id())
        self.assertEqual(payload["env_sh"], env_sh)
        # archive registry holds the verified stack
        archives = list_site_archives(self.workspace)
        stacks = archives["m87"]["deps"]
        self.assertEqual(len(stacks), 1)
        stack = stacks[0]
        self.assertEqual(stack["status"], "verified")
        self.assertEqual(stack["signature"], self.signature())
        self.assertEqual([p["name"] for p in stack["packages"]],
                         ["compiler", "kokkos"])
        self.assertEqual(stack["recipe"]["providers"]["kokkos"], "module")
        # stack.yaml landed on the site tree
        stack_yaml = os.path.join(
            self.site_root, "deps", self.stack_id(), "stack.yaml")
        on_site = load_flat_yaml(stack_yaml, "stack.yaml")
        self.assertEqual(on_site["stack_id"], self.stack_id())
        self.assertEqual(on_site["site_id"], "m87")
        self.assertEqual(on_site["status"], "verified")
        # the db mirror is refreshed too
        profile = self.store.get_site("m87")
        self.assertEqual(profile["deps"][0]["stack_id"], self.stack_id())
        # re-registering replaces the entry instead of duplicating it
        code, again = self.cli_json(
            "site", "deps-add", "m87", "--from-checkpoint", checkpoint)
        self.assertEqual(code, 0, again)
        archives = list_site_archives(self.workspace)
        self.assertEqual(len(archives["m87"]["deps"]), 1)

    def test_deps_add_zero_write_on_unverified_checkpoint(self):
        self.write_env_sh()
        for checkpoint in [self.write_checkpoint(compatibility="fail"),
                           self.write_checkpoint(confirmed=False)]:
            code, payload = self.cli_json(
                "site", "deps-add", "m87", "--from-checkpoint", checkpoint)
            self.assertEqual(code, 2)
            self.assertEqual(payload["status"], "needs_decision")
        archives = list_site_archives(self.workspace)
        self.assertEqual(archives["m87"].get("deps") or [], [])
        self.assertFalse(os.path.exists(
            os.path.join(self.site_root, "deps", self.stack_id(),
                         "stack.yaml")))

    def test_deps_add_zero_write_when_env_sh_missing(self):
        checkpoint = self.write_checkpoint()
        code, payload = self.cli_json(
            "site", "deps-add", "m87", "--from-checkpoint", checkpoint)
        self.assertEqual(code, 2)
        self.assertIn("env.sh", payload["error"])
        self.assertIn("zero writes", payload["error"])
        archives = list_site_archives(self.workspace)
        self.assertEqual(archives["m87"].get("deps") or [], [])

    def test_deps_add_rejects_foreign_checkpoint(self):
        self.write_env_sh()
        checkpoint = self.write_checkpoint(site_id="other-site")
        code, payload = self.cli_json(
            "site", "deps-add", "m87", "--from-checkpoint", checkpoint)
        self.assertEqual(code, 2)
        self.assertIn("other-site", payload["error"])

    def test_deps_add_site_write_failure_leaves_archive_untouched(self):
        env_sh = self.write_env_sh()
        checkpoint = self.write_checkpoint()
        # make the stack directory unwritable: the on-site stack.yaml write
        # must fail BEFORE the archive registry is touched
        os.chmod(os.path.dirname(env_sh), 0o500)
        try:
            code, payload = self.cli_json(
                "site", "deps-add", "m87", "--from-checkpoint", checkpoint)
        finally:
            os.chmod(os.path.dirname(env_sh), 0o700)
        self.assertEqual(code, 2)
        archives = list_site_archives(self.workspace)
        self.assertEqual(archives["m87"].get("deps") or [], [])
        self.assertFalse(os.path.exists(
            os.path.join(self.site_root, "deps", self.stack_id(),
                         "stack.yaml")))


class SiteDepsAnalysisKindTest(DepsTestBase):
    def analysis_checkpoint(self, interpreter):
        checkpoint = {
            "schema_version": 2,
            "requirements": {"path": "", "embedded": {
                "entity": {"site_id": "m87"},
                "environment": {},
                "compile": {},
            }},
            "entity": {"site_id": "m87"},
            # no compatibility pass / no parameter confirmation: the
            # analysis-kind gate only probes the interpreter on the Site
            "selected": {
                "python": {"name": "python", "version": "3.11",
                           "bin": interpreter, "provider": "conda"},
                "nt2py": {"name": "nt2py", "version": "1.5.3",
                          "provider": "pip"},
            },
        }
        path = os.path.join(self.temp, "analysis-env.json")
        with open(path, "w") as handle:
            json.dump(checkpoint, handle)
        return path

    def test_deps_add_analysis_kind(self):
        interpreter = os.path.join(self.temp, "venv", "bin", "python")
        os.makedirs(os.path.dirname(interpreter))
        with open(interpreter, "w") as handle:
            handle.write("#!/bin/sh\n")
        checkpoint = self.analysis_checkpoint(interpreter)
        code, payload = self.cli_json(
            "site", "deps-add", "m87", "--kind", "analysis",
            "--from-checkpoint", checkpoint)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["stack_kind"], "analysis")
        archives = list_site_archives(self.workspace)
        stack = archives["m87"]["deps"][0]
        self.assertEqual(stack["kind"], "analysis")
        self.assertNotIn("env_sh", stack)
        names = [p["name"] for p in stack["packages"]]
        self.assertEqual(names, ["nt2py", "python"])
        # stack.yaml written on the site tree with the kind field
        stack_yaml = load_flat_yaml(payload["stack_yaml"], "stack.yaml")
        self.assertEqual(stack_yaml["kind"], "analysis")
        # the human view groups by kind
        code, text, unused = self.cli("site", "deps", "m87")
        self.assertEqual(code, 0)
        self.assertIn("[analysis]", text)

    def test_deps_add_analysis_requires_existing_interpreter(self):
        checkpoint = self.analysis_checkpoint(
            os.path.join(self.temp, "no-such-python"))
        code, payload = self.cli_json(
            "site", "deps-add", "m87", "--kind", "analysis",
            "--from-checkpoint", checkpoint)
        self.assertEqual(code, 2)
        self.assertIn("analysis interpreter", payload["error"])
        archives = list_site_archives(self.workspace)
        self.assertEqual(archives["m87"].get("deps") or [], [])
        # and a checkpoint without any python entry fails before probing
        bare = self.analysis_checkpoint("")
        code, payload = self.cli_json(
            "site", "deps-add", "m87", "--kind", "analysis",
            "--from-checkpoint", bare)
        self.assertEqual(code, 2)
        self.assertIn("selected.python", payload["error"])

    def test_analysis_kind_semantics_pinned(self):
        # the interpreter may be a directory (selected.python.prefix, e.g. a
        # conda env root): existence is the gate, not file-ness
        env_dir = os.path.join(self.temp, "conda-env")
        os.makedirs(env_dir)
        checkpoint = self.analysis_checkpoint("")
        with open(checkpoint, "r") as handle:
            data = json.load(handle)
        data["selected"]["python"] = {"name": "python", "version": "3.11",
                                      "prefix": env_dir, "provider": "conda"}
        with open(checkpoint, "w") as handle:
            json.dump(data, handle)
        code, payload = self.cli_json(
            "site", "deps-add", "m87", "--kind", "analysis",
            "--from-checkpoint", checkpoint)
        self.assertEqual(code, 0, payload)
        # re-registering the same analysis stack replaces, never appends
        code, again = self.cli_json(
            "site", "deps-add", "m87", "--kind", "analysis",
            "--from-checkpoint", checkpoint)
        self.assertEqual(code, 0, again)
        archives = list_site_archives(self.workspace)
        self.assertEqual(len(archives["m87"]["deps"]), 1)
        # a foreign checkpoint is refused for analysis stacks too
        data["requirements"]["embedded"]["entity"]["site_id"] = "other"
        data["entity"]["site_id"] = "other"
        with open(checkpoint, "w") as handle:
            json.dump(data, handle)
        code, payload = self.cli_json(
            "site", "deps-add", "m87", "--kind", "analysis",
            "--from-checkpoint", checkpoint)
        self.assertEqual(code, 2)
        self.assertIn("other", payload["error"])


class SiteDepsViewTest(DepsTestBase):
    def test_site_deps_json_and_text(self):
        self.write_env_sh()
        checkpoint = self.write_checkpoint()
        code, unused = self.cli_json(
            "site", "deps-add", "m87", "--from-checkpoint", checkpoint)
        self.assertEqual(code, 0)
        code, payload = self.cli_json("site", "deps", "m87", "--json")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["origin"], "archive")
        self.assertEqual(len(payload["stacks"]), 1)
        self.assertEqual(payload["stacks"][0]["stack_id"], self.stack_id())
        code, text, unused_err = self.cli("site", "deps", "m87")
        self.assertEqual(code, 0)
        self.assertIn("deps registry", text)
        self.assertIn(self.stack_id(), text)
        self.assertIn("verified", text)
        # build is the default kind: no redundant tag
        self.assertNotIn("[build]", text)
        # empty registry renders a hint, unknown site is an error
        write_site_yaml(self.workspace, {"site_id": "empty",
                                         "transport": {"kind": "local"}})
        code, text, unused_err = self.cli("site", "deps", "empty")
        self.assertEqual(code, 0)
        self.assertIn("(empty)", text)
        code, payload = self.cli_json("site", "deps", "ghost", "--json")
        self.assertEqual(code, 2)


class RecordBuildStackTest(DepsTestBase):
    def setUp(self):
        super(RecordBuildStackTest, self).setUp()
        self.store.upsert_site({
            "schema_version": 1, "site_id": "local",
            "transport": {"kind": "local"}, "scheduler": {"kind": "none"},
            "roots": {}, "policy": {}})
        self.project = os.path.join(self.workspace, "projects", "demo")
        os.makedirs(self.project)
        self.store.upsert_project("project-1", "demo", self.project)
        self.store.upsert_case(
            "case-1", "alpha", self.project,
            {"authority": {"site_id": "local", "path": self.project},
             "transfer_policy": "snapshot",
             "revision": {"kind": "path", "root": self.project}},
            {"source_id": "", "build_id": "", "run_id": "",
             "active_run": None, "data_id": "", "analysis_id": ""},
            project_uid="project-1")
        self.executable = os.path.join(self.temp, "entity.xc")
        with open(self.executable, "w") as handle:
            handle.write("binary\n")
        os.chmod(self.executable, 0o755)

    def record_build(self, checkpoint):
        return self.cli_json(
            "record", "build", "--project-root", self.project,
            "--site", "local", "--checkpoint", checkpoint,
            "--executable", self.executable)

    def test_record_build_carries_stack_id_and_hints_deps_add(self):
        # the site archive has no stack yet -> the hint suggests deps-add
        write_site_yaml(self.workspace, {
            "site_id": "local", "transport": {"kind": "local"}})
        checkpoint = self.write_checkpoint(site_id="local")
        expected = self.stack_id()
        code, payload = self.record_build(checkpoint)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["stack_id"], expected)
        self.assertTrue(any("deps-add" in warning
                            for warning in payload["warnings"]))
        case = self.store.get_case("case-1")
        identity = case["identities"]["build"]["items"][0]
        self.assertEqual(identity["stack_id"], expected)
        # register the stack; the same build record stops hinting
        write_site_yaml(self.workspace, {
            "site_id": "local", "transport": {"kind": "local"},
            "site_root": self.site_root,
        })
        self.write_env_sh()
        code, unused = self.cli_json(
            "site", "deps-add", "local", "--from-checkpoint", checkpoint)
        self.assertEqual(code, 0)
        code, again = self.record_build(checkpoint)
        self.assertEqual(code, 0, again)
        self.assertEqual(again["warnings"], [])

    def test_record_build_without_selected_has_no_stack_reference(self):
        write_site_yaml(self.workspace, {
            "site_id": "local", "transport": {"kind": "local"}})
        checkpoint = {
            "schema_version": 2,
            "compatibility": {"status": "pass"},
            "decisions": {"parameters": {"digest": "sha256:" + "1" * 64}},
            "selected": {},
        }
        path = os.path.join(self.temp, "checkpoint-bare.json")
        with open(path, "w") as handle:
            json.dump(checkpoint, handle)
        code, payload = self.record_build(path)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["stack_id"], "")
        case = self.store.get_case("case-1")
        identity = case["identities"]["build"]["items"][0]
        self.assertNotIn("stack_id", identity)


class CrossSkillRegistryTest(RecordBuildStackTest):
    """Cross-skill closure: ledger deps registry -> env-build
    --from-registry -> record build must keep one stack_id."""

    ENV_BUILD = os.path.join(ROOT, "skills", "entity-env-build")

    def write_requirements(self, selected_site="local"):
        root = os.path.join(self.temp, "req")
        for name in ("src", "build", "deps", "artifacts"):
            os.makedirs(os.path.join(root, name))
        requirements = {
            "schema_version": 2,
            "entity": {
                "site_id": selected_site,
                "source_checkout": os.path.join(root, "src"),
                "source_revision": {"kind": "git", "commit": "a", "tree": "b"},
                "build_root": os.path.join(root, "build"),
                "deps_root": os.path.join(root, "deps"),
                "artifacts_root": os.path.join(root, "artifacts"),
                "version_bucket": "1.4.3",
                "dependency_profile": "modern",
            },
            "environment": {"backend": "cpu", "output": True, "mpi": False,
                            "dependency_policy": "reuse-existing"},
            "compile": {"pgen": "smoke", "cxx_standard": "20"},
        }
        path = os.path.join(root, "requirements.json")
        with open(path, "w") as handle:
            json.dump(requirements, handle)
        return path

    def env_create(self, requirements, registry, output):
        env = dict((key, value) for key, value in os.environ.items()
                   if not key.startswith("ENTITY_"))
        process = subprocess.Popen(
            [sys.executable,
             os.path.join("scripts", "entity_checkpoint.py"),
             "create", requirements,
             "--from-registry", registry,
             "--output", output],
            cwd=self.ENV_BUILD, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 0, stderr)
        with open(output, "r") as handle:
            return json.load(handle)

    def export_registry(self):
        registry = os.path.join(self.temp, "registry.json")
        code, stdout, unused = self.cli("site", "deps", "local", "--json")
        self.assertEqual(code, 0)
        with open(registry, "w") as handle:
            handle.write(stdout)
        return registry

    def test_registry_hit_closes_stack_id_loop(self):
        write_site_yaml(self.workspace, {
            "site_id": "local", "transport": {"kind": "local"},
            "site_root": self.site_root})
        self.write_env_sh()
        checkpoint = self.write_checkpoint(site_id="local")
        code, payload = self.cli_json(
            "site", "deps-add", "local", "--from-checkpoint", checkpoint)
        self.assertEqual(code, 0, payload)
        stack_id = payload["stack_id"]
        # env-build consumes the exported registry
        requirements = self.write_requirements()
        created = self.env_create(
            requirements, self.export_registry(),
            os.path.join(self.temp, "checkpoint-from-registry.json"))
        self.assertEqual(created["stack_id"], stack_id)
        # the original providers are preserved (origin is validation.source)
        self.assertEqual(created["selected"]["compiler"]["provider"],
                         "system")
        self.assertEqual(created["selected"]["kokkos"]["provider"], "module")
        self.assertEqual(
            created["selected"]["kokkos"]["validation"]["source"],
            "site-registry")
        # a verified checkpoint from that stack records the same stack_id
        # with no spurious "stack not registered" hint
        created["compatibility"] = {"status": "pass"}
        created["decisions"] = {"parameters": {"digest": "sha256:" + "1" * 64}}
        verified = os.path.join(self.temp, "checkpoint-verified.json")
        with open(verified, "w") as handle:
            json.dump(created, handle)
        code, built = self.record_build(verified)
        self.assertEqual(code, 0, built)
        self.assertEqual(built["stack_id"], stack_id)
        self.assertEqual(built["warnings"], [])

    def test_cmake_config_only_dependency_roundtrips(self):
        selected = {
            "cmake": {"name": "cmake", "version": "3.28.0",
                      "cmake_config": "/opt/cmake/lib/cmake",
                      "provider": "system"},
        }
        signature = self.signature()
        stack_id = derive_stack_id(selected, signature)
        checkpoint = {
            "schema_version": 2,
            "requirements": {"path": "", "embedded": {
                "entity": {"site_id": "local",
                           "dependency_profile": "modern"},
                "environment": {"backend": "cpu", "mpi": False,
                                "gpu_aware_mpi": False, "output": True},
                "compile": {"cxx_standard": "20"},
            }},
            "entity": {"site_id": "local"},
            "selected": selected,
            "compatibility": {"status": "pass"},
            "decisions": {"parameters": {"digest": "sha256:" + "1" * 64}},
        }
        checkpoint_path = os.path.join(self.temp, "checkpoint-cmake.json")
        with open(checkpoint_path, "w") as handle:
            json.dump(checkpoint, handle)
        env_sh = os.path.join(self.site_root, "deps", stack_id, "env.sh")
        os.makedirs(os.path.dirname(env_sh))
        with open(env_sh, "w") as handle:
            handle.write("export X=1\n")
        write_site_yaml(self.workspace, {
            "site_id": "local", "transport": {"kind": "local"},
            "site_root": self.site_root})
        code, payload = self.cli_json(
            "site", "deps-add", "local", "--from-checkpoint", checkpoint_path)
        self.assertEqual(code, 0, payload)
        archives = list_site_archives(self.workspace)
        package = archives["local"]["deps"][0]["packages"][0]
        # cmake-config-only dependencies keep their config path; no
        # prefix<-bin fallback invents one
        self.assertEqual(package["cmake_config"], "/opt/cmake/lib/cmake")
        self.assertNotIn("prefix", package)
        self.assertNotIn("bin", package)
        # ...and env-build can consume the stack again (--from-registry)
        requirements = self.write_requirements()
        created = self.env_create(
            requirements, self.export_registry(),
            os.path.join(self.temp, "checkpoint-cmake-out.json"))
        self.assertEqual(created["stack_id"], stack_id)
        self.assertEqual(created["selected"]["cmake"]["cmake_config"],
                         "/opt/cmake/lib/cmake")
        self.assertEqual(created["selected"]["cmake"]["provider"], "system")


if __name__ == "__main__":
    unittest.main()
