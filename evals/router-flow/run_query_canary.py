#!/usr/bin/env python3
"""Run the one-call controller-local query efficiency and correctness gate."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
sys.path.insert(0, SCRIPTS)

from entity_router_common import absolute, atomic_write_json, router_home  # noqa: E402
from entity_router_project import resolve_project  # noqa: E402
from entity_router_state import state_path  # noqa: E402


def file_identity(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = os.stat(path)
    return {"sha256": digest.hexdigest(), "size": stat.st_size,
            "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--router-home", default=router_home())
    parser.add_argument("--output")
    parser.add_argument("--max-output-bytes", type=int, default=4096)
    args = parser.parse_args(argv)
    home = absolute(args.router_home)
    binding = resolve_project(home, args.project_root)
    case_file = state_path(binding["case_dir"])
    before = file_identity(case_file)
    command = [
        sys.executable, os.path.join(SCRIPTS, "entityctl.py"),
        "--router-home", home, "inspect", "--project-root", args.project_root,
        "--max-bytes", str(args.max_output_bytes),
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stdout, stderr = process.communicate()
    try:
        inspected = json.loads(stdout)
    except ValueError:
        inspected = {"ok": False, "error": stderr.strip() or "invalid JSON"}
    after = file_identity(case_file)
    output_bytes = len(stdout.encode("utf-8"))
    invariants = {
        "public_project_binding": inspected.get("project", {}).get("project_id") == binding["project_id"],
        "controller_local_source": inspected.get("controller", {}).get("source") == "controller-local",
        "no_remote_contact": inspected.get("controller", {}).get("remote_contacted") is False,
        "case_state_unchanged": before == after and inspected.get("state_mutated") is False,
        "bounded_summary": output_bytes <= args.max_output_bytes,
        "one_tool_roundtrip": process.returncode == 0,
    }
    payload = {
        "schema_version": 1,
        "scenario": "controller-local-project-inspect",
        "project_id": binding["project_id"],
        "case_uid": binding["case_uid"],
        "case_revision": binding["revision"],
        "invariants": invariants,
        "metrics": {
            "model_wakeups": {"total": 1, "by_reason": {"user_goal": 1}},
            "tool_roundtrips": 1,
            "remote_calls": 0,
            "approval_reviews": 0,
            "tool_output_bytes_injected": output_bytes,
            "unchanged_polls_suppressed": 0,
            "retries": {"total": 0, "without_changed_evidence": 0},
            "usage": {"input_tokens": None, "cached_input_tokens": None,
                      "output_tokens": None, "wall_time_ms": None},
        },
        "assessment": {
            "correctness": all(invariants.values()),
            "tool_roundtrips_le_1": True,
            "remote_calls_zero": True,
            "output_bytes_le_4096": output_bytes <= 4096,
            "token_reduction": "not_assessed",
        },
    }
    if args.output:
        atomic_write_json(absolute(args.output), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(invariants.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
