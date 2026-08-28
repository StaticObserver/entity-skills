from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import EntityError
from .paths import Workspace
from .records import copy_tree, load_json, now_utc, require_fields, require_id, write_json


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise EntityError(result.stderr.strip() or f"git failed in {path}", code="git_error")
    return result.stdout.strip()


def add_source(
    workspace: Workspace,
    project_id: str,
    source_id: str,
    repository: str,
    commit: str,
    checkout: Path | None = None,
) -> dict[str, Any]:
    source_id = require_id(source_id, "source id")
    if not repository or not commit:
        raise EntityError("source requires repository and git commit", code="invalid_record")
    root = workspace.source_dir(project_id, source_id)
    if root.exists():
        raise EntityError(f"source already exists: {source_id}", code="already_exists")
    root.mkdir(parents=True)
    checkout_name = "checkout"
    if checkout:
        checkout = checkout.expanduser().resolve()
        if not checkout.is_dir():
            raise EntityError(f"source checkout not found: {checkout}", code="not_found")
        actual = _git(checkout, "rev-parse", "HEAD")
        expected = _git(checkout, "rev-parse", commit)
        if actual != expected:
            raise EntityError(
                f"checkout HEAD {actual} does not match requested commit {expected}",
                code="source_mismatch",
            )
        destination = root / checkout_name
        subprocess.run(
            ["git", "clone", "--no-hardlinks", "--no-checkout", str(checkout), str(destination)],
            check=True,
            text=True,
            capture_output=True,
        )
        _git(destination, "checkout", "--detach", expected)
        commit = expected
    record = {
        "schema_version": 1,
        "id": source_id,
        "repository": repository,
        "git_commit": commit,
        "checkout": checkout_name,
        "created_at": now_utc(),
    }
    write_json(root / "source.json", record, replace=False)
    return record


def add_pgen(
    workspace: Workspace,
    project_id: str,
    pgen_id: str,
    source_dir: Path,
    entry: str,
    name: str | None = None,
) -> dict[str, Any]:
    pgen_id = require_id(pgen_id, "pgen id")
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise EntityError(f"PGen directory not found: {source_dir}", code="not_found")
    if not (source_dir / entry).is_file():
        raise EntityError(f"PGen entry not found: {source_dir / entry}", code="not_found")
    root = workspace.pgen_dir(project_id, pgen_id)
    if root.exists():
        raise EntityError(f"PGen already exists: {pgen_id}", code="already_exists")
    copy_tree(source_dir, root)
    record = {
        "schema_version": 1,
        "id": pgen_id,
        "name": name or pgen_id,
        "entry": entry,
        "created_at": now_utc(),
    }
    write_json(root / "pgen.json", record, replace=False)
    return record


def add_build(
    workspace: Workspace,
    project_id: str,
    build_id: str,
    source_id: str,
    pgen_id: str,
    site_id: str,
    deps_id: str,
    options: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    build_id = require_id(build_id, "build id")
    require_id(source_id, "source id")
    require_id(pgen_id, "pgen id")
    require_id(site_id, "site id")
    require_id(deps_id, "deps id")
    if not (workspace.source_dir(project_id, source_id) / "source.json").is_file():
        raise EntityError(f"source not found: {source_id}", code="dangling_reference")
    if not (workspace.pgen_dir(project_id, pgen_id) / "pgen.json").is_file():
        raise EntityError(f"PGen not found: {pgen_id}", code="dangling_reference")
    if not workspace.site_file(site_id).is_file():
        raise EntityError(f"site not found: {site_id}", code="dangling_reference")
    root = workspace.build_dir(project_id, build_id)
    if root.exists():
        raise EntityError(f"build already exists: {build_id}", code="already_exists")
    (root / "runs").mkdir(parents=True)
    record = {
        "schema_version": 1,
        "id": build_id,
        "source": source_id,
        "pgen": pgen_id,
        "site": site_id,
        "deps": deps_id,
        "options": options or {},
        "runtime": runtime or {"mpi": False, "gpu": False},
        "created_at": now_utc(),
    }
    write_json(root / "build.json", record, replace=False)
    return record


def add_run(
    workspace: Workspace,
    project_id: str,
    run_id: str,
    build_id: str,
    toml: Path,
    resources: dict[str, Any] | None = None,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    run_id = require_id(run_id, "run id")
    build_root = workspace.build_dir(project_id, build_id)
    if not (build_root / "build.json").is_file():
        raise EntityError(f"build not found: {build_id}", code="dangling_reference")
    toml = toml.expanduser().resolve()
    if not toml.is_file():
        raise EntityError(f"TOML not found: {toml}", code="not_found")
    root = workspace.run_dir(project_id, build_id, run_id)
    if root.exists():
        raise EntityError(f"run already exists: {run_id}", code="already_exists")
    root.mkdir(parents=True)
    shutil.copy2(toml, root / "input.toml")
    record = {
        "schema_version": 1,
        "id": run_id,
        "build": build_id,
        "toml": "input.toml",
        "resources": resources or {},
        "environment": environment or {},
        "created_at": now_utc(),
    }
    write_json(root / "run.json", record, replace=False)
    return record


def load_source(workspace: Workspace, project_id: str, source_id: str) -> dict[str, Any]:
    path = workspace.source_dir(project_id, source_id) / "source.json"
    record = load_json(path)
    require_fields(record, ("id", "repository", "git_commit", "checkout"), path)
    return record


def load_pgen(workspace: Workspace, project_id: str, pgen_id: str) -> dict[str, Any]:
    path = workspace.pgen_dir(project_id, pgen_id) / "pgen.json"
    record = load_json(path)
    require_fields(record, ("id", "entry"), path)
    return record


def load_build(workspace: Workspace, project_id: str, build_id: str) -> dict[str, Any]:
    path = workspace.build_dir(project_id, build_id) / "build.json"
    record = load_json(path)
    require_fields(record, ("id", "source", "pgen", "site", "deps"), path)
    return record


def load_run(
    workspace: Workspace,
    project_id: str,
    run_id: str,
    build_id: str | None = None,
) -> tuple[str, Path, dict[str, Any]]:
    resolved_build, root = workspace.find_run(project_id, run_id, build_id)
    path = root / "run.json"
    record = load_json(path)
    require_fields(record, ("id", "build", "toml"), path)
    return resolved_build, root, record
