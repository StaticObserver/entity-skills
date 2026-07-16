from __future__ import print_function

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
STATE = os.path.join(SCRIPTS, "entity_router_state.py")
SITE = os.path.join(SCRIPTS, "entity_router_site.py")


class RouterV3CLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-router-v3-")
        self.home = os.path.join(self.temp, "control")
        self.source = os.path.join(self.temp, "source")
        self.remote = os.path.join(self.temp, "remote")
        for path in [self.source, self.remote]:
            os.makedirs(path)
        subprocess.check_call(["git", "init", "-q", self.source])
        subprocess.check_call(["git", "-C", self.source, "config", "user.email", "test@example.invalid"])
        subprocess.check_call(["git", "-C", self.source, "config", "user.name", "Router Test"])
        os.makedirs(os.path.join(self.source, "docs"))
        self._write(os.path.join(self.source, "README.md"), "source\n")
        subprocess.check_call(["git", "-C", self.source, "add", "."])
        subprocess.check_call(["git", "-C", self.source, "commit", "-qm", "base"])
        self.add_site("local", self.temp)
        self.add_site("remote-sim", self.remote)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def _write(self, path, value):
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w") as handle:
            handle.write(value)

    def cli(self, script, *args):
        command = [sys.executable, script, "--router-home", self.home] + list(args)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True)
        stdout, stderr = process.communicate()
        self.assertTrue(stdout.strip(), "no JSON output; stderr=%s" % stderr)
        return process.returncode, json.loads(stdout)

    def add_site(self, site_id, root):
        args = ["add", "--site-id", site_id, "--transport", "local"]
        for name in ["source", "build", "run", "deps", "staging", "analysis"]:
            path = os.path.join(root, name)
            os.makedirs(path, exist_ok=True)
            args.extend(["--%s-root" % name, path])
        code, payload = self.cli(SITE, *args)
        self.assertEqual(code, 0, payload)

    def create_case(self, case_id="smoke", build_site="remote-sim", replicas=None):
        pgen = os.path.join(self.source, "pgen.hpp")
        toml = os.path.join(self.source, "smoke.toml")
        design = os.path.join(self.source, "docs", "design.md")
        args = [
            "create", "--case-id", case_id,
            "--source-authority", "local:%s" % self.source,
            "--pgen-locator", "local:%s" % pgen,
            "--toml-locator", "local:%s" % toml,
            "--design-locator", "local:%s" % design,
            "--build-root", "%s:%s" % (build_site, os.path.join(self.remote, "build")),
            "--run-root", "remote-sim:%s" % os.path.join(self.remote, "run"),
            "--data-root", "remote-sim:%s" % os.path.join(self.remote, "run"),
            "--analysis-root", "remote-sim:%s" % os.path.join(self.remote, "analysis"),
            "--goal", "exercise multi-site state",
            "--done-when", "verified evidence exists",
        ]
        for replica in replicas or []:
            args.extend(["--source-replica", replica])
        code, payload = self.cli(STATE, *args)
        self.assertEqual(code, 0, payload)
        return payload

    def test_cross_site_action_lifecycle_and_snapshot(self):
        created = self.create_case()
        case = created["case_dir"]
        state = created["state"]
        self.assertEqual(state["schema_version"], 3)
        self.assertEqual(state["readiness"]["source"]["status"], "unmaterialized")
        pgen = os.path.join(self.source, "pgen.hpp")

        code, bad = self.cli(
            STATE, "start-action", "--case", case, "--expected-revision", "0",
            "--action-id", "bad-site", "--action-type", "pgen.design",
            "--owner", "entity-pgen", "--execution-domain", "entity-pgen",
            "--execution-site", "remote-sim", "--goal", "invalid",
            "--write-root", "remote-sim:%s" % os.path.join(self.remote, "source"),
        )
        self.assertEqual(code, 2)
        self.assertIn("authority site", bad["error"])

        code, started = self.cli(
            STATE, "start-action", "--case", case, "--expected-revision", "0",
            "--action-id", "pgen-1", "--action-type", "pgen.design",
            "--owner", "entity-pgen", "--execution-domain", "entity-pgen",
            "--execution-site", "local", "--goal", "write pgen",
            "--read-root", "local:%s" % self.source,
            "--write-root", "local:%s" % pgen,
            "--expected-output", "local:%s" % pgen, "--acceptance-check", "file exists",
        )
        self.assertEqual(code, 0, started)
        self._write(pgen, "// pgen\n")
        code, finished = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "1",
            "--action-id", "pgen-1", "--status", "completed",
            "--output", "local:%s" % pgen, "--verification", "file inspected",
            "--readiness", "pgen=verified",
        )
        self.assertEqual(code, 0, finished)
        self.assertIn("source.materialize", finished["allowed_actions"])

        target = "remote-sim:%s" % os.path.join(self.remote, "staging", created["case_uid"])
        code, materialized = self.cli(
            SITE, "materialize", "--mode", "snapshot",
            "--source", "local:%s" % self.source, "--target", target,
        )
        self.assertEqual(code, 0, materialized)
        output = materialized["materialized"]
        code, started = self.cli(
            STATE, "start-action", "--case", case, "--expected-revision", "2",
            "--action-id", "source-1", "--action-type", "source.materialize",
            "--owner", "router", "--execution-domain", "playbook-sync",
            "--execution-site", "remote-sim", "--goal", "record snapshot",
            "--write-root", target, "--expected-output", target,
        )
        self.assertEqual(code, 0, started)
        code, finished = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "3",
            "--action-id", "source-1", "--status", "completed",
            "--output", "%s:%s" % (output["site_id"], output["path"]),
            "--verification", "manifest hash verified", "--readiness", "source=ready",
        )
        self.assertEqual(code, 0, finished)
        self.assertIn("build.compile", finished["allowed_actions"])

        build_id = "build-001"
        build_path = os.path.join(self.remote, "build", created["case_uid"], build_id)
        os.makedirs(build_path)
        code, started = self.cli(
            STATE, "start-action", "--case", case, "--expected-revision", "4",
            "--action-id", "build-action", "--action-type", "build.compile",
            "--owner", "entity-env-build", "--execution-domain", "entity-env-build",
            "--execution-site", "remote-sim", "--identity-id", build_id,
            "--goal", "compile immutable source", "--read-root", "%s:%s" % (output["site_id"], output["path"]),
            "--input", "%s:%s" % (output["site_id"], output["path"]),
            "--write-root", "remote-sim:%s" % build_path,
            "--expected-output", "remote-sim:%s" % os.path.join(build_path, "entity.xc"),
        )
        self.assertEqual(code, 0, started)
        executable = os.path.join(build_path, "entity.xc")
        self._write(executable, "binary\n")
        code, finished = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "5",
            "--action-id", "build-action", "--status", "completed",
            "--output", "remote-sim:%s" % executable,
            "--verification", "executable inspected", "--readiness", "build=pass",
        )
        self.assertEqual(code, 0, finished)
        self.assertIn("run.prepare", finished["allowed_actions"])

        run_id = "run-001"
        run_path = os.path.join(self.remote, "run", created["case_uid"], run_id)
        os.makedirs(run_path)
        code, started = self.cli(
            STATE, "start-action", "--case", case, "--expected-revision", "6",
            "--action-id", "run-prepare", "--action-type", "run.prepare",
            "--owner", "playbook-run", "--execution-domain", "playbook-run",
            "--execution-site", "remote-sim", "--identity-id", run_id,
            "--goal", "prepare immutable run", "--read-root", "remote-sim:%s" % build_path,
            "--input", "remote-sim:%s" % executable,
            "--write-root", "remote-sim:%s" % run_path,
            "--expected-output", "remote-sim:%s" % os.path.join(run_path, "run-manifest.yaml"),
        )
        self.assertEqual(code, 0, started)
        manifest = os.path.join(run_path, "run-manifest.yaml")
        self._write(manifest, "run_id: run-001\nbuild_id: build-001\n")
        code, finished = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "7",
            "--action-id", "run-prepare", "--status", "completed",
            "--output", "remote-sim:%s" % manifest,
            "--verification", "manifest inspected", "--readiness", "run=prepared",
        )
        self.assertEqual(code, 0, finished)
        code, shown = self.cli(STATE, "show", "--case", case)
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["state"]["resources"]["build"]["current_id"], build_id)
        build_record = shown["state"]["resources"]["build"]["identities"][0]
        self.assertEqual(build_record["source_revision"]["kind"], "snapshot")
        self.assertEqual(build_record["source_revision"]["snapshot_id"], materialized["snapshot_id"])
        run_record = shown["state"]["resources"]["run"]["identities"][0]
        self.assertEqual(run_record["build_id"], build_id)

    def test_suspend_registry_and_control_state_is_separate(self):
        created = self.create_case("separate")
        case = created["case_dir"]
        self.assertFalse(case.startswith(self.source + os.sep))
        self.assertTrue(os.path.isfile(os.path.join(case, "case.json")))
        self.assertFalse(os.path.exists(os.path.join(self.source, "_case")))
        code, payload = self.cli(STATE, "suspend", "--case", created["case_uid"],
                                 "--expected-revision", "0", "--summary", "pause")
        self.assertEqual(code, 0, payload)
        code, listed = self.cli(STATE, "list")
        self.assertEqual(code, 0, listed)
        self.assertEqual(listed["cases"][0]["case_status"], "suspended")
        with open(os.path.join(self.home, "registry.json"), "w") as handle:
            json.dump({"schema_version": 1, "updated_at": "", "cases": {}}, handle)
        code, rebuilt = self.cli(
            STATE, "rebuild-registry", "--scan-root", os.path.dirname(case)
        )
        self.assertEqual(code, 0, rebuilt)
        self.assertEqual(rebuilt["cases"], 1)
        code, shown = self.cli(STATE, "show", "--case", created["case_uid"])
        self.assertEqual(code, 0, shown)

    def test_control_root_inside_source_is_rejected(self):
        forbidden = os.path.join(self.source, "router-control")
        code, payload = self.cli(
            STATE, "create", "--case-dir", forbidden, "--case-id", "bad-control",
            "--source-authority", "local:%s" % self.source,
            "--pgen-locator", "local:%s" % os.path.join(self.source, "pgen.hpp"),
            "--toml-locator", "local:%s" % os.path.join(self.source, "case.toml"),
            "--design-locator", "local:%s" % os.path.join(self.source, "docs", "design.md"),
            "--goal", "must fail",
        )
        self.assertEqual(code, 2)
        self.assertIn("separate", payload["error"])
        self.assertFalse(os.path.exists(forbidden))

    def test_explicit_data_purge_contract(self):
        created = self.create_case("purge")
        case = created["case_dir"]
        run_data = os.path.join(self.remote, "run", "purge-data")
        os.makedirs(run_data)
        self._write(os.path.join(run_data, "fields.bp"), "raw\n")
        code, reconciled = self.cli(
            STATE, "reconcile", "--case", case, "--expected-revision", "0",
            "--readiness", "data=ready",
            "--evidence", "data=remote-sim:%s" % run_data,
        )
        self.assertEqual(code, 0, reconciled)
        self.assertIn("data.purge", reconciled["allowed_actions"])

        receipt = os.path.join(self.remote, "staging", "purge-receipt.json")
        common = [
            "start-action", "--case", case, "--expected-revision", "1",
            "--action-id", "purge-1", "--action-type", "data.purge",
            "--owner", "router", "--execution-domain", "router",
            "--execution-site", "remote-sim", "--goal", "delete authorized data",
            "--input", "remote-sim:%s" % run_data,
            "--read-root", "remote-sim:%s" % run_data,
            "--write-root", "remote-sim:%s" % run_data,
            "--write-root", "remote-sim:%s" % os.path.dirname(receipt),
            "--expected-output", "remote-sim:%s" % receipt,
            "--acceptance-check", "receipt exists",
        ]
        code, rejected = self.cli(STATE, *common)
        self.assertEqual(code, 2)
        self.assertIn("authorization", rejected["error"])

        code, started = self.cli(STATE, *(common + ["--authorization", "explicit test request"]))
        self.assertEqual(code, 0, started)
        shutil.rmtree(run_data)
        self._write(receipt, "{}\n")
        code, finished = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "2",
            "--action-id", "purge-1", "--status", "completed",
            "--output", "remote-sim:%s" % receipt,
            "--verification", "target missing and receipt inspected",
            "--readiness", "data=absent",
        )
        self.assertEqual(code, 0, finished)
        self.assertNotIn("data.purge", finished["allowed_actions"])

    def test_v2_migration_is_non_destructive(self):
        legacy = os.path.join(self.temp, "legacy-case")
        os.makedirs(os.path.join(legacy, "_case"))
        self._write(os.path.join(legacy, "pgen.hpp"), "// old\n")
        old = {
            "schema_version": 2, "revision": 4, "case_id": "old",
            "case_status": "active",
            "scope": {"pgen_path": os.path.join(legacy, "pgen.hpp")},
            "memory": {"goal": "old goal", "done_when": []},
            "workflow": {"workflow_id": "wf-old", "type": "new-simulation", "status": "active"},
        }
        with open(os.path.join(legacy, "_case", "case.json"), "w") as handle:
            json.dump(old, handle)
        code, dry = self.cli(STATE, "migrate-case", "--legacy-case", legacy, "--dry-run")
        self.assertEqual(code, 0, dry)
        self.assertFalse(os.path.exists(os.path.join(legacy, "_case", "migration-backup.json")))
        code, committed = self.cli(STATE, "migrate-case", "--legacy-case", legacy, "--commit")
        self.assertEqual(code, 0, committed)
        self.assertTrue(os.path.isfile(os.path.join(legacy, "pgen.hpp")))
        self.assertTrue(os.path.isfile(os.path.join(legacy, "_case", "migration-backup.json")))
        with open(os.path.join(legacy, "_case", "case.json")) as handle:
            self.assertEqual(json.load(handle)["case_status"], "suspended")
        self.assertTrue(os.path.isdir(os.path.join(committed["case_dir"], "evidence", "legacy-v2-control")))


if __name__ == "__main__":
    unittest.main()
