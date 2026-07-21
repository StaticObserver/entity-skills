#!/usr/bin/env python3
"""Small file-backed Slurm façade for E2E harness tests.

Create symlinks named `sbatch`, `squeue`, and `sacct` to this file, put their
directory first in PATH, and set FAKE_SLURM_STATE to an isolated JSON path.
No submitted command is executed.
"""

from __future__ import print_function

import argparse
import datetime
import json
import os
import sys
import tempfile


def now_utc():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def state_path():
    path = os.environ.get("FAKE_SLURM_STATE", "")
    if not path:
        raise SystemExit("FAKE_SLURM_STATE is required")
    return os.path.realpath(path)


def load_state():
    path = state_path()
    if not os.path.isfile(path):
        return {"schema_version": 1, "next_job_id": 1000, "jobs": []}
    with open(path, "r") as handle:
        return json.load(handle)


def save_state(value):
    path = state_path()
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".fake-slurm-", dir=parent)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def flag(args, name, default=""):
    return args[args.index(name) + 1] if name in args else default


def sbatch(args):
    if "--test-only" in args:
        print("accepted")
        return 0
    state = load_state()
    job_id = str(state["next_job_id"])
    state["next_job_id"] += 1
    job = {
        "job_id": job_id,
        "job_name": flag(args, "--job-name"),
        "submit_user": os.environ.get("FAKE_SLURM_USER", "tester"),
        "submitted_at": now_utc(),
        "state": "RUNNING",
        "run_root": flag(args, "--chdir", os.getcwd()),
        "comment": flag(args, "--comment"),
    }
    state["jobs"].append(job)
    save_state(state)
    print(job_id)
    return 0


def selected_jobs(args):
    jobs = load_state().get("jobs", [])
    user = flag(args, "--user")
    job_id = flag(args, "-j")
    if user:
        jobs = [item for item in jobs if item.get("submit_user") == user]
    if job_id:
        jobs = [item for item in jobs if item.get("job_id") == job_id]
    return jobs


def squeue(args):
    jobs = selected_jobs(args)
    if "--format" in args:
        for item in jobs:
            print("{job_id}|{job_name}|{submit_user}|{submitted_at}|{state}|{run_root}|{comment}".format(**item))
    else:
        for item in jobs:
            print(item["state"])
    return 0


def sacct(args):
    for item in selected_jobs(args):
        print("{job_id}|{state}|0:0".format(**item))
    return 0


def control(args):
    parser = argparse.ArgumentParser(prog="fake-slurmctl")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init")
    terminal = sub.add_parser("set-state")
    terminal.add_argument("job_id")
    terminal.add_argument("state")
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--job-name", required=True)
    snapshot.add_argument("--submit-user", required=True)
    snapshot.add_argument("--run-root", required=True)
    snapshot.add_argument("--comment", required=True)
    snapshot.add_argument("--output", required=True)
    parsed = parser.parse_args(args)
    if parsed.command == "init":
        save_state({"schema_version": 1, "next_job_id": 1000, "jobs": []})
        return 0
    state = load_state()
    if parsed.command == "set-state":
        matches = [item for item in state["jobs"] if item["job_id"] == parsed.job_id]
        if len(matches) != 1:
            raise SystemExit("job_id must match exactly one fake job")
        matches[0]["state"] = parsed.state.upper()
        save_state(state)
        return 0
    if parsed.command == "snapshot":
        query = {"job_name": parsed.job_name, "submit_user": parsed.submit_user,
                 "run_root": os.path.realpath(parsed.run_root), "comment": parsed.comment}
        matches = [item for item in state["jobs"]
                   if item["job_name"] == query["job_name"]
                   and item["submit_user"] == query["submit_user"]
                   and os.path.realpath(item["run_root"]) == query["run_root"]
                   and item["comment"] == query["comment"]]
        payload = {"schema_version": 1, "scheduler": "slurm", "observed_at": now_utc(),
                   "query": query, "jobs": matches}
        with open(parsed.output, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return 0
    parser.error("command required")


def main():
    command = os.path.basename(sys.argv[0])
    args = sys.argv[1:]
    if command == "sbatch":
        return sbatch(args)
    if command == "squeue":
        return squeue(args)
    if command == "sacct":
        return sacct(args)
    if command in {"fake-slurmctl", "fake_slurm.py"}:
        return control(args)
    raise SystemExit("unsupported fake Slurm command: %s" % command)


if __name__ == "__main__":
    sys.exit(main())
