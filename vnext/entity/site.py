from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from .errors import EntityError
from .paths import Workspace
from .records import load_json, now_utc, require_fields, require_id, write_json, write_text


def add_site(workspace: Workspace, config: dict[str, Any]) -> dict[str, Any]:
    site_id = require_id(str(config.get("id") or ""), "site id")
    root = str(config.get("root") or "")
    if not root.startswith("/"):
        raise EntityError("site root must be an absolute path", code="invalid_record")
    transport = config.get("transport") or {"kind": "local"}
    scheduler = config.get("scheduler") or {"kind": "none"}
    if transport.get("kind") not in {"local", "ssh"}:
        raise EntityError("transport.kind must be local or ssh", code="invalid_record")
    if transport.get("kind") == "ssh" and not transport.get("alias"):
        raise EntityError("SSH site requires transport.alias", code="invalid_record")
    if scheduler.get("kind") not in {"none", "slurm"}:
        raise EntityError("scheduler.kind must be none or slurm", code="invalid_record")
    record = dict(config)
    record.setdefault("schema_version", 1)
    record["id"] = site_id
    record["root"] = root
    record["transport"] = transport
    record["scheduler"] = scheduler
    record.setdefault("environment", {"script": "site-env.sh"})
    record.setdefault("mpi", {"launcher": "mpirun", "template": ["mpirun", "-np", "{tasks}"]})
    record.setdefault("created_at", now_utc())
    write_json(workspace.site_file(site_id), record, replace=False)
    return record


def load_site(workspace: Workspace, site_id: str) -> dict[str, Any]:
    path = workspace.site_file(site_id)
    record = load_json(path)
    require_fields(record, ("id", "root", "transport", "scheduler"), path)
    return record


class SiteOps:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.root = PurePosixPath(str(config["root"]))
        transport = config.get("transport") or {}
        self.kind = str(transport.get("kind") or "local")
        self.alias = str(transport.get("alias") or "")

    @classmethod
    def from_workspace(cls, workspace: Workspace, site_id: str) -> "SiteOps":
        return cls(load_site(workspace, site_id))

    def path(self, *parts: str) -> PurePosixPath:
        result = self.root
        for part in parts:
            result /= part
        return result

    def _ssh(self, command: str, *, capture: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["ssh", self.alias, command],
            text=True,
            capture_output=capture,
            check=False,
        )
        return result

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: PurePosixPath | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if self.kind == "local":
            result = subprocess.run(
                list(argv),
                cwd=str(cwd) if cwd else None,
                text=True,
                capture_output=True,
                check=False,
            )
        else:
            command = " ".join(shlex.quote(str(item)) for item in argv)
            if cwd:
                command = f"cd {shlex.quote(str(cwd))} && {command}"
            result = self._ssh(command)
        if check and result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise EntityError(detail or f"site command failed: {argv[0]}", code="site_command_failed")
        return result

    def mkdir(self, *paths: PurePosixPath) -> None:
        if self.kind == "local":
            for path in paths:
                Path(path).mkdir(parents=True, exist_ok=True)
        else:
            self.run(["mkdir", "-p", "--", *[str(path) for path in paths]])

    def exists(self, path: PurePosixPath) -> bool:
        if self.kind == "local":
            return Path(path).exists()
        return self.run(["test", "-e", str(path)], check=False).returncode == 0

    def is_file(self, path: PurePosixPath) -> bool:
        if self.kind == "local":
            return Path(path).is_file()
        return self.run(["test", "-f", str(path)], check=False).returncode == 0

    def read_text(self, path: PurePosixPath) -> str:
        if self.kind == "local":
            try:
                return Path(path).read_text(encoding="utf-8")
            except FileNotFoundError as exc:
                raise EntityError(f"site file not found: {path}", code="not_found") from exc
        return self.run(["cat", str(path)]).stdout

    def read_json(self, path: PurePosixPath) -> dict[str, Any]:
        try:
            value = json.loads(self.read_text(path))
        except json.JSONDecodeError as exc:
            raise EntityError(f"invalid site JSON {path}: {exc}", code="invalid_json") from exc
        if not isinstance(value, dict):
            raise EntityError(f"site JSON root must be object: {path}", code="invalid_json")
        return value

    def write_text(self, path: PurePosixPath, text: str, *, executable: bool = False) -> None:
        if self.kind == "local":
            write_text(Path(path), text, executable=executable)
            return
        with tempfile.TemporaryDirectory(prefix="entity-site-write-") as temp:
            local = Path(temp) / "payload"
            write_text(local, text, executable=executable)
            self.mkdir(path.parent)
            destination = f"{self.alias}:{shlex.quote(str(path))}"
            result = subprocess.run(["scp", "-q", str(local), destination], text=True, capture_output=True)
            if result.returncode:
                raise EntityError(result.stderr.strip() or f"scp failed: {path}", code="site_command_failed")

    def write_json(self, path: PurePosixPath, value: dict[str, Any]) -> None:
        self.write_text(path, json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")

    def put_file(self, source: Path, destination: PurePosixPath) -> None:
        source = source.resolve()
        if not source.is_file():
            raise EntityError(f"local file not found: {source}", code="not_found")
        self.mkdir(destination.parent)
        if self.kind == "local":
            shutil.copy2(source, Path(destination))
            return
        result = subprocess.run(
            ["scp", "-q", str(source), f"{self.alias}:{shlex.quote(str(destination))}"],
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise EntityError(result.stderr.strip() or f"scp failed: {destination}", code="site_command_failed")

    def put_tree(self, source: Path, destination: PurePosixPath) -> None:
        source = source.resolve()
        if not source.is_dir():
            raise EntityError(f"local directory not found: {source}", code="not_found")
        if self.exists(destination):
            raise EntityError(f"site destination already exists: {destination}", code="already_exists")
        self.mkdir(destination.parent)
        if self.kind == "local":
            shutil.copytree(source, Path(destination), symlinks=True)
            return
        command = ["ssh", self.alias, f"mkdir -p {shlex.quote(str(destination))} && tar -C {shlex.quote(str(destination))} -xf -"]
        tar = subprocess.Popen(["tar", "-C", str(source), "-cf", "-", "."], stdout=subprocess.PIPE)
        remote = subprocess.run(command, stdin=tar.stdout, capture_output=True)
        assert tar.stdout is not None
        tar.stdout.close()
        tar_code = tar.wait()
        if tar_code or remote.returncode:
            raise EntityError("failed to copy directory to SSH site", code="site_command_failed")


def init_site(workspace: Workspace, site_id: str) -> dict[str, Any]:
    config = load_site(workspace, site_id)
    site = SiteOps(config)
    roots = [
        site.root,
        site.path("checkouts"),
        site.path("deps"),
        site.path("staging", "deps"),
        site.path("projects"),
    ]
    site.mkdir(*roots)
    site.write_json(site.path("site.json"), config)
    env_path = site.path(str((config.get("environment") or {}).get("script") or "site-env.sh"))
    if not site.exists(env_path):
        site.write_text(env_path, "#!/usr/bin/env bash\n# Site-wide shell initialization.\n", executable=True)
    return config


def add_deps(
    workspace: Workspace,
    site_id: str,
    deps_id: str,
    config: dict[str, Any],
    env_text: str,
) -> dict[str, Any]:
    deps_id = require_id(deps_id, "deps id")
    init_site(workspace, site_id)
    site = SiteOps.from_workspace(workspace, site_id)
    root = site.path("deps", deps_id)
    if site.exists(root):
        raise EntityError(f"deps already exists: {deps_id}", code="already_exists")
    site.mkdir(
        root,
        root / "install",
        root / "sources",
        root / "scripts",
        root / "logs",
    )
    record = dict(config)
    record.update({"schema_version": 1, "id": deps_id, "site": site_id})
    record.setdefault("kind", "build")
    record.setdefault("status", "ready")
    record.setdefault("created_at", now_utc())
    site.write_json(root / "deps.json", record)
    if not env_text.startswith("#!"):
        env_text = "#!/usr/bin/env bash\n" + env_text
    site.write_text(root / "env.sh", env_text.rstrip() + "\n", executable=True)
    return record


def load_deps(site: SiteOps, deps_id: str) -> dict[str, Any]:
    deps_id = require_id(deps_id, "deps id")
    return site.read_json(site.path("deps", deps_id, "deps.json"))
