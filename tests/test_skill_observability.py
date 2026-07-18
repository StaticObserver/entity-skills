import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "skill_observability" / "skill_observer.py"

from tools.skill_observability.core import (  # noqa: E402
    TraceError,
    append_event,
    finish_run,
    read_jsonl,
    register_artifact,
    run_paths,
    run_tool,
    sha256_text,
    start_run,
    validate_run,
)
from tools.skill_observability.evidence import (  # noqa: E402
    validate_env_build,
    validate_nt2py_inventory,
    validate_pgen_preflight,
    validate_router_action,
)
from tools.skill_observability.adapters.codex_rollout import import_codex_rollout  # noqa: E402
from tools.skill_observability.adapters.claude_transcript import import_claude_transcript  # noqa: E402
from tools.skill_observability.adapters.kimi_wire import import_kimi_session  # noqa: E402


class SkillObservabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.trace_home = self.root / "traces"

    def tearDown(self):
        self.temp.cleanup()

    def start(self, name="run", skills=(), decision_records=True, protected_roots=()):
        return start_run(
            task_id="case-001",
            input_ref="fixture://case-001",
            input_sha256=sha256_text("test task"),
            variant="full",
            agent_provider="test-provider",
            agent_model="test-model",
            agent_configuration=sha256_text("agent-config"),
            tool_profile="test-tools",
            tool_configuration=sha256_text("tool-config"),
            skill_paths=list(skills),
            trace_home=self.trace_home,
            run_id=name,
            protected_roots=list(protected_roots),
            decision_records=decision_records,
        )

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_start_records_exact_skill_identity_and_incomplete_run_is_valid(self):
        skill = self.root / "fake-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: fake-skill\ndescription: fixture\n---\n\n# Fake\n",
            encoding="utf-8",
        )
        run_dir, manifest = self.start(skills=[skill])

        self.assertEqual(manifest["skills"][0]["name"], "fake-skill")
        self.assertEqual(len(manifest["skills"][0]["content_sha256"]), 64)
        self.assertIn(str(skill.resolve()), manifest["capture"]["protected_roots"])
        events = read_jsonl(run_paths(run_dir)["events"], "events")
        self.assertEqual([event["type"] for event in events], ["run.started", "skill.exposed"])

        validation = validate_run(run_dir)
        self.assertTrue(validation["valid"], validation)
        self.assertEqual(validation["terminal_status"], "incomplete")
        self.assertFalse(run_paths(run_dir)["result"].exists())

    def test_trace_home_inside_protected_root_is_rejected(self):
        source_root = self.root / "source"
        source_root.mkdir()
        with self.assertRaisesRegex(TraceError, "protected root"):
            start_run(
                task_id="case",
                input_ref="fixture://case",
                input_sha256=sha256_text("case"),
                variant="full",
                agent_provider="test",
                agent_model="test",
                agent_configuration=sha256_text("config"),
                tool_profile="tools",
                tool_configuration=sha256_text("tools-config"),
                skill_paths=[],
                trace_home=source_root / "trace",
                run_id="unsafe",
                protected_roots=[source_root],
            )
        self.assertEqual(list(source_root.iterdir()), [])

    def test_invalid_configuration_hash_fails_before_creating_run_directory(self):
        with self.assertRaisesRegex(TraceError, "SHA-256"):
            start_run(
                task_id="case",
                input_ref="fixture://case",
                input_sha256=sha256_text("case"),
                variant="full",
                agent_provider="test",
                agent_model="test",
                agent_configuration="not-a-hash",
                tool_profile="tools",
                tool_configuration=sha256_text("tools"),
                skill_paths=[],
                trace_home=self.trace_home,
                run_id="invalid-config",
            )
        self.assertFalse(any(self.trace_home.rglob("invalid-config")))

    def test_secret_redaction_covers_structured_events_arguments_and_output_tails(self):
        run_dir, _ = self.start()
        append_event(
            run_dir,
            event_type="decision.recorded",
            source_kind="agent",
            source_id="test-agent",
            evidence_level="declared",
            phase="decide",
            payload={
                "choice": "continue",
                "token": "structured-secret",
                "note": "Authorization: Bearer bearer-secret",
                "nested": {"private_key": "private-secret"},
                "text_protocol": "token: colon-secret {'password': 'single-secret'}",
            },
        )
        code = (
            'import json,sys; '
            'print(json.dumps({"ok": True, "token": "json-secret"})); '
            'print("Bearer stderr-secret", file=sys.stderr)'
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = run_tool(
                run_dir,
                name="json-probe",
                command=[sys.executable, "-c", code, "--token=argument-secret"],
                capture_json=True,
                capture_authority="test-json-output",
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("json-secret", stdout.getvalue())
        self.assertIn("stderr-secret", stderr.getvalue())

        finish_run(run_dir, status="completed")
        trace_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in run_paths(run_dir).values()
            if path.is_file()
        )
        evidence_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (run_dir / "evidence").glob("*.json")
        )
        for secret in (
            "structured-secret", "bearer-secret", "private-secret", "json-secret",
            "stderr-secret", "argument-secret",
            "colon-secret", "single-secret",
        ):
            self.assertNotIn(secret, trace_text)
            self.assertNotIn(secret, evidence_text)
        self.assertIn("[REDACTED]", trace_text)
        self.assertTrue(validate_run(run_dir)["valid"])

    def test_decision_logging_can_be_disabled_without_losing_tool_trace(self):
        run_dir, _ = self.start(decision_records=False)
        with self.assertRaisesRegex(TraceError, "disabled"):
            append_event(
                run_dir,
                event_type="decision.recorded",
                source_kind="agent",
                source_id="test-agent",
                evidence_level="declared",
                phase="decide",
                payload={"choice": "ignored"},
            )
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_tool(
                run_dir,
                name="smoke",
                command=[sys.executable, "-c", "print('ok')"],
            ), 0)
        result = finish_run(run_dir, status="completed")
        self.assertEqual(result["decisions"], 0)
        self.assertEqual(result["tool_calls"], {"total": 1, "failed": 0})
        self.assertTrue(validate_run(run_dir)["valid"])

    def test_terminal_event_closes_run_and_artifact_drift_is_detected(self):
        run_dir, _ = self.start()
        producer = append_event(
            run_dir,
            event_type="state.transition_observed",
            source_kind="adapter",
            source_id="fixture",
            evidence_level="observed",
            phase="execute",
            payload={"from": "new", "to": "ready"},
        )
        artifact_path = self.root / "artifact.json"
        self.write_json(artifact_path, {"status": "ready"})
        register_artifact(
            run_dir,
            path=artifact_path,
            role="fixture",
            authority="fixture-authority",
            produced_by=producer["event_id"],
        )
        finish_run(run_dir, status="completed")
        with self.assertRaisesRegex(TraceError, "terminal"):
            append_event(
                run_dir,
                event_type="error.observed",
                source_kind="collector",
                source_id="late",
                evidence_level="observed",
                phase="finish",
                payload={},
            )
        artifact_path.write_text('{"status":"changed"}\n', encoding="utf-8")
        validation = validate_run(run_dir)
        self.assertFalse(validation["valid"])
        self.assertTrue(any("fingerprint drifted" in item for item in validation["errors"]))

    def test_finish_is_idempotent_and_lifecycle_events_are_collector_owned(self):
        run_dir, _ = self.start()
        first = finish_run(run_dir, status="completed")
        second = finish_run(run_dir, status="completed")
        self.assertEqual(first, second)
        with self.assertRaisesRegex(TraceError, "collector-owned|terminal"):
            append_event(
                run_dir,
                event_type="run.failed",
                source_kind="adapter",
                source_id="untrusted-adapter",
                evidence_level="observed",
                phase="finish",
                payload={},
            )

    def test_validate_reports_invalid_derived_usage_without_crashing(self):
        run_dir, _ = self.start()
        finish_run(run_dir, status="completed")
        events_path = run_paths(run_dir)["events"]
        events = read_jsonl(events_path, "events")
        events[-1]["payload"]["input_tokens"] = "not-an-integer"
        events_path.write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        validation = validate_run(run_dir)
        self.assertFalse(validation["valid"])
        self.assertTrue(any("cannot derive result" in item for item in validation["errors"]))

    def _router_fixtures(self):
        source = self.root / "source"
        target = source / "pgens" / "demo" / "pgen.hpp"
        target.parent.mkdir(parents=True)
        target.write_text("// fixture\n", encoding="utf-8")
        action_dir = self.root / "controller" / "case" / "actions" / "action-1"
        request_path = action_dir / "request.json"
        result_path = action_dir / "result.json"
        request = {
            "schema_version": 2,
            "case_revision": 4,
            "case_uid": "case-uid",
            "case_id": "case-id",
            "workflow_id": "workflow-1",
            "action_id": "action-1",
            "action_type": "pgen.edit",
            "owner": "entity-pgen",
            "execution_domain": "entity-pgen",
            "execution_site_id": "source-site",
            "identity_id": "",
            "source_revision": {"kind": "git", "commit": "abc"},
            "build_id": "",
            "run_id": "",
            "goal": "edit fixture",
            "playbook": "",
            "inputs": [],
            "read_roots": [{"site_id": "source-site", "path": str(source)}],
            "write_roots": [{"site_id": "source-site", "path": str(target.parent)}],
            "protected_paths": [],
            "constraints": [],
            "expected_outputs": [{"site_id": "source-site", "path": str(target)}],
            "acceptance_checks": ["file exists"],
            "failure_evidence": [],
            "worker_request": {"site_id": "source-site", "path": "/staging/request.json"},
            "started_at": "2026-07-15T00:00:00Z",
        }
        result = {
            "schema_version": 2,
            "case_uid": "case-uid",
            "case_id": "case-id",
            "workflow_id": "workflow-1",
            "action_id": "action-1",
            "action_type": "pgen.edit",
            "owner": "entity-pgen",
            "execution_site_id": "source-site",
            "status": "completed",
            "outputs": [{
                "kind": "file",
                "locator": {"site_id": "source-site", "path": str(target)},
                "fingerprint": {"sha256": "abc"},
            }],
            "verification": ["file exists"],
            "blockers": [],
            "diagnosis": "",
            "suggested_owner": "",
            "started_at": "2026-07-15T00:00:00Z",
            "finished_at": "2026-07-15T00:01:00Z",
        }
        self.write_json(request_path, request)
        self.write_json(result_path, result)
        return source, target, request_path, result_path

    def test_all_four_owner_evidence_adapters_form_one_verified_chain(self):
        run_dir, _ = self.start()
        source, target, request_path, result_path = self._router_fixtures()

        router = validate_router_action(
            run_dir,
            request_path=request_path,
            result_path=result_path,
        )
        self.assertEqual(router["status"], "pass", router)

        preflight_path = self.root / "pgen-preflight.json"
        self.write_json(preflight_path, {
            "allowed": True,
            "mode": "managed-write",
            "target": {"site_id": "source-site", "path": str(target)},
            "case_uid": "case-uid",
            "control_root": str(self.root / "controller" / "case"),
            "action_id": "action-1",
            "reason": "active PGen Action authorizes this locator",
        })
        pgen = validate_pgen_preflight(
            run_dir,
            result_path=preflight_path,
            expected="allowed",
            action_request_path=request_path,
        )
        self.assertEqual(pgen["status"], "pass", pgen)

        build_root = self.root / "build" / "build-1"
        executable = build_root / "src" / "entity.xc"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        script = self.root / "records" / "entity-build.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        runner_log = self.root / "records" / "build.log"
        runner_log.write_text("build ok\n", encoding="utf-8")
        env_path = self.root / "records" / "env.sh"
        env_path.write_text("#!/bin/sh\nexport CXX=c++\n", encoding="utf-8")
        env_path.chmod(0o755)
        checkpoint_path = self.root / "records" / "entity-deps.local.json"
        checkpoint_time = "2026-07-15T00:00:00+00:00"
        self.write_json(checkpoint_path, {
            "schema_version": 2,
            "entity": {
                "site_id": "build-site",
                "source_checkout": str(source),
                "source_revision": {"kind": "git", "commit": "abc", "tree": "def"},
                "build_root": str(build_root),
                "deps_root": str(self.root / "deps"),
                "artifacts_root": str(self.root / "records"),
            },
            "compatibility": {"status": "pass"},
            "env_sh": {
                "path": str(env_path),
                "status": "generated",
                "generated_at": checkpoint_time,
            },
        })
        requirements_path = self.root / "records" / "requirements.json"
        self.write_json(requirements_path, {
            "schema_version": 2,
            "entity": {
                "site_id": "build-site",
                "source_checkout": str(source),
                "source_revision": {"kind": "git", "commit": "abc", "tree": "def"},
                "build_root": str(build_root),
                "deps_root": str(self.root / "deps"),
                "artifacts_root": str(self.root / "records"),
            },
            "build_result": {
                "status": "pass",
                "exit_code": 0,
                "run_id": "build-1",
                "runner_log": str(runner_log),
                "script": str(script),
                "expected_executable": str(executable),
            },
            "entity_build_script": {
                "path": str(script),
                "status": "generated",
                "generated_from": {
                    "requirements_json": str(requirements_path),
                    "env_sh": str(env_path),
                    "env_fingerprint": checkpoint_time,
                    "checkpoint_json": str(checkpoint_path),
                },
            },
        })
        env = validate_env_build(
            run_dir,
            requirements_path=requirements_path,
            expected="pass",
        )
        self.assertEqual(env["status"], "pass", env)

        data_root = self.root / "raw-data"
        data_root.mkdir()
        inventory_path = self.root / "analysis" / "inventory.json"
        self.write_json(inventory_path, {
            "schema_version": 1,
            "status": "ok",
            "reference_version": "1.5.3",
            "nt2py_version": "1.5.3",
            "version_match": True,
            "data_root": str(data_root),
            "format": "bp5",
            "coordinate_system": "cartesian",
            "attribute_keys": [],
            "fields": {"defined": True, "variables": []},
            "particles": {"defined": False},
            "spectra": {"defined": False},
            "diagnostics": {"available": False},
            "warnings": [],
        })
        nt2py = validate_nt2py_inventory(
            run_dir,
            inventory_path=inventory_path,
            expected="ok",
        )
        self.assertEqual(nt2py["status"], "pass", nt2py)

        result = finish_run(run_dir, status="completed")
        self.assertEqual(result["validations"], {"pass": 4, "fail": 0, "unknown": 0})
        validation = validate_run(run_dir)
        self.assertTrue(validation["valid"], validation)

    def test_failed_behavior_validation_is_preserved_without_corrupting_trace(self):
        run_dir, _ = self.start()
        preflight_path = self.root / "preflight-denied.json"
        self.write_json(preflight_path, {
            "allowed": False,
            "mode": "router-required",
            "target": {"site_id": "local", "path": str(self.root / "source")},
            "case_uid": "case-uid",
            "control_root": str(self.root / "controller"),
            "action_id": "",
            "reason": "registered source write requires an Action",
        })
        outcome = validate_pgen_preflight(
            run_dir,
            result_path=preflight_path,
            expected="allowed",
        )
        self.assertEqual(outcome["status"], "fail")
        result = finish_run(run_dir, status="failed")
        self.assertEqual(result["validations"], {"pass": 0, "fail": 1, "unknown": 0})
        validation = validate_run(run_dir)
        self.assertTrue(validation["valid"], validation)
        self.assertEqual(validation["terminal_status"], "failed")

    def test_collector_serializes_concurrent_cli_emitters(self):
        run_dir, _ = self.start()
        processes = []
        for index in range(8):
            command = [
                sys.executable, str(CLI), "emit",
                "--run-dir", str(run_dir),
                "--type", "state.transition_observed",
                "--source-kind", "adapter",
                "--source-id", f"worker-{index}",
                "--evidence-level", "observed",
                "--phase", "execute",
                "--payload-json", json.dumps({"index": index}),
            ]
            processes.append(subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ))
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        events = read_jsonl(run_paths(run_dir)["events"], "events")
        self.assertEqual([event["seq"] for event in events], list(range(1, 10)))
        validation = validate_run(run_dir)
        self.assertTrue(validation["valid"], validation)
        self.assertEqual(validation["terminal_status"], "incomplete")

    def test_cli_end_to_end_with_normalized_adapter_import(self):
        task = self.root / "task.json"
        self.write_json(task, {"request": "fixture"})
        command = [
            sys.executable, str(CLI), "start",
            "--task-id", "cli-case",
            "--input-ref", str(task),
            "--input-file", str(task),
            "--variant", "baseline",
            "--agent-provider", "cli-test",
            "--agent-model", "cli-model",
            "--agent-configuration", sha256_text("agent"),
            "--tool-profile", "cli-tools",
            "--tool-configuration", sha256_text("tools"),
            "--trace-home", str(self.trace_home),
            "--run-id", "cli-run",
        ]
        started = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        run_dir = Path(json.loads(started.stdout)["run_dir"])

        normalized = self.root / "normalized.jsonl"
        rows = [
            {
                "type": "decision.recorded",
                "source": {"kind": "agent", "id": "adapter-agent"},
                "evidence_level": "declared",
                "phase": "decide",
                "span_id": "adapter-root",
                "payload": {"choice": "inspect"},
            },
            {
                "type": "state.transition_observed",
                "source": {"kind": "adapter", "id": "adapter"},
                "evidence_level": "observed",
                "phase": "execute",
                "parent_span_id": "adapter-root",
                "payload": {"state": "inspected"},
            },
        ]
        normalized.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        imported = subprocess.run(
            [sys.executable, str(CLI), "import-events", "--run-dir", str(run_dir), str(normalized)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        self.assertEqual(json.loads(imported.stdout)["imported"], 2)

        finished = subprocess.run(
            [sys.executable, str(CLI), "finish", "--run-dir", str(run_dir), "--status", "completed"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
        checked = subprocess.run(
            [sys.executable, str(CLI), "validate", "--run-dir", str(run_dir)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertTrue(json.loads(checked.stdout)["valid"])

    def test_codex_adapter_imports_only_observable_tools_and_is_incremental(self):
        skill = self.root / "fake-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: fake-skill\ndescription: fixture\n---\n",
            encoding="utf-8",
        )
        run_dir, _ = self.start(skills=[skill])
        rollout = self.root / "codex-rollout.jsonl"
        records = [
            {
                "type": "session_meta",
                "payload": {"cwd": str(self.root), "id": "session"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "summary": "hidden-reasoning-secret",
                    "encrypted_content": "ciphertext",
                },
            },
            {
                "type": "event_msg",
                "payload": {"type": "agent_reasoning", "text": "agent-reasoning-secret"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": "user-message-secret",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "call-1",
                    "name": "exec",
                    "status": "completed",
                    "input": f"read {skill}/SKILL.md --token=adapter-input-secret",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "observer-call",
                    "name": "exec",
                    "status": "completed",
                    "input": "python3 tools/skill_observability/skill_observer.py import-codex",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "observer-call",
                    "output": [{"type": "input_text", "text": "observer output"}],
                },
            },
        ]
        rollout.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )
        first = import_codex_rollout(run_dir, rollout_path=rollout)
        self.assertEqual(first["started_imported"], 1)
        self.assertEqual(first["finished_imported"], 0)
        self.assertEqual(first["resources_observed"], 1)
        self.assertEqual(first["observer_calls_skipped"], 1)
        self.assertEqual(first["reasoning_records_skipped"], 2)
        incomplete = validate_run(run_dir)
        self.assertTrue(incomplete["valid"], incomplete)
        self.assertTrue(any("unfinished tool spans" in item for item in incomplete["warnings"]))

        output_record = {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-1",
                "output": [{"type": "input_text", "text": "unlabeled-output-secret"}],
            },
        }
        with rollout.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(output_record) + "\n")
        second = import_codex_rollout(run_dir, rollout_path=rollout)
        self.assertEqual(second["started_imported"], 0)
        self.assertEqual(second["finished_imported"], 1)
        self.assertEqual(second["resources_observed"], 0)
        third = import_codex_rollout(run_dir, rollout_path=rollout)
        self.assertEqual(third["started_imported"], 0)
        self.assertEqual(third["finished_imported"], 0)

        finish_run(run_dir, status="completed")
        validation = validate_run(run_dir)
        self.assertTrue(validation["valid"], validation)
        events = read_jsonl(run_paths(run_dir)["events"], "events")
        self.assertEqual(sum(event["type"] == "tool.started" for event in events), 1)
        self.assertEqual(sum(event["type"] == "tool.finished" for event in events), 1)
        self.assertEqual(sum(event["type"] == "skill.resource_observed" for event in events), 1)
        self.assertFalse(any(event["type"] == "decision.recorded" for event in events))
        trace_text = run_paths(run_dir)["events"].read_text(encoding="utf-8")
        for secret in (
            "hidden-reasoning-secret", "agent-reasoning-secret", "user-message-secret",
            "adapter-input-secret", "unlabeled-output-secret",
        ):
            self.assertNotIn(secret, trace_text)

    def test_claude_adapter_hashes_tools_skips_reasoning_and_imports_usage(self):
        run_dir, _ = self.start(name="claude-native")
        transcript = self.root / "claude-session.jsonl"
        records = [
            {
                "type": "assistant", "sessionId": "claude-session", "cwd": str(self.root),
                "message": {
                    "usage": {"input_tokens": 11, "cache_read_input_tokens": 7,
                              "output_tokens": 3},
                    "content": [
                        {"type": "thinking", "thinking": "private-claude-reasoning"},
                        {"type": "tool_use", "id": "tool-1", "name": "Bash",
                         "input": {"command": "printf claude-secret"}},
                    ],
                },
            },
            {
                "type": "user", "sessionId": "claude-session", "cwd": str(self.root),
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tool-1",
                     "content": "claude-output-secret", "is_error": False},
                ]},
            },
        ]
        transcript.write_text(
            "".join(json.dumps(item) + "\n" for item in records), encoding="utf-8"
        )
        first = import_claude_transcript(run_dir, transcript_path=transcript)
        self.assertEqual(first["calls_seen"], 1)
        self.assertEqual(first["started_imported"], 1)
        self.assertEqual(first["finished_imported"], 1)
        self.assertEqual(first["reasoning_records_skipped"], 1)
        self.assertEqual(first["usage"]["input_tokens"], 11)
        self.assertEqual(first["usage"]["cached_input_tokens"], 7)
        second = import_claude_transcript(run_dir, transcript_path=transcript)
        self.assertEqual(second["started_imported"], 0)
        self.assertEqual(second["finished_imported"], 0)
        trace = run_paths(run_dir)["events"].read_text(encoding="utf-8")
        self.assertNotIn("private-claude-reasoning", trace)
        self.assertNotIn("claude-secret", trace)
        self.assertNotIn("claude-output-secret", trace)

    def test_kimi_adapter_imports_all_agents_and_native_usage(self):
        run_dir, _ = self.start(name="kimi-native")
        session = self.root / "session-kimi"
        self.write_json(session / "state.json", {"workDir": str(self.root)})
        main = session / "agents" / "main" / "wire.jsonl"
        child = session / "agents" / "agent-0" / "wire.jsonl"
        main.parent.mkdir(parents=True)
        child.parent.mkdir(parents=True)
        main_records = [
            {"type": "context.append_loop_event", "event": {
                "type": "content.part", "part": {"type": "think", "think": "kimi-private"}}},
            {"type": "context.append_loop_event", "event": {
                "type": "tool.call", "toolCallId": "call-1", "name": "Shell",
                "args": {"command": "printf kimi-main-secret"}}},
            {"type": "context.append_loop_event", "event": {
                "type": "tool.result", "toolCallId": "call-1",
                "result": "kimi-main-output"}},
            {"type": "usage.record", "usage": {
                "inputOther": 100, "inputCacheCreation": 10,
                "inputCacheRead": 40, "output": 20}},
        ]
        child_records = [
            {"type": "context.append_loop_event", "event": {
                "type": "tool.call", "toolCallId": "call-1", "name": "Read",
                "args": {"path": "kimi-child-secret"}}},
            {"type": "context.append_loop_event", "event": {
                "type": "tool.result", "toolCallId": "call-1",
                "result": "kimi-child-output"}},
        ]
        main.write_text("".join(json.dumps(item) + "\n" for item in main_records), encoding="utf-8")
        child.write_text("".join(json.dumps(item) + "\n" for item in child_records), encoding="utf-8")
        outcome = import_kimi_session(run_dir, session_path=session)
        self.assertEqual(outcome["calls_seen"], 2)
        self.assertEqual(outcome["started_imported"], 2)
        self.assertEqual(outcome["finished_imported"], 2)
        self.assertEqual(outcome["reasoning_records_skipped"], 1)
        self.assertEqual(outcome["usage"]["input_tokens"], 110)
        self.assertEqual(outcome["usage"]["cached_input_tokens"], 40)
        events = read_jsonl(run_paths(run_dir)["events"], "events")
        agents = {
            event["payload"].get("native_agent_id") for event in events
            if event["type"] == "tool.started"
        }
        self.assertEqual(agents, {"main", "agent-0"})
        self.assertTrue(all(
            event["payload"].get("agent_run_id") == "kimi-native"
            for event in events if event["type"] == "tool.started"
        ))
        trace = run_paths(run_dir)["events"].read_text(encoding="utf-8")
        for secret in ("kimi-private", "kimi-main-secret", "kimi-main-output",
                       "kimi-child-secret", "kimi-child-output"):
            self.assertNotIn(secret, trace)

    def test_runtime_skills_have_no_observability_dependency(self):
        for path in (ROOT / "skills").glob("*/scripts/*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("skill_observability", text, path)
            self.assertNotIn("skill-observer", text, path)


if __name__ == "__main__":
    unittest.main()
