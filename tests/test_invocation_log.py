#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LEDGER_SCRIPTS = ROOT / "skills" / "entity-ledger" / "scripts"
sys.path.insert(0, str(LEDGER_SCRIPTS))

import _invocation_log  # noqa: E402


class SanitizeTest(unittest.TestCase):
    def test_flag_value_form(self):
        out = _invocation_log.sanitize_argv(
            ["--token", "abc123", "run", "--Password", "hunter2"])
        self.assertEqual(out, ["--token", "<redacted>", "run",
                               "--Password", "<redacted>"])

    def test_flag_equals_form(self):
        out = _invocation_log.sanitize_argv(
            ["--api-key=sk-xyz", "--api_key=sk-xyz", "--credential=s3cr3t"])
        self.assertEqual(out, ["--api-key=<redacted>", "--api_key=<redacted>",
                               "--credential=<redacted>"])

    def test_flag_name_and_plain_args_kept(self):
        out = _invocation_log.sanitize_argv(
            ["--site", "astro", "tokenize", "--normal", "v"])
        self.assertEqual(out, ["--site", "astro", "tokenize", "--normal", "v"])

    def test_plural_flag_also_redacted(self):
        # the spec pattern matches substrings: --tokens is treated as secret
        out = _invocation_log.sanitize_argv(["--tokens", "abc"])
        self.assertEqual(out, ["--tokens", "<redacted>"])

    def test_trailing_secret_flag(self):
        out = _invocation_log.sanitize_argv(["--secret"])
        self.assertEqual(out, ["--secret"])


class RecordTest(unittest.TestCase):
    def _read_records(self, path):
        return [json.loads(line)
                for line in Path(path).read_text().splitlines() if line.strip()]

    def test_record_fields_and_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "custom", "inv.jsonl")
            with mock.patch.dict(os.environ,
                                 {_invocation_log.ENV_OVERRIDE: log}):
                _invocation_log.record(
                    "entity-test", "tool.py", ["--token", "s3cr3t"], 2,
                    time.time() - 0.05, error_type="ValueError",
                    script_file=__file__)
            (record,) = self._read_records(log)
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["skill"], "entity-test")
        self.assertEqual(record["script"], "tool.py")
        self.assertEqual(record["argv"], ["--token", "<redacted>"])
        self.assertEqual(record["exit_code"], 2)
        self.assertEqual(record["error_type"], "ValueError")
        self.assertTrue(record["ts"].endswith("Z"))
        self.assertGreaterEqual(record["duration_ms"], 0)
        self.assertIsInstance(record["pid"], int)
        self.assertTrue(record["host"])
        self.assertTrue(record["cwd"])

    def test_default_path_uses_utc_month(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"HOME": td}):
                os.environ.pop(_invocation_log.ENV_OVERRIDE, None)
                _invocation_log.record("s", "x.py", [], 0, time.time(),
                                       script_file=__file__)
            import datetime
            month = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
            log = Path(td) / ".entity-skills" / "observability" / \
                "invocations" / (month + ".jsonl")
            self.assertTrue(log.is_file())
            (record,) = self._read_records(log)
            self.assertEqual(record["skill"], "s")

    def test_skill_version_from_version_file(self):
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "inv.jsonl")
            with mock.patch.dict(os.environ,
                                 {_invocation_log.ENV_OVERRIDE: log}):
                _invocation_log.record(
                    "entity-ledger", "entityctl.py", [], 0, time.time(),
                    script_file=str(LEDGER_SCRIPTS / "entityctl.py"))
            (record,) = self._read_records(log)
        expected = (LEDGER_SCRIPTS.parent / "VERSION").read_text().strip()
        self.assertEqual(record.get("skill_version"), expected)

    def test_unwritable_destination_never_raises(self):
        with mock.patch.dict(os.environ,
                             {_invocation_log.ENV_OVERRIDE: "/dev/null/x/inv.jsonl"}):
            _invocation_log.record("s", "x.py", [], 0, time.time())  # no raise
        # and trace_invocation keeps host semantics even when logging fails
        with mock.patch.dict(os.environ,
                             {_invocation_log.ENV_OVERRIDE: "/dev/null/x/inv.jsonl"}):
            with self.assertRaises(SystemExit) as caught:
                with _invocation_log.trace_invocation("s", "x.py", []):
                    raise SystemExit(3)
        self.assertEqual(caught.exception.code, 3)

    def test_trace_records_exit_codes_and_error_types(self):
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "inv.jsonl")
            with mock.patch.dict(os.environ,
                                 {_invocation_log.ENV_OVERRIDE: log}):
                with _invocation_log.trace_invocation("s", "ok.py", []):
                    pass
                with self.assertRaises(SystemExit):
                    with _invocation_log.trace_invocation("s", "exit2.py", []):
                        raise SystemExit(2)
                with self.assertRaises(RuntimeError):
                    with _invocation_log.trace_invocation("s", "boom.py", []):
                        raise RuntimeError("kaput")
            records = self._read_records(log)
        self.assertEqual([r["exit_code"] for r in records], [0, 2, 1])
        self.assertEqual(records[2]["error_type"], "RuntimeError")
        self.assertNotIn("error_type", records[0])


class KillSwitchTest(unittest.TestCase):
    def test_off_disables_logging_completely(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ, {"HOME": td}):
                for value in ("off", "OFF", " Off "):
                    with mock.patch.dict(
                            os.environ,
                            {_invocation_log.ENV_OVERRIDE: value}):
                        _invocation_log.record(
                            "s", "x.py", [], 0, time.time())
            self.assertEqual(os.listdir(td), [])

    def test_only_the_exact_word_off_is_a_kill_switch(self):
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "offline")
            with mock.patch.dict(
                    os.environ, {_invocation_log.ENV_OVERRIDE: target}):
                _invocation_log.record("s", "x.py", [], 0, time.time())
            self.assertTrue(os.path.isfile(target))


class AgentHintTest(unittest.TestCase):
    def _one_record(self, extra_env):
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "inv.jsonl")
            env = {_invocation_log.ENV_OVERRIDE: log}
            # an empty value counts as unset: neutralize any hint variables
            # the surrounding agent may have exported
            env.update((name, "") for name in _invocation_log.AGENT_ENV_HINTS)
            env.update(extra_env)
            with mock.patch.dict(os.environ, env):
                _invocation_log.record("s", "x.py", [], 0, time.time(),
                                       script_file=__file__)
            (record,) = [json.loads(line)
                         for line in Path(log).read_text().splitlines()]
        return record

    def test_hint_records_variable_names_not_values(self):
        record = self._one_record({"CLAUDECODE": "s3cr3t-value"})
        self.assertEqual(record["agent_hint"], "CLAUDECODE")
        self.assertNotIn("s3cr3t-value", json.dumps(record))

    def test_no_hint_variable_omits_the_field(self):
        record = self._one_record({})
        self.assertNotIn("agent_hint", record)


class IntegrationTest(unittest.TestCase):
    def test_entityctl_readonly_subcommand_logs_one_record(self):
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "inv.jsonl")
            env = dict(os.environ)
            env[_invocation_log.ENV_OVERRIDE] = log
            env["HOME"] = td
            for key in ("ENTITY_LEDGER_HOME", "ENTITY_ROUTER_HOME",
                        "ENTITY_WORKSPACE"):
                env.pop(key, None)
            proc = subprocess.run(
                [sys.executable, str(LEDGER_SCRIPTS / "entityctl.py"),
                 "--ledger-home", os.path.join(td, "nowhere"), "doctor"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, env=env)
            records = [json.loads(line)
                       for line in Path(log).read_text().splitlines()]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["skill"], "entity-ledger")
        self.assertEqual(record["script"], "entityctl.py")
        self.assertEqual(record["argv"],
                         ["--ledger-home", os.path.join(td, "nowhere"), "doctor"])
        self.assertEqual(record["exit_code"], proc.returncode)


class ConsistencyTest(unittest.TestCase):
    def test_all_four_copies_are_byte_identical(self):
        canonical = (ROOT / "skills" / "entity-ledger" / "scripts"
                     / "_invocation_log.py").read_bytes()
        for skill in ("entity-env-build", "entity-pgen", "entity-nt2py"):
            copy = (ROOT / "skills" / skill / "scripts"
                    / "_invocation_log.py").read_bytes()
            self.assertEqual(copy, canonical, skill + " copy drifted")

    def test_executor_runs_when_staged_as_a_single_file(self):
        # the site executor is content-addressed and staged ALONE (no
        # sibling _invocation_log.py); the logging import must degrade
        with tempfile.TemporaryDirectory() as td:
            import shutil
            staged = Path(td) / "entity_ledger_executor.py"
            shutil.copy2(LEDGER_SCRIPTS / "entity_ledger_executor.py", staged)
            proc = subprocess.run(
                [sys.executable, str(staged)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("ImportError", proc.stderr)


if __name__ == "__main__":
    unittest.main()
