#!/usr/bin/env python3
"""Compact controller status and the content-addressed Site executor client."""

from __future__ import print_function

import json
import os
import shlex
import shutil
import tempfile

from entity_ledger_common import (
    LedgerError,
    absolute,
    atomic_write_json,
    now_utc,
    run_command,
    run_on_site,
    sha256_file,
)


class OperationError(LedgerError):
    pass


def _json_from_stdout(stdout, label):
    for line in reversed((stdout or "").splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise OperationError("%s returned invalid JSON" % label)


def _copy_verified(source, target, expected):
    if sha256_file(source) != expected:
        raise OperationError("payload changed since planning: %s" % source)
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    if os.path.isfile(target):
        if sha256_file(target) != expected:
            raise OperationError("staged payload exists with another identity: %s" % target)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".payload-", dir=parent)
    os.close(descriptor)
    try:
        shutil.copy2(source, temporary)
        if sha256_file(temporary) != expected:
            raise OperationError("copied payload failed identity verification")
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


class ExecutorClient(object):
    def __init__(self, profile):
        self.profile = profile
        self.transport = profile.get("transport", {}).get("kind")
        self.alias = profile.get("transport", {}).get("ssh_alias", "")
        self.script = os.path.join(os.path.dirname(__file__), "entity_ledger_executor.py")
        self.digest = sha256_file(self.script)
        staging = profile.get("roots", {}).get("staging_root")
        if not staging:
            raise OperationError("execution Site has no staging_root")
        self.remote_script = os.path.join(
            staging, ".entity-ledger-executor", self.digest, "entity_ledger_executor.py"
        )

    def _remote_hash(self, path):
        script = (
            "import hashlib,os,sys; p=sys.argv[1]; "
            "print(hashlib.sha256(open(p,'rb').read()).hexdigest() if os.path.isfile(p) else '')"
        )
        code, stdout, stderr = run_on_site(self.profile, ["python3", "-c", script, path])
        if code != 0:
            raise OperationError("cannot verify remote file: %s" % (stderr.strip() or stdout.strip()))
        return stdout.strip()

    def _scp(self, source, target):
        code, unused, stderr = run_command([
            "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--",
            source, "%s:%s" % (self.alias, shlex.quote(target)),
        ])
        if code != 0:
            raise OperationError("cannot stage remote file: %s" % stderr.strip())

    def ensure_executor(self):
        if self.transport == "local":
            _copy_verified(self.script, self.remote_script, self.digest)
            return self.remote_script
        parent = os.path.dirname(self.remote_script)
        code, unused, stderr = run_on_site(self.profile, ["mkdir", "-p", parent])
        if code != 0:
            raise OperationError("cannot prepare remote executor directory: %s" % stderr.strip())
        current = self._remote_hash(self.remote_script)
        if current:
            if current != self.digest:
                raise OperationError("content-addressed remote executor has wrong identity")
            return self.remote_script
        temporary = self.remote_script + ".tmp-%d" % os.getpid()
        self._scp(self.script, temporary)
        if self._remote_hash(temporary) != self.digest:
            raise OperationError("remote executor failed identity verification")
        code, unused, stderr = run_on_site(
            self.profile, ["python3", "-c", "import os,sys; os.replace(sys.argv[1],sys.argv[2])",
                           temporary, self.remote_script]
        )
        if code != 0:
            raise OperationError("cannot activate remote executor: %s" % stderr.strip())
        return self.remote_script

    def stage_payload(self, payload):
        source = absolute(payload["source"])
        target = payload["target"]
        expected = payload["sha256"]
        if self.transport == "local":
            _copy_verified(source, target, expected)
            return
        if sha256_file(source) != expected:
            raise OperationError("payload changed since planning: %s" % source)
        parent = os.path.dirname(target)
        code, unused, stderr = run_on_site(self.profile, ["mkdir", "-p", parent])
        if code != 0:
            raise OperationError("cannot prepare remote payload directory: %s" % stderr.strip())
        current = self._remote_hash(target)
        if current:
            if current != expected:
                raise OperationError("staged payload exists with another identity")
            return
        temporary = target + ".tmp-%d" % os.getpid()
        self._scp(source, temporary)
        if self._remote_hash(temporary) != expected:
            raise OperationError("remote payload failed identity verification")
        code, unused, stderr = run_on_site(
            self.profile, ["python3", "-c", "import os,sys; os.replace(sys.argv[1],sys.argv[2])",
                           temporary, target]
        )
        if code != 0:
            raise OperationError("cannot activate remote payload: %s" % stderr.strip())

    def _stage_envelope(self, envelope):
        request_path = os.path.join(
            os.path.dirname(envelope["receipt"]), envelope["step_id"] + "-request.json"
        )
        if self.transport == "local":
            atomic_write_json(request_path, envelope)
            return request_path
        descriptor, local_path = tempfile.mkstemp(prefix="entity-step-", suffix=".json")
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(envelope, handle, indent=2, sort_keys=True)
                handle.write("\n")
            parent = os.path.dirname(request_path)
            code, unused, stderr = run_on_site(self.profile, ["mkdir", "-p", parent])
            if code != 0:
                raise OperationError("cannot prepare remote request directory: %s" % stderr.strip())
            self._scp(local_path, request_path)
            return request_path
        finally:
            try:
                os.unlink(local_path)
            except OSError:
                pass

    def invoke(self, command, envelope):
        executor = self.ensure_executor()
        request_path = self._stage_envelope(envelope)
        code, stdout, stderr = run_on_site(
            self.profile, ["python3", executor, command, "--request", request_path]
        )
        result = _json_from_stdout(stdout, "Site executor")
        if code != 0 or result.get("status") not in {"completed", "verified"}:
            raise OperationError(
                result.get("message") or stderr.strip() or "Site executor failed"
            )
        return result


def _same_path(left, right):
    """Path comparison that also works for remote paths on ssh Sites."""
    try:
        return os.path.realpath(left) == os.path.realpath(right)
    except OSError:
        return left == right


def _slurm_reconcile_job(profile, scheduler, job_id, live_state, observed_at):
    """Classify divergence between the recorded job and scheduler reality.

    Returns (divergences, extra_remote_calls). Only Slurm facts are used;
    every classification is reproducible from the same scheduler answers.
    """
    divergences = []
    remote_calls = 0
    ssh = profile.get("transport", {}).get("kind") == "ssh"
    if live_state == "NOT_FOUND":
        try:
            code, stdout, stderr = run_on_site(
                profile, ["sacct", "-n", "-X", "-j", job_id, "--format=State"]
            )
        except OSError as exc:
            code, stdout, stderr = 127, "", str(exc)
        if ssh:
            remote_calls += 1
        terminal = ""
        if code == 0 and stdout.strip():
            terminal = stdout.strip().splitlines()[0].split()[0].upper()
        if terminal:
            divergences.append({
                "kind": "state_mismatch", "job_id": job_id,
                "recorded": "submitted", "observed": terminal,
                "detail": "recorded job reached terminal scheduler state %s "
                          "without the ledger observing it" % terminal,
                "observed_at": observed_at,
            })
        else:
            detail = "recorded job is absent from squeue"
            if code == 0:
                detail += " and sacct has no record of it"
            else:
                detail += "; sacct unavailable (%s)" % (
                    stderr.strip() or stdout.strip() or "exit %d" % code)
            divergences.append({
                "kind": "job_gone", "job_id": job_id, "confirmed": code == 0,
                "detail": detail, "observed_at": observed_at,
            })
    run_root = scheduler.get("run_root", "")
    submit_user = scheduler.get("submit_user", "")
    if run_root and submit_user:
        try:
            code, stdout, stderr = run_on_site(
                profile, ["squeue", "-h", "--user", submit_user, "--format", "%i|%Z"]
            )
        except OSError:
            code, stdout = 127, ""
        if ssh:
            remote_calls += 1
        if code == 0:
            for line in stdout.splitlines():
                fields = line.strip().split("|", 1)
                if len(fields) != 2 or not fields[0] or fields[0] == job_id:
                    continue
                if _same_path(fields[1], run_root):
                    divergences.append({
                        "kind": "untracked_job", "job_id": fields[0],
                        "run_root": fields[1],
                        "detail": "scheduler job %s runs in the Case run root "
                                  "but is not the recorded job %s"
                                  % (fields[0], job_id),
                        "observed_at": observed_at,
                    })
    return divergences, remote_calls


def status_for_project(store, project_root, live=False):
    case = store.resolve_project(project_root)
    current = case["current"]
    run_id = current.get("run_id", "")
    run_identity = None
    for item in case.get("identities", {}).get("run", {}).get("items", []):
        if item.get("id") == run_id or item.get("identity_id") == run_id:
            run_identity = item
            break
    result = {
        "schema_version": 1, "kind": "entity-ledger.status", "ok": True,
        "state_mutated": False, "remote_calls": 0,
        "project_root": case.get("project_root"), "case_uid": case["case_uid"],
        "current": current, "run": run_identity, "live": None, "divergences": [],
    }
    if not live or not run_identity:
        return result
    scheduler = run_identity.get("scheduler", {})
    if not scheduler:
        return result
    profile = store.get_site(run_identity["site_id"])
    kind = profile.get("scheduler", {}).get("kind")
    backend = LIVE_STATUS_BACKENDS.get(kind)
    if backend is None:
        raise OperationError(
            "live status currently supports scheduler kinds: %s (got '%s')"
            % (", ".join(sorted(LIVE_STATUS_BACKENDS)), kind)
        )
    return backend(profile, scheduler, result)


def _slurm_live_status(profile, scheduler, result):
    job_id = scheduler.get("job_id", "")
    if not job_id:
        return result
    ssh = profile.get("transport", {}).get("kind") == "ssh"
    code, stdout, stderr = run_on_site(
        profile, ["squeue", "-h", "-j", job_id, "-o", "%T"]
    )
    if ssh:
        result["remote_calls"] = 1
    if code != 0:
        detail = (stderr.strip() or stdout.strip() or "exit %d" % code)
        result["live"] = {
            "scheduler": "slurm", "job_id": job_id, "state": "UNKNOWN",
            "warning": "scheduler query failed (%s); showing cached controller "
                       "state" % detail,
            "observed_at": now_utc(),
        }
        return result
    state = stdout.strip().splitlines()[0] if stdout.strip() else "NOT_FOUND"
    observed_at = now_utc()
    result["live"] = {"scheduler": "slurm", "job_id": job_id,
                      "state": state, "observed_at": observed_at}
    divergences, extra_calls = _slurm_reconcile_job(
        profile, scheduler, job_id, state, observed_at
    )
    result["divergences"] = divergences
    result["remote_calls"] += extra_calls
    return result


LIVE_STATUS_BACKENDS = {"slurm": _slurm_live_status}


def _direct_foreign_scan(profile, run_root, recorded_pid, recorded_pgid):
    """Scan for entity run.sh processes working in the Case run root that are
    not the recorded launch.  Returns (foreign, unknown, detail): the scan
    degrades to unknown — never to a failure — when pgrep/lsof are missing
    or the probe itself fails (restricted permissions, container boundary).
    Members of the recorded process group (e.g. the run.sh timeout watcher,
    which inherits the launcher argv) are part of the recorded launch, not
    foreign work."""
    script = (
        "command -v pgrep >/dev/null 2>&1 && command -v lsof >/dev/null 2>&1 "
        "|| { echo UNSUPPORTED; exit 0; }; "
        "pids=$(pgrep -f 'run\\.sh entity-(ledger|router):' 2>/dev/null); rc=$?; "
        "if [ $rc -gt 1 ]; then echo SCAN_FAILED; exit 0; fi; "
        "for pid in $pids; do "
        "cwd=$(lsof -a -p \"$pid\" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p'); "
        "pgid=$(ps -o pgid= -p \"$pid\" 2>/dev/null | tr -d ' '); "
        "[ -n \"$cwd\" ] && echo \"$pid|$pgid|$cwd\"; done; true"
    )
    try:
        code, stdout, stderr = run_on_site(profile, ["bash", "-c", script])
    except OSError as exc:
        return [], True, "out-of-band process scan failed (%s)" % exc
    if code != 0:
        return [], True, "out-of-band process scan failed (%s)" % (
            stderr.strip() or stdout.strip() or "exit %d" % code)
    if "UNSUPPORTED" in stdout:
        return [], True, ("pgrep/lsof are unavailable on the Site; foreign "
                          "processes cannot be scanned")
    if "SCAN_FAILED" in stdout:
        return [], True, "out-of-band process scan was refused on the Site"
    foreign = []
    for line in stdout.splitlines():
        fields = line.strip().split("|", 2)
        if len(fields) != 3 or not fields[0].isdigit():
            continue
        pid = int(fields[0])
        if pid == recorded_pid or (fields[1] and fields[1] == str(recorded_pgid)):
            continue
        if _same_path(fields[2], run_root):
            foreign.append({"pid": pid, "run_root": fields[2]})
    return foreign, False, ""


def _direct_live_status(profile, scheduler, result):
    """Probe a scheduler-less run: the exit file decides terminal state,
    kill -0 on the recorded pid decides RUNNING, and a dead process without
    an exit file is reported as job_gone.  At most three bounded probes:
    exit file, process liveness, and the foreign-process scan."""
    pid = scheduler.get("pid")
    if not pid:
        return result
    exit_file = scheduler.get("exit_file", "")
    run_root = scheduler.get("run_root", "")
    ssh = profile.get("transport", {}).get("kind") == "ssh"
    remote_calls = 0
    exit_code = None
    if exit_file:
        try:
            code, stdout, unused = run_on_site(profile, ["cat", exit_file])
        except OSError:
            code, stdout = 127, ""
        if ssh:
            remote_calls += 1
        if code == 0 and stdout.strip().isdigit():
            exit_code = int(stdout.strip())
    divergences = []
    observed_at = now_utc()
    if exit_code is not None:
        result["live"] = {"scheduler": "direct", "pid": pid, "state": "EXITED",
                          "exit_code": exit_code, "observed_at": observed_at}
        divergences.append({
            "kind": "state_mismatch", "pid": pid,
            "recorded": "submitted", "observed": "EXITED",
            "detail": "recorded process exited with code %s without the "
                      "ledger observing it" % exit_code,
            "observed_at": observed_at,
        })
    else:
        try:
            code, unused_out, unused_err = run_on_site(profile, ["kill", "-0", str(pid)])
        except OSError:
            code = 127
        if ssh:
            remote_calls += 1
        observed_at = now_utc()
        if code == 0:
            result["live"] = {"scheduler": "direct", "pid": pid,
                              "state": "RUNNING", "observed_at": observed_at}
        else:
            result["live"] = {"scheduler": "direct", "pid": pid,
                              "state": "NOT_FOUND", "observed_at": observed_at}
            divergences.append({
                "kind": "job_gone", "pid": pid, "confirmed": True,
                "detail": "recorded process %s is gone and no exit file "
                          "was written" % pid,
                "observed_at": observed_at,
            })
    if run_root:
        foreign, unknown, detail = _direct_foreign_scan(
            profile, run_root, pid, scheduler.get("pgid") or pid)
        if ssh:
            remote_calls += 1
        if unknown:
            divergences.append({
                "kind": "untracked_job", "unknown": True,
                "detail": detail, "observed_at": observed_at,
            })
        for item in foreign:
            divergences.append({
                "kind": "untracked_job", "pid": item["pid"],
                "run_root": item["run_root"],
                "detail": "process %s runs in the Case run root but is not "
                          "the recorded process %s" % (item["pid"], pid),
                "observed_at": observed_at,
            })
    result["divergences"] = divergences
    result["remote_calls"] += remote_calls
    return result


LIVE_STATUS_BACKENDS["none"] = _direct_live_status
