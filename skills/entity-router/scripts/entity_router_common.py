#!/usr/bin/env python3
"""Shared primitives for the Entity Router runtime.

The module is standard-library only and remains compatible with Python 3.6 so
the same probe helpers can run on older HPC login nodes.
"""

from __future__ import print_function

import datetime
import hashlib
import json
import os
import shlex
import stat
import subprocess
import tempfile


SITE_SCHEMA_VERSION = 1

ACTOR_ENVIRONMENT = {
    "run_id": "ENTITY_AGENT_RUN_ID",
    "provider": "ENTITY_AGENT_PROVIDER",
    "client": "ENTITY_AGENT_CLIENT",
    "session_id": "ENTITY_AGENT_SESSION_ID",
    "model": "ENTITY_AGENT_MODEL",
    "bundle_hash": "ENTITY_SKILLS_BUNDLE_HASH",
}


class RouterError(Exception):
    pass


def now_utc():
    value = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def absolute(path):
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def router_home(value=None):
    return absolute(value or os.environ.get("ENTITY_ROUTER_HOME", "~/.entity-router"))


def actor_identity(values=None):
    """Return a stable, non-secret Agent run identity for state provenance.

    ``values`` may be an argparse namespace or a mapping.  Explicit values win
    over environment variables.  Missing identity is recorded as
    ``unattributed`` rather than guessed from a process or client directory.
    """
    result = {}
    for key, environment in ACTOR_ENVIRONMENT.items():
        explicit = None
        if isinstance(values, dict):
            explicit = values.get("actor_" + key)
        elif values is not None:
            explicit = getattr(values, "actor_" + key, None)
        value = explicit if explicit is not None else os.environ.get(environment, "")
        result[key] = str(value or "").strip()
    if not result["run_id"]:
        result["run_id"] = "unattributed"
    return result


def require_attributed_actor(actor):
    if os.environ.get("ENTITY_ROUTER_REQUIRE_ACTOR", "") == "1":
        if not actor or actor.get("run_id") == "unattributed":
            raise RouterError(
                "mutation requires ENTITY_AGENT_RUN_ID or --actor-run-id"
            )
    return actor


def atomic_write_json(path, value):
    path = absolute(path)
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def load_json(path, label="JSON file"):
    try:
        with open(path, "r") as handle:
            value = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise RouterError("cannot read %s %s: %s" % (label, path, exc))
    if not isinstance(value, dict):
        raise RouterError("%s must contain a JSON object: %s" % (label, path))
    return value


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_locator(value):
    if isinstance(value, dict):
        site_id = str(value.get("site_id", "")).strip()
        path = str(value.get("path", "")).strip()
    else:
        text = str(value or "")
        if ":" not in text:
            raise RouterError("locator must use SITE_ID:/absolute/path: %s" % text)
        site_id, path = text.split(":", 1)
        site_id = site_id.strip()
        path = path.strip()
    if not site_id or not path or not path.startswith("/"):
        raise RouterError("locator must use SITE_ID:/absolute/path")
    return {"site_id": site_id, "path": os.path.normpath(path)}


def locator_within(locator, root):
    locator = parse_locator(locator)
    root = parse_locator(root)
    if locator["site_id"] != root["site_id"]:
        return False
    try:
        return os.path.commonpath([locator["path"], root["path"]]) == root["path"]
    except ValueError:
        return False


def validate_site_profile(profile):
    if profile.get("schema_version") != SITE_SCHEMA_VERSION:
        raise RouterError("unsupported site profile schema")
    site_id = str(profile.get("site_id", ""))
    if not site_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in site_id):
        raise RouterError("invalid site_id: %s" % site_id)
    transport = profile.get("transport", {})
    kind = transport.get("kind")
    if kind not in {"local", "ssh"}:
        raise RouterError("site transport.kind must be local or ssh")
    if kind == "ssh" and not transport.get("ssh_alias"):
        raise RouterError("ssh site requires transport.ssh_alias")
    scheduler = profile.get("scheduler", {})
    if scheduler.get("kind", "none") not in {"none", "slurm", "pbs", "custom"}:
        raise RouterError("unsupported scheduler kind")
    for name, path in profile.get("roots", {}).items():
        if path and not str(path).startswith("/"):
            raise RouterError("site root %s must be absolute" % name)
    for mapping in profile.get("shared_mappings", []):
        if not mapping.get("peer_site_id"):
            raise RouterError("shared mapping requires peer_site_id")
        for name in ["this_root", "peer_root"]:
            if not str(mapping.get(name, "")).startswith("/"):
                raise RouterError("shared mapping %s must be absolute" % name)
    return profile


def run_command(command, cwd=None):
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stdout, stderr = process.communicate()
    return process.returncode, stdout, stderr


def run_on_site(profile, argv):
    kind = profile["transport"]["kind"]
    if kind == "local":
        return run_command(argv)
    alias = profile["transport"]["ssh_alias"]
    remote = " ".join(shlex.quote(str(item)) for item in argv)
    return run_command([
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", alias, remote
    ])


def git_revision(profile, path):
    code, stdout, stderr = run_on_site(
        profile, ["git", "-C", path, "rev-parse", "HEAD", "HEAD^{tree}"]
    )
    if code != 0:
        return None
    values = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(values) < 2:
        return None
    dirty_code, dirty_out, unused = run_on_site(
        profile, ["git", "-C", path, "status", "--porcelain"]
    )
    return {
        "kind": "git",
        "commit": values[0],
        "tree": values[1],
        "dirty": dirty_code != 0 or bool(dirty_out.strip()),
    }


def _git_files(source):
    code, stdout, unused = run_command(
        ["git", "-C", source, "ls-files", "-co", "--exclude-standard"]
    )
    if code == 0:
        return sorted(set(line for line in stdout.splitlines() if line))
    files = []
    for root, dirs, names in os.walk(source):
        dirs[:] = sorted(name for name in dirs if name not in {".git", "__pycache__", "build", "_build"} and not name.startswith("run-"))
        for name in sorted(names):
            relative = os.path.relpath(os.path.join(root, name), source)
            files.append(relative)
    return files


def source_manifest(source):
    source = absolute(source)
    if not os.path.isdir(source):
        raise RouterError("snapshot source is not a directory: %s" % source)
    entries = []
    for relative in _git_files(source):
        path = os.path.join(source, relative)
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        entries.append({
            "path": relative,
            "sha256": sha256_file(path),
            "size": os.path.getsize(path),
            "mode": stat.S_IMODE(os.stat(path).st_mode),
        })
    revision = git_revision({"transport": {"kind": "local"}}, source)
    payload = {
        "schema_version": 1,
        "source": source,
        "base_revision": revision or {},
        "files": entries,
    }
    identity = {
        "schema_version": payload["schema_version"],
        "base_revision": payload["base_revision"],
        "files": payload["files"],
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["snapshot_id"] = hashlib.sha256(canonical).hexdigest()
    return payload
