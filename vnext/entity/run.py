from __future__ import annotations

import json
import os
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .build import site_build_root
from .errors import EntityError
from .objects import load_build, load_run
from .paths import Workspace
from .records import now_utc, require_id
from .site import SiteOps


ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def site_run_root(site: SiteOps, project_id: str, build_id: str, run_id: str) -> PurePosixPath:
    return site_build_root(site, project_id, build_id) / "runs" / run_id


def _new_attempt_id() -> str:
    return datetime.now(timezone.utc).strftime("attempt-%Y%m%dT%H%M%S%fZ")


def _merge_resources(site_config: dict[str, Any], run: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    scheduler = site_config.get("scheduler") or {}
    result = dict(scheduler.get("defaults") or {})
    result.update(run.get("resources") or {})
    result.update(override or {})
    return {key: value for key, value in result.items() if value not in (None, "")}


def _launcher(site_config: dict[str, Any], build: dict[str, Any], resources: dict[str, Any]) -> list[str]:
    if not bool((build.get("runtime") or {}).get("mpi")):
        return []
    template = (site_config.get("mpi") or {}).get("template")
    if not isinstance(template, list) or not template:
        raise EntityError("MPI build requires site.mpi.template", code="invalid_record")
    values = {key: str(value) for key, value in resources.items()}
    values.setdefault("tasks", "1")
    try:
        return [str(item).format(**values) for item in template]
    except (KeyError, ValueError) as exc:
        detail = exc.args[0] if isinstance(exc, KeyError) else str(exc)
        raise EntityError(f"invalid MPI launcher template: {detail}", code="invalid_record") from exc


def _expand_runtime_arguments(arguments: Any, values: dict[str, str]) -> list[str]:
    if not isinstance(arguments, list):
        raise EntityError("runtime.arguments must be a JSON array", code="invalid_record")
    try:
        return [str(item).format(**values) for item in arguments]
    except (KeyError, ValueError) as exc:
        detail = exc.args[0] if isinstance(exc, KeyError) else str(exc)
        raise EntityError(f"invalid runtime argument placeholder: {detail}", code="invalid_record") from exc


def _slurm_value(name: str, value: Any) -> str:
    text = str(value)
    if not text or text.strip() != text or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in text
    ):
        raise EntityError(f"invalid Slurm resource value for {name}: {value!r}", code="invalid_record")
    return text


def render_run_script(
    site: SiteOps,
    build: dict[str, Any],
    resources: dict[str, Any],
    environment: dict[str, str],
    run_root: PurePosixPath,
) -> str:
    site_env = site.path(str((site.config.get("environment") or {}).get("script") or "site-env.sh"))
    deps_env = site.path("deps", str(build["deps"]), "env.sh")
    executable = run_root.parents[1] / "bin" / "entity"
    input_toml = run_root / "input.toml"
    data_root = run_root / "data"
    exports: list[str] = []
    for key, value in sorted(environment.items()):
        if not ENV_NAME.fullmatch(str(key)):
            raise EntityError(f"invalid environment variable name: {key}", code="invalid_record")
        exports.append(f"export {key}={shlex.quote(str(value))}")
    command = _launcher(site.config, build, resources) + [str(executable), "-input", str(input_toml)]
    extra = (build.get("runtime") or {}).get("arguments") or []
    if extra:
        values = {"toml": str(input_toml), "data": str(data_root), "executable": str(executable)}
        command.extend(_expand_runtime_arguments(extra, values))
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            f"source {shlex.quote(str(site_env))}",
            f"source {shlex.quote(str(deps_env))}",
            *exports,
            "",
            f"mkdir -p {shlex.quote(str(data_root))}",
            f"cd {shlex.quote(str(data_root))}",
            f"exec {' '.join(shlex.quote(item) for item in command)}",
            "",
        ]
    )


def render_slurm_script(
    project_id: str,
    run_id: str,
    attempt_id: str,
    resources: dict[str, Any],
    attempt_root: PurePosixPath,
) -> str:
    directives = [f"#SBATCH --job-name={run_id}"]
    mapping = (
        ("nodes", "nodes"),
        ("tasks", "ntasks"),
        ("tasks_per_node", "ntasks-per-node"),
        ("cpus_per_task", "cpus-per-task"),
        ("walltime", "time"),
        ("partition", "partition"),
        ("account", "account"),
        ("qos", "qos"),
    )
    for key, option in mapping:
        if key in resources:
            value = _slurm_value(key, resources[key])
            if key in {"nodes", "tasks", "tasks_per_node", "cpus_per_task"}:
                if not value.isdigit() or int(value) < 1:
                    raise EntityError(f"Slurm resource {key} must be a positive integer", code="invalid_record")
                value = str(int(value))
            directives.append(f"#SBATCH --{option}={value}")
    gres = resources.get("gres")
    if not gres and resources.get("gpus_per_node"):
        gpu_count = _slurm_value("gpus_per_node", resources["gpus_per_node"])
        if not gpu_count.isdigit() or int(gpu_count) < 1:
            raise EntityError("Slurm resource gpus_per_node must be a positive integer", code="invalid_record")
        gres = f"gpu:{int(gpu_count)}"
    if gres:
        directives.append(f"#SBATCH --gres={_slurm_value('gres', gres)}")
    directives.extend(
        [
            "#SBATCH --output=stdout.log",
            "#SBATCH --error=stderr.log",
            f"#SBATCH --comment=entity:{project_id}:{run_id}:{attempt_id}",
        ]
    )
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            *directives,
            "",
            "set -euo pipefail",
            f"cd {shlex.quote(str(attempt_root))}",
            "exec bash run.sh",
            "",
        ]
    )


def prepare_attempt(
    workspace: Workspace,
    project_id: str,
    run_id: str,
    *,
    build_id: str | None = None,
    attempt_id: str | None = None,
    resource_override: dict[str, Any] | None = None,
    environment_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    resolved_build, local_run_root, run = load_run(workspace, project_id, run_id, build_id)
    build = load_build(workspace, project_id, resolved_build)
    site = SiteOps.from_workspace(workspace, str(build["site"]))
    site_build = site_build_root(site, project_id, resolved_build)
    result_path = site_build / "build-result.json"
    if not site.is_file(result_path) or site.read_json(result_path).get("status") != "completed":
        raise EntityError(f"build is not completed: {resolved_build}", code="build_not_ready")
    run_root = site_run_root(site, project_id, resolved_build, run_id)
    attempt_id = require_id(attempt_id or _new_attempt_id(), "attempt id")
    attempt_root = run_root / "attempts" / attempt_id
    if site.exists(attempt_root):
        raise EntityError(f"attempt already exists: {attempt_id}", code="already_exists")
    local_input = local_run_root / "input.toml"
    site_input = run_root / "input.toml"
    if site.is_file(site_input):
        if site.read_text(site_input) != local_input.read_text(encoding="utf-8"):
            raise EntityError(
                f"Site Run TOML conflicts with Workspace record: {site_input}; repair it manually",
                code="run_input_conflict",
            )
    resources = _merge_resources(site.config, run, resource_override)
    environment = {str(key): str(value) for key, value in (run.get("environment") or {}).items()}
    environment.update({str(key): str(value) for key, value in (environment_override or {}).items()})
    scheduler = str((site.config.get("scheduler") or {}).get("kind") or "none")
    run_script = render_run_script(site, build, resources, environment, run_root)
    slurm_script = (
        render_slurm_script(project_id, run_id, attempt_id, resources, attempt_root)
        if scheduler == "slurm"
        else None
    )
    attempt = {
        "schema_version": 1,
        "id": attempt_id,
        "run": run_id,
        "build": resolved_build,
        "site": build["site"],
        "scheduler": scheduler,
        "resources": resources,
        "environment": environment,
        "status": "prepared",
        "prepared_at": now_utc(),
    }
    site.mkdir(run_root, run_root / "attempts", run_root / "data", run_root / "analysis", attempt_root)
    if not site.is_file(site_input):
        site.put_file(local_input, site_input)
    site.write_json(attempt_root / "attempt.json", attempt)
    site.write_text(attempt_root / "run.sh", run_script, executable=True)
    if slurm_script is not None:
        site.write_text(
            attempt_root / "job.slurm",
            slurm_script,
            executable=True,
        )
    return {**attempt, "root": str(attempt_root)}


def _parse_job_id(output: str) -> str:
    for line in output.splitlines():
        text = line.strip()
        match = re.fullmatch(r"Submitted batch job (\d+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.fullmatch(r"(\d+)(?:;[^\s;]+)?", text)
        if match:
            return match.group(1)
    raise EntityError(f"cannot parse Slurm job id from: {output!r}", code="submit_unknown")


def _parse_scheduler_state(output: str) -> str:
    known = {
        "PENDING", "RUNNING", "COMPLETING", "COMPLETED", "FAILED", "CANCELLED",
        "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED", "SUSPENDED",
    }
    tokens = re.split(r"[|\s]+", output.strip())
    for token in tokens:
        state = token.strip().upper().rstrip("+")
        if state in known:
            return state
    return output.strip().splitlines()[0].strip() if output.strip() else "UNKNOWN"


def submit_attempt(
    workspace: Workspace,
    project_id: str,
    run_id: str,
    attempt_id: str,
    *,
    build_id: str | None = None,
) -> dict[str, Any]:
    resolved_build, _, _ = load_run(workspace, project_id, run_id, build_id)
    build = load_build(workspace, project_id, resolved_build)
    site = SiteOps.from_workspace(workspace, str(build["site"]))
    attempt_root = site_run_root(site, project_id, resolved_build, run_id) / "attempts" / require_id(attempt_id, "attempt id")
    attempt_file = attempt_root / "attempt.json"
    if not site.is_file(attempt_file):
        raise EntityError(f"attempt not prepared: {attempt_id}", code="not_prepared")
    result_file = attempt_root / "submit-result.json"
    if site.is_file(result_file):
        return site.read_json(result_file)
    intent_file = attempt_root / "submit-intent.json"
    if site.is_file(intent_file):
        raise EntityError(
            f"submission outcome is uncertain for {attempt_id}; inspect the scheduler or process before manual repair",
            code="submit_uncertain",
        )
    claim = attempt_root / "submit-intent.lock"
    if not site.claim_directory(claim):
        if site.is_file(result_file):
            return site.read_json(result_file)
        raise EntityError(
            f"submission outcome is uncertain for {attempt_id}; inspect the scheduler or process before manual repair",
            code="submit_uncertain",
        )
    attempt = site.read_json(attempt_file)
    scheduler = str(attempt.get("scheduler") or "none")
    submitted_at = now_utc()
    intent = {
        "attempt": attempt_id,
        "scheduler": scheduler,
        "status": "submitting",
        "created_at": submitted_at,
    }
    site.write_json(intent_file, intent)
    if scheduler == "slurm":
        submit = str((site.config.get("scheduler") or {}).get("submit") or "sbatch")
        result = site.run([*shlex.split(submit), "job.slurm"], cwd=attempt_root, check=False)
        if result.returncode:
            failed = {
                "attempt": attempt_id,
                "scheduler": "slurm",
                "status": "failed",
                "submitted_at": submitted_at,
                "exit_code": result.returncode,
                "raw": (result.stderr or result.stdout).strip(),
            }
            site.write_json(result_file, failed)
            site.write_json(intent_file, {**intent, "status": "resolved", "resolved_at": now_utc()})
            raise EntityError(
                result.stderr.strip() or "Slurm submission failed",
                code="submit_failed",
            )
        try:
            job_id = _parse_job_id(result.stdout)
        except EntityError:
            unknown = {
                "attempt": attempt_id,
                "scheduler": "slurm",
                "status": "unknown",
                "submitted_at": submitted_at,
                "raw": result.stdout.strip(),
            }
            site.write_json(result_file, unknown)
            site.write_json(intent_file, {**intent, "status": "resolved", "resolved_at": now_utc()})
            raise
        record = {
            "attempt": attempt_id,
            "scheduler": "slurm",
            "job_id": job_id,
            "submitted_at": submitted_at,
            "raw": result.stdout.strip(),
        }
    else:
        stdout_path = attempt_root / "stdout.log"
        stderr_path = attempt_root / "stderr.log"
        exit_path = attempt_root / "exit-code"
        wrapper = f"bash run.sh; code=$?; printf '%s\\n' \"$code\" > {shlex.quote(str(exit_path))}; exit $code"
        if site.kind == "local":
            command = (
                f"nohup bash -c {shlex.quote(wrapper)} "
                f">{shlex.quote(str(stdout_path))} 2>{shlex.quote(str(stderr_path))} </dev/null & echo $!"
            )
            result = site.run(["bash", "-lc", command], cwd=attempt_root)
            try:
                pid = int(result.stdout.strip().splitlines()[-1])
            except (IndexError, ValueError) as exc:
                raise EntityError("direct submission returned no process id", code="submit_unknown") from exc
        else:
            command = f"nohup bash -c {shlex.quote(wrapper)} >stdout.log 2>stderr.log </dev/null & echo $!"
            result = site.run(["bash", "-lc", command], cwd=attempt_root)
            try:
                pid = int(result.stdout.strip().splitlines()[-1])
            except (IndexError, ValueError) as exc:
                raise EntityError("direct submission returned no process id", code="submit_unknown") from exc
        record = {
            "attempt": attempt_id,
            "scheduler": "none",
            "pid": pid,
            "submitted_at": submitted_at,
        }
    site.write_json(result_file, record)
    site.write_json(intent_file, {**intent, "status": "resolved", "resolved_at": now_utc()})
    return record


def attempt_status(
    workspace: Workspace,
    project_id: str,
    run_id: str,
    attempt_id: str,
    *,
    build_id: str | None = None,
) -> dict[str, Any]:
    resolved_build, _, _ = load_run(workspace, project_id, run_id, build_id)
    build = load_build(workspace, project_id, resolved_build)
    site = SiteOps.from_workspace(workspace, str(build["site"]))
    attempt_id = require_id(attempt_id, "attempt id")
    root = site_run_root(site, project_id, resolved_build, run_id) / "attempts" / attempt_id
    result_file = root / "submit-result.json"
    if not site.is_file(result_file):
        intent_file = root / "submit-intent.json"
        if site.is_file(intent_file):
            intent = site.read_json(intent_file)
            return {**intent, "state": "UNKNOWN"}
        if site.exists(root / "submit-intent.lock"):
            return {"attempt": attempt_id, "state": "UNKNOWN", "status": "submitting"}
        if site.is_file(root / "attempt.json"):
            return {"attempt": attempt_id, "state": "PREPARED"}
        raise EntityError(f"attempt not prepared: {attempt_id}", code="not_prepared")
    result = site.read_json(result_file)
    if result.get("scheduler") == "slurm":
        if not result.get("job_id"):
            return {**result, "state": "UNKNOWN"}
        scheduler = site.config.get("scheduler") or {}
        query = str(scheduler.get("query") or "squeue")
        probe = site.run([*shlex.split(query), "-h", "-j", str(result["job_id"]), "-o", "%T"], check=False)
        state = _parse_scheduler_state(probe.stdout) if probe.stdout.strip() else ""
        if not state:
            accounting = str(scheduler.get("accounting") or "sacct")
            probe = site.run(
                [*shlex.split(accounting), "-n", "-j", str(result["job_id"]), "--format=State"],
                check=False,
            )
            state = _parse_scheduler_state(probe.stdout)
        return {**result, "state": state or "UNKNOWN"}
    exit_file = root / "exit-code"
    if site.is_file(exit_file):
        code_text = site.read_text(exit_file).strip()
        code = int(code_text) if code_text.lstrip("-").isdigit() else None
        return {**result, "state": "COMPLETED" if code == 0 else "FAILED", "exit_code": code}
    pid = int(result["pid"])
    if site.kind == "local":
        try:
            os.kill(pid, 0)
            state = "RUNNING"
        except ProcessLookupError:
            state = "UNKNOWN"
        except PermissionError:
            state = "RUNNING"
    else:
        state = "RUNNING" if site.run(["kill", "-0", str(pid)], check=False).returncode == 0 else "UNKNOWN"
    return {**result, "state": state}


def data_summary(
    workspace: Workspace,
    project_id: str,
    run_id: str,
    *,
    build_id: str | None = None,
) -> dict[str, Any]:
    resolved_build, _, _ = load_run(workspace, project_id, run_id, build_id)
    build = load_build(workspace, project_id, resolved_build)
    site = SiteOps.from_workspace(workspace, str(build["site"]))
    root = site_run_root(site, project_id, resolved_build, run_id) / "data"
    if not site.exists(root):
        return {"run": run_id, "path": str(root), "files": 0, "bytes": 0, "checkpoints": 0}
    if site.kind == "local":
        files = [path for path in Path(root).rglob("*") if path.is_file()]
        return {
            "run": run_id,
            "path": str(root),
            "files": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "checkpoints": sum("ckpt" in path.name.lower() or "checkpoint" in path.name.lower() for path in files),
            "checked_at": now_utc(),
        }
    command = (
        "files=$(find . -type f | wc -l); "
        "bytes=$(find . -type f -exec stat -c %s {} + 2>/dev/null | awk '{s+=$1} END {print s+0}'); "
        "ckpt=$(find . -type f | grep -Eic 'ckpt|checkpoint' || true); "
        "printf '%s %s %s\\n' \"$files\" \"$bytes\" \"$ckpt\""
    )
    result = site.run(["bash", "-lc", command], cwd=root)
    files, size, checkpoints = [int(value) for value in result.stdout.strip().split()]
    return {
        "run": run_id,
        "path": str(root),
        "files": files,
        "bytes": size,
        "checkpoints": checkpoints,
        "checked_at": now_utc(),
    }
