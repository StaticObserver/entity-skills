#!/usr/bin/env python3
"""Run generated Entity build artifacts and record structured results.

Subcommands:
  build <requirements.json> --script <entity-build.sh>
"""

import argparse
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from _json_io import add_json_flag, ensure_harness_home, load_json, log_event, protocol_ok, write_json_atomic
from _version_profile import version_profile as validate_entity_version
from entity_state import record_step
from entity_schema import entity_paths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_artifacts_dir(req: Dict[str, Any]) -> Path:
    artifacts = req.get("artifacts", {})
    if isinstance(artifacts, dict) and artifacts.get("logs_dir"):
        return Path(str(artifacts["logs_dir"]))

    artifacts_root = entity_paths(req).get("artifacts_root", "")
    if artifacts_root:
        return Path(artifacts_root) / "build-logs"
    return Path.cwd() / "build-logs"


def _set_build_result(req: Dict[str, Any], result: Dict[str, Any]) -> None:
    build_result = req.setdefault("build_result", {})
    if not isinstance(build_result, dict):
        build_result = {}
        req["build_result"] = build_result
    build_result.update(result)


def cmd_build(args: argparse.Namespace) -> None:
    req = load_json(args.requirements_json)
    validate_entity_version(req)
    script = args.script
    if not script.is_file():
        raise SystemExit(f"entity-build.sh not found: {script}")

    ensure_harness_home()
    run_id = args.run_id or uuid.uuid4().hex[:8]
    log_dir = _build_artifacts_dir(req)
    log_dir.mkdir(parents=True, exist_ok=True)
    run_log = log_dir / f"entity-run-{run_id}.log"

    started_at = _utc_now()
    _set_build_result(req, {
        "status": "running",
        "started_at": started_at,
        "finished_at": "",
        "exit_code": None,
        "run_id": run_id,
        "runner_log": str(run_log.resolve()),
        "script": str(script.resolve()),
    })
    write_json_atomic(args.requirements_json, req)
    log_event(run_id, run_id, "build.run", "started", script=str(script.resolve()), artifacts=[str(run_log.resolve())])

    exit_code = 1
    try:
        with run_log.open("w", encoding="utf-8") as log:
            log.write(f"# entity_run.py build started {started_at}\n")
            log.write(f"# script: {script.resolve()}\n\n")
            proc = subprocess.Popen(
                ["bash", str(script.resolve())],
                cwd=str(script.parent.resolve()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                log.flush()
                if not args.quiet:
                    sys.stdout.write(line)
                    sys.stdout.flush()
            exit_code = proc.wait()
    except Exception as exc:
        try:
            with run_log.open("a", encoding="utf-8") as log:
                log.write(f"\n# Runner crashed: {exc}\n")
        except OSError:
            pass
        exit_code = -1

    finished_at = _utc_now()
    status = "pass" if exit_code == 0 else "fail"
    req = load_json(args.requirements_json)
    _set_build_result(req, {
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "run_id": run_id,
        "runner_log": str(run_log.resolve()),
        "script": str(script.resolve()),
    })
    write_json_atomic(args.requirements_json, req)
    log_event(
        run_id,
        run_id,
        "build.run",
        status,
        script=str(script.resolve()),
        artifacts=[str(run_log.resolve()), str(args.requirements_json.resolve())],
        exit_code=exit_code,
    )
    record_step(
        script.parent,
        "build_executed",
        status,
        inputs={
            "requirements_json": str(args.requirements_json.resolve()),
            "entity_build_sh": str(script.resolve()),
        },
        outputs={
            "requirements_json": str(args.requirements_json.resolve()),
            "runner_log": str(run_log.resolve()),
        },
        run_id=run_id,
        message=f"exit_code={exit_code}",
    )

    if args.json:
        if exit_code != 0:
            protocol_error(
                "run.build",
                f"Build failed with exit code {exit_code}",
                result=status,
                exit_code=exit_code,
                run_id=run_id,
                log=str(run_log.resolve()),
            )
        protocol_ok(
            "run.build",
            result=status,
            exit_code=exit_code,
            run_id=run_id,
            log=str(run_log.resolve()),
        )
    if exit_code != 0:
        raise SystemExit(exit_code)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="subcommand")

    p_build = sub.add_parser("build", help="Run generated entity-build.sh and update requirements.json")
    p_build.add_argument("requirements_json", type=Path)
    p_build.add_argument("--script", type=Path, required=True, help="Generated entity-build.sh")
    p_build.add_argument("--run-id", help="Run ID for logs (auto-generated if omitted)")
    p_build.add_argument("--quiet", action="store_true", help="Do not mirror build output to stdout")
    add_json_flag(p_build)

    args = parser.parse_args()
    if args.subcommand is None:
        parser.print_help()
        raise SystemExit(1)
    if args.subcommand == "build":
        cmd_build(args)


if __name__ == "__main__":
    main()
