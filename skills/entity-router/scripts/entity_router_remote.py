#!/usr/bin/env python3
"""Python 3.6-compatible remote snapshot helper for Router staging.

This file is copied to an SSH site's staging root. It has no package imports,
stores no credential, and never writes controller state.
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command(argv, cwd=None):
    process = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True)
    stdout, stderr = process.communicate()
    return process.returncode, stdout, stderr


def git_revision(source):
    code, stdout, unused = command(["git", "-C", source, "rev-parse", "HEAD", "HEAD^{tree}"])
    if code != 0:
        return {}
    values = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(values) < 2:
        return {}
    code, dirty, unused = command(["git", "-C", source, "status", "--porcelain"])
    return {"kind": "git", "commit": values[0], "tree": values[1],
            "dirty": code != 0 or bool(dirty.strip())}


def source_files(source):
    code, stdout, unused = command(["git", "-C", source, "ls-files", "-co", "--exclude-standard"])
    if code == 0:
        return sorted(set(line for line in stdout.splitlines() if line))
    result = []
    for root, dirs, names in os.walk(source):
        dirs[:] = sorted(name for name in dirs if name not in {".git", "__pycache__", "build", "_build"})
        for name in sorted(names):
            result.append(os.path.relpath(os.path.join(root, name), source))
    return result


def make_manifest(source):
    source = os.path.realpath(os.path.abspath(os.path.expanduser(source)))
    entries = []
    for relative in source_files(source):
        path = os.path.join(source, relative)
        if os.path.isfile(path) and not os.path.islink(path):
            entries.append({"path": relative, "sha256": sha256_file(path),
                            "size": os.path.getsize(path),
                            "mode": stat.S_IMODE(os.stat(path).st_mode)})
    payload = {"schema_version": 1, "source": source,
               "base_revision": git_revision(source), "files": entries}
    identity = {"schema_version": 1, "base_revision": payload["base_revision"],
                "files": entries}
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["snapshot_id"] = hashlib.sha256(canonical).hexdigest()
    return payload


def verify(root):
    with open(os.path.join(root, "snapshot-manifest.json"), "r") as handle:
        manifest = json.load(handle)
    for entry in manifest.get("files", []):
        path = os.path.join(root, entry["path"])
        if not os.path.isfile(path) or sha256_file(path) != entry["sha256"]:
            raise ValueError("snapshot verification failed: %s" % entry["path"])
    return manifest


def snapshot_archive(args):
    source = os.path.realpath(os.path.abspath(os.path.expanduser(args.source)))
    manifest = make_manifest(source)
    parent = os.path.dirname(os.path.abspath(args.archive))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    handle, manifest_path = tempfile.mkstemp(prefix="manifest-", suffix=".json", dir=parent)
    try:
        with os.fdopen(handle, "w") as output:
            json.dump(manifest, output, indent=2, sort_keys=True)
            output.write("\n")
        with tarfile.open(args.archive, "w") as bundle:
            for entry in manifest["files"]:
                bundle.add(os.path.join(source, entry["path"]), arcname=entry["path"], recursive=False)
            bundle.add(manifest_path, arcname="snapshot-manifest.json", recursive=False)
    finally:
        try:
            os.unlink(manifest_path)
        except OSError:
            pass
    print(json.dumps(manifest, sort_keys=True))


def safe_extract(archive, destination):
    with tarfile.open(archive, "r") as bundle:
        members = bundle.getmembers()
        for member in members:
            if os.path.isabs(member.name) or ".." in member.name.split("/"):
                raise ValueError("unsafe archive path")
        bundle.extractall(destination)


def snapshot_install(args):
    with tarfile.open(args.archive, "r") as bundle:
        member = bundle.extractfile("snapshot-manifest.json")
        if member is None:
            raise ValueError("snapshot manifest missing")
        manifest = json.loads(member.read().decode("utf-8"))
    snapshot_id = manifest["snapshot_id"]
    root = os.path.abspath(args.target_root)
    destination = os.path.join(root, snapshot_id)
    if os.path.exists(destination):
        current = verify(destination)
        if current.get("snapshot_id") != snapshot_id:
            raise ValueError("existing snapshot ID mismatch")
    else:
        if not os.path.isdir(root):
            os.makedirs(root)
        temp = destination + ".tmp-" + str(os.getpid())
        os.makedirs(temp)
        try:
            safe_extract(args.archive, temp)
            verify(temp)
            os.rename(temp, destination)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
    print(json.dumps({"snapshot_id": snapshot_id, "destination": destination}, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    create = sub.add_parser("snapshot-archive")
    create.add_argument("--source", required=True)
    create.add_argument("--archive", required=True)
    create.set_defaults(func=snapshot_archive)
    install = sub.add_parser("snapshot-install")
    install.add_argument("--archive", required=True)
    install.add_argument("--target-root", required=True)
    install.set_defaults(func=snapshot_install)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        raise SystemExit("command required")
    try:
        args.func(args)
        return 0
    except (IOError, OSError, ValueError, KeyError, AssertionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
