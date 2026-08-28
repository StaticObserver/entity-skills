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
    return datetime.now(timezone.utc).strftime("attempt-%Y%m%dT%H%M%SZ")


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
    except KeyError as exc:
        raise EntityError(f"MPI template requires resource: {exc.args[0]}", code="invalid_record") from exc


def render_run_script(
    site: SiteOps,
    build: dict[str, Any],
    run: dict[str, Any],
    resources: dict[str, Any],
    run_root: PurePosixPath,
) -> str:
    site_env = site.path(str((site.config.get("environment") or {}).get("script") or "site-env.sh"))
    deps_env = site.path("deps", str(build["deps"]), "env.sh")
    executable = site_build_root(site, "__PROJECT__", str(build["id"])) / "bin" / "entity"
    # Replace the temporary project marker using the actual run path hierarchy.
    executable = run_root.parents[1] / "bin" / "entity"
    input_toml = run_root / "input.toml"
    data_root = run_root / "data"
    exports: list[str] = []
    for key, value in sorted((run.get("environment") or {}).items()):
        if not ENV_NAME.fullmatch(str(key)):
            raise EntityError(f"invalid environment variable name: {key}", code="invalid_record")
        exports.append(f"export {key}={shlex.quote(str(value))}")
    command = _launcher(site.config, build, resources) + [str(executable), str(input_toml)]
    extra = (build.get("runtime") or {}).get("arguments") or []
    if extra:
        values = {"toml": str(input_toml), "data": str(data_root), "executable": str(executable)}
        command = _launcher(site.config, build, resources) + [str(executable)] + [
            str(item).format(**values) for item in extra
        ]
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
            directives.append(f"#SBATCH --{option}={resources[key]}")
    gres = resources.get("gres")
    if not gres and resources.get("gpus_per_node"):
        gres = f"gpu:{resources['gpus_per_node']}"
    if gres:
        directives.append(f"#SBATCH --gres={gres}")
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
    site.mkdir(run_root, run_root / "attempts", run_root / "data", run_root / "analysis", attempt_root)
    if not site.is_file(run_root / "input.toml"):
        site.put_file(local_run_root / "input.toml", run_root / "input.toml")
    resources = _merge_resources(site.config, run, resource_override)
    scheduler = str((site.config.get("scheduler") or {}).get("kind") or "none")
    attempt = {
        "schema_version": 1,
        "id": attempt_id,
        "run": run_id,
        "build": resolved_build,
        "site": build["site"],
        "scheduler": scheduler,
        "resources": resources,
        "status": "prepared",
        "prepared_at": now_utc(),
    }
    site.write_json(attempt_root / "attempt.json", attempt)
    run_script = render_run_script(site, build, run, resources, run_root)
    site.write_text(attempt_root / "run.sh", run_script, executable=True)
    if scheduler == "slurm":
        site.write_text(
            attempt_root / "job.slurm",
            render_slurm_script(project_id, run_id, attempt_id, resources, attempt_root),
            executable=True,
        )
    return {**attempt, "root": str(attempt_root)}


def _parse_job_id(output: str) -> str:
    match = re.search(r"\b(\d+)\b", output)
    if not match:
        raise EntityError(f"cannot parse Slurm job id from: {output!r}", code="submit_unknown")
    return match.group(1)


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
    attempt = site.read_json(attempt_file)
    scheduler = str(attempt.get("scheduler") or "none")
    submitted_at = now_utc()
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
            pid = int(result.stdout.strip().splitlines()[-1])
        else:
            command = f"nohup bash -c {shlex.quote(wrapper)} >stdout.log 2>stderr.log </dev/null & echo $!"
            result = site.run(["bash", "-lc", command], cwd=attempt_root)
            pid = int(result.stdout.strip().splitlines()[-1])
        record = {
            "attempt": attempt_id,
            "scheduler": "none",
            "pid": pid,
            "submitted_at": submitted_at,
        }
    site.write_json(result_file, record)
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
    root = site_run_root(site, project_id, resolved_build, run_id) / "attempts" / attempt_id
    result = site.read_json(root / "submit-result.json")
    if result.get("scheduler") == "slurm":
        if not result.get("job_id"):
            return {**result, "state": "UNKNOWN"}
        scheduler = site.config.get("scheduler") or {}
        query = str(scheduler.get("query") or "squeue")
        probe = site.run([*shlex.split(query), "-h", "-j", str(result["job_id"]), "-o", "%T"], check=False)
        state = probe.stdout.strip().splitlines()[0] if probe.stdout.strip() else ""
        if not state:
            accounting = str(scheduler.get("accounting") or "sacct")
            probe = site.run(
                [*shlex.split(accounting), "-n", "-j", str(result["job_id"]), "--format=State"],
                check=False,
            )
            state = probe.stdout.strip().splitlines()[0].split()[0] if probe.stdout.strip() else "UNKNOWN"
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
