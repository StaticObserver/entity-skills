from __future__ import print_function

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
STATUS = os.path.join(SCRIPTS, "entity_router_status.py")
sys.path.insert(0, SCRIPTS)

import entity_router_status as router_status


class RouterStatusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-status-")
        self.run_root = os.path.join(self.temp, "run-001")
        self.bin = os.path.join(self.temp, "bin")
        os.makedirs(os.path.join(self.run_root, "logs"))
        os.makedirs(os.path.join(self.run_root, "data", "fields", "fields.000001.bp"))
        os.makedirs(os.path.join(self.run_root, "data", "fields", "fields.000002.bp"))
        os.makedirs(os.path.join(self.run_root, "data", "checkpoints", "step-000001.bp"))
        os.makedirs(self.bin)
        self.write(
            os.path.join(self.run_root, "logs", "stdout.log"),
            "Step: 120 / 1000\n"
            "\x1b[0mTime:\x1b[90m \x1b[92m12.5\x1b[0m"
            "..................\x1b[90m[Δt = 0.0013]\x1b[0m\n"
            "Elapsed time: 2min\nRemaining time: 14min\n",
        )
        self.write(os.path.join(self.run_root, "logs", "stderr.log"), "")
        self.write(
            os.path.join(self.run_root, "data", "fields", "fields.000002.bp", "data.0"),
            "field\n",
        )
        self.write(
            os.path.join(self.run_root, "data", "checkpoints", "step-000001.bp", "data.0"),
            "checkpoint\n",
        )
        self.write(
            os.path.join(self.bin, "squeue"),
            "#!/bin/sh\nprintf '42|RUNNING|00:02:00|node-a\\n'\n",
            executable=True,
        )
        self.write(
            os.path.join(self.bin, "sacct"),
            "#!/bin/sh\nprintf '42|RUNNING|00:02:00|0:0|\\n'\n",
            executable=True,
        )

    def tearDown(self):
        shutil.rmtree(self.temp)

    def write(self, path, value, executable=False):
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w") as handle:
            handle.write(value)
        if executable:
            os.chmod(path, 0o755)

    def tree_hash(self):
        digest = hashlib.sha256()
        for root, dirs, names in os.walk(self.run_root):
            for name in sorted(names):
                path = os.path.join(root, name)
                digest.update(os.path.relpath(path, self.run_root).encode("utf-8"))
                with open(path, "rb") as handle:
                    digest.update(handle.read())
        return digest.hexdigest()

    def cli(self, *extra):
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env.get("PATH", "")
        process = subprocess.run(
            [
                sys.executable, STATUS,
                "--scheduler", "slurm",
                "--run-root", self.run_root,
                "--job-id", "42",
                "--progress-log", "logs/stdout.log",
                "--stderr-log", "logs/stderr.log",
                "--fields-root", "data/fields",
                "--checkpoint-root", "data/checkpoints",
                "--target-time", "100.0",
            ] + list(extra),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        return process.returncode, json.loads(process.stdout)

    def test_quick_status_is_read_only_and_compact(self):
        before = self.tree_hash()
        code, payload = self.cli()
        after = self.tree_hash()
        self.assertEqual(code, 0, payload)
        self.assertEqual(before, after)
        self.assertEqual(payload["kind"], "run.status")
        self.assertFalse(payload["state_mutated"])
        self.assertEqual(payload["remote_calls"], 0)
        self.assertEqual(payload["scheduler"]["state"], "RUNNING")
        self.assertEqual(payload["progress"]["latest_step"], 120)
        self.assertEqual(payload["progress"]["simulation_time"], 12.5)
        self.assertAlmostEqual(payload["progress"]["percent_complete"], 12.5)
        self.assertEqual(payload["fields"]["count"], 2)
        self.assertEqual(payload["checkpoints"]["count"], 1)
        self.assertNotIn("total_bytes", payload["fields"])
        self.assertEqual(payload["recommendation"], "observe_only")

    def test_progress_parser_accepts_scientific_notation(self):
        payload = router_status.parse_progress("Time: -1.25e+02 / +5.0E+02\n")
        self.assertEqual(payload["simulation_time"], -125.0)
        self.assertEqual(payload["target_simulation_time"], 500.0)
        self.assertAlmostEqual(payload["percent_complete"], -25.0)

    def test_malformed_time_line_does_not_abort_or_replace_valid_progress(self):
        payload = router_status.parse_progress(
            "Time: 12.5 / 100.0\nTime: 13.0.5..................[Δt = 0.1]\n"
        )
        self.assertEqual(payload["simulation_time"], 12.5)
        self.assertEqual(payload["target_simulation_time"], 100.0)
        self.assertAlmostEqual(payload["percent_complete"], 12.5)

    def test_full_status_adds_bounded_inventory(self):
        code, payload = self.cli("--profile", "full")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["fields"]["member_file_count"], 1)
        self.assertEqual(payload["checkpoints"]["member_file_count"], 1)
        self.assertGreater(payload["fields"]["total_bytes"], 0)

    def test_terminal_or_fatal_status_requires_full_monitor(self):
        self.write(os.path.join(self.bin, "squeue"), "#!/bin/sh\nexit 0\n", executable=True)
        self.write(
            os.path.join(self.bin, "sacct"),
            "#!/bin/sh\nprintf '42|COMPLETED|00:10:00|0:0|\\n'\n",
            executable=True,
        )
        code, payload = self.cli()
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["terminal"])
        self.assertEqual(payload["recommendation"], "promote_to_run_monitor")

        self.write(os.path.join(self.run_root, "logs", "stderr.log"), "fatal: broken\n")
        code, payload = self.cli()
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["anomaly"])
        self.assertEqual(payload["recommendation"], "promote_to_run_monitor")

    def test_status_rejects_paths_outside_run_root(self):
        code, payload = self.cli("--progress-log", "../outside.log")
        self.assertEqual(code, 2)
        self.assertIn("escapes run root", payload["error"])

        outside = os.path.join(self.temp, "outside.log")
        self.write(outside, "secret\n")
        os.symlink(outside, os.path.join(self.run_root, "logs", "linked.log"))
        code, payload = self.cli("--progress-log", "logs/linked.log")
        self.assertEqual(code, 2)
        self.assertIn("escapes run root", payload["error"])

    def test_scheduler_probe_failure_promotes_to_monitor(self):
        self.write(os.path.join(self.bin, "squeue"), "#!/bin/sh\nexit 9\n", executable=True)
        self.write(os.path.join(self.bin, "sacct"), "#!/bin/sh\nexit 9\n", executable=True)
        code, payload = self.cli()
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["scheduler"]["state"], "PROBE_FAILED")
        self.assertTrue(payload["anomaly"])
        self.assertEqual(payload["recommendation"], "promote_to_run_monitor")

    def test_running_slurm_status_skips_accounting_query(self):
        with mock.patch.object(
            router_status, "command",
            return_value=(0, "42|RUNNING|00:02:00|node-a\n", ""),
        ) as probe:
            payload = router_status.scheduler_status("slurm", "42")
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(payload["state"], "RUNNING")

    def test_ssh_transport_uses_exactly_one_remote_call(self):
        config = {
            "site_id": "remote",
            "run_id": "run-001",
            "run_root": "/remote/run-001",
            "scheduler": "slurm",
            "job_id": "42",
            "pid": None,
            "pid_start_ticks": "",
            "progress_log": "logs/stdout.log",
            "stderr_log": "logs/stderr.log",
            "fields_root": "data/fields",
            "checkpoint_root": "data/checkpoints",
            "field_pattern": "fields.*.bp",
            "checkpoint_pattern": "step-*.bp",
            "total_steps": None,
            "target_time": None,
            "tail_bytes": 131072,
            "profile": "quick",
        }
        observed = {
            "schema_version": 1,
            "kind": "run.status",
            "state_mutated": False,
            "recommendation": "observe_only",
        }
        profile = {
            "site_id": "remote",
            "transport": {"kind": "ssh", "ssh_alias": "remote"},
            "scheduler": {"kind": "slurm"},
            "roots": {},
        }
        with mock.patch.object(
            router_status, "run_on_site",
            return_value=(0, json.dumps(observed), ""),
        ) as probe:
            payload = router_status.collect_site_status(self.temp, profile, config)
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(payload["remote_calls"], 1)
        self.assertFalse(payload["state_mutated"])


if __name__ == "__main__":
    unittest.main()
