from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import Any, Iterable

from .errors import EntityError
from .objects import load_build, load_pgen, load_source
from .paths import Workspace
from .records import now_utc
from .site import SiteOps, init_site, load_deps


def site_build_root(site: SiteOps, project_id: str, build_id: str) -> PurePosixPath:
    return site.path("projects", project_id, "builds", build_id)


def _shell_command(parts: Iterable[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def _expand_command(parts: list[Any], values: dict[str, str]) -> list[str]:
    expanded: list[str] = []
    for part in parts:
        text = str(part)
        try:
            expanded.append(text.format(**values))
        except KeyError as exc:
            raise EntityError(f"unknown build command placeholder: {exc.args[0]}", code="invalid_record") from exc
    return expanded


def _materialize_source(site: SiteOps, source: dict[str, Any]) -> PurePosixPath:
    target = site.path("checkouts", str(source["id"]))
    commit = str(source["git_commit"])
    if site.exists(target):
        actual = site.run(["git", "rev-parse", "HEAD"], cwd=target).stdout.strip()
        expected = site.run(["git", "rev-parse", commit], cwd=target).stdout.strip()
        if actual != expected:
            raise EntityError(
                f"site checkout {target} is at {actual}, expected {expected}",
                code="source_mismatch",
            )
        return target
    repository = str(source["repository"])
    site.run(["git", "clone", "--no-checkout", repository, str(target)])
    site.run(["git", "checkout", "--detach", commit], cwd=target)
    return target


def _default_cmake_options(build: dict[str, Any], pgen_entry: PurePosixPath) -> list[str]:
    options = build.get("options") or {}
    result = [f"-Dpgen={pgen_entry}"]
    backend = str(options.get("backend") or "cpu").lower()
    if backend == "cuda":
        result.append("-DKokkos_ENABLE_CUDA=ON")
    elif backend == "hip":
        result.append("-DKokkos_ENABLE_HIP=ON")
    gpu_arch = str(options.get("gpu_arch") or "")
    if gpu_arch:
        key = gpu_arch if gpu_arch.startswith("Kokkos_ARCH_") else f"Kokkos_ARCH_{gpu_arch}"
        result.append(f"-D{key}=ON")
    for value in options.get("cmake_options") or []:
        result.append(str(value))
    return result


def render_build_script(
    site: SiteOps,
    build: dict[str, Any],
    source_checkout: PurePosixPath,
    pgen_entry: PurePosixPath,
    root: PurePosixPath,
) -> str:
    deps_env = site.path("deps", str(build["deps"]), "env.sh")
    site_env = site.path(str((site.config.get("environment") or {}).get("script") or "site-env.sh"))
    work = root / "work"
    bin_dir = root / "bin"
    logs = root / "logs"
    options = build.get("options") or {}
    jobs = str(options.get("jobs") or 4)
    values = {
        "source": str(source_checkout),
        "pgen": str(pgen_entry),
        "work": str(work),
        "bin": str(bin_dir),
        "logs": str(logs),
        "jobs": jobs,
    }
    custom = "configure_command" in options or "build_command" in options
    commands: list[str] = []
    if custom:
        configure = options.get("configure_command") or []
        compile_command = options.get("build_command") or []
        if configure:
            if not isinstance(configure, list):
                raise EntityError("options.configure_command must be a JSON array", code="invalid_record")
            commands.append(_shell_command(_expand_command(configure, values)))
        if not isinstance(compile_command, list) or not compile_command:
            raise EntityError("custom build requires options.build_command array", code="invalid_record")
        commands.append(_shell_command(_expand_command(compile_command, values)))
    else:
        cmake_options = " ".join(shlex.quote(item) for item in _default_cmake_options(build, pgen_entry))
        commands.extend(
            [
                f'cmake -S "$SOURCE" -B "$WORK" {cmake_options}',
                f'cmake --build "$WORK" -j {shlex.quote(jobs)}',
            ]
        )
    executable_from = str(options.get("executable_from") or "{work}/src/entity.xc").format(**values)
    if executable_from != str(bin_dir / "entity"):
        commands.append(f"cp {shlex.quote(executable_from)} \"$BIN/entity\"")
    body = "\n".join(f"{command} 2>&1 | tee -a \"$LOGS/build.log\"" for command in commands)
    return f"""#!/usr/bin/env bash
set -euo pipefail

source {shlex.quote(str(site_env))}
source {shlex.quote(str(deps_env))}

SOURCE={shlex.quote(str(source_checkout))}
PGEN={shlex.quote(str(pgen_entry))}
WORK={shlex.quote(str(work))}
BIN={shlex.quote(str(bin_dir))}
LOGS={shlex.quote(str(logs))}

mkdir -p "$WORK" "$BIN" "$LOGS"
{body}
test -f "$BIN/entity"
chmod +x "$BIN/entity"
"""


def prepare_build(workspace: Workspace, project_id: str, build_id: str) -> dict[str, Any]:
    build = load_build(workspace, project_id, build_id)
    source = load_source(workspace, project_id, str(build["source"]))
    pgen = load_pgen(workspace, project_id, str(build["pgen"]))
    init_site(workspace, str(build["site"]))
    site = SiteOps.from_workspace(workspace, str(build["site"]))
    load_deps(site, str(build["deps"]))
    source_checkout = _materialize_source(site, source)
    root = site_build_root(site, project_id, build_id)
    if site.exists(root):
        raise EntityError(f"site build already prepared: {build_id}", code="already_exists")
    site.mkdir(root, root / "scripts", root / "work", root / "bin", root / "logs", root / "runs")
    pgen_destination = root / "pgen"
    site.put_tree(workspace.pgen_dir(project_id, str(build["pgen"])), pgen_destination)
    pgen_entry = pgen_destination / str(pgen["entry"])
    script = render_build_script(site, build, source_checkout, pgen_entry, root)
    site.write_text(root / "scripts" / "build.sh", script, executable=True)
    prepared = {
        "build": build_id,
        "site": build["site"],
        "root": str(root),
        "source_checkout": str(source_checkout),
        "pgen": str(pgen_destination),
        "script": str(root / "scripts" / "build.sh"),
        "prepared_at": now_utc(),
    }
    site.write_json(root / "build-prepared.json", prepared)
    return prepared


def run_build(workspace: Workspace, project_id: str, build_id: str) -> dict[str, Any]:
    build = load_build(workspace, project_id, build_id)
    site = SiteOps.from_workspace(workspace, str(build["site"]))
    root = site_build_root(site, project_id, build_id)
    script = root / "scripts" / "build.sh"
    if not site.is_file(script):
        raise EntityError(f"build is not prepared: {build_id}", code="not_prepared")
    started = now_utc()
    result = site.run(["bash", str(script)], cwd=root, check=False)
    executable = root / "bin" / "entity"
    status = "completed" if result.returncode == 0 and site.is_file(executable) else "failed"
    record = {
        "build": build_id,
        "status": status,
        "executable": "bin/entity",
        "script": "scripts/build.sh",
        "logs": "logs",
        "started_at": started,
        "finished_at": now_utc(),
        "exit_code": result.returncode,
    }
    if result.stderr.strip():
        record["error"] = result.stderr.strip()[-2000:]
    site.write_json(root / "build-result.json", record)
    if status != "completed":
        raise EntityError(
            record.get("error") or result.stdout.strip()[-2000:] or f"build failed: {build_id}",
            code="build_failed",
        )
    return record


def show_build_site(workspace: Workspace, project_id: str, build_id: str) -> dict[str, Any]:
    build = load_build(workspace, project_id, build_id)
    site = SiteOps.from_workspace(workspace, str(build["site"]))
    root = site_build_root(site, project_id, build_id)
    result = site.read_json(root / "build-result.json") if site.is_file(root / "build-result.json") else None
    return {"build": build, "site_root": str(root), "result": result}
