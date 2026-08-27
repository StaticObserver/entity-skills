#!/usr/bin/env python3
"""Shared primitives for the Entity Ledger runtime.

The module is standard-library only and remains compatible with Python 3.6 so
the same probe helpers can run on older HPC login nodes.
"""

from __future__ import print_function

import datetime
import hashlib
import json
import os
import re
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


class LedgerError(Exception):
    pass


# Slurm gres spec for a GPU allocation: "gpu:<count>" (generic) or
# "gpu:<type>:<count>" (typed, e.g. gpu:V100:1).  Kept in sync with the
# standalone executor's copy (entity_ledger_executor._GRES_RE).
GRES_RE = re.compile(r"^gpu(?::[A-Za-z0-9_.-]+)?:[0-9]+$")


def valid_gres(value):
    return bool(GRES_RE.match(str(value or "")))


def now_utc():
    value = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def absolute(path):
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def ledger_home(value=None):
    if value:
        return absolute(value)
    explicit = os.environ.get("ENTITY_LEDGER_HOME")
    if explicit:
        return absolute(explicit)
    # Backward compatibility with the pre-rename Router storage: honour the
    # legacy ENTITY_ROUTER_HOME variable when ENTITY_LEDGER_HOME is unset.
    legacy_env = os.environ.get("ENTITY_ROUTER_HOME")
    if legacy_env:
        return absolute(legacy_env)
    home = absolute("~/.entity-ledger")
    legacy = absolute("~/.entity-router")
    # One-time storage migration: adopt a pre-rename ~/.entity-router home.
    # A concurrent process may have completed the rename already (the legacy
    # path vanishes mid-call), so only a failure that leaves the new home
    # missing is an error.
    if not os.path.exists(home) and os.path.isdir(legacy):
        try:
            os.rename(legacy, home)
        except OSError:
            if not os.path.isdir(home):
                raise LedgerError(
                    "cannot migrate the legacy Ledger home %s to %s; move it "
                    "manually or set ENTITY_LEDGER_HOME" % (legacy, home))
    return home


def active_workspace_pointer():
    """Path of the active-workspace pointer file.  Reading it has no side
    effects (in particular it never triggers the legacy home migration)."""
    return os.path.join(absolute("~/.entity-ledger"), "active-workspace")


def read_active_workspace():
    """Return the adopted workspace path from the active-workspace pointer,
    or None when no pointer exists.  A corrupt pointer fails loudly instead
    of silently falling back to the legacy home."""
    path = active_workspace_pointer()
    if not os.path.isfile(path):
        return None
    record = load_json(path, "active-workspace pointer")
    workspace = str(record.get("workspace", "")).strip()
    if not workspace:
        raise LedgerError(
            "active-workspace pointer has no workspace path: %s" % path)
    return absolute(workspace)


def write_active_workspace(workspace):
    """Write the active-workspace pointer atomically; returns the record."""
    record = {"workspace": absolute(workspace), "adopted_at": now_utc()}
    atomic_write_json(active_workspace_pointer(), record)
    return record


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
    if os.environ.get("ENTITY_LEDGER_REQUIRE_ACTOR", "") == "1":
        if not actor or actor.get("run_id") == "unattributed":
            raise LedgerError(
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
        raise LedgerError("cannot read %s %s: %s" % (label, path, exc))
    if not isinstance(value, dict):
        raise LedgerError("%s must contain a JSON object: %s" % (label, path))
    return value


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Digest purposes from the hash-verification plan (WP0): every new digest
# declares exactly one.  Kept in sync with the standalone executor's copy
# (entity_ledger_executor._DOMAIN_PURPOSES).
DOMAIN_DIGEST_PURPOSES = {"identity", "evidence", "transfer", "observation"}


def domain_digest(purpose, schema, payload):
    """Domain-separated digest: "sha256:" + sha256 of the canonical JSON of
    {"purpose", "schema", "payload"}.  The purpose/schema pair keeps digests
    of identical payloads in different roles (identity vs evidence vs ...)
    from ever colliding."""
    if purpose not in DOMAIN_DIGEST_PURPOSES:
        raise LedgerError(
            "digest purpose must be one of %s (got %s)"
            % (sorted(DOMAIN_DIGEST_PURPOSES), purpose))
    canonical = json.dumps(
        {"purpose": purpose, "schema": schema, "payload": payload},
        sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def site_file_sha256(profile, path):
    """Fingerprint a file on its Site, locally or over SSH.  Returns "" when
    the file is absent; raises LedgerError when the Site cannot be queried."""
    if profile.get("transport", {}).get("kind") == "local":
        return sha256_file(path) if os.path.isfile(path) else ""
    script = (
        "import hashlib,os,sys; p=sys.argv[1]; "
        "print(hashlib.sha256(open(p,'rb').read()).hexdigest() if os.path.isfile(p) else '')"
    )
    code, stdout, stderr = run_on_site(profile, ["python3", "-c", script, path])
    if code != 0:
        raise LedgerError(
            "cannot fingerprint file on Site: %s" % (stderr.strip() or stdout.strip() or path))
    return stdout.strip()


def find_identity(items, identity_id):
    """Locate an identity payload by id (current key) or identity_id
    (legacy key); returns None when no item matches."""
    for item in items:
        if item.get("id") == identity_id or item.get("identity_id") == identity_id:
            return item
    return None


def load_simulation_confirmation(input_path):
    """Read ``<input>.decisions.json`` and compare it against the current
    input bytes.  Returns ``(record, matches)``: record is the parsed
    confirmation dict (None when the file is missing, unreadable, or of the
    wrong kind); matches is True only when the recorded input_sha256 equals
    the current file digest."""
    record = None
    try:
        with open(input_path + ".decisions.json", "r") as handle:
            candidate = json.load(handle)
        if (isinstance(candidate, dict)
                and candidate.get("kind") == "entity-pgen.simulation-confirmation"):
            record = candidate
    except (IOError, OSError, ValueError):
        record = None
    if record is None or not os.path.isfile(input_path):
        return record, False
    return record, record.get("input_sha256") == sha256_file(input_path)


def parse_locator(value):
    if isinstance(value, dict):
        site_id = str(value.get("site_id", "")).strip()
        path = str(value.get("path", "")).strip()
    else:
        text = str(value or "")
        if ":" not in text:
            raise LedgerError("locator must use SITE_ID:/absolute/path: %s" % text)
        site_id, path = text.split(":", 1)
        site_id = site_id.strip()
        path = path.strip()
    if not site_id or not path or not path.startswith("/"):
        raise LedgerError("locator must use SITE_ID:/absolute/path")
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


def validate_slug(value, label="slug"):
    """Directory-name slug: readable, filesystem-safe, no separators."""
    text = str(value or "").strip()
    if not text or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in text):
        raise LedgerError("invalid %s: %s" % (label, value))
    return text


def validate_site_profile(profile):
    if profile.get("schema_version") != SITE_SCHEMA_VERSION:
        raise LedgerError("unsupported site profile schema")
    site_id = str(profile.get("site_id", ""))
    if not site_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in site_id):
        raise LedgerError("invalid site_id: %s" % site_id)
    transport = profile.get("transport", {})
    kind = transport.get("kind")
    if kind not in {"local", "ssh"}:
        raise LedgerError("site transport.kind must be local or ssh")
    if kind == "ssh":
        alias = str(transport.get("ssh_alias", ""))
        # The alias is passed as an ssh/scp argv element; forbid leading dashes
        # and option syntax so it can never smuggle ssh options like
        # -oProxyCommand=... into the command line.
        if not alias or not re.match(r"^[A-Za-z0-9_.@][A-Za-z0-9_.@-]*$", alias):
            raise LedgerError("invalid transport.ssh_alias: %s" % alias)
    scheduler = profile.get("scheduler", {})
    if scheduler.get("kind", "none") not in {"none", "slurm", "pbs", "custom"}:
        raise LedgerError("unsupported scheduler kind")
    site_root = profile.get("site_root")
    if site_root and not str(site_root).startswith("/"):
        raise LedgerError("site_root must be absolute")
    policy = profile.get("policy", {})
    default_gres = str(policy.get("default_gres", "") or "")
    if default_gres and not valid_gres(default_gres):
        raise LedgerError(
            "policy.default_gres must match gpu[:type]:count: %s" % default_gres)
    for name, path in profile.get("roots", {}).items():
        if path and not str(path).startswith("/"):
            raise LedgerError("site root %s must be absolute" % name)
    for mapping in profile.get("shared_mappings", []):
        if not mapping.get("peer_site_id"):
            raise LedgerError("shared mapping requires peer_site_id")
        for name in ["this_root", "peer_root"]:
            if not str(mapping.get(name, "")).startswith("/"):
                raise LedgerError("shared mapping %s must be absolute" % name)
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
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", alias, remote
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
        raise LedgerError("snapshot source is not a directory: %s" % source)
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
