#!/usr/bin/env python3
"""Allowlisted deterministic owner adapters for entity_router_flow.py."""

from __future__ import print_function

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

from entity_router_common import (
    RouterError,
    atomic_write_json,
    canonical_locator,
    load_site_profile,
    locators_overlap,
    locator_within,
    now_utc,
    run_on_site,
)


FORBIDDEN_RUNNER_KEYS = {"command", "shell", "script_text", "pre_command"}
RUNNER_ACTIONS = {
    "source.materialize.v1": "source.materialize",
    "build.plan.v1": "build.plan",
    "build.compile.v1": "build.compile",
    "run.prepare.v1": "run.prepare",
    "run.launch.v1": "run.launch",
    "run.monitor.v1": "run.monitor",
    "data.inspect.v1": "data.inspect",
}
RUNNER_READINESS = {
    "source.materialize.v1": {"source": "ready"},
    "build.plan.v1": {"build": "planned"},
    "build.compile.v1": {"build": "pass"},
    "run.prepare.v1": {"run": "prepared"},
    "run.launch.v1": {"run": "submitted"},
    "data.inspect.v1": {"data": "ready"},
}


class RunnerOutcome(object):
    def __init__(self, status, outputs=None, verification=None, readiness=None,
                 message="", receipt=None):
        self.status = status
        self.outputs = outputs or []
        self.verification = verification or []
        self.readiness = readiness or {}
        self.message = message
        self.receipt = receipt


def _stream(value):
    data = (value or "").encode("utf-8", errors="replace")
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "tail": data[-2048:].decode("utf-8", errors="replace"),
    }


def _run(command, cwd=None):
    process = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stdout, stderr = process.communicate()
    return process.returncode, stdout, stderr


def _require_keys(value, allowed, required, label):
    if not isinstance(value, dict):
        raise RouterError("%s must be an object" % label)
    forbidden = set(value).intersection(FORBIDDEN_RUNNER_KEYS)
    if forbidden:
        raise RouterError("%s contains forbidden shell field: %s" % (label, sorted(forbidden)[0]))
    unknown = set(value).difference(allowed)
    if unknown:
        raise RouterError("%s contains unknown field: %s" % (label, sorted(unknown)[0]))
    missing = set(required).difference(value)
    if missing:
        raise RouterError("%s is missing field: %s" % (label, sorted(missing)[0]))


def _locator(home, value, site_id=None):
    item = canonical_locator(home, value)
    if site_id and item["site_id"] != site_id:
        raise RouterError("runner Locator is on the wrong execution site")
    return item


def _covered(locator, roots):
    return any(locator_within(locator, item) for item in roots)


def _runner_locator(home, step, value, access, label, site_id=None):
    locator = _locator(home, value, site_id)
    read_roots = [canonical_locator(home, item) for item in step.get("read_roots", [])]
    write_roots = [canonical_locator(home, item) for item in step.get("write_roots", [])]
    protected = [canonical_locator(home, item) for item in step.get("protected_paths", [])]
    if access == "read":
        if not _covered(locator, read_roots + write_roots):
            raise RouterError("%s is outside step read/write roots" % label)
    elif access == "write":
        if not _covered(locator, write_roots):
            raise RouterError("%s is outside step write roots" % label)
        if any(locators_overlap(locator, item) for item in protected):
            raise RouterError("%s overlaps a protected path" % label)
    else:
        raise RouterError("unknown runner Locator access: %s" % access)
    return locator


def _validate_runner_args(home, step):
    runner = step["runner"]
    args = step.get("runner_args", {})
    site_id = step["execution_site_id"]
    if runner == "source.materialize.v1":
        _require_keys(
            args, {"mode", "source", "target", "repository", "commit", "receipt"},
            {"mode", "target", "receipt"}, "source.materialize.v1 runner_args",
        )
        if args.get("source"):
            _runner_locator(home, step, args["source"], "read", "source")
        _runner_locator(home, step, args["target"], "write", "target", site_id)
        _runner_locator(home, step, args["receipt"], "write", "receipt", site_id)
    elif runner == "build.plan.v1":
        fields = {"requirements", "checkpoint", "env", "build_script", "receipt"}
        _require_keys(args, fields, fields, "build.plan.v1 runner_args")
        _runner_locator(home, step, args["requirements"], "read", "requirements", site_id)
        for key in ["checkpoint", "env", "build_script", "receipt"]:
            _runner_locator(home, step, args[key], "write", key, site_id)
    elif runner == "build.compile.v1":
        fields = {"requirements", "build_script", "executable", "receipt"}
        _require_keys(args, fields, fields, "build.compile.v1 runner_args")
        for key in ["requirements", "build_script"]:
            _runner_locator(home, step, args[key], "read", key, site_id)
        for key in ["executable", "receipt"]:
            _runner_locator(home, step, args[key], "write", key, site_id)
    elif runner == "run.prepare.v1":
        fields = {"input_toml", "run_root", "manifest", "manifest_payload", "receipt"}
        _require_keys(args, fields, fields, "run.prepare.v1 runner_args")
        _runner_locator(home, step, args["input_toml"], "read", "input_toml")
        for key in ["run_root", "manifest", "receipt"]:
            _runner_locator(home, step, args[key], "write", key, site_id)
    elif runner == "run.launch.v1":
        mode = args.get("mode", "scheduler")
        if mode == "process":
            fields = {"mode", "run_root", "executable", "input_toml", "pid_record",
                      "stdout_log", "stderr_log", "receipt"}
            _require_keys(args, fields, fields, "run.launch.v1 process runner_args")
            for key in ["run_root", "executable", "input_toml"]:
                _runner_locator(home, step, args[key], "read", key, site_id)
            for key in ["pid_record", "stdout_log", "stderr_log", "receipt"]:
                _runner_locator(home, step, args[key], "write", key, site_id)
        elif mode == "scheduler":
            allowed = {"mode", "run_root", "submit_script", "job_name", "submit_user", "receipt"}
            required = {"run_root", "submit_script", "job_name", "submit_user", "receipt"}
            _require_keys(args, allowed, required, "run.launch.v1 runner_args")
            for key in ["run_root", "submit_script"]:
                _runner_locator(home, step, args[key], "read", key, site_id)
            _runner_locator(home, step, args["receipt"], "write", "receipt", site_id)
        else:
            raise RouterError("run.launch.v1 mode must be scheduler or process")
    elif runner == "run.monitor.v1":
        allowed = {"run_root", "trace", "job_id", "pid", "pid_start_ticks",
                   "pid_record", "progress_log", "stderr_log", "fields_root",
                   "checkpoint_root", "field_pattern", "checkpoint_pattern",
                   "total_steps", "target_time"}
        _require_keys(args, allowed, {"run_root", "trace"}, "run.monitor.v1 runner_args")
        _runner_locator(home, step, args["run_root"], "read", "run_root", site_id)
        _runner_locator(home, step, args["trace"], "write", "trace", site_id)
        if args.get("pid_record"):
            _runner_locator(home, step, args["pid_record"], "read", "pid_record", site_id)
        if not args.get("job_id") and not args.get("pid"):
            raise RouterError("run.monitor.v1 requires job_id or pid")
    elif runner == "data.inspect.v1":
        fields = {"data_root", "inventory", "receipt"}
        _require_keys(args, fields, fields, "data.inspect.v1 runner_args")
        _runner_locator(home, step, args["data_root"], "read", "data_root", site_id)
        for key in ["inventory", "receipt"]:
            _runner_locator(home, step, args[key], "write", key, site_id)


def _receipt(home, step, flow_hash, state, effect_identity, outputs, stdout, stderr):
    args = step["runner_args"]
    receipt = _locator(home, args["receipt"], step["execution_site_id"])
    roots = [canonical_locator(home, item) for item in step["write_roots"]]
    if not _covered(receipt, roots):
        raise RouterError("dispatch receipt is outside step write roots")
    profile = load_site_profile(home, receipt["site_id"])
    payload = {
        "schema_version": 1,
        "case_uid": step["case_uid"],
        "action_id": step["action_id"],
        "flow_request_hash": flow_hash,
        "runner": step["runner"],
        "state": state,
        "attempt": 1,
        "intent_written_at": now_utc(),
        "effect_identity": effect_identity or {},
        "outputs": outputs,
        "stdout": _stream(stdout),
        "stderr": _stream(stderr),
    }
    _write_site_json(profile, receipt["path"], payload)
    return receipt


def _write_site_json(profile, path, payload):
    if profile["transport"]["kind"] == "local":
        atomic_write_json(path, payload)
        return
    script = (
        "import json,os,sys; p=sys.argv[1]; v=json.loads(sys.argv[2]); "
        "d=os.path.dirname(p); os.makedirs(d) if not os.path.isdir(d) else None; "
        "t=p+'.tmp-'+str(os.getpid()); f=open(t,'w'); "
        "json.dump(v,f,indent=2,sort_keys=True); f.write('\\n'); "
        "f.flush(); os.fsync(f.fileno()); f.close(); os.rename(t,p)"
    )
    code, stdout, stderr = run_on_site(
        profile, ["python3", "-c", script, path, json.dumps(payload, sort_keys=True)]
    )
    if code != 0:
        raise RouterError("remote receipt write failed: %s" %
                          (stderr.strip() or stdout.strip()))


def _read_site_json(profile, path):
    if profile["transport"]["kind"] == "local":
        if not os.path.isfile(path):
            return None
        with open(path, "r") as handle:
            return json.load(handle)
    script = (
        "import json,os,sys; p=sys.argv[1]; "
        "sys.exit(3) if not os.path.isfile(p) else None; "
        "print(json.dumps(json.load(open(p)),sort_keys=True))"
    )
    code, stdout, stderr = run_on_site(profile, ["python3", "-c", script, path])
    if code == 3:
        return None
    if code != 0:
        raise RouterError("remote receipt read failed: %s" %
                          (stderr.strip() or stdout.strip()))
    try:
        return json.loads(stdout)
    except ValueError:
        raise RouterError("remote receipt returned invalid JSON")


def _recover_receipt(home, step, flow_hash):
    args = step.get("runner_args", {})
    if "receipt" not in args:
        return None
    receipt = _locator(home, args["receipt"], step["execution_site_id"])
    profile = load_site_profile(home, receipt["site_id"])
    payload = _read_site_json(profile, receipt["path"])
    if payload is None:
        return None
    if (payload.get("case_uid") != step.get("case_uid")
            or payload.get("action_id") != step.get("action_id")
            or payload.get("flow_request_hash") != flow_hash
            or payload.get("runner") != step.get("runner")):
        raise RouterError("existing dispatch receipt does not match flow step")
    outputs = list(payload.get("outputs", []))
    outputs.append(receipt)
    if payload.get("state") == "outputs_verified":
        return RunnerOutcome(
            "completed", outputs, ["recovered verified dispatch receipt"],
            RUNNER_READINESS[step["runner"]], receipt=receipt,
        )
    return RunnerOutcome(
        "anomaly", outputs, message="previous runner stopped after an external effect",
        receipt=receipt,
    )


def _dispatch_payload(step, flow_hash, state, effect_identity=None, outputs=None,
                      stdout="", stderr="", intent_written_at=None, attempt=1):
    return {
        "schema_version": 1,
        "case_uid": step["case_uid"],
        "action_id": step["action_id"],
        "flow_request_hash": flow_hash,
        "runner": step["runner"],
        "state": state,
        "attempt": attempt,
        "intent_written_at": intent_written_at or now_utc(),
        "effect_identity": effect_identity or {},
        "outputs": outputs or [],
        "stdout": _stream(stdout),
        "stderr": _stream(stderr),
    }


def _write_launch_receipt(home, step, flow_hash, state, effect_identity=None,
                          outputs=None, stdout="", stderr="", previous=None):
    args = step["runner_args"]
    receipt = _locator(home, args["receipt"], step["execution_site_id"])
    roots = [canonical_locator(home, item) for item in step["write_roots"]]
    if not _covered(receipt, roots):
        raise RouterError("dispatch receipt is outside step write roots")
    payload = _dispatch_payload(
        step, flow_hash, state, effect_identity, outputs, stdout, stderr,
        (previous or {}).get("intent_written_at"),
        (previous or {}).get("attempt", 1),
    )
    atomic_write_json(receipt["path"], payload)
    return receipt, payload


def _load_matching_launch_receipt(home, step, flow_hash):
    receipt = _locator(home, step["runner_args"]["receipt"], step["execution_site_id"])
    if not os.path.isfile(receipt["path"]):
        return receipt, None
    with open(receipt["path"], "r") as handle:
        payload = json.load(handle)
    expected = (step["case_uid"], step["action_id"], flow_hash, step["runner"])
    actual = (payload.get("case_uid"), payload.get("action_id"),
              payload.get("flow_request_hash"), payload.get("runner"))
    if actual != expected:
        raise RouterError("existing launch receipt does not match flow step")
    return receipt, payload


def _parse_scheduler_time(value):
    text = str(value or "").strip()
    for pattern in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S.%f"]:
        try:
            return datetime.datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _launch_comment(step, flow_hash):
    digest = hashlib.sha256(
        (step["case_uid"] + "\0" + step["action_id"] + "\0" + flow_hash).encode("utf-8")
    ).hexdigest()[:24]
    return "entity-router-%s" % digest


def _slurm_matches(job_name, submit_user, intent_written_at, run_root, comment):
    code, stdout, stderr = _run([
        "squeue", "-h", "-n", job_name, "-u", submit_user,
        "-o", "%i|%j|%u|%V|%T|%Z|%k",
    ])
    if code != 0:
        raise RouterError("scheduler recovery query failed: %s" %
                          (stderr.strip() or stdout.strip()))
    matches = []
    intent_time = _parse_scheduler_time(intent_written_at)
    if intent_time is None:
        raise RouterError("launch receipt has an invalid intent timestamp")
    for line in stdout.splitlines():
        fields = line.strip().split("|", 6)
        submitted = _parse_scheduler_time(fields[3]) if len(fields) == 7 else None
        in_window = submitted is not None and abs((submitted - intent_time).total_seconds()) <= 600
        if (len(fields) == 7 and fields[1] == job_name and fields[2] == submit_user
                and in_window and os.path.realpath(fields[5]) == os.path.realpath(run_root)
                and fields[6] == comment):
            matches.append({
                "scheduler": "slurm", "job_id": fields[0], "job_name": fields[1],
                "submit_user": fields[2], "submitted_at": fields[3],
                "state": fields[4].upper(), "run_root": fields[5],
                "comment": fields[6],
            })
    return matches, stdout, stderr


def _read_pid_record(path, step, flow_hash, run_root):
    if not os.path.isfile(path):
        return None
    with open(path, "r") as handle:
        payload = json.load(handle)
    if (payload.get("case_uid") != step["case_uid"]
            or payload.get("action_id") != step["action_id"]
            or payload.get("flow_request_hash") != flow_hash
            or payload.get("run_root") != run_root):
        raise RouterError("PID record does not match launch intent")
    pid = str(payload.get("pid", ""))
    ticks = str(payload.get("pid_start_ticks", ""))
    stat_path = "/proc/%s/stat" % pid
    cwd_path = "/proc/%s/cwd" % pid
    if not pid or not ticks:
        raise RouterError("PID launch record lacks process identity")
    if not os.path.isfile(stat_path) and "exit_code" in payload:
        return {
            "scheduler": "none", "pid": int(pid), "pid_start_ticks": ticks,
            "run_root": run_root, "exit_code": int(payload["exit_code"]),
            "finished_at": payload.get("finished_at", ""),
        }
    if not os.path.isfile(stat_path):
        raise RouterError("PID launch produced an effect but identity is no longer observable")
    with open(stat_path, "r") as handle:
        fields = handle.read().split()
    if len(fields) <= 21 or fields[21] != ticks:
        raise RouterError("PID identity was reused or changed")
    if os.path.realpath(cwd_path) != run_root:
        raise RouterError("PID process cwd differs from immutable run root")
    return {
        "scheduler": "none", "pid": int(pid), "pid_start_ticks": ticks,
        "run_root": run_root,
    }


def _process_launch(home, step, flow_hash, args):
    run_root = _locator(home, args["run_root"], step["execution_site_id"])
    executable = _locator(home, args["executable"], step["execution_site_id"])
    input_toml = _locator(home, args["input_toml"], step["execution_site_id"])
    pid_record = _locator(home, args["pid_record"], step["execution_site_id"])
    stdout_log = _locator(home, args["stdout_log"], step["execution_site_id"])
    stderr_log = _locator(home, args["stderr_log"], step["execution_site_id"])
    roots = [canonical_locator(home, item) for item in step["write_roots"]]
    for item in [pid_record, stdout_log, stderr_log]:
        if not _covered(item, roots):
            raise RouterError("process launch artifact is outside step write roots")
    if not os.path.isfile("/proc/self/stat") or not os.path.isdir("/proc/self/fd"):
        raise RouterError("safe PID launch requires observable /proc start ticks")
    receipt, previous = _load_matching_launch_receipt(home, step, flow_hash)
    if previous and previous.get("state") == "outputs_verified":
        identity = previous.get("effect_identity", {})
        _read_pid_record(pid_record["path"], step, flow_hash, run_root["path"])
        return RunnerOutcome("completed", list(previous.get("outputs", [])) + [receipt],
                             ["verified PID receipt recovered"], {"run": "running"},
                             receipt=receipt)
    if previous or os.path.isfile(pid_record["path"]):
        identity = _read_pid_record(pid_record["path"], step, flow_hash, run_root["path"])
        identity["pid_record"] = pid_record
        outputs = [pid_record]
        receipt, unused = _write_launch_receipt(
            home, step, flow_hash, "outputs_verified", identity, outputs,
            previous=previous,
        )
        outputs.append(receipt)
        return RunnerOutcome("completed", outputs, ["unique PID process recovered"],
                             {"run": "running"}, receipt=receipt)
    receipt, intent = _write_launch_receipt(home, step, flow_hash, "intent_written")
    wrapper = (
        "import datetime,json,os,subprocess,sys; "
        "record,root,exe,inp,out,err,case,action,flow=sys.argv[1:]; "
        "os.chdir(root); "
        "o=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o644); "
        "e=os.open(err,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o644); "
        "os.dup2(o,1); os.dup2(e,2); "
        "ticks=open('/proc/self/stat').read().split()[21]; "
        "p={'schema_version':1,'case_uid':case,'action_id':action,'flow_request_hash':flow,'pid':os.getpid(),'pid_start_ticks':ticks,'run_root':root}; "
        "tmp=record+'.tmp-'+str(os.getpid()); "
        "f=open(tmp,'w'); json.dump(p,f,sort_keys=True); f.flush(); os.fsync(f.fileno()); f.close(); "
        "os.rename(tmp,record); code=subprocess.call([exe,inp]); "
        "p['exit_code']=code; p['finished_at']=datetime.datetime.utcnow().replace(microsecond=0).isoformat()+'Z'; "
        "tmp=record+'.tmp-'+str(os.getpid()); f=open(tmp,'w'); json.dump(p,f,sort_keys=True); f.flush(); os.fsync(f.fileno()); f.close(); os.rename(tmp,record); sys.exit(code)"
    )
    try:
        subprocess.Popen([
            sys.executable, "-c", wrapper, pid_record["path"], run_root["path"],
            executable["path"], input_toml["path"], stdout_log["path"],
            stderr_log["path"], step["case_uid"], step["action_id"], flow_hash,
        ], cwd=run_root["path"], close_fds=True)
    except OSError as exc:
        return RunnerOutcome("anomaly", [receipt], message=str(exc), receipt=receipt)
    for unused in range(100):
        if os.path.isfile(pid_record["path"]):
            break
        time.sleep(0.02)
    if not os.path.isfile(pid_record["path"]):
        return RunnerOutcome(
            "blocked", [receipt],
            message="process effect may exist but PID record is not yet observable",
            receipt=receipt,
        )
    identity = _read_pid_record(pid_record["path"], step, flow_hash, run_root["path"])
    identity["pid_record"] = pid_record
    outputs = [pid_record]
    receipt, effect = _write_launch_receipt(
        home, step, flow_hash, "effect_observed", identity, outputs, previous=intent,
    )
    receipt, unused = _write_launch_receipt(
        home, step, flow_hash, "outputs_verified", identity, outputs, previous=effect,
    )
    outputs.append(receipt)
    return RunnerOutcome("completed", outputs, ["PID, start ticks and run root recorded"],
                         {"run": "running"}, receipt=receipt)


def _run_launch(home, step, flow_hash):
    args = step["runner_args"]
    mode = args.get("mode", "scheduler")
    if mode == "process":
        _require_keys(
            args,
            {"mode", "run_root", "executable", "input_toml", "pid_record",
             "stdout_log", "stderr_log", "receipt"},
            {"mode", "run_root", "executable", "input_toml", "pid_record",
             "stdout_log", "stderr_log", "receipt"},
            "run.launch.v1 process runner_args",
        )
        return _process_launch(home, step, flow_hash, args)
    if mode != "scheduler":
        raise RouterError("run.launch.v1 mode must be scheduler or process")
    _require_keys(
        args, {"mode", "run_root", "submit_script", "job_name", "submit_user", "receipt"},
        {"run_root", "submit_script", "job_name", "submit_user", "receipt"},
        "run.launch.v1 runner_args",
    )
    profile = load_site_profile(home, step["execution_site_id"])
    if profile["transport"]["kind"] != "local":
        raise RouterError("run.launch.v1 remote runner is not staged")
    if profile.get("scheduler", {}).get("kind") != "slurm":
        raise RouterError("run.launch.v1 currently requires a Slurm site")
    run_root = _locator(home, args["run_root"], step["execution_site_id"])
    submit_script = _locator(home, args["submit_script"], step["execution_site_id"])
    if not os.path.isdir(run_root["path"]) or not os.path.isfile(submit_script["path"]):
        raise RouterError("run root or submit script is missing")
    receipt, previous = _load_matching_launch_receipt(home, step, flow_hash)
    comment = _launch_comment(step, flow_hash)
    if previous and previous.get("state") == "outputs_verified":
        outputs = list(previous.get("outputs", [])) + [receipt]
        return RunnerOutcome("completed", outputs, ["recovered verified scheduler receipt"],
                             {"run": "submitted"}, receipt=receipt)
    if previous and previous.get("effect_identity", {}).get("job_id"):
        identity = previous["effect_identity"]
        outputs = list(previous.get("outputs", []))
        receipt, unused = _write_launch_receipt(
            home, step, flow_hash, "outputs_verified", identity, outputs,
            previous=previous,
        )
        outputs.append(receipt)
        return RunnerOutcome("completed", outputs, ["scheduler job identity recovered"],
                             {"run": "submitted"}, receipt=receipt)
    if previous:
        matches, stdout, stderr = _slurm_matches(
            args["job_name"], args["submit_user"], previous.get("intent_written_at"),
            run_root["path"], comment,
        )
        if len(matches) > 1:
            return RunnerOutcome(
                "anomaly", [receipt],
                message="multiple scheduler jobs match launch intent", receipt=receipt,
            )
        if len(matches) == 1:
            identity = matches[0]
            receipt, unused = _write_launch_receipt(
                home, step, flow_hash, "outputs_verified", identity, [], stdout, stderr,
                previous=previous,
            )
            return RunnerOutcome("completed", [receipt], ["unique scheduler job recovered"],
                                 {"run": "submitted"}, receipt=receipt)
        previous["attempt"] = int(previous.get("attempt", 1)) + 1
    receipt, intent = _write_launch_receipt(
        home, step, flow_hash, "intent_written", previous=previous,
    )
    code, stdout, stderr = _run([
        "sbatch", "--parsable", "--job-name", args["job_name"],
        "--comment", comment, "--chdir", run_root["path"], submit_script["path"]
    ], cwd=run_root["path"])
    if code != 0:
        return RunnerOutcome("anomaly", [receipt], message=stderr or stdout, receipt=receipt)
    job_id = stdout.strip().split(";", 1)[0].splitlines()[0].strip()
    if not job_id or not job_id.replace("_", "").replace(".", "").isdigit():
        return RunnerOutcome("anomaly", [receipt],
                             message="sbatch returned an invalid job identity", receipt=receipt)
    identity = {
        "scheduler": "slurm", "job_id": job_id, "job_name": args["job_name"],
        "submit_user": args["submit_user"], "run_root": run_root["path"],
        "comment": comment,
    }
    receipt, effect = _write_launch_receipt(
        home, step, flow_hash, "effect_observed", identity, [], stdout, stderr,
        previous=intent,
    )
    receipt, unused = _write_launch_receipt(
        home, step, flow_hash, "outputs_verified", identity, [], stdout, stderr,
        previous=effect,
    )
    return RunnerOutcome("completed", [receipt], ["scheduler submission identity recorded"],
                         {"run": "submitted"}, receipt=receipt)


def _source_materialize(home, step, flow_hash):
    args = step["runner_args"]
    _require_keys(
        args,
        {"mode", "source", "target", "repository", "commit", "receipt"},
        {"mode", "target", "receipt"}, "source.materialize.v1 runner_args",
    )
    script = os.path.join(os.path.dirname(__file__), "entity_router_site.py")
    command = [sys.executable, script, "--router-home", home, "materialize",
               "--mode", args["mode"], "--target", _locator(home, args["target"])["site_id"] + ":" + _locator(home, args["target"])["path"]]
    if args.get("source"):
        source = _locator(home, args["source"])
        command.extend(["--source", source["site_id"] + ":" + source["path"]])
    if args.get("repository"):
        command.extend(["--repository", args["repository"]])
    if args.get("commit"):
        command.extend(["--commit", args["commit"]])
    code, stdout, stderr = _run(command)
    if code != 0:
        receipt = _receipt(home, step, flow_hash, "effect_observed", {}, [], stdout, stderr)
        return RunnerOutcome("anomaly", [receipt], message=stderr or stdout, receipt=receipt)
    payload = json.loads(stdout)
    materialized = payload.get("materialized")
    outputs = [materialized] if materialized else []
    receipt = _receipt(
        home, step, flow_hash, "outputs_verified",
        {"mode": args["mode"], "snapshot_id": payload.get("snapshot_id", "")},
        outputs, stdout, stderr,
    )
    outputs.append(receipt)
    return RunnerOutcome("completed", outputs, ["materialized revision reprobed"],
                         {"source": "ready"}, receipt=receipt)


def _build_plan(home, step, flow_hash):
    args = step["runner_args"]
    _require_keys(
        args,
        {"requirements", "checkpoint", "env", "build_script", "receipt"},
        {"requirements", "checkpoint", "env", "build_script", "receipt"},
        "build.plan.v1 runner_args",
    )
    profile = load_site_profile(home, step["execution_site_id"])
    if profile["transport"]["kind"] != "local":
        raise RouterError("build.plan.v1 remote runner is not staged")
    paths = {key: _locator(home, args[key], step["execution_site_id"])["path"]
             for key in ["requirements", "checkpoint", "env", "build_script"]}
    skill = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "entity-env-build", "scripts"))
    commands = [
        [sys.executable, os.path.join(skill, "entity_checkpoint.py"), "validate", paths["requirements"]],
    ]
    create = [sys.executable, os.path.join(skill, "entity_checkpoint.py"), "create",
              paths["requirements"], "--output", paths["checkpoint"], "--json"]
    if os.path.isfile(paths["checkpoint"]):
        create.extend(["--merge", paths["checkpoint"]])
    commands.append(create)
    commands.extend([
        [sys.executable, os.path.join(skill, "entity_compat.py"), paths["requirements"],
         "--checkpoint", paths["checkpoint"], "--json"],
        [sys.executable, os.path.join(skill, "entity_generate.py"), "env", paths["checkpoint"],
         "--output", paths["env"], "--json"],
        [sys.executable, os.path.join(skill, "entity_generate.py"), "build", paths["requirements"],
         "--env", paths["env"], "--checkpoint", paths["checkpoint"],
         "--output", paths["build_script"], "--json"],
    ])
    combined_out = []
    combined_err = []
    for command in commands:
        code, stdout, stderr = _run(command)
        combined_out.append(stdout)
        combined_err.append(stderr)
        if code != 0:
            status = "needs_decision" if "partial" in (stdout + stderr).lower() or "compat" in (stdout + stderr).lower() else "anomaly"
            receipt = _receipt(home, step, flow_hash, "effect_observed", {}, [],
                               "".join(combined_out), "".join(combined_err))
            return RunnerOutcome(status, [receipt], message=stderr or stdout, receipt=receipt)
    outputs = [_locator(home, args[key], step["execution_site_id"])
               for key in ["requirements", "checkpoint", "env", "build_script"]]
    receipt = _receipt(home, step, flow_hash, "outputs_verified", {}, outputs,
                       "".join(combined_out), "".join(combined_err))
    outputs.append(receipt)
    return RunnerOutcome("completed", outputs, ["requirements, compatibility, env and build script verified"],
                         {"build": "planned"}, receipt=receipt)


def _build_compile(home, step, flow_hash):
    args = step["runner_args"]
    _require_keys(
        args, {"requirements", "build_script", "executable", "receipt"},
        {"requirements", "build_script", "executable", "receipt"},
        "build.compile.v1 runner_args",
    )
    profile = load_site_profile(home, step["execution_site_id"])
    if profile["transport"]["kind"] != "local":
        raise RouterError("build.compile.v1 remote runner is not staged")
    requirements = _locator(home, args["requirements"], step["execution_site_id"])
    build_script = _locator(home, args["build_script"], step["execution_site_id"])
    executable = _locator(home, args["executable"], step["execution_site_id"])
    runner = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "entity-env-build", "scripts", "entity_run.py"))
    code, stdout, stderr = _run([
        sys.executable, runner, "build", requirements["path"],
        "--script", build_script["path"], "--quiet", "--json",
    ])
    if code != 0 or not os.path.isfile(executable["path"]):
        receipt = _receipt(home, step, flow_hash, "effect_observed", {}, [], stdout, stderr)
        return RunnerOutcome("anomaly", [receipt], message=stderr or stdout or "expected executable is missing", receipt=receipt)
    outputs = [requirements, executable]
    receipt = _receipt(home, step, flow_hash, "outputs_verified", {}, outputs, stdout, stderr)
    outputs.append(receipt)
    return RunnerOutcome("completed", outputs, ["build result and executable verified"],
                         {"build": "pass"}, receipt=receipt)


def _run_prepare(home, step, flow_hash):
    args = step["runner_args"]
    _require_keys(
        args, {"input_toml", "run_root", "manifest", "manifest_payload", "receipt"},
        {"input_toml", "run_root", "manifest", "manifest_payload", "receipt"},
        "run.prepare.v1 runner_args",
    )
    profile = load_site_profile(home, step["execution_site_id"])
    if profile["transport"]["kind"] != "local":
        raise RouterError("run.prepare.v1 remote runner is not staged")
    input_toml = _locator(home, args["input_toml"])["path"]
    run_root = _locator(home, args["run_root"], step["execution_site_id"])["path"]
    manifest = _locator(home, args["manifest"], step["execution_site_id"])["path"]
    if os.path.exists(run_root):
        raise RouterError("immutable run root already exists")
    os.makedirs(run_root)
    copied_input = os.path.join(run_root, "input.toml")
    shutil.copy2(input_toml, copied_input)
    atomic_write_json(manifest, args["manifest_payload"])
    outputs = [
        {"site_id": step["execution_site_id"], "path": copied_input},
        {"site_id": step["execution_site_id"], "path": manifest},
    ]
    receipt = _receipt(home, step, flow_hash, "outputs_verified", {}, outputs, "", "")
    outputs.append(receipt)
    return RunnerOutcome("completed", outputs, ["immutable input and run manifest verified"],
                         {"run": "prepared"}, receipt=receipt)


def _data_inspect(home, step, flow_hash):
    args = step["runner_args"]
    _require_keys(
        args, {"data_root", "inventory", "receipt"},
        {"data_root", "inventory", "receipt"}, "data.inspect.v1 runner_args",
    )
    profile = load_site_profile(home, step["execution_site_id"])
    if profile["transport"]["kind"] != "local":
        raise RouterError("data.inspect.v1 remote runner is not staged")
    data_root = _locator(home, args["data_root"], step["execution_site_id"])
    inventory = _locator(home, args["inventory"], step["execution_site_id"])
    if locator_within(inventory, data_root):
        raise RouterError("nt2 inventory must be outside the raw data root")
    roots = [canonical_locator(home, item) for item in step["write_roots"]]
    if not _covered(inventory, roots):
        raise RouterError("nt2 inventory is outside step write roots")
    script = os.path.realpath(os.path.join(
        os.path.dirname(__file__), "..", "..", "entity-nt2py", "scripts",
        "inspect_nt2_data.py",
    ))
    code, stdout, stderr = _run([
        sys.executable, script, data_root["path"], "--output", inventory["path"]
    ])
    if not os.path.isfile(inventory["path"]):
        receipt = _receipt(home, step, flow_hash, "effect_observed", {}, [], stdout, stderr)
        return RunnerOutcome("anomaly", [receipt], message=stderr or stdout, receipt=receipt)
    with open(inventory["path"], "r") as handle:
        payload = json.load(handle)
    readiness = "ready" if code == 0 and payload.get("status") == "ok" else "corrupt"
    outputs = [inventory]
    receipt = _receipt(
        home, step, flow_hash, "outputs_verified",
        {"inventory_status": payload.get("status", "error"),
         "nt2py_version": payload.get("nt2py_version")},
        outputs, stdout, stderr,
    )
    outputs.append(receipt)
    return RunnerOutcome(
        "completed", outputs, ["nt2 inventory parsed and content hash reprobed"],
        {"data": readiness}, message=payload.get("error", {}).get("message", ""),
        receipt=receipt,
    )


def preflight_step(home, step):
    runner = step.get("runner")
    if runner not in RUNNER_ACTIONS:
        raise RouterError("runner is not allowlisted: %s" % runner)
    if RUNNER_ACTIONS[runner] != step.get("action_type"):
        raise RouterError("runner does not match Action type")
    profile = load_site_profile(home, step["execution_site_id"])
    if profile["transport"]["kind"] != "local" and runner != "source.materialize.v1":
        raise RouterError("remote runner staging is not implemented for %s" % runner)
    args = step.get("runner_args", {})
    forbidden = set(args).intersection(FORBIDDEN_RUNNER_KEYS)
    if forbidden:
        raise RouterError("runner_args contains forbidden shell field: %s" % sorted(forbidden)[0])
    _validate_runner_args(home, step)


def run_step(home, step, flow_hash):
    preflight_step(home, step)
    runner = step.get("runner")
    step = dict(step)
    step["case_uid"] = step.get("case_uid", "")
    if runner == "run.launch.v1":
        return _run_launch(home, step, flow_hash)
    if runner == "run.monitor.v1":
        raise RouterError("run.monitor.v1 must be driven by flow watch")
    recovered = _recover_receipt(home, step, flow_hash)
    if recovered is not None:
        return recovered
    if runner == "source.materialize.v1":
        return _source_materialize(home, step, flow_hash)
    if runner == "build.plan.v1":
        return _build_plan(home, step, flow_hash)
    if runner == "build.compile.v1":
        return _build_compile(home, step, flow_hash)
    if runner == "run.prepare.v1":
        return _run_prepare(home, step, flow_hash)
    if runner == "data.inspect.v1":
        return _data_inspect(home, step, flow_hash)
    raise RouterError("runner has no implementation: %s" % runner)
