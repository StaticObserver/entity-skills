#!/usr/bin/env python3
"""Shared multi-site primitives for the Entity Router runtime.

The module is standard-library only and remains compatible with Python 3.6 so
the same probe helpers can run on older HPC login nodes.
"""

from __future__ import print_function

import datetime
import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import tempfile


SITE_SCHEMA_VERSION = 1
REGISTRY_SCHEMA_VERSION = 1


class RouterError(Exception):
    pass


def now_utc():
    value = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def absolute(path):
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def router_home(value=None):
    return absolute(value or os.environ.get("ENTITY_ROUTER_HOME", "~/.entity-router"))


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


def locator_text(locator):
    item = parse_locator(locator)
    return "%s:%s" % (item["site_id"], item["path"])


def canonical_locator(home, locator):
    """Resolve local-site symlinks while preserving remote path semantics."""
    item = parse_locator(locator)
    profile = load_site_profile(home, item["site_id"])
    if profile["transport"]["kind"] == "local":
        item["path"] = absolute(item["path"])
    return item


def locator_within(locator, root):
    locator = parse_locator(locator)
    root = parse_locator(root)
    if locator["site_id"] != root["site_id"]:
        return False
    try:
        return os.path.commonpath([locator["path"], root["path"]]) == root["path"]
    except ValueError:
        return False


def locators_overlap(left, right):
    return locator_within(left, right) or locator_within(right, left)


def ensure_home(home):
    home = router_home(home)
    for relative in ["sites", "cases"]:
        path = os.path.join(home, relative)
        if not os.path.isdir(path):
            os.makedirs(path)
    registry = os.path.join(home, "registry.json")
    if not os.path.isfile(registry):
        atomic_write_json(registry, {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "updated_at": now_utc(),
            "cases": {},
        })
    return home


def registry_path(home):
    return os.path.join(ensure_home(home), "registry.json")


def load_registry(home):
    value = load_json(registry_path(home), "Router registry")
    if value.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise RouterError("unsupported Router registry schema")
    value.setdefault("cases", {})
    return value


def register_case(home, case_uid, case_id, control_root):
    registry = load_registry(home)
    current = registry["cases"].get(case_uid)
    record = {
        "case_uid": case_uid,
        "case_id": case_id,
        "control_root": absolute(control_root),
    }
    if current and absolute(current.get("control_root", "")) != record["control_root"]:
        raise RouterError("case_uid is already registered at another control root")
    registry["cases"][case_uid] = record
    registry["updated_at"] = now_utc()
    atomic_write_json(registry_path(home), registry)
    return record


def unregister_case(home, case_uid, control_root):
    registry = load_registry(home)
    record = registry["cases"].get(case_uid)
    if record and absolute(record.get("control_root", "")) == absolute(control_root):
        del registry["cases"][case_uid]
        registry["updated_at"] = now_utc()
        atomic_write_json(registry_path(home), registry)


def site_profile_path(home, site_id):
    return os.path.join(ensure_home(home), "sites", "%s.json" % site_id)


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


def load_site_profile(home, site_id):
    path = site_profile_path(home, site_id)
    if not os.path.isfile(path):
        raise RouterError("unknown site_id: %s" % site_id)
    return validate_site_profile(load_json(path, "site profile"))


def save_site_profile(home, profile):
    profile = validate_site_profile(profile)
    path = site_profile_path(home, profile["site_id"])
    atomic_write_json(path, profile)
    return path


def list_site_profiles(home):
    directory = os.path.join(ensure_home(home), "sites")
    result = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            result.append(load_site_profile(home, name[:-5]))
    return result


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


def _remote_probe(profile, path):
    script = """import hashlib,json,os,sys
p=sys.argv[1]
r={'path':p}
if os.path.isfile(p):
 r.update({'kind':'file','sha256':hashlib.sha256(open(p,'rb').read()).hexdigest(),'size':os.path.getsize(p)})
elif os.path.isdir(p):
 mpath=os.path.join(p,'snapshot-manifest.json')
 if os.path.isfile(mpath):
  m=json.load(open(mpath))
  for e in m.get('files',[]):
   f=os.path.join(p,e['path'])
   assert os.path.isfile(f), 'missing snapshot file: '+e['path']
   assert hashlib.sha256(open(f,'rb').read()).hexdigest()==e['sha256'], 'snapshot hash mismatch: '+e['path']
  r.update({'kind':'snapshot','snapshot_id':m.get('snapshot_id',''),'manifest_sha256':hashlib.sha256(open(mpath,'rb').read()).hexdigest(),'files':len(m.get('files',[]))})
 else:
  r.update({'kind':'directory'})
else:
 r.update({'kind':'missing'})
print(json.dumps(r,sort_keys=True))"""
    code, stdout, stderr = run_on_site(profile, ["python3", "-c", script, path])
    if code != 0:
        raise RouterError("remote probe failed: %s" % (stderr.strip() or stdout.strip()))
    try:
        return json.loads(stdout)
    except ValueError:
        raise RouterError("remote probe returned invalid JSON")


def probe_locator(home, locator, probe_kind="auto"):
    locator = canonical_locator(home, locator)
    profile = load_site_profile(home, locator["site_id"])
    path = locator["path"]
    observed_at = now_utc()
    if profile["transport"]["kind"] == "local":
        if os.path.isfile(path):
            item = {
                "kind": "file",
                "fingerprint": {"sha256": sha256_file(path), "size": os.path.getsize(path)},
            }
        elif os.path.isdir(path):
            manifest_path = os.path.join(path, "snapshot-manifest.json")
            if os.path.isfile(manifest_path):
                manifest = verify_snapshot(path)
                item = {
                    "kind": "snapshot",
                    "fingerprint": {
                        "snapshot_id": manifest.get("snapshot_id", ""),
                        "manifest_sha256": sha256_file(manifest_path),
                        "files": len(manifest.get("files", [])),
                    },
                }
            else:
                item = {"kind": "directory", "fingerprint": {}}
        else:
            item = {"kind": "missing", "fingerprint": {}}
    else:
        remote = _remote_probe(profile, path)
        item = {"kind": remote["kind"], "fingerprint": {}}
        if "sha256" in remote:
            item["fingerprint"] = {"sha256": remote["sha256"], "size": remote.get("size", 0)}
        elif remote["kind"] == "snapshot":
            item["fingerprint"] = {
                "snapshot_id": remote.get("snapshot_id", ""),
                "manifest_sha256": remote.get("manifest_sha256", ""),
                "files": remote.get("files", 0),
            }
    if item["kind"] == "directory" and probe_kind in {"auto", "git"}:
        revision = git_revision(profile, path)
        if revision:
            item["fingerprint"] = revision
    item.update({
        "locator": locator,
        "observed_at": observed_at,
        "observer_site": "controller",
    })
    return item


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


def copy_snapshot_local(source, target_root, manifest):
    snapshot_id = manifest["snapshot_id"]
    destination = os.path.join(absolute(target_root), snapshot_id)
    manifest_path = os.path.join(destination, "snapshot-manifest.json")
    if os.path.exists(destination):
        if os.path.isfile(manifest_path):
            current = load_json(manifest_path, "snapshot manifest")
            if current.get("snapshot_id") == snapshot_id:
                return destination
        raise RouterError("snapshot destination already exists with different content")
    os.makedirs(destination)
    try:
        for entry in manifest["files"]:
            source_path = os.path.join(source, entry["path"])
            target_path = os.path.join(destination, entry["path"])
            parent = os.path.dirname(target_path)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            shutil.copy2(source_path, target_path)
        atomic_write_json(manifest_path, manifest)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def verify_snapshot(path):
    path = absolute(path)
    manifest = load_json(os.path.join(path, "snapshot-manifest.json"), "snapshot manifest")
    for entry in manifest.get("files", []):
        target = os.path.join(path, entry["path"])
        if not os.path.isfile(target) or sha256_file(target) != entry["sha256"]:
            raise RouterError("snapshot verification failed: %s" % entry["path"])
    return manifest
