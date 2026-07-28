#!/usr/bin/env python3
"""Controller-local source snapshot helpers for the Ledger.

The manifest walk is shared with the rest of the runtime via
``entity_ledger_common.source_manifest`` so a Case source identity and a
snapshot archive always agree on the snapshot_id.  This module only adds
the tar archive read/write on top; it never writes controller state.
"""

from __future__ import print_function

import argparse
import json
import os
import sys
import tarfile
import tempfile

from entity_ledger_common import LedgerError, source_manifest


def make_manifest(source):
    return source_manifest(source)


def archive_manifest(archive):
    """Read the manifest recorded inside a snapshot archive; raises
    ValueError when the archive is truncated or carries no manifest, so the
    caller can regenerate instead of trusting a half-written tar."""
    try:
        with tarfile.open(archive, "r") as bundle:
            member = bundle.extractfile("snapshot-manifest.json")
            if member is None:
                raise ValueError("snapshot manifest missing")
            return json.loads(member.read().decode("utf-8"))
    except (tarfile.TarError, IOError, OSError) as exc:
        raise ValueError("snapshot archive is unreadable: %s" % exc)


def snapshot_archive(source, archive):
    source = os.path.realpath(os.path.abspath(os.path.expanduser(source)))
    manifest = make_manifest(source)
    parent = os.path.dirname(os.path.abspath(archive))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    handle, manifest_path = tempfile.mkstemp(prefix="manifest-", suffix=".json", dir=parent)
    try:
        with os.fdopen(handle, "w") as output:
            json.dump(manifest, output, indent=2, sort_keys=True)
            output.write("\n")
        # Write to a temporary sibling and rename, so a concurrent reader
        # never observes a half-written archive.
        temporary = os.path.abspath(archive) + ".tmp-" + str(os.getpid())
        try:
            with tarfile.open(temporary, "w") as bundle:
                for entry in manifest["files"]:
                    bundle.add(os.path.join(source, entry["path"]), arcname=entry["path"], recursive=False)
                bundle.add(manifest_path, arcname="snapshot-manifest.json", recursive=False)
            os.replace(temporary, os.path.abspath(archive))
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    finally:
        try:
            os.unlink(manifest_path)
        except OSError:
            pass
    return manifest


def command_snapshot_archive(args):
    manifest = snapshot_archive(args.source, args.archive)
    print(json.dumps(manifest, sort_keys=True))
    return 0


def build_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    create = sub.add_parser("snapshot-archive")
    create.add_argument("--source", required=True)
    create.add_argument("--archive", required=True)
    create.set_defaults(func=command_snapshot_archive)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        raise SystemExit("command required")
    try:
        args.func(args)
        return 0
    except (LedgerError, IOError, OSError, ValueError, KeyError, AssertionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
