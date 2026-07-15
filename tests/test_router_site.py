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
SITE = os.path.join(SCRIPTS, "entity_router_site.py")
STATE = os.path.join(SCRIPTS, "entity_router_state.py")
REMOTE = os.path.join(SCRIPTS, "entity_router_remote.py")


class RouterSiteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-site-")
        self.home = os.path.join(self.temp, "control")
        self.source = os.path.realpath(os.path.join(self.temp, "source"))
        self.target = os.path.realpath(os.path.join(self.temp, "target"))
        os.makedirs(self.source)
        os.makedirs(self.target)
        subprocess.check_call(["git", "init", "-q", self.source])
        subprocess.check_call(["git", "-C", self.source, "config", "user.email", "test@example.invalid"])
        subprocess.check_call(["git", "-C", self.source, "config", "user.name", "Test"])
        self.write(os.path.join(self.source, "tracked.txt"), "tracked\n")
        subprocess.check_call(["git", "-C", self.source, "add", "."])
        subprocess.check_call(["git", "-C", self.source, "commit", "-qm", "base"])
        self.add_site("source", self.source)
        self.add_site("build", self.target)

    def tearDown(self):
        shutil.rmtree(self.temp)

    def write(self, path, value):
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w") as handle:
            handle.write(value)

    def cli(self, script, *args):
        proc = subprocess.run([sys.executable, script, "--router-home", self.home, *args],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc.returncode, json.loads(proc.stdout)

    def add_site(self, site_id, root):
        code, payload = self.cli(
            SITE, "add", "--site-id", site_id, "--transport", "local",
            "--source-root", root, "--build-root", root,
            "--staging-root", root,
        )
        self.assertEqual(code, 0, payload)

    def test_dirty_snapshot_is_content_addressed_and_verified(self):
        self.write(os.path.join(self.source, "untracked.txt"), "dirty\n")
        code, payload = self.cli(
            SITE, "materialize", "--mode", "snapshot",
            "--source", "source:%s" % self.source,
            "--target", "build:%s" % self.target,
        )
        self.assertEqual(code, 0, payload)
        destination = payload["materialized"]["path"]
        self.assertTrue(os.path.isfile(os.path.join(destination, "untracked.txt")))
        code, repeated = self.cli(
            SITE, "materialize", "--mode", "snapshot",
            "--source", "source:%s" % self.source,
            "--target", "build:%s" % self.target,
        )
        self.assertEqual(code, 0, repeated)
        self.assertEqual(repeated["snapshot_id"], payload["snapshot_id"])
        self.write(os.path.join(destination, "untracked.txt"), "tampered\n")
        code, failed = self.cli(SITE, "verify-snapshot", "--path", destination)
        self.assertEqual(code, 2)
        self.assertIn("verification failed", failed["error"])

    def test_python36_remote_helper_archives_and_installs_snapshot(self):
        self.write(os.path.join(self.source, "remote-dirty.txt"), "remote\n")
        archive = os.path.join(self.temp, "remote-source.tar")
        installed = os.path.join(self.temp, "installed")
        process = subprocess.run(
            [sys.executable, REMOTE, "snapshot-archive", "--source", self.source,
             "--archive", archive], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        manifest = json.loads(process.stdout)
        process = subprocess.run(
            [sys.executable, REMOTE, "snapshot-install", "--archive", archive,
             "--target-root", installed], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        payload = json.loads(process.stdout)
        self.assertEqual(payload["snapshot_id"], manifest["snapshot_id"])
        self.assertTrue(os.path.isfile(os.path.join(payload["destination"], "remote-dirty.txt")))

    def test_git_ref_and_external_require_exact_revision(self):
        commit = subprocess.check_output(["git", "-C", self.source, "rev-parse", "HEAD"], text=True).strip()
        checkout = os.path.join(self.target, "checkout")
        code, payload = self.cli(
            SITE, "materialize", "--mode", "git-ref", "--target", "build:%s" % checkout,
            "--repository", self.source, "--commit", commit,
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.cli(
            SITE, "materialize", "--mode", "external",
            "--source", "source:%s" % self.source, "--target", "build:%s" % checkout,
        )
        self.assertEqual(code, 0, payload)
        code, missing_map = self.cli(
            SITE, "materialize", "--mode", "shared",
            "--source", "source:%s" % self.source, "--target", "build:%s" % checkout,
        )
        self.assertEqual(code, 2)
        self.assertIn("declared", missing_map["error"])
        code, profile = self.cli(
            SITE, "add", "--site-id", "source", "--transport", "local",
            "--source-root", self.source, "--staging-root", self.source,
            "--shared-map", "build=%s|%s" % (self.source, checkout),
        )
        self.assertEqual(code, 0, profile)
        code, payload = self.cli(
            SITE, "materialize", "--mode", "shared",
            "--source", "source:%s" % self.source, "--target", "build:%s" % checkout,
        )
        self.assertEqual(code, 0, payload)
        self.write(os.path.join(checkout, "tracked.txt"), "diverged\n")
        code, payload = self.cli(
            SITE, "materialize", "--mode", "external",
            "--source", "source:%s" % self.source, "--target", "build:%s" % checkout,
        )
        self.assertEqual(code, 2)
        self.assertIn("differ", payload["error"])

    def test_authority_transfer_is_an_explicit_action(self):
        replica = os.path.join(self.target, "replica")
        subprocess.check_call(["git", "clone", "-q", self.source, replica])
        args = [
            "create", "--controller-site", "source", "--case-id", "transfer",
            "--source-authority", "source:%s" % self.source,
            "--source-replica", "build:%s" % replica,
            "--pgen-locator", "source:%s" % os.path.join(self.source, "pgen.hpp"),
            "--toml-locator", "source:%s" % os.path.join(self.source, "case.toml"),
            "--design-locator", "source:%s" % os.path.join(self.source, "docs", "design.md"),
            "--goal", "transfer authority",
        ]
        code, created = self.cli(STATE, *args)
        self.assertEqual(code, 0, created)
        self.assertIn("source.transfer-authority", created["state"]["workflow"]["allowed_actions"])
        code, started = self.cli(
            STATE, "start-action", "--case", created["case_uid"], "--expected-revision", "0",
            "--action-id", "transfer-1", "--action-type", "source.transfer-authority",
            "--owner", "router", "--execution-domain", "playbook-sync",
            "--execution-site", "build", "--goal", "make replica authoritative",
            "--write-root", "build:%s" % replica,
        )
        self.assertEqual(code, 0, started)
        code, finished = self.cli(
            STATE, "finish-action", "--case", created["case_uid"], "--expected-revision", "1",
            "--action-id", "transfer-1", "--status", "completed",
            "--new-authority", "build:%s" % replica,
        )
        self.assertEqual(code, 0, finished)
        code, shown = self.cli(STATE, "show", "--case", created["case_uid"])
        self.assertEqual(code, 0, shown)
        self.assertEqual(shown["state"]["source"]["authority"]["site_id"], "build")
        self.assertEqual(shown["state"]["artifacts"]["pgen"]["site_id"], "build")

    def test_slurm_scheduler_probe_records_current_observation(self):
        bindir = os.path.join(self.temp, "bin")
        os.makedirs(bindir)
        squeue = os.path.join(bindir, "squeue")
        self.write(squeue, "#!/bin/sh\nprintf RUNNING\n")
        os.chmod(squeue, 0o755)
        code, profile = self.cli(
            SITE, "add", "--site-id", "scheduler", "--transport", "local",
            "--scheduler", "slurm", "--run-root", self.target,
        )
        self.assertEqual(code, 0, profile)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = bindir + os.pathsep + old_path
        try:
            code, payload = self.cli(
                SITE, "scheduler-probe", "--site-id", "scheduler", "--job-id", "42"
            )
        finally:
            os.environ["PATH"] = old_path
        self.assertEqual(code, 0, payload)
        evidence = payload["evidence"]
        self.assertEqual(evidence["kind"], "scheduler")
        self.assertEqual(evidence["fingerprint"]["state"], "RUNNING")

    def test_unreachable_ssh_site_is_not_reported_as_current(self):
        code, profile = self.cli(
            SITE, "add", "--site-id", "offline", "--transport", "ssh",
            "--ssh-alias", "127.0.0.1", "--scheduler", "slurm",
            "--run-root", "/remote/run",
        )
        self.assertEqual(code, 0, profile)
        code, payload = self.cli(SITE, "verify", "--site-id", "offline")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["issues"])


if __name__ == "__main__":
    unittest.main()
