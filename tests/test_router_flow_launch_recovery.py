from __future__ import print_function

import json
import os
import shutil
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_router_common import ensure_home, now_utc, save_site_profile  # noqa: E402
from entity_router_flow_runners import _launch_comment, run_step  # noqa: E402


class RouterLaunchRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-launch-recovery-")
        self.home = ensure_home(os.path.join(self.temp, "control"))
        self.run_root = os.path.join(self.temp, "run")
        self.bin = os.path.join(self.temp, "bin")
        os.makedirs(self.run_root)
        os.makedirs(self.bin)
        self.script = os.path.join(self.run_root, "submit.sh")
        self.receipt = os.path.join(self.run_root, "launch-receipt.json")
        self.write(self.script, "#!/bin/sh\n")
        save_site_profile(self.home, {
            "schema_version": 1, "site_id": "slurm", "display_name": "slurm",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "slurm"},
            "roots": {"run_root": self.run_root}, "shared_mappings": [],
            "created_at": now_utc(), "updated_at": now_utc(),
        })
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin + os.pathsep + self.old_path

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        shutil.rmtree(self.temp)

    def write(self, path, value, executable=False):
        with open(path, "w") as handle:
            handle.write(value)
        if executable:
            os.chmod(path, 0o755)

    def step(self):
        return {
            "case_uid": "case-launch", "action_id": "launch-1",
            "action_type": "run.launch", "execution_site_id": "slurm",
            "runner": "run.launch.v1",
            "read_roots": [{"site_id": "slurm", "path": self.run_root}],
            "write_roots": [{"site_id": "slurm", "path": self.run_root}],
            "protected_paths": [],
            "runner_args": {
                "run_root": {"site_id": "slurm", "path": self.run_root},
                "submit_script": {"site_id": "slurm", "path": self.script},
                "job_name": "entity-case-launch", "submit_user": "tester",
                "receipt": {"site_id": "slurm", "path": self.receipt},
            },
        }

    def intent(self):
        observed_at = now_utc()
        with open(self.receipt, "w") as handle:
            json.dump({
                "schema_version": 1, "case_uid": "case-launch", "action_id": "launch-1",
                "flow_request_hash": "sha256:" + "a" * 64, "runner": "run.launch.v1",
                "state": "intent_written", "attempt": 1,
                "intent_written_at": observed_at, "effect_identity": {}, "outputs": [],
                "stdout": {"sha256": "", "bytes": 0, "tail": ""},
                "stderr": {"sha256": "", "bytes": 0, "tail": ""},
            }, handle)
        return observed_at

    def test_verified_receipt_replay_never_resubmits(self):
        marker = os.path.join(self.temp, "submits")
        self.write(os.path.join(self.bin, "sbatch"),
                   "#!/bin/sh\necho x >> '%s'\nprintf '42\\n'\n" % marker, True)
        self.write(os.path.join(self.bin, "squeue"), "#!/bin/sh\nexit 0\n", True)
        first = run_step(self.home, self.step(), "sha256:" + "a" * 64)
        second = run_step(self.home, self.step(), "sha256:" + "a" * 64)
        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "completed")
        with open(marker) as handle:
            self.assertEqual(len(handle.readlines()), 1)

    def test_intent_with_one_scheduler_match_recovers_without_submit(self):
        observed_at = self.intent()
        marker = os.path.join(self.temp, "submitted")
        self.write(os.path.join(self.bin, "sbatch"),
                   "#!/bin/sh\ntouch '%s'\n" % marker, True)
        comment = _launch_comment(self.step(), "sha256:" + "a" * 64)
        self.write(os.path.join(self.bin, "squeue"),
                   "#!/bin/sh\nprintf '77|entity-case-launch|tester|%s|RUNNING|%s|%s\\n'\n" %
                   (observed_at, self.run_root, comment), True)
        outcome = run_step(self.home, self.step(), "sha256:" + "a" * 64)
        self.assertEqual(outcome.status, "completed")
        self.assertFalse(os.path.exists(marker))
        with open(self.receipt) as handle:
            receipt = json.load(handle)
        self.assertEqual(receipt["effect_identity"]["job_id"], "77")
        self.assertEqual(receipt["state"], "outputs_verified")

    def test_multiple_scheduler_matches_are_anomaly(self):
        observed_at = self.intent()
        comment = _launch_comment(self.step(), "sha256:" + "a" * 64)
        self.write(os.path.join(self.bin, "squeue"),
                   "#!/bin/sh\nprintf '77|entity-case-launch|tester|%s|RUNNING|%s|%s\\n78|entity-case-launch|tester|%s|RUNNING|%s|%s\\n'\n" %
                   (observed_at, self.run_root, comment,
                    observed_at, self.run_root, comment), True)
        self.write(os.path.join(self.bin, "sbatch"), "#!/bin/sh\nexit 99\n", True)
        outcome = run_step(self.home, self.step(), "sha256:" + "a" * 64)
        self.assertEqual(outcome.status, "anomaly")
        self.assertIn("multiple", outcome.message)

    def test_unrelated_same_name_job_is_not_adopted(self):
        observed_at = self.intent()
        marker = os.path.join(self.temp, "submitted")
        self.write(os.path.join(self.bin, "sbatch"),
                   "#!/bin/sh\ntouch '%s'\nprintf '99\\n'\n" % marker, True)
        self.write(os.path.join(self.bin, "squeue"),
                   "#!/bin/sh\nprintf '77|entity-case-launch|tester|%s|RUNNING|%s|wrong-comment\\n'\n" %
                   (observed_at, self.run_root), True)
        outcome = run_step(self.home, self.step(), "sha256:" + "a" * 64)
        self.assertEqual(outcome.status, "completed")
        self.assertTrue(os.path.exists(marker))
        with open(self.receipt) as handle:
            receipt = json.load(handle)
        self.assertEqual(receipt["effect_identity"]["job_id"], "99")


if __name__ == "__main__":
    unittest.main()
