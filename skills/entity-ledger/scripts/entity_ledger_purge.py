#!/usr/bin/env python3
"""Execute an explicitly authorized Ledger data.purge request on its target site."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path):
    with open(path, "r") as handle:
        return json.load(handle)


def absolute(path):
    return os.path.abspath(os.path.normpath(path))


def within(path, root):
    try:
        return os.path.commonpath([absolute(path), absolute(root)]) == absolute(root)
    except ValueError:
        return False


def overlaps(left, right):
    lexical = within(left, right) or within(right, left)
    canonical_left = os.path.realpath(absolute(left))
    canonical_right = os.path.realpath(absolute(right))
    canonical = within(canonical_left, canonical_right) or within(
        canonical_right, canonical_left
    )
    return lexical or canonical


def path_bytes(path):
    if not os.path.lexists(path):
        return 0
    if os.path.islink(path) or os.path.isfile(path):
        return os.lstat(path).st_size
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in files:
            item = os.path.join(root, name)
            try:
                total += os.lstat(item).st_size
            except FileNotFoundError:
                pass
        for name in dirs:
            item = os.path.join(root, name)
            if os.path.islink(item):
                try:
                    total += os.lstat(item).st_size
                except FileNotFoundError:
                    pass
    return total


def entity_processes():
    process = subprocess.run(
        ["ps", "-axo", "uid=,pid=,comm=,args="],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    found = []
    for line in process.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if (len(parts) >= 3 and parts[0].isdigit()
                and int(parts[0]) == os.getuid()
                and parts[2] in {"entity", "entity.xc"}):
            found.append(line.strip())
    return found


def remove_path(path):
    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def existing_directory(path):
    """Nearest existing directory at or above path; deletion targets may
    remove the probe directory itself, so re-resolve before measuring."""
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def validate_request(request, receipt):
    if request.get("action_type") != "data.purge":
        raise ValueError("request is not data.purge")
    if request.get("owner") != "ledger" or request.get("execution_domain") != "ledger":
        raise ValueError("data.purge must be ledger-owned")
    if not request.get("authorization", "").strip():
        raise ValueError("data.purge request lacks explicit authorization")
    outputs = [absolute(item["path"]) for item in request.get("expected_outputs", [])]
    if absolute(receipt) not in outputs:
        raise ValueError("receipt is not a declared expected output")
    roots = [absolute(item["path"]) for item in request.get("write_roots", [])]
    receipt_roots = [root for root in roots if within(receipt, root)]
    if len(receipt_roots) != 1:
        raise ValueError("receipt must be covered by exactly one write root")
    targets = [root for root in roots if root != receipt_roots[0]]
    if not targets:
        raise ValueError("data.purge has no deletion targets")
    for target in targets:
        if target == os.path.sep or len(Path(target).parts) < 4:
            raise ValueError("refusing unsafe deletion target: %s" % target)
        if overlaps(target, receipt_roots[0]):
            raise ValueError("purge receipt root overlaps deletion target: %s" % target)
    for index, target in enumerate(targets):
        for other in targets[index + 1:]:
            if overlaps(target, other):
                raise ValueError("overlapping deletion targets: %s and %s" % (target, other))
    protected = [
        absolute(item["path"]) for item in request.get("protected_paths", [])
        if item.get("site_id") == request.get("execution_site_id")
    ]
    for target in targets:
        for item in protected:
            if overlaps(target, item):
                raise ValueError("deletion target overlaps protected path: %s" % target)
    input_targets = {
        absolute(item["locator"]["path"])
        for item in request.get("inputs", [])
        if item.get("locator", {}).get("site_id") == request.get("execution_site_id")
        and item.get("locator", {}).get("path")
    }
    if set(targets) != input_targets:
        raise ValueError("deletion targets must exactly match Action input locators")
    return targets, protected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--recover-after-delete", action="store_true")
    args = parser.parse_args()

    request_path = absolute(args.request)
    receipt_path = absolute(args.receipt)
    request = load_json(request_path)
    targets, protected = validate_request(request, receipt_path)
    running = entity_processes()
    if running:
        raise RuntimeError("refusing purge while Entity process is active: %s" % running)

    input_evidence = {
        absolute(item["locator"]["path"]): item.get("fingerprint", {})
        for item in request.get("inputs", []) if item.get("locator", {}).get("path")
    }
    manifest = []
    for target in targets:
        exists_now = os.path.lexists(target)
        fingerprint = input_evidence.get(target, {})
        manifest.append({
            "path": target,
            "existed_at_action_start": exists_now or bool(fingerprint),
            "existed_before_execution": exists_now,
            "bytes": path_bytes(target) if exists_now else int(fingerprint.get("size", 0)),
        })
    missing_before = [item["path"] for item in manifest if not item["existed_before_execution"]]
    if missing_before and not args.recover_after_delete:
        raise RuntimeError("declared purge targets missing before execution: %s" % missing_before)
    if args.recover_after_delete:
        if len(missing_before) != len(targets):
            raise RuntimeError("recovery requires every deletion target to be already absent")
        if not all(item["existed_at_action_start"] for item in manifest):
            raise RuntimeError("recovery lacks Action-start evidence for one or more targets")
    protected_before = {path: os.path.lexists(path) for path in protected}
    missing_protected = [path for path, exists in protected_before.items() if not exists]
    if missing_protected:
        raise RuntimeError("protected paths missing before purge: %s" % missing_protected)

    usage_path = existing_directory(os.path.commonpath(targets))
    before_usage = shutil.disk_usage(usage_path)
    request_sha256 = hashlib.sha256(Path(request_path).read_bytes()).hexdigest()

    if not args.recover_after_delete:
        for target in sorted(targets, key=lambda value: len(Path(value).parts), reverse=True):
            remove_path(target)
    if hasattr(os, "sync"):
        os.sync()

    probe_path = existing_directory(usage_path)
    after_usage = shutil.disk_usage(probe_path)
    remaining = [target for target in targets if os.path.lexists(target)]
    protected_after = {path: os.path.lexists(path) for path in protected}
    running_after = entity_processes()
    status = "completed" if not remaining and all(protected_after.values()) and not running_after else "failed"
    receipt = {
        "schema_version": 1,
        "status": status,
        "case_uid": request.get("case_uid"),
        "workflow_id": request.get("workflow_id"),
        "action_id": request.get("action_id"),
        "execution_site_id": request.get("execution_site_id"),
        "authorization": request.get("authorization"),
        "recovered_after_executor_failure": bool(args.recover_after_delete),
        "request": {"path": request_path, "sha256": request_sha256},
        "started_at": request.get("started_at"),
        "finished_at": now_utc(),
        "manifest": manifest,
        "manifest_bytes": sum(item["bytes"] for item in manifest),
        "filesystem": {
            "probe_path": probe_path,
            "free_bytes_before": before_usage.free,
            "free_bytes_after": after_usage.free,
            "free_bytes_delta": after_usage.free - before_usage.free,
        },
        "verification": {
            "remaining_targets": remaining,
            "protected_before": protected_before,
            "protected_after": protected_after,
            "entity_processes_before": running,
            "entity_processes_after": running_after,
        },
    }
    os.makedirs(os.path.dirname(receipt_path), exist_ok=True)
    Path(receipt_path).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        sys.exit(2)
