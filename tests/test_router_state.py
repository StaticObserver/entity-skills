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
        data_path = os.path.join(run_path, "data")
        analysis_path = os.path.join(self.remote, "analysis", created["case_uid"], run_id)
        os.makedirs(run_path)
        target_path = os.path.join(self.temp, "workflow-target.json")
        target = {
            "schema_version": 1,
            "target_id": "target-run-001",
            "source_revision_hash": "",
            "build_id": build_id,
            "build_spec_hash": "",
            "run_id": run_id,
            "run_spec_hash": "sha256:run-spec-001",
            "data_id": "",
            "analysis_id": "",
            "criteria": [],
        }
        self._write(target_path, json.dumps(target))
        code, targeted = self.cli(
            STATE, "set-workflow-target", "--case", case, "--expected-revision", "6",
            "--target", target_path,
        )
        self.assertEqual(code, 0, targeted)
        code, started = self.cli(
            STATE, "start-action", "--case", case, "--expected-revision", "7",
            "--action-id", "run-prepare", "--action-type", "run.prepare",
            "--owner", "playbook-run", "--execution-domain", "playbook-run",
            "--execution-site", "remote-sim", "--identity-id", run_id,
            "--flow-id", "flow-001",
            "--flow-request-hash", "sha256:" + "a" * 64,
            "--target-hash", targeted["target_hash"],
            "--flow-step-index", "0", "--runner", "run.prepare.v1",
            "--spec-hash", "sha256:run-spec-001", "--parent", "build_id=" + build_id,
            "--resource-binding", "run=remote-sim:%s" % run_path,
            "--resource-binding", "data=remote-sim:%s" % data_path,
            "--resource-binding", "analysis=remote-sim:%s" % analysis_path,
            "--goal", "prepare immutable run", "--read-root", "remote-sim:%s" % build_path,
            "--input", "remote-sim:%s" % executable,
            "--write-root", "remote-sim:%s" % run_path,
            "--expected-output", "remote-sim:%s" % os.path.join(run_path, "run-manifest.yaml"),
        )
        self.assertEqual(code, 0, started)
        manifest = os.path.join(run_path, "run-manifest.yaml")
        self._write(manifest, "run_id: run-001\nbuild_id: build-001\n")
        code, finished = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "8",
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
        self.assertEqual(run_record["spec_hash"], "sha256:run-spec-001")
        self.assertEqual(shown["state"]["resources"]["run"]["active"]["path"], os.path.realpath(run_path))
        self.assertEqual(shown["state"]["resources"]["data"]["root"]["path"], os.path.realpath(data_path))
        self.assertEqual(shown["state"]["resources"]["analysis"]["root"]["path"], os.path.realpath(analysis_path))
        self.assertEqual(shown["state"]["readiness"]["data"]["status"], "unknown")
        self.assertEqual(shown["state"]["readiness"]["analysis"]["status"], "none")

        inventory = os.path.join(analysis_path, "nt2-inventory.json")
        code, started = self.cli(
            STATE, "start-action", "--case", case, "--expected-revision", "9",
            "--action-id", "data-inspect", "--action-type", "data.inspect",
            "--owner", "entity-nt2py", "--execution-domain", "entity-nt2py",
            "--execution-site", "remote-sim", "--goal", "inspect current run data",
            "--flow-id", "flow-001", "--flow-request-hash", "sha256:" + "a" * 64,
            "--target-hash", targeted["target_hash"],
            "--flow-step-index", "1", "--runner", "data.inspect.v1",
            "--parent", "run_id=" + run_id,
            "--resource-binding", "data=remote-sim:%s" % data_path,
            "--resource-binding", "analysis=remote-sim:%s" % analysis_path,
            "--write-root", "remote-sim:%s" % analysis_path,
            "--expected-output", "remote-sim:%s" % inventory,
        )
        self.assertEqual(code, 0, started)
        self._write(inventory, '{"schema_version": 1, "status": "ok"}\n')
        code, finished = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "10",
            "--action-id", "data-inspect", "--status", "completed",
            "--output", "remote-sim:%s" % inventory,
            "--readiness", "data=ready",
        )
        self.assertEqual(code, 0, finished)
        code, shown = self.cli(STATE, "show", "--case", case)
        self.assertEqual(code, 0, shown)
        data_id = shown["state"]["resources"]["data"]["current_id"]
        self.assertTrue(data_id.startswith("data-"))
        data_record = shown["state"]["resources"]["data"]["identities"][0]
        self.assertEqual(data_record["parents"]["run_id"], run_id)

        report = os.path.join(analysis_path, "report.json")
        code, started = self.cli(
            STATE, "start-action", "--case", case, "--expected-revision", "11",
            "--action-id", "analysis-run", "--action-type", "analysis.run",
            "--owner", "playbook-analysis", "--execution-domain", "playbook-analysis",
            "--execution-site", "remote-sim", "--goal", "analyze current data",
            "--flow-id", "flow-001", "--flow-request-hash", "sha256:" + "a" * 64,
            "--target-hash", targeted["target_hash"],
            "--flow-step-index", "2", "--runner", "owner-model.v1",
            "--spec-hash", "sha256:analysis-spec", "--parent", "data_id=" + data_id,
            "--resource-binding", "analysis=remote-sim:%s" % analysis_path,
            "--write-root", "remote-sim:%s" % analysis_path,
            "--expected-output", "remote-sim:%s" % report,
        )
        self.assertEqual(code, 0, started)
        self._write(report, '{"status": "complete"}\n')
        code, finished = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "12",
            "--action-id", "analysis-run", "--status", "completed",
            "--output", "remote-sim:%s" % report,
            "--readiness", "analysis=complete",
        )
        self.assertEqual(code, 0, finished)
        code, shown = self.cli(STATE, "show", "--case", case)
        self.assertEqual(code, 0, shown)
        analysis_record = shown["state"]["resources"]["analysis"]["identities"][0]
        self.assertEqual(analysis_record["parents"]["data_id"], data_id)

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

    def test_writer_lease_blocks_parallel_mutation_and_supports_handoff(self):
        created = self.create_case("writer-lease")
        case = created["case_dir"]
        codex = ["--actor-run-id", "codex-run", "--actor-provider", "codex"]
        claude = ["--actor-run-id", "claude-run", "--actor-provider", "claude"]

        code, acquired = self.cli(
            STATE, *(codex + [
                "acquire-writer", "--case", case, "--expected-revision", "0",
                "--lease-id", "lease-codex", "--ttl-seconds", "300",
            ])
        )
        self.assertEqual(code, 0, acquired)
        self.assertEqual(acquired["writer_lease"]["holder"]["run_id"], "codex-run")

        code, rejected = self.cli(
            STATE, *(claude + [
                "suspend", "--case", case, "--expected-revision", "1",
                "--summary", "must not win",
            ])
        )
        self.assertEqual(code, 2)
        self.assertIn("another Agent run", rejected["error"])

        code, suspended = self.cli(
            STATE, *(codex + [
                "--writer-lease-id", "lease-codex", "suspend", "--case", case,
                "--expected-revision", "1", "--summary", "handoff ready",
            ])
        )
        self.assertEqual(code, 0, suspended)
        code, handed = self.cli(
            STATE, *(codex + [
                "--writer-lease-id", "lease-codex", "handoff-writer", "--case", case,
                "--expected-revision", "2", "--new-lease-id", "lease-claude",
                "--to-run-id", "claude-run", "--to-provider", "claude",
                "--ttl-seconds", "300",
            ])
        )
        self.assertEqual(code, 0, handed)
        self.assertEqual(handed["writer_lease"]["holder"]["run_id"], "claude-run")

        code, resumed = self.cli(
            STATE, *(claude + [
                "--writer-lease-id", "lease-claude", "resume", "--case", case,
                "--expected-revision", "3",
            ])
        )
        self.assertEqual(code, 0, resumed)
        code, released = self.cli(
            STATE, *(claude + [
                "--writer-lease-id", "lease-claude", "release-writer", "--case", case,
                "--expected-revision", "4",
            ])
        )
        self.assertEqual(code, 0, released)
        code, status = self.cli(STATE, "writer-status", "--case", case)
        self.assertEqual(code, 0, status)
        self.assertFalse(status["active"])
        self.assertIsNone(status["lease"])

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

    def test_v2_migration_preserves_remote_scope_and_can_be_finalized(self):
        legacy = os.path.join(self.temp, "legacy-case")
        os.makedirs(os.path.join(legacy, "_case"))
        self._write(os.path.join(legacy, "pgen.hpp"), "// old\n")
        old = {
            "schema_version": 2, "revision": 4, "case_id": "old",
            "case_status": "active",
            "scope": {"pgen_path": os.path.join(legacy, "pgen.hpp")},
            "memory": {"goal": "old goal", "done_when": [], "constraints": ["keep raw data"]},
            "workflow": {"workflow_id": "wf-old", "type": "new-simulation", "status": "active"},
        }
        with open(os.path.join(legacy, "_case", "case.json"), "w") as handle:
            json.dump(old, handle)
        run_root = os.path.join(self.remote, "run")
        active_run = os.path.join(run_root, "run-001")
        os.makedirs(active_run)
        migration_scope = [
            "--build-root", "remote-sim:%s" % os.path.join(self.remote, "build"),
            "--run-root", "remote-sim:%s" % run_root,
            "--data-root", "remote-sim:%s" % os.path.join(active_run, "data"),
            "--analysis-root", "remote-sim:%s" % os.path.join(active_run, "analysis"),
            "--active-run", "remote-sim:%s" % active_run,
            "--active-run-id", "run-001",
        ]
        code, dry = self.cli(STATE, "migrate-case", "--legacy-case", legacy,
                             *(migration_scope + ["--dry-run"]))
        self.assertEqual(code, 0, dry)
        self.assertEqual(dry["proposal"]["run_root"], "remote-sim:%s" % run_root)
        self.assertFalse(os.path.exists(os.path.join(legacy, "_case", "migration-backup.json")))
        code, committed = self.cli(STATE, "migrate-case", "--legacy-case", legacy,
                                   *(migration_scope + ["--commit"]))
        self.assertEqual(code, 0, committed)
        self.assertEqual(committed["state"]["resources"]["run"]["root"]["path"], os.path.realpath(run_root))
        self.assertEqual(committed["state"]["resources"]["run"]["active"]["path"], os.path.realpath(active_run))
        self.assertEqual(committed["state"]["memory"]["constraints"], ["keep raw data"])
        self.assertTrue(os.path.isfile(os.path.join(legacy, "pgen.hpp")))
        self.assertTrue(os.path.isfile(os.path.join(legacy, "_case", "migration-backup.json")))
        with open(os.path.join(legacy, "_case", "case.json")) as handle:
            self.assertEqual(json.load(handle)["case_status"], "suspended")
        self.assertTrue(os.path.isdir(os.path.join(committed["case_dir"], "evidence", "legacy-v2-control")))

        case = committed["case_dir"]
        code, reconciled = self.cli(
            STATE, "reconcile", "--case", case, "--expected-revision", "1",
            "--readiness", "run=running", "--observation", "run=external process active",
        )
        self.assertEqual(code, 0, reconciled)
        request = [
            "start-action", "--case", case, "--expected-revision", "2",
            "--action-id", "monitor-1", "--action-type", "run.monitor",
            "--owner", "playbook-run", "--execution-domain", "playbook-run",
            "--execution-site", "remote-sim", "--goal", "monitor migrated run",
            "--write-root", "remote-sim:%s" % active_run,
        ]
        code, started = self.cli(STATE, *request)
        self.assertEqual(code, 0, started)
        code, finished = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "3",
            "--action-id", "monitor-1", "--status", "completed",
            "--verification", "scope accepted",
        )
        self.assertEqual(code, 0, finished)

        code, finalized = self.cli(
            STATE, "finalize-migration", "--case", case, "--expected-revision", "4",
            "--authorization", "test explicitly authorizes v2 control cleanup",
            "--purge-control-copy",
        )
        self.assertEqual(code, 0, finalized)
        self.assertFalse(os.path.exists(os.path.join(legacy, "_case")))
        self.assertFalse(os.path.exists(os.path.join(case, "evidence", "legacy-v2-control")))
        self.assertTrue(os.path.isfile(finalized["receipt"]))

    def test_reconcile_resource_root_rejects_active_run_outside_root(self):
        created = self.create_case()
        outside = os.path.join(self.remote, "outside")
        code, payload = self.cli(
            STATE, "reconcile", "--case", created["case_dir"], "--expected-revision", "0",
            "--resource-root", "run=remote-sim:%s" % os.path.join(self.remote, "run"),
            "--active-run", "remote-sim:%s" % outside,
        )
        self.assertEqual(code, 2)
        self.assertIn("inside the configured run root", payload["error"])
        inside = os.path.join(self.remote, "run", "run-001")
        code, payload = self.cli(
            STATE, "reconcile", "--case", created["case_dir"], "--expected-revision", "0",
            "--active-run", "remote-sim:%s" % inside,
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.cli(
            STATE, "reconcile", "--case", created["case_dir"], "--expected-revision", "1",
            "--resource-root", "run=remote-sim:%s" % os.path.join(self.remote, "outside"),
        )
        self.assertEqual(code, 2)
        self.assertIn("inside the configured run root", payload["error"])

    def test_structured_target_controls_flow_hash_and_completion(self):
        created = self.create_case("targeted")
        case = created["case_dir"]
        target_path = os.path.join(self.temp, "target.json")
        target = {
            "schema_version": 1,
            "target_id": "target-initial",
            "source_revision_hash": "",
            "build_id": "",
            "build_spec_hash": "",
            "run_id": "",
            "run_spec_hash": "",
            "data_id": "",
            "analysis_id": "",
            "criteria": [{
                "id": "run-none",
                "subject": "run",
                "subject_id": "",
                "check": "terminal_status",
                "expected": "none",
            }],
        }
        self._write(target_path, json.dumps(target))
        code, targeted = self.cli(
            STATE, "set-workflow-target", "--case", case, "--expected-revision", "0",
            "--target", target_path,
        )
        self.assertEqual(code, 0, targeted)
        pgen = os.path.join(self.source, "pgen.hpp")
        flow_args = [
            "start-action", "--case", case, "--expected-revision", "1",
            "--action-id", "pgen-flow", "--action-type", "pgen.design",
            "--owner", "entity-pgen", "--execution-domain", "entity-pgen",
            "--execution-site", "local", "--goal", "prepare pgen",
            "--write-root", "local:%s" % pgen,
            "--flow-id", "flow-targeted", "--flow-request-hash", "sha256:" + "b" * 64,
            "--flow-step-index", "0", "--runner", "owner-model.v1",
        ]
        code, mismatch = self.cli(STATE, *(flow_args + ["--target-hash", "sha256:" + "c" * 64]))
        self.assertEqual(code, 2)
        self.assertIn("target hash", mismatch["error"])
        code, started = self.cli(STATE, *(flow_args + ["--target-hash", targeted["target_hash"]]))
        self.assertEqual(code, 0, started)
        with open(started["request"]) as handle:
            request = json.load(handle)
        self.assertEqual(request["orchestration"]["flow_id"], "flow-targeted")
        self.assertEqual(request["orchestration"]["target_hash"], targeted["target_hash"])
        code, cancelled = self.cli(
            STATE, "finish-action", "--case", case, "--expected-revision", "2",
            "--action-id", "pgen-flow", "--status", "cancelled",
        )
        self.assertEqual(code, 0, cancelled)
        code, completed = self.cli(
            STATE, "complete-workflow", "--case", case, "--expected-revision", "3",
            "--summary", "structured criterion passed",
        )
        self.assertEqual(code, 0, completed)

    def test_artifact_criterion_rejects_unrelated_cli_evidence(self):
        created = self.create_case("artifact-subject")
        case = created["case_dir"]
        target_path = os.path.join(self.temp, "artifact-target.json")
        target = {
            "schema_version": 1, "target_id": "analysis-artifact",
            "source_revision_hash": "", "build_id": "", "build_spec_hash": "",
            "run_id": "", "run_spec_hash": "", "data_id": "", "analysis_id": "",
            "criteria": [{
                "id": "analysis-output", "subject": "analysis", "subject_id": "",
                "check": "artifact_exists", "expected": True,
            }],
        }
        self._write(target_path, json.dumps(target))
        code, targeted = self.cli(
            STATE, "set-workflow-target", "--case", case, "--expected-revision", "0",
            "--target", target_path,
        )
        self.assertEqual(code, 0, targeted)
        code, rejected = self.cli(
            STATE, "complete-workflow", "--case", case, "--expected-revision", "1",
            "--summary", "must not complete", "--evidence",
            "local:%s" % os.path.join(self.source, "pgen.hpp"),
        )
        self.assertEqual(code, 2, rejected)
        self.assertIn("analysis-output", rejected["error"])

    def test_new_target_invalidates_conflicting_run_state(self):
        created = self.create_case("retarget")
        case = created["case_dir"]
        code, reconciled = self.cli(
            STATE, "reconcile", "--case", case, "--expected-revision", "0",
            "--readiness", "run=completed", "--observation", "run=old run complete",
            "--readiness", "data=ready", "--observation", "data=old data readable",
        )
        self.assertEqual(code, 0, reconciled)
        target_path = os.path.join(self.temp, "new-run-target.json")
        target = {
            "schema_version": 1,
            "target_id": "target-new-run",
            "source_revision_hash": "",
            "build_id": "",
            "build_spec_hash": "",
            "run_id": "run-new",
            "run_spec_hash": "sha256:new-run",
            "data_id": "",
            "analysis_id": "",
            "criteria": [],
        }
        self._write(target_path, json.dumps(target))
        code, targeted = self.cli(
            STATE, "set-workflow-target", "--case", case, "--expected-revision", "1",
            "--target", target_path,
        )
        self.assertEqual(code, 0, targeted)
        code, shown = self.cli(STATE, "show", "--case", case)
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["state"]["readiness"]["run"]["status"], "stale")
        self.assertEqual(shown["state"]["readiness"]["data"]["status"], "unknown")
        self.assertEqual(shown["state"]["readiness"]["analysis"]["status"], "none")


if __name__ == "__main__":
    unittest.main()
