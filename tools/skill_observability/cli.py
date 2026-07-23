"""Command-line interface for the Entity skills observability collector."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .contracts import EVIDENCE_LEVELS, EVENT_TYPES, PHASES, SOURCE_KINDS, ContractError
from .core import (
    TraceError,
    append_event,
    finish_run,
    register_artifact,
    run_tool,
    sha256_file,
    start_run,
    validate_run,
)
from .evidence import (
    validate_env_build,
    validate_nt2py_inventory,
    validate_pgen_preflight,
    validate_router_action,
    validate_router_operation,
)
from .adapters.codex_rollout import import_codex_rollout
from .adapters.claude_transcript import import_claude_transcript
from .adapters.claude_phases import write_phases_report
from .adapters.claude_activities import write_activities_report
from .adapters.kimi_wire import import_kimi_session


def _json_out(value: Any, stream: Any = None) -> None:
    # Resolve stdout at call time so redirected sys.stdout (tests, embedding)
    # is honored; a default of sys.stdout would bind at import time.
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False),
          file=stream if stream is not None else sys.stdout)


def _payload(args: argparse.Namespace) -> Dict[str, Any]:
    if getattr(args, "payload_file", None):
        try:
            value = json.loads(args.payload_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TraceError(f"cannot read payload file: {exc}") from exc
    elif getattr(args, "payload_json", None):
        try:
            value = json.loads(args.payload_json)
        except json.JSONDecodeError as exc:
            raise TraceError(f"--payload-json is invalid: {exc}") from exc
    else:
        value = {}
    if not isinstance(value, dict):
        raise TraceError("event payload must be a JSON object")
    return value


def _input_sha256(args: argparse.Namespace) -> str:
    if args.input_sha256:
        return args.input_sha256
    digest, _ = sha256_file(args.input_file.expanduser().resolve())
    return digest


def command_start(args: argparse.Namespace) -> int:
    run_dir, manifest = start_run(
        task_id=args.task_id,
        input_ref=args.input_ref,
        input_sha256=_input_sha256(args),
        variant=args.variant,
        agent_provider=args.agent_provider,
        agent_model=args.agent_model,
        agent_configuration=args.agent_configuration,
        tool_profile=args.tool_profile,
        tool_configuration=args.tool_configuration,
        skill_paths=args.skill,
        trace_home=args.trace_home,
        run_id=args.run_id,
        protected_roots=args.protected_root,
        decision_records=not args.no_decision_records,
    )
    _json_out({"ok": True, "run_id": manifest["run_id"], "run_dir": str(run_dir)})
    return 0


def command_emit(args: argparse.Namespace) -> int:
    event = append_event(
        args.run_dir,
        event_type=args.type,
        source_kind=args.source_kind,
        source_id=args.source_id,
        evidence_level=args.evidence_level,
        phase=args.phase,
        payload=_payload(args),
        span_id=args.span_id,
        parent_span_id=args.parent_span_id,
    )
    _json_out({"ok": True, "event": event})
    return 0


def command_import_events(args: argparse.Namespace) -> int:
    count = 0
    try:
        handle = args.path.open("r", encoding="utf-8") if args.path else sys.stdin
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TraceError(f"normalized event line {number} is invalid JSON: {exc}") from exc
            if not isinstance(item, dict):
                raise TraceError(f"normalized event line {number} must be an object")
            required = {"type", "source", "evidence_level", "phase", "payload"}
            missing = required - set(item)
            if missing:
                raise TraceError(
                    f"normalized event line {number} missing keys: {', '.join(sorted(missing))}"
                )
            source = item.get("source")
            if not isinstance(source, dict) or not source.get("kind") or not source.get("id"):
                raise TraceError(f"normalized event line {number} has invalid source")
            append_event(
                args.run_dir,
                event_type=item["type"],
                source_kind=source["kind"],
                source_id=source["id"],
                evidence_level=item["evidence_level"],
                phase=item["phase"],
                payload=item["payload"],
                span_id=item.get("span_id"),
                parent_span_id=item.get("parent_span_id"),
            )
            count += 1
    finally:
        if args.path and "handle" in locals():
            handle.close()
    _json_out({"ok": True, "imported": count})
    return 0


def command_import_codex(args: argparse.Namespace) -> int:
    outcome = import_codex_rollout(
        args.run_dir,
        rollout_path=args.rollout,
        parent_span_id=args.parent_span_id,
    )
    _json_out({"ok": True, **outcome})
    return 0


def command_import_claude(args: argparse.Namespace) -> int:
    outcome = import_claude_transcript(
        args.run_dir,
        transcript_path=args.transcript,
        parent_span_id=args.parent_span_id,
    )
    _json_out({"ok": True, **outcome})
    return 0


def command_import_kimi(args: argparse.Namespace) -> int:
    outcome = import_kimi_session(
        args.run_dir,
        session_path=args.session,
        parent_span_id=args.parent_span_id,
    )
    _json_out({"ok": True, **outcome})
    return 0


def command_phases(args: argparse.Namespace) -> int:
    rules = None
    if args.rules:
        try:
            rules = json.loads(args.rules.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TraceError(f"cannot read rules file: {exc}") from exc
        if not isinstance(rules, list):
            raise TraceError("rules file must contain a JSON array of phase/pattern objects")
    report = write_phases_report(
        args.run_dir,
        transcript_path=args.transcript,
        rules=rules,
        output_path=args.output,
    )
    event = append_event(
        args.run_dir,
        event_type="validation.finished",
        source_kind="validator",
        source_id="skill-observer.phases",
        evidence_level="observed",
        phase="verify",
        payload={
            "kind": "claude-phases",
            "transcript_sha256": report["source"]["transcript_sha256"],
            "session_id": report["source"]["session_id"],
            "phases_present": [p["name"] for p in report["phases"] if p["records"] > 0],
            "unclassified_token_share": report["unclassified_token_share"],
            "comparable": report["comparable"],
            "status": "pass" if report["comparable"] else "fail",
        },
    )
    artifact = register_artifact(
        args.run_dir,
        path=Path(report["written_to"]),
        role="phases-report",
        authority="derived:claude-transcript",
        produced_by=event["event_id"],
        media_type="application/json",
        phase="verify",
    )
    _json_out({
        "ok": True,
        "written_to": report["written_to"],
        "comparable": report["comparable"],
        "unclassified_token_share": report["unclassified_token_share"],
        "artifact_id": artifact["artifact_id"],
    })
    return 0 if report["comparable"] else 1


def command_activities(args: argparse.Namespace) -> int:
    rules = None
    if args.rules:
        try:
            rules = json.loads(args.rules.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TraceError(f"cannot read rules file: {exc}") from exc
        if not isinstance(rules, list):
            raise TraceError("rules file must contain a JSON array of category/pattern objects")
    report = write_activities_report(
        args.run_dir,
        transcript_path=args.transcript,
        rules=rules,
        output_path=args.output,
    )
    event = append_event(
        args.run_dir,
        event_type="validation.finished",
        source_kind="validator",
        source_id="skill-observer.activities",
        evidence_level="observed",
        phase="verify",
        payload={
            "kind": "claude-activities",
            "transcript_sha256": report["source"]["transcript_sha256"],
            "session_id": report["source"]["session_id"],
            "categories_present": [c["name"] for c in report["categories"] if c["records"] > 0],
            "unclassified_tool_share": report["unclassified_tool_share"],
            # descriptive metric only: unclassified share never gates the exit code
            "status": "pass",
        },
    )
    artifact = register_artifact(
        args.run_dir,
        path=Path(report["written_to"]),
        role="activities-report",
        authority="derived:claude-transcript",
        produced_by=event["event_id"],
        media_type="application/json",
        phase="verify",
    )
    _json_out({
        "ok": True,
        "written_to": report["written_to"],
        "unclassified_tool_share": report["unclassified_tool_share"],
        "submissions_total": report["job_lifecycle"]["submissions_total"],
        "artifact_id": artifact["artifact_id"],
    })
    return 0


def command_artifact(args: argparse.Namespace) -> int:
    artifact = register_artifact(
        args.run_dir,
        path=args.path,
        role=args.role,
        authority=args.authority,
        produced_by=args.produced_by,
        site_id=args.site_id,
        media_type=args.media_type,
        phase=args.phase,
    )
    _json_out({"ok": True, "artifact": artifact})
    return 0


def command_tool(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    return run_tool(
        args.run_dir,
        name=args.name,
        command=command,
        phase=args.phase,
        parent_span_id=args.parent_span_id,
        capture_json=args.capture_json,
        capture_authority=args.capture_authority,
        capture_json_name=args.capture_json_name,
        cwd=args.cwd,
    )


def _evidence_exit(outcome: Dict[str, Any]) -> int:
    _json_out({"ok": outcome["status"] == "pass", **outcome})
    if outcome["status"] == "pass":
        return 0
    if outcome["status"] == "unknown":
        return 2
    return 1


def command_evidence_router(args: argparse.Namespace) -> int:
    return _evidence_exit(validate_router_action(
        args.run_dir,
        request_path=args.request,
        result_path=args.result,
        case_state_path=args.case_state,
        parent_span_id=args.parent_span_id,
    ))


def command_evidence_router_operation(args: argparse.Namespace) -> int:
    return _evidence_exit(validate_router_operation(
        args.run_dir,
        plan_path=args.plan,
        operation_path=args.operation,
        receipt_paths=args.receipt,
        status_path=args.status,
        scheduler_path=args.scheduler,
        parent_span_id=args.parent_span_id,
    ))


def command_evidence_pgen(args: argparse.Namespace) -> int:
    return _evidence_exit(validate_pgen_preflight(
        args.run_dir,
        result_path=args.result,
        expected=args.expect,
        action_request_path=args.action_request,
        parent_span_id=args.parent_span_id,
    ))


def command_evidence_env(args: argparse.Namespace) -> int:
    return _evidence_exit(validate_env_build(
        args.run_dir,
        requirements_path=args.requirements,
        expected=args.expect,
        checkpoint_path=args.checkpoint,
        env_path=args.env,
        parent_span_id=args.parent_span_id,
    ))


def command_evidence_nt2py(args: argparse.Namespace) -> int:
    return _evidence_exit(validate_nt2py_inventory(
        args.run_dir,
        inventory_path=args.inventory,
        expected=args.expect,
        parent_span_id=args.parent_span_id,
    ))


def command_finish(args: argparse.Namespace) -> int:
    result = finish_run(
        args.run_dir,
        status=args.status,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        wall_time_ms=args.wall_time_ms,
    )
    _json_out({"ok": True, "result": result})
    return 0


def command_validate(args: argparse.Namespace) -> int:
    result = validate_run(args.run_dir, verify_artifact_content=not args.skip_artifact_content)
    _json_out(result)
    return 0 if result["valid"] else 1


def _add_run_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-dir", type=Path, required=True)


def _add_parent_span(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--parent-span-id")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-observer",
        description="Collect and validate evidence-backed Entity skill execution traces.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Create an immutable run manifest and initial events")
    start.add_argument("--task-id", required=True)
    start.add_argument("--input-ref", required=True)
    input_group = start.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input-sha256")
    input_group.add_argument("--input-file", type=Path)
    start.add_argument("--variant", required=True)
    start.add_argument("--agent-provider", required=True)
    start.add_argument("--agent-model", required=True)
    start.add_argument("--agent-configuration", required=True)
    start.add_argument("--tool-profile", required=True)
    start.add_argument("--tool-configuration", required=True)
    start.add_argument("--skill", type=Path, action="append", default=[])
    start.add_argument("--protected-root", type=Path, action="append", default=[])
    start.add_argument("--trace-home", type=Path)
    start.add_argument("--run-id")
    start.add_argument("--no-decision-records", action="store_true")
    start.set_defaults(func=command_start)

    emit = sub.add_parser("emit", help="Append one normalized event")
    _add_run_dir(emit)
    emit.add_argument("--type", choices=sorted(EVENT_TYPES - {"run.started", "run.finished", "run.failed"}), required=True)
    emit.add_argument("--source-kind", choices=sorted(SOURCE_KINDS), required=True)
    emit.add_argument("--source-id", required=True)
    emit.add_argument("--evidence-level", choices=sorted(EVIDENCE_LEVELS), required=True)
    emit.add_argument("--phase", choices=sorted(PHASES), required=True)
    payload_group = emit.add_mutually_exclusive_group()
    payload_group.add_argument("--payload-json")
    payload_group.add_argument("--payload-file", type=Path)
    emit.add_argument("--span-id")
    emit.add_argument("--parent-span-id")
    emit.set_defaults(func=command_emit)

    imported = sub.add_parser("import-events", help="Import platform-adapter normalized JSONL")
    _add_run_dir(imported)
    imported.add_argument("path", type=Path, nargs="?", help="Read stdin when omitted")
    imported.set_defaults(func=command_import_events)

    codex = sub.add_parser("import-codex", help="Import observable tool calls from Codex rollout JSONL")
    _add_run_dir(codex)
    _add_parent_span(codex)
    codex.add_argument("--rollout", type=Path, required=True)
    codex.set_defaults(func=command_import_codex)

    claude = sub.add_parser(
        "import-claude", help="Import observable tool calls from Claude Code JSONL"
    )
    _add_run_dir(claude)
    _add_parent_span(claude)
    claude.add_argument("--transcript", type=Path, required=True)
    claude.set_defaults(func=command_import_claude)

    kimi = sub.add_parser(
        "import-kimi", help="Import observable tool calls from a Kimi Code session"
    )
    _add_run_dir(kimi)
    _add_parent_span(kimi)
    kimi.add_argument("--session", type=Path, required=True)
    kimi.set_defaults(func=command_import_kimi)

    phases = sub.add_parser(
        "phases",
        help="Segment a Claude Code transcript into lifecycle phases (offline, post-hoc)",
    )
    _add_run_dir(phases)
    phases.add_argument("--transcript", type=Path, required=True)
    phases.add_argument("--rules", type=Path,
                        help="Optional JSON array of {\"phase\", \"pattern\"} overrides")
    phases.add_argument("--output", type=Path,
                        help="Report path (default: <run-dir>/phases.json)")
    phases.set_defaults(func=command_phases)

    activities = sub.add_parser(
        "activities",
        help="Tag a Claude Code transcript with activity categories (offline, post-hoc)",
    )
    _add_run_dir(activities)
    activities.add_argument("--transcript", type=Path, required=True)
    activities.add_argument("--rules", type=Path,
                            help="Optional JSON array of {\"category\", \"pattern\"} overrides")
    activities.add_argument("--output", type=Path,
                            help="Report path (default: <run-dir>/activities.json)")
    activities.set_defaults(func=command_activities)

    artifact = sub.add_parser("artifact", help="Fingerprint and link an existing artifact")
    _add_run_dir(artifact)
    artifact.add_argument("--path", type=Path, required=True)
    artifact.add_argument("--role", required=True)
    artifact.add_argument("--authority", required=True)
    artifact.add_argument("--produced-by", required=True)
    artifact.add_argument("--site-id", default="local")
    artifact.add_argument("--media-type")
    artifact.add_argument("--phase", choices=sorted(PHASES), default="verify")
    artifact.set_defaults(func=command_artifact)

    tool = sub.add_parser("tool", help="Run a command while streaming and tracing stdout/stderr")
    _add_run_dir(tool)
    tool.add_argument("--name", required=True)
    tool.add_argument("--phase", choices=sorted(PHASES), default="execute")
    _add_parent_span(tool)
    tool.add_argument("--capture-json", action="store_true")
    tool.add_argument("--capture-authority", default="tool-json-output")
    tool.add_argument("--capture-json-name")
    tool.add_argument("--cwd", type=Path)
    tool.add_argument("command", nargs=argparse.REMAINDER)
    tool.set_defaults(func=command_tool)

    evidence = sub.add_parser("evidence", help="Validate and link existing owner evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_kind", required=True)

    router = evidence_sub.add_parser("router-action")
    _add_run_dir(router)
    _add_parent_span(router)
    router.add_argument("--request", type=Path, required=True)
    router_anchor = router.add_mutually_exclusive_group()
    router_anchor.add_argument("--result", type=Path)
    router_anchor.add_argument("--case-state", type=Path)
    router.set_defaults(func=command_evidence_router)

    operation = evidence_sub.add_parser("router-operation")
    _add_run_dir(operation)
    _add_parent_span(operation)
    operation.add_argument("--plan", type=Path, required=True)
    operation.add_argument("--operation", type=Path, required=True,
                           help="Operation object or complete Router v5 export")
    operation.add_argument("--receipt", type=Path, action="append", default=[],
                           help="Repeat once for each owner-site Step receipt")
    operation.add_argument("--status", type=Path, required=True)
    operation.add_argument("--scheduler", type=Path, required=True)
    operation.set_defaults(func=command_evidence_router_operation)

    pgen = evidence_sub.add_parser("pgen-preflight")
    _add_run_dir(pgen)
    _add_parent_span(pgen)
    pgen.add_argument("--result", type=Path, required=True)
    pgen.add_argument("--expect", choices=["allowed", "denied"], required=True)
    pgen.add_argument("--action-request", type=Path)
    pgen.set_defaults(func=command_evidence_pgen)

    env = evidence_sub.add_parser("env-build")
    _add_run_dir(env)
    _add_parent_span(env)
    env.add_argument("--requirements", type=Path, required=True)
    env.add_argument("--expect", choices=["pass", "fail", "running", "not_run"], required=True)
    env.add_argument("--checkpoint", type=Path,
                     help="Override checkpoint path when requirements do not record it")
    env.add_argument("--env", type=Path,
                     help="Override env.sh path when requirements do not record it")
    env.set_defaults(func=command_evidence_env)

    nt2py = evidence_sub.add_parser("nt2py-inventory")
    _add_run_dir(nt2py)
    _add_parent_span(nt2py)
    nt2py.add_argument("--inventory", type=Path, required=True)
    nt2py.add_argument("--expect", choices=["ok", "error"], required=True)
    nt2py.set_defaults(func=command_evidence_nt2py)

    finish = sub.add_parser("finish", help="Append terminal event and derive result.json")
    _add_run_dir(finish)
    finish.add_argument("--status", choices=["completed", "failed"], required=True)
    finish.add_argument("--input-tokens", type=int)
    finish.add_argument("--output-tokens", type=int)
    finish.add_argument("--wall-time-ms", type=int)
    finish.set_defaults(func=command_finish)

    validate = sub.add_parser("validate", help="Validate the complete or incomplete run")
    _add_run_dir(validate)
    validate.add_argument("--skip-artifact-content", action="store_true")
    validate.set_defaults(func=command_validate)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (TraceError, ContractError, OSError, ValueError) as exc:
        _json_out({"ok": False, "error": str(exc), "type": type(exc).__name__}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
