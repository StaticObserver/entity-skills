#!/usr/bin/env python3
"""Content-addressed local/SSH executor for Entity Router StepSpec.

This file is intentionally standalone.  It may be copied to an execution Site,
accepts only allowlisted structured requests, writes owner-site receipts, and
never writes controller state.
"""

from __future__ import print_function

import argparse
import calendar
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


SCHEMA_VERSION = 1
KINDS = {"run.preflight.v1", "run.prepare.v2", "run.launch.v2",
         "build.register.v1", "data.inventory.v1"}


class ExecutorError(Exception):
    pass


def now_utc():
    value = datetime.datetime.utcnow().replace(microsecond=0)
    return value.isoformat() + "Z"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=parent)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def read_json(path, label):
    try:
        with open(path, "r") as handle:
            value = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise ExecutorError("cannot read %s: %s" % (label, exc))
    if not isinstance(value, dict):
        raise ExecutorError("%s must be an object" % label)
    return value


def within(path, roots):
    path = os.path.abspath(path)
    for root in roots:
        root = os.path.abspath(root)
        try:
            if os.path.commonpath([path, root]) == root:
                return True
        except ValueError:
            pass
    return False


def require_path(path, roots, label):
    if not isinstance(path, str) or not path.startswith("/") or not within(path, roots):
        raise ExecutorError("%s is outside allowed roots" % label)
    return os.path.normpath(path)


def command(argv, cwd=None):
    process = subprocess.Popen(
        argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stdout, stderr = process.communicate()
    return process.returncode, stdout, stderr


def stream(value):
    data = (value or "").encode("utf-8", errors="replace")
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "tail": data[-2048:].decode("utf-8", errors="replace")}


def file_evidence(path):
    if not os.path.isfile(path):
        raise ExecutorError("expected file is missing: %s" % path)
    return {"path": path, "kind": "file",
            "fingerprint": {"sha256": sha256_file(path), "size": os.path.getsize(path)}}


def directory_evidence(path):
    if not os.path.isdir(path):
        raise ExecutorError("expected directory is missing: %s" % path)
    return {"path": path, "kind": "directory", "fingerprint": {}}


def validate_envelope(value):
    required = {"schema_version", "operation_id", "plan_hash", "step_index", "step_id",
                "kind", "site_id", "receipt", "allowed_roots", "request"}
    if set(value) != required or value.get("schema_version") != SCHEMA_VERSION:
        raise ExecutorError("executor request keys differ from schema")
    if value.get("kind") not in KINDS:
        raise ExecutorError("executor Step kind is not allowlisted")
    if not isinstance(value.get("allowed_roots"), list) or not value["allowed_roots"]:
        raise ExecutorError("executor request requires allowed_roots")
    roots = []
    for root in value["allowed_roots"]:
        if not isinstance(root, str) or not root.startswith("/"):
            raise ExecutorError("allowed root must be absolute")
        roots.append(os.path.normpath(root))
    value["allowed_roots"] = roots
    value["receipt"] = require_path(value["receipt"], roots, "receipt")
    if not isinstance(value.get("request"), dict):
        raise ExecutorError("executor request payload must be an object")
    if any(key in value["request"] for key in {"command", "shell", "pre_command"}):
        raise ExecutorError("executor request contains forbidden command field")
    return value


def receipt_base(envelope, state, effect=None, outputs=None, stdout="", stderr="",
                 previous=None):
    payload = {
        "schema_version": 1, "operation_id": envelope["operation_id"],
        "plan_hash": envelope["plan_hash"], "step_index": envelope["step_index"],
        "step_id": envelope["step_id"], "kind": envelope["kind"],
        "state": state, "attempt": int((previous or {}).get("attempt", 0)) + 1,
        "intent_written_at": (previous or {}).get("intent_written_at") or now_utc(),
        "effect_identity": effect or {}, "outputs": outputs or [],
        "stdout": stream(stdout), "stderr": stream(stderr), "updated_at": now_utc(),
    }
    atomic_json(envelope["receipt"], payload)
    return payload


def matching_receipt(envelope):
    path = envelope["receipt"]
    if not os.path.isfile(path):
        return None
    value = read_json(path, "Step receipt")
    for key in ["operation_id", "plan_hash", "step_index", "step_id", "kind"]:
        if value.get(key) != envelope.get(key):
            raise ExecutorError("existing receipt belongs to another Step")
    return value


def render_sbatch(run_spec):
    if set(run_spec or {}) != {"executable", "compute", "input_name"}:
        raise ExecutorError("run_spec keys differ from schema")
    executable = run_spec["executable"]
    input_name = run_spec["input_name"]
    compute = run_spec["compute"]
    if not isinstance(executable, str) or not executable.startswith("/"):
        raise ExecutorError("run_spec executable must be absolute")
    if not isinstance(input_name, str) or not re.match(r"^[A-Za-z0-9_.-]+$", input_name):
        raise ExecutorError("run_spec input_name is invalid")
    allowed = {"nodes", "tasks", "gpus", "cpus_per_task", "walltime", "partition",
               "qos", "submit_user", "precision"}
    if not isinstance(compute, dict) or set(compute) != allowed:
        raise ExecutorError("run_spec compute keys differ from schema")
    for key in ["nodes", "tasks", "gpus", "cpus_per_task"]:
        if not isinstance(compute[key], int) or isinstance(compute[key], bool) or compute[key] < 1:
            raise ExecutorError("run_spec compute.%s is invalid" % key)
    for key in ["partition", "qos", "submit_user"]:
        if not isinstance(compute[key], str) or not re.match(r"^[A-Za-z0-9_.@+-]*$", compute[key]):
            raise ExecutorError("run_spec compute.%s is invalid" % key)
    if compute["precision"] not in {"single", "double"}:
        raise ExecutorError("run_spec precision is invalid")
    if not re.match(r"^[0-9]+(?:-[0-9]{2})?:[0-9]{2}:[0-9]{2}$", compute["walltime"]):
        raise ExecutorError("run_spec walltime is invalid")
    lines = ["#!/bin/bash", "# generated by Entity Router executor"]
    options = [
        ("nodes", compute["nodes"]), ("ntasks", compute["tasks"]),
        ("cpus-per-task", compute["cpus_per_task"]),
        ("gres", "gpu:%s" % compute["gpus"]), ("time", compute["walltime"]),
    ]
    if compute["partition"]:
        options.append(("partition", compute["partition"]))
    if compute["qos"]:
        options.append(("qos", compute["qos"]))
    for key, value in options:
        lines.append("#SBATCH --%s=%s" % (key, value))
    lines.extend(["set -eu", "srun %s -input %s" % (
        shlex.quote(executable), shlex.quote(input_name)), ""])
    return "\n".join(lines)


def _preflight(envelope):
    request = envelope["request"]
    required = {"run_spec", "job_name", "staging_root"}
    if set(request) != required:
        raise ExecutorError("run.preflight request keys differ from schema")
    staging = require_path(request["staging_root"], envelope["allowed_roots"], "staging_root")
    if not os.path.isdir(staging):
        os.makedirs(staging)
    script_text = render_sbatch(request["run_spec"])
    if not os.path.isfile(request["run_spec"]["executable"]):
        raise ExecutorError("run executable is missing")
    previous = matching_receipt(envelope)
    if previous and previous.get("state") == "outputs_verified":
        return previous
    intent = receipt_base(envelope, "intent_written", previous=previous)
    descriptor, path = tempfile.mkstemp(prefix="preflight-", suffix=".sbatch", dir=staging)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(script_text)
            handle.flush()
            os.fsync(handle.fileno())
        code, stdout, stderr = command([
            "sbatch", "--test-only", "--job-name", request["job_name"], path
        ], cwd=staging)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if code != 0:
        return receipt_base(envelope, "effect_observed", {}, [], stdout, stderr, intent)
    return receipt_base(
        envelope, "outputs_verified", {"scheduler": "slurm", "accepted": True},
        [], stdout, stderr, intent,
    )


def _verify_prepare(envelope, request):
    run_root = require_path(request["run_root"], envelope["allowed_roots"], "run_root")
    manifest = require_path(request["manifest"], envelope["allowed_roots"], "manifest")
    submit = require_path(request["submit_script"], envelope["allowed_roots"], "submit_script")
    copied = os.path.join(run_root, "input.toml")
    outputs = [directory_evidence(run_root), file_evidence(copied),
               file_evidence(manifest), file_evidence(submit)]
    current = read_json(manifest, "run manifest")
    if canonical_json(current) != canonical_json(request["manifest_payload"]):
        raise ExecutorError("existing run manifest differs from immutable request")
    if sha256_file(copied) != request["manifest_payload"].get("input_sha256"):
        raise ExecutorError("prepared input differs from the planned input identity")
    with open(submit, "r") as handle:
        submit_text = handle.read()
    if submit_text != render_sbatch(request["run_spec"]):
        raise ExecutorError("existing submit script differs from immutable request")
    return outputs


def _prepare(envelope):
    request = envelope["request"]
    required = {"run_root", "manifest", "manifest_payload", "submit_script",
                "run_spec", "staging_root", "staged_input"}
    if set(request) != required:
        raise ExecutorError("run.prepare request keys differ from schema")
    run_root = require_path(request["run_root"], envelope["allowed_roots"], "run_root")
    staged = require_path(request["staged_input"], envelope["allowed_roots"], "staged_input")
    manifest = require_path(request["manifest"], envelope["allowed_roots"], "manifest")
    submit = require_path(request["submit_script"], envelope["allowed_roots"], "submit_script")
    if not os.path.isfile(staged):
        raise ExecutorError("staged input is missing")
    if sha256_file(staged) != request["manifest_payload"].get("input_sha256"):
        raise ExecutorError("staged input differs from the planned input identity")
    previous = matching_receipt(envelope)
    if previous and previous.get("state") == "outputs_verified":
        _verify_prepare(envelope, request)
        return previous
    intent = receipt_base(envelope, "intent_written", previous=previous)
    if os.path.exists(run_root):
        outputs = _verify_prepare(envelope, request)
        return receipt_base(envelope, "outputs_verified", {}, outputs, previous=intent)
    parent = os.path.dirname(run_root)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    temporary = run_root + ".tmp-" + str(os.getpid())
    os.makedirs(temporary)
    try:
        shutil.copy2(staged, os.path.join(temporary, "input.toml"))
        atomic_json(os.path.join(temporary, os.path.basename(manifest)), request["manifest_payload"])
        submit_temp = os.path.join(temporary, os.path.basename(submit))
        with open(submit_temp, "w") as handle:
            handle.write(render_sbatch(request["run_spec"]))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(submit_temp, 0o755)
        os.rename(temporary, run_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    outputs = _verify_prepare(envelope, request)
    return receipt_base(envelope, "outputs_verified", {}, outputs, previous=intent)


def _parse_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, AttributeError):
        try:
            return datetime.datetime.strptime(text.split("+", 1)[0], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None


def _slurm_matches(request, receipt, comment):
    code, stdout, stderr = command([
        "squeue", "--noheader", "--user", request["submit_user"],
        "--format", "%i|%j|%u|%V|%T|%Z|%k",
    ])
    if code != 0:
        raise ExecutorError("cannot query Slurm recovery identity: %s" % (stderr or stdout))
    intent = _parse_time(receipt.get("intent_written_at"))
    if intent is None:
        raise ExecutorError("launch receipt has invalid intent time")
    # The receipt records UTC while squeue %V reports site-local time; compare
    # both as epoch seconds so non-UTC sites still match their own intent.
    intent_epoch = calendar.timegm(intent.timetuple())
    matches = []
    for line in stdout.splitlines():
        fields = line.strip().split("|", 6)
        submitted = _parse_time(fields[3]) if len(fields) == 7 else None
        submitted_epoch = (time.mktime(submitted.timetuple())
                           if submitted is not None else None)
        in_window = (submitted_epoch is not None
                     and abs(submitted_epoch - intent_epoch) <= 600)
        if (len(fields) == 7 and fields[1] == request["job_name"]
                and fields[2] == request["submit_user"] and in_window
                and os.path.realpath(fields[5]) == os.path.realpath(request["run_root"])
                and fields[6] == comment):
            matches.append({"scheduler": "slurm", "job_id": fields[0],
                            "job_name": fields[1], "submit_user": fields[2],
                            "submitted_at": fields[3], "state": fields[4].upper(),
                            "run_root": fields[5], "comment": fields[6]})
    return matches, stdout, stderr


def _slurm_history_matches(request, comment):
    """Fallback for jobs that already left squeue (completed/failed) before
    recovery ran: match accounting records by job name, user, working
    directory, and the launch comment.  An unavailable sacct yields no
    matches so the caller falls back to a fresh submit, as before."""
    code, stdout, stderr = command([
        "sacct", "--noheader", "--parsable2", "--user", request["submit_user"],
        "--format", "JobID,JobName,User,WorkDir,Comment,State",
    ])
    if code != 0:
        return [], stdout, stderr
    matches = []
    for line in stdout.splitlines():
        fields = [item.strip() for item in line.split("|")]
        if len(fields) < 6 or not fields[0] or "." in fields[0]:
            continue
        if (fields[1] == request["job_name"]
                and fields[2] == request["submit_user"]
                and os.path.realpath(fields[3]) == os.path.realpath(request["run_root"])
                and fields[4] == comment):
            matches.append({"scheduler": "slurm", "job_id": fields[0],
                            "job_name": fields[1], "submit_user": fields[2],
                            "state": fields[5].split()[0].upper() if fields[5] else "",
                            "run_root": fields[3], "comment": fields[4]})
    return matches, stdout, stderr


def _launch(envelope):
    request = envelope["request"]
    required = {"run_root", "submit_script", "job_name", "submit_user"}
    if set(request) != required:
        raise ExecutorError("run.launch request keys differ from schema")
    run_root = require_path(request["run_root"], envelope["allowed_roots"], "run_root")
    submit = require_path(request["submit_script"], envelope["allowed_roots"], "submit_script")
    if not os.path.isdir(run_root) or not os.path.isfile(submit):
        raise ExecutorError("prepared run root or submit script is missing")
    previous = matching_receipt(envelope)
    if previous and previous.get("state") == "outputs_verified":
        return previous
    if previous and previous.get("effect_identity", {}).get("job_id"):
        return receipt_base(envelope, "outputs_verified", previous["effect_identity"],
                            previous.get("outputs", []), previous=previous)
    comment = "entity-router:%s:%s" % (
        envelope["operation_id"], envelope["plan_hash"].split(":", 1)[-1][:16]
    )
    if previous:
        matches, stdout, stderr = _slurm_matches(request, previous, comment)
        if len(matches) > 1:
            raise ExecutorError("multiple scheduler jobs match launch intent")
        if not matches:
            matches, stdout, stderr = _slurm_history_matches(request, comment)
            if len(matches) > 1:
                raise ExecutorError("multiple scheduler jobs match launch intent")
        if len(matches) == 1:
            return receipt_base(envelope, "outputs_verified", matches[0], [],
                                stdout, stderr, previous)
    intent = receipt_base(envelope, "intent_written", previous=previous)
    code, stdout, stderr = command([
        "sbatch", "--parsable", "--job-name", request["job_name"],
        "--comment", comment, "--chdir", run_root, submit,
    ], cwd=run_root)
    if code != 0:
        return receipt_base(envelope, "effect_observed", {}, [], stdout, stderr, intent)
    job_id = stdout.strip().split(";", 1)[0].splitlines()[0].strip()
    if not job_id or not job_id.replace("_", "").replace(".", "").isdigit():
        raise ExecutorError("sbatch returned an invalid job identity")
    identity = {"scheduler": "slurm", "job_id": job_id,
                "job_name": request["job_name"], "submit_user": request["submit_user"],
                "run_root": run_root, "comment": comment}
    effect = receipt_base(envelope, "effect_observed", identity, [], stdout, stderr, intent)
    return receipt_base(envelope, "outputs_verified", identity, [], stdout, stderr, effect)


def _scheduler_remediation(text):
    """Map known scheduler rejections to the exact repair path."""
    lowered = (text or "").lower()
    if "invalid qos" in lowered:
        return ("Scheduler rejected the QoS; run 'entityctl site discover <site_id>' "
                "and set policy.default_qos to a listed value, then re-plan.")
    if "invalid partition" in lowered:
        return ("Scheduler rejected the partition; run 'entityctl site discover <site_id>' "
                "and set policy.default_partition to a listed value, then re-plan.")
    return ""


def _build_register(envelope):
    request = envelope["request"]
    if set(request) != {"executable"}:
        raise ExecutorError("build.register request keys differ from schema")
    executable = require_path(request["executable"], envelope["allowed_roots"],
                              "executable")
    if not os.path.isfile(executable):
        raise ExecutorError("build executable is missing")
    previous = matching_receipt(envelope)
    if previous and previous.get("state") == "outputs_verified":
        return previous
    intent = receipt_base(envelope, "intent_written", previous=previous)
    return receipt_base(envelope, "outputs_verified", {},
                        [file_evidence(executable)], previous=intent)


def _data_inventory(envelope):
    request = envelope["request"]
    if set(request) != {"run_root", "manifest"}:
        raise ExecutorError("data.inventory request keys differ from schema")
    run_root = require_path(request["run_root"], envelope["allowed_roots"], "run_root")
    manifest = require_path(request["manifest"], envelope["allowed_roots"], "manifest")
    if not os.path.isdir(run_root):
        raise ExecutorError("run root is missing")
    # Inventory is a pure function of the current run root, so it always
    # re-walks: this is what makes `apply --refresh` able to pick up
    # artifacts that appeared after the first inventory.
    previous = matching_receipt(envelope)
    intent = receipt_base(envelope, "intent_written", previous=previous)
    entries = []
    for current, directories, names in os.walk(run_root):
        directories[:] = sorted(directories)
        for name in sorted(names):
            path = os.path.join(current, name)
            if os.path.realpath(path) == os.path.realpath(manifest):
                continue
            entries.append({
                "path": os.path.relpath(path, run_root),
                "sha256": sha256_file(path),
                "bytes": os.path.getsize(path),
            })
    payload = {
        "schema_version": 1, "kind": "entity-router.data-inventory",
        "run_root": run_root, "files": entries, "created_at": now_utc(),
    }
    atomic_json(manifest, payload)
    outputs = [file_evidence(manifest), directory_evidence(run_root)]
    return receipt_base(envelope, "outputs_verified", {"files": len(entries)},
                        outputs, previous=intent)


def execute(envelope):
    kind = envelope["kind"]
    if kind == "run.preflight.v1":
        receipt = _preflight(envelope)
    elif kind == "run.prepare.v2":
        receipt = _prepare(envelope)
    elif kind == "run.launch.v2":
        receipt = _launch(envelope)
    elif kind == "build.register.v1":
        receipt = _build_register(envelope)
    elif kind == "data.inventory.v1":
        receipt = _data_inventory(envelope)
    else:
        raise ExecutorError("unsupported Step kind")
    if receipt.get("state") != "outputs_verified":
        message = receipt.get("stderr", {}).get("tail") or receipt.get("stdout", {}).get("tail")
        hint = _scheduler_remediation(message)
        if hint:
            message = "%s\n%s" % (message, hint) if message else hint
        return {"schema_version": 1, "status": "anomaly", "message": message,
                "receipt": envelope["receipt"], "effect": receipt.get("effect_identity", {}),
                "outputs": receipt.get("outputs", [])}
    return {"schema_version": 1, "status": "completed", "message": "",
            "receipt": envelope["receipt"], "effect": receipt.get("effect_identity", {}),
            "outputs": receipt.get("outputs", [])}


def verify(envelope):
    receipt = matching_receipt(envelope)
    if receipt is None or receipt.get("state") != "outputs_verified":
        raise ExecutorError("Step receipt is not outputs_verified")
    request = envelope["request"]
    if envelope["kind"] == "run.prepare.v2":
        outputs = _verify_prepare(envelope, request)
    else:
        outputs = receipt.get("outputs", [])
    for item in outputs:
        path = require_path(item.get("path"), envelope["allowed_roots"], "output")
        if item.get("kind") == "file":
            current = file_evidence(path)
            if current.get("fingerprint") != item.get("fingerprint"):
                raise ExecutorError("output fingerprint changed: %s" % path)
        elif item.get("kind") == "directory":
            directory_evidence(path)
        else:
            raise ExecutorError("receipt contains unsupported output evidence")
    return {"schema_version": 1, "status": "verified", "receipt": receipt,
            "effect": receipt.get("effect_identity", {}), "outputs": outputs}


def command_execute(args):
    envelope = validate_envelope(read_json(args.request, "executor request"))
    result = execute(envelope)
    if args.result:
        atomic_json(args.result, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "completed" else 2


def command_verify(args):
    envelope = validate_envelope(read_json(args.request, "executor request"))
    result = verify(envelope)
    print(json.dumps(result, sort_keys=True))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Entity Router Site executor")
    sub = parser.add_subparsers(dest="command")
    execute_parser = sub.add_parser("execute")
    execute_parser.add_argument("--request", required=True)
    execute_parser.add_argument("--result")
    execute_parser.set_defaults(func=command_execute)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--request", required=True)
    verify_parser.set_defaults(func=command_verify)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        raise SystemExit("command required")
    try:
        return args.func(args)
    except (ExecutorError, IOError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"schema_version": 1, "status": "anomaly",
                          "message": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
