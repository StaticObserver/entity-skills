#!/usr/bin/env python3
"""One-shot, read-only Entity run status probe.

The quick path performs at most one SSH call, writes no files, and never
mutates Router Case state. It is intentionally independent of Action state so
that suspended and legacy Cases can be observed without resume/suspend churn.
"""

from __future__ import print_function

import argparse
import datetime
import fnmatch
import json
import math
import os
import re
import subprocess
import sys

from entity_router_common import RouterError, load_site_profile, router_home, run_on_site


SCHEMA_VERSION = 1
TERMINAL_SUCCESS = {"COMPLETED"}
TERMINAL_FAILURE = {
    "BOOT_FAIL", "CANCELLED", "DEADLINE", "FAILED", "NODE_FAIL",
    "OUT_OF_MEMORY", "PREEMPTED", "REVOKED", "TIMEOUT",
}
FATAL_RE = re.compile(
    r"fatal|segmentation fault|double free|out of memory|uncaught exception|traceback",
    re.IGNORECASE,
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
FLOAT_TOKEN = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
TIME_RE = re.compile(
    r"\bTime:\s*(%s)(?=\.{2,}|\s|\[|$)"
    r"(?:\.{2,})?(?:\s*/\s*(%s)(?=\.{2,}|\s|\[|$))?"
    % (FLOAT_TOKEN, FLOAT_TOKEN)
)
COMMAND_TIMEOUT_SECONDS = 8


def now_utc():
    value = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def command(argv):
    try:
        process = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except OSError as exc:
        return 127, "", str(exc)
    try:
        stdout, stderr = process.communicate(timeout=COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        detail = (stderr.strip() or stdout.strip())[-512:]
        return 124, stdout, "timed out after %ss%s" % (
            COMMAND_TIMEOUT_SECONDS, ": " + detail if detail else "",
        )
    return process.returncode, stdout, stderr


def probe_error(name, code, stderr):
    detail = (stderr.strip() or "exit %s" % code)[-512:]
    return "%s: %s" % (name, detail)


def finite_float(value):
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def tail_text(path, limit):
    if not path or not os.path.isfile(path):
        return ""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - limit), os.SEEK_SET)
        value = handle.read(limit)
    return value.decode("utf-8", errors="replace")


def parse_progress(text, configured_steps=None, configured_time=None):
    clean = ANSI_RE.sub("", text or "")
    step = None
    total_steps = configured_steps
    simulation_time = None
    target_time = finite_float(configured_time)
    elapsed = ""
    remaining = ""
    for line in clean.splitlines():
        match = re.search(r"\bStep:\s*([0-9]+)(?:\s*/\s*([0-9]+))?", line)
        if match:
            step = int(match.group(1))
            if match.group(2):
                total_steps = int(match.group(2))
        match = TIME_RE.search(line)
        if match:
            parsed_time = finite_float(match.group(1))
            if parsed_time is not None:
                simulation_time = parsed_time
            if match.group(2):
                parsed_target = finite_float(match.group(2))
                if parsed_target is not None:
                    target_time = parsed_target
        match = re.search(r"\bElapsed time:\s*(.+)$", line)
        if match:
            elapsed = match.group(1).strip()
        match = re.search(r"\bRemaining time:\s*(.+)$", line)
        if match:
            remaining = match.group(1).strip()
    percent = None
    if simulation_time is not None and target_time:
        percent = 100.0 * simulation_time / target_time
    elif step is not None and total_steps:
        percent = 100.0 * step / total_steps
    return {
        "latest_step": step,
        "total_steps": total_steps,
        "simulation_time": simulation_time,
        "target_simulation_time": target_time,
        "percent_complete": percent,
        "elapsed": elapsed,
        "estimated_remaining": remaining,
    }


def directory_inventory(path, pattern, full=False):
    result = {
        "path": path or "",
        "exists": bool(path and os.path.isdir(path)),
        "count": 0,
        "latest": "",
        "latest_mtime": None,
    }
    if not result["exists"]:
        return result
    entries = []
    for name in os.listdir(path):
        if fnmatch.fnmatch(name, pattern):
            full_path = os.path.join(path, name)
            entries.append((os.path.getmtime(full_path), name, full_path))
    entries.sort()
    result["count"] = len(entries)
    if entries:
        result["latest"] = entries[-1][1]
        result["latest_mtime"] = datetime.datetime.fromtimestamp(
            entries[-1][0], datetime.timezone.utc
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if full:
        files = 0
        total_bytes = 0
        for unused_mtime, unused_name, entry in entries:
            if os.path.isfile(entry):
                files += 1
                total_bytes += os.path.getsize(entry)
                continue
            for root, unused_dirs, names in os.walk(entry):
                for name in names:
                    item = os.path.join(root, name)
                    if os.path.isfile(item):
                        files += 1
                        total_bytes += os.path.getsize(item)
        result["member_file_count"] = files
        result["total_bytes"] = total_bytes
    return result


def scheduler_status(kind, job_id):
    result = {
        "kind": kind,
        "job_id": job_id or "",
        "state": "NOT_CONFIGURED",
        "elapsed": "",
        "exit_code": "",
        "probe_errors": [],
    }
    if not job_id:
        return result
    if kind == "slurm":
        squeue_code, stdout, stderr = command([
            "squeue", "-h", "-j", str(job_id), "-o", "%i|%T|%M|%R"
        ])
        if squeue_code == 0 and stdout.strip():
            fields = stdout.strip().splitlines()[0].split("|", 3)
            result["state"] = fields[1].strip().upper() if len(fields) > 1 else "UNKNOWN"
            result["elapsed"] = fields[2].strip() if len(fields) > 2 else ""
            result["location"] = fields[3].strip() if len(fields) > 3 else ""
        elif squeue_code != 0:
            result["probe_errors"].append(probe_error("squeue", squeue_code, stderr))
        sacct_code = None
        if result["state"] == "NOT_CONFIGURED":
            sacct_code, stdout, stderr = command([
                "sacct", "-n", "-X", "-j", str(job_id),
                "--format=JobIDRaw,State,Elapsed,ExitCode", "-P",
            ])
            if sacct_code == 0:
                for line in stdout.splitlines():
                    fields = line.split("|")
                    if fields and fields[0].strip() == str(job_id):
                        result["state"] = fields[1].strip().split()[0].upper()
                        if len(fields) > 2 and fields[2].strip():
                            result["elapsed"] = fields[2].strip()
                        if len(fields) > 3:
                            result["exit_code"] = fields[3].strip()
                        break
            else:
                result["probe_errors"].append(probe_error("sacct", sacct_code, stderr))
        if result["state"] == "NOT_CONFIGURED":
            result["state"] = (
                "PROBE_FAILED"
                if squeue_code != 0 and sacct_code not in {None, 0}
                else "NOT_FOUND"
            )
    elif kind == "pbs":
        code, stdout, stderr = command(["qstat", "-f", str(job_id)])
        result["state"] = "PROBE_FAILED" if code else "UNKNOWN"
        if code:
            result["probe_errors"].append(probe_error("qstat", code, stderr))
        if code == 0:
            for line in stdout.splitlines():
                if "job_state" in line and "=" in line:
                    result["state"] = line.split("=", 1)[1].strip().upper()
                    break
    else:
        result["state"] = "UNSUPPORTED"
    return result


def process_status(pid, expected_start_ticks=""):
    result = {
        "pid": pid,
        "running": False,
        "start_ticks": "",
        "identity_observable": False,
        "identity_matches": None,
    }
    if not pid:
        return result
    try:
        os.kill(int(pid), 0)
        result["running"] = True
    except (OSError, ValueError):
        return result
    stat_path = "/proc/%s/stat" % pid
    if os.path.isfile(stat_path):
        with open(stat_path, "r") as handle:
            fields = handle.read().split()
        if len(fields) > 21:
            result["start_ticks"] = fields[21]
            result["identity_observable"] = True
    if expected_start_ticks and result["identity_observable"]:
        result["identity_matches"] = result["start_ticks"] == str(expected_start_ticks)
    return result


def resolve_path(run_root, value):
    if not value:
        return ""
    path = value if os.path.isabs(value) else os.path.join(run_root, value)
    path = os.path.realpath(os.path.normpath(path))
    try:
        within = os.path.commonpath([run_root, path]) == run_root
    except ValueError:
        within = False
    if not within:
        raise ValueError("status path escapes run root: %s" % value)
    return path


def collect(config):
    run_root = os.path.realpath(os.path.normpath(config["run_root"]))
    progress_log = resolve_path(run_root, config.get("progress_log", ""))
    stderr_log = resolve_path(run_root, config.get("stderr_log", ""))
    fields_root = resolve_path(run_root, config.get("fields_root", ""))
    checkpoint_root = resolve_path(run_root, config.get("checkpoint_root", ""))
    scheduler = scheduler_status(config.get("scheduler", "none"), config.get("job_id", ""))
    process = process_status(config.get("pid"), config.get("pid_start_ticks", ""))
    progress_tail = tail_text(progress_log, config.get("tail_bytes", 131072))
    stderr_tail = tail_text(stderr_log, min(config.get("tail_bytes", 131072), 32768))
    progress = parse_progress(
        progress_tail, config.get("total_steps"), config.get("target_time")
    )
    full = config.get("profile") == "full"
    fields = directory_inventory(
        fields_root, config.get("field_pattern", "fields.*.bp"), full
    )
    checkpoints = directory_inventory(
        checkpoint_root, config.get("checkpoint_pattern", "step-*.bp"), full
    )
    scheduler_state = scheduler.get("state", "")
    terminal = scheduler_state in TERMINAL_SUCCESS or scheduler_state in TERMINAL_FAILURE
    if not config.get("job_id") and config.get("pid") and not process["running"]:
        terminal = True
    anomaly = bool(stderr_tail.strip() and FATAL_RE.search(stderr_tail))
    if config.get("job_id") and scheduler_state in {
        "NOT_FOUND", "PROBE_FAILED", "UNSUPPORTED",
    }:
        anomaly = True
    if process.get("identity_matches") is False:
        anomaly = True
    recommendation = "promote_to_run_monitor" if terminal or anomaly else "observe_only"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "run.status",
        "observed_at": now_utc(),
        "site_id": config.get("site_id", ""),
        "run_id": config.get("run_id", ""),
        "run_root": run_root,
        "profile": config.get("profile", "quick"),
        "scheduler": scheduler,
        "process": process,
        "progress": progress,
        "stderr": {
            "path": stderr_log,
            "bytes": os.path.getsize(stderr_log) if stderr_log and os.path.isfile(stderr_log) else 0,
            "tail": stderr_tail[-4096:],
        },
        "fields": fields,
        "checkpoints": checkpoints,
        "terminal": terminal,
        "anomaly": anomaly,
        "recommendation": recommendation,
        "state_mutated": False,
    }


# REMOTE_PROGRAM_BOUNDARY


def remote_program_source():
    """Return a self-contained Python program for one SSH invocation."""
    path = os.path.abspath(__file__)
    with open(path, "r") as handle:
        source = handle.read()
    marker = "# REMOTE_PROGRAM_BOUNDARY"
    prefix = source.split(marker, 1)[0]
    prefix = prefix.replace(
        "from entity_router_common import RouterError, load_site_profile, router_home, run_on_site\n",
        "",
    )
    return prefix + "\nconfig=json.loads(sys.argv[1])\nprint(json.dumps(collect(config),sort_keys=True))\n"


def collect_site_status(home, profile, config):
    if profile["transport"]["kind"] == "local":
        result = collect(config)
        result["remote_calls"] = 0
        return result
    code, stdout, stderr = run_on_site(
        profile, ["python3", "-c", remote_program_source(), json.dumps(config, sort_keys=True)]
    )
    if code != 0:
        raise RouterError("run.status remote probe failed: %s" % (stderr.strip() or stdout.strip()))
    try:
        result = json.loads(stdout)
    except ValueError:
        raise RouterError("run.status remote probe returned invalid JSON")
    result["remote_calls"] = 1
    return result


def build_profile(args):
    home = router_home(args.router_home)
    if args.site_id:
        profile = load_site_profile(home, args.site_id)
    elif args.ssh_alias:
        profile = {
            "site_id": args.ssh_alias,
            "transport": {"kind": "ssh", "ssh_alias": args.ssh_alias},
            "scheduler": {"kind": args.scheduler or "none"},
            "roots": {},
        }
    else:
        profile = {
            "site_id": "local",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": args.scheduler or "none"},
            "roots": {},
        }
    if args.scheduler:
        profile["scheduler"] = {"kind": args.scheduler}
    return home, profile


def build_config(args, profile):
    if not os.path.isabs(args.run_root):
        raise RouterError("--run-root must be absolute")
    scheduler = profile.get("scheduler", {}).get("kind", "none")
    if not args.job_id and not args.pid:
        raise RouterError("run.status requires --job-id or --pid")
    if args.job_id and scheduler not in {"slurm", "pbs"}:
        raise RouterError("--job-id requires --scheduler slurm or pbs")
    return {
        "site_id": profile.get("site_id", args.site_id or args.ssh_alias or "local"),
        "run_id": args.run_id or os.path.basename(os.path.normpath(args.run_root)),
        "run_root": os.path.normpath(args.run_root),
        "scheduler": scheduler,
        "job_id": args.job_id or "",
        "pid": args.pid,
        "pid_start_ticks": args.pid_start_ticks or "",
        "progress_log": args.progress_log,
        "stderr_log": args.stderr_log,
        "fields_root": args.fields_root,
        "checkpoint_root": args.checkpoint_root,
        "field_pattern": args.field_pattern,
        "checkpoint_pattern": args.checkpoint_pattern,
        "total_steps": args.total_steps,
        "target_time": args.target_time,
        "tail_bytes": args.tail_bytes,
        "profile": args.profile,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Read-only one-shot Entity run status; never mutates Router state."
    )
    parser.add_argument("--router-home")
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--site-id")
    location.add_argument("--ssh-alias")
    parser.add_argument("--scheduler", choices=["none", "slurm", "pbs"])
    parser.add_argument("--run-id")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--pid-start-ticks")
    parser.add_argument("--progress-log", default="logs/stdout.log")
    parser.add_argument("--stderr-log", default="logs/stderr.log")
    parser.add_argument("--fields-root", default="data/fields")
    parser.add_argument("--checkpoint-root", default="data/checkpoints")
    parser.add_argument("--field-pattern", default="fields.*.bp")
    parser.add_argument("--checkpoint-pattern", default="step-*.bp")
    parser.add_argument("--total-steps", type=int)
    parser.add_argument("--target-time", type=float)
    parser.add_argument("--tail-bytes", type=int, default=131072)
    parser.add_argument("--profile", choices=["quick", "full"], default="quick")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        home, profile = build_profile(args)
        config = build_config(args, profile)
        result = collect_site_status(home, profile, config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (IOError, OSError, ValueError, KeyError, RouterError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
