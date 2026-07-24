#!/usr/bin/env python3
"""Primitive record commands: show, record build, record data, and the run
chain (render-run, record run-prepare/run-launch/run-exit).

These commands book Case facts directly (identities + current + an audit
event) without the Operation Plan protocol.  Every write gate is embedded in
the primitive itself: ``record build`` requires a verified env-build
checkpoint and probes the executable on its Site before anything is written;
``record data`` re-runs the site-side inventory and only then projects the
data identity; ``record run-prepare`` requires the pgen simulation
confirmation before any state is written; ``record run-launch`` validates
the submission with the scheduler (Slurm preflight), relies on the executor
receipt for exactly-once submission and probes the scheduler before
adopting an out-of-band job; ``record run-exit`` probes the terminal state
and only then books it.  This module is standard-library only and Python 3.6
compatible.
"""

from __future__ import print_function

import argparse
import contextlib
import io
import json
import os
import re

from entity_ledger_common import (
    absolute,
    now_utc,
    run_on_site,
    sha256_file,
)
from entity_ledger_executor import ExecutorError, RENDER_BACKENDS
from entity_ledger_facts import (
    PlanError,
    _content_sha256,
    _current_build_executable,
    _resolve_case,
    _resolve_input,
    _run_backend,
    _simulation_confirmation,
    _site_policy,
    _source_identity,
    derive_run_paths,
    require_verified_checkpoint,
)
from entity_ledger_operation import ExecutorClient, OperationError, _same_path
from entity_ledger_remote import archive_manifest, make_manifest, snapshot_archive
from entity_ledger_store import StoreError, canonical_hash, canonical_json


def show_case(store, project_root):
    """Read-only Case fact detail: the full controller-local projection."""
    case = store.resolve_project(project_root)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.show",
        "ok": True,
        "state_mutated": False,
        "case_uid": case["case_uid"],
        "case_id": case["case_id"],
        "project_root": case["project_root"],
        "source": case["source"],
        "current": case["current"],
        "identities": case["identities"],
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
    }


def _require_case(store, project_root):
    try:
        return store.resolve_project(project_root)
    except StoreError:
        raise PlanError(
            "no Case covers the project; create it first",
            "needs_decision",
            [{"field": "case",
              "question": "run entityctl record run-prepare to create the Case"}],
        )


def _load_checkpoint(path):
    path = absolute(path)
    if not os.path.isfile(path):
        raise PlanError("build checkpoint does not exist: %s" % path)
    try:
        with open(path, "r") as handle:
            checkpoint = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise PlanError("cannot read build checkpoint: %s" % exc)
    if not isinstance(checkpoint, dict):
        raise PlanError("build checkpoint must contain a JSON object")
    require_verified_checkpoint(checkpoint)
    return path


def _probe_executable(profile, executable):
    """Evidence gate: the executable must exist and be executable on its
    Site.  Returns the content fingerprint; raises before any state write."""
    if not os.path.isabs(executable):
        raise PlanError("executable must be an absolute path on the execution Site")
    executable = os.path.normpath(executable)
    if profile.get("transport", {}).get("kind") == "local":
        if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            raise PlanError(
                "executable does not exist or is not executable on Site %s: %s"
                % (profile["site_id"], executable))
    else:
        code, stdout, stderr = run_on_site(profile, ["test", "-x", executable])
        if code != 0:
            raise PlanError(
                "executable does not exist or is not executable on Site %s: %s"
                % (profile["site_id"], stderr.strip() or stdout.strip() or executable))
    return executable, _content_sha256(profile, executable)


def record_intent(store, project_root, text, actor):
    """Record the current research intent of a Case.  The intent is the only
    stored pointer: it cannot be derived from artifacts, so it is written
    explicitly and shown on the dashboard.  Recording a new intent replaces
    the previous one (history stays in the audit events)."""
    if not text or not text.strip():
        raise PlanError("intent text must be non-empty")
    case = _require_case(store, project_root)
    current = dict(case["current"])
    current["intent"] = {"text": text.strip(), "recorded_at": now_utc()}
    with store.transaction() as connection:
        connection.execute(
            "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
            (canonical_json(current), now_utc(), case["case_uid"]),
        )
        store.record_event(
            case["case_uid"], None, "record.intent",
            {"text": text.strip()}, actor, connection)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.intent",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "intent": current["intent"],
    }


def record_build(store, project_root, site_id, checkpoint, executable, actor):
    """Register a verified build identity.  The build_id is content-addressed
    from (case, checkpoint, executable, site), so recording the same build
    twice is a successful no-op."""
    case = _require_case(store, project_root)
    profile = store.get_site(site_id)
    checkpoint_path = _load_checkpoint(checkpoint)
    executable, executable_sha256 = _probe_executable(profile, executable)
    checkpoint_sha256 = sha256_file(checkpoint_path)
    seed = {"case_uid": case["case_uid"], "checkpoint_sha256": checkpoint_sha256,
            "executable": executable, "executable_sha256": executable_sha256,
            "site_id": site_id}
    digest = canonical_hash(seed).split(":", 1)[1][:16]
    build_id = "build-" + digest
    identity = {
        "id": build_id, "kind": "build", "site_id": site_id,
        "root": {"site_id": site_id, "path": os.path.dirname(executable)},
        "parents": {"source_id": case.get("current", {}).get("source_id", "")},
        "checkpoint": checkpoint_path,
        "checkpoint_sha256": checkpoint_sha256,
        "executable_sha256": executable_sha256,
        "status": "verified",
        "outputs": [{"kind": "file",
                     "locator": {"site_id": site_id, "path": executable}}],
    }
    current = dict(case["current"])
    readiness = dict(current.get("readiness", {}))
    current["build_id"] = build_id
    readiness["build"] = "verified"
    current["readiness"] = readiness
    with store.transaction() as connection:
        store.add_identity(
            case["case_uid"], "build", build_id, identity, True, connection)
        connection.execute(
            "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
            (canonical_json(current), now_utc(), case["case_uid"]),
        )
        store.record_event(
            case["case_uid"], None, "record.build",
            {"build_id": build_id, "site_id": site_id, "executable": executable},
            actor, connection)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.build",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "build_id": build_id,
        "site_id": site_id,
        "evidence": {
            "executable": executable,
            "executable_sha256": executable_sha256,
            "checkpoint": checkpoint_path,
            "checkpoint_sha256": checkpoint_sha256,
        },
    }


def _run_identity(case, run_id):
    for item in case.get("identities", {}).get("run", {}).get("items", []):
        if item.get("id") == run_id or item.get("identity_id") == run_id:
            return item
    return None


def _inventory_envelope(case_uid, run_id, site_id, staging_root, run_root):
    digest = canonical_hash({"case_uid": case_uid, "run_id": run_id})
    digest = digest.split(":", 1)[1][:16]
    staging = os.path.join(staging_root, case_uid, "op-" + digest)
    manifest = os.path.join(run_root, "data-inventory.json")
    envelope = {
        "schema_version": 1,
        "operation_id": "op-" + digest,
        "plan_hash": canonical_hash({"kind": "entity-ledger.record.data",
                                     "case_uid": case_uid, "run_id": run_id}),
        "step_index": 0,
        "step_id": "record-data",
        "kind": "data.inventory.v1",
        "site_id": site_id,
        "receipt": os.path.join(staging, "receipts", "data-inventory.json"),
        "allowed_roots": [staging, run_root],
        "request": {"run_root": run_root, "manifest": manifest},
    }
    return "data-" + digest, manifest, envelope


def record_data(store, project_root, run_id, actor):
    """Inventory a run's outputs and book the data identity.  The data_id is
    content-addressed from (case, run), so re-inventorying the same run is
    idempotent and refreshes the recorded file count."""
    case = _require_case(store, project_root)
    current = case.get("current", {})
    run_id = run_id or current.get("run_id", "")
    if not run_id:
        raise PlanError(
            "Case has no current run",
            "needs_decision",
            [{"field": "run", "question": "select the run to inventory"}],
        )
    run_identity = _run_identity(case, run_id)
    if run_identity is None:
        raise PlanError(
            "unknown run identity: %s" % run_id,
            "needs_decision",
            [{"field": "run", "question": "select a known run id"}],
        )
    root = run_identity.get("root", {})
    site_id = root.get("site_id") or run_identity.get("site_id", "")
    run_root = root.get("path", "") or run_identity.get("scheduler", {}).get("run_root", "")
    if not site_id or not run_root:
        raise PlanError("run identity has no usable root locator")
    profile = store.get_site(site_id)
    staging_root = profile.get("roots", {}).get("staging_root")
    if not staging_root:
        raise PlanError("execution Site is missing staging_root")
    data_id, manifest, envelope = _inventory_envelope(
        case["case_uid"], run_id, site_id, staging_root, run_root)
    client = ExecutorClient(profile)
    client.invoke("execute", envelope)
    verified = client.invoke("verify", envelope)
    files = int(verified.get("effect", {}).get("files", 0))
    if profile.get("transport", {}).get("kind") == "local":
        if not os.path.isfile(manifest):
            raise PlanError("data inventory manifest was not written: %s" % manifest)
        with open(manifest, "r") as handle:
            files = len(json.load(handle).get("files", []))
    refreshed = any(
        item.get("id") == data_id or item.get("identity_id") == data_id
        for item in case.get("identities", {}).get("data", {}).get("items", []))
    identity = {
        "id": data_id, "kind": "data", "site_id": site_id,
        "root": {"site_id": site_id, "path": run_root},
        "parents": {"run_id": run_id},
        "manifest": manifest,
        "status": "inventoried",
        "files": files,
    }
    new_current = dict(current)
    readiness = dict(new_current.get("readiness", {}))
    new_current["data_id"] = data_id
    readiness["data"] = "inventoried"
    new_current["readiness"] = readiness
    with store.transaction() as connection:
        store.add_identity(
            case["case_uid"], "data", data_id, identity, True, connection)
        connection.execute(
            "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
            (canonical_json(new_current), now_utc(), case["case_uid"]),
        )
        store.record_event(
            case["case_uid"], None, "record.data",
            {"data_id": data_id, "run_id": run_id, "files": files,
             "refreshed": refreshed},
            actor, connection)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.data",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "data_id": data_id,
        "run_id": run_id,
        "files": files,
        "manifest": manifest,
        "refreshed": refreshed,
    }


def _compute_request(gpus, walltime, precision):
    """Validate the CLI compute overrides before site policy fills the rest."""
    if not isinstance(gpus, int) or isinstance(gpus, bool) or gpus < 1:
        raise PlanError("gpus must be a positive integer")
    if not re.match(r"^[0-9]+(?:-[0-9]{2})?:[0-9]{2}:[0-9]{2}$", walltime or ""):
        raise PlanError("walltime must use HH:MM:SS or D-HH:MM:SS")
    if precision not in {"single", "double"}:
        raise PlanError("precision must be single or double")
    return {"gpus": gpus, "walltime": walltime, "precision": precision}


def _derive_run(store, project_root, input_value, site_id, compute, executable):
    """Content-addressed run derivation shared by render-run and record
    run-prepare: identical inputs always yield the same run_id, paths, and
    synthetic executor envelope identity."""
    project_root = absolute(project_root)
    if not os.path.isdir(project_root):
        raise PlanError("project root does not exist: %s" % project_root)
    case, create_case = _resolve_case(store, project_root, {})
    profile = store.get_site(site_id)
    unused_kind, backend = _run_backend(profile)
    scheduler_kind = backend["scheduler"]
    roots = profile.get("roots", {})
    for key in ["build_root", "run_root", "staging_root"]:
        if not roots.get(key):
            raise PlanError("execution Site is missing %s" % key)
    input_path = _resolve_input(project_root, input_value)
    authority = case["source"]["authority"]
    source_profile = store.get_site(authority["site_id"])
    if source_profile.get("transport", {}).get("kind") != "local":
        raise PlanError(
            "run recording currently requires a controller-local source authority",
            "needs_decision",
            [{"field": "source",
              "question": "materialize the exact source on a local authority"}],
        )
    source_fingerprint, unused_ignored = _source_identity(authority["path"])
    source_id = "source-" + source_fingerprint["snapshot_id"][:16]
    executable, build_id = _current_build_executable(case, profile, executable)
    normalized = _site_policy(profile, compute)
    input_sha256 = sha256_file(input_path)
    paths = derive_run_paths(
        case["case_uid"], site_id, roots, scheduler_kind, source_id,
        input_sha256, executable, build_id, normalized)
    plan_hash = canonical_hash({"kind": "entity-ledger.record.run",
                                "seed": paths["seed"]})
    return {
        "case": case, "create_case": create_case, "profile": profile,
        "scheduler_kind": scheduler_kind, "input_path": input_path,
        "input_sha256": input_sha256, "source_id": source_id,
        "source_fingerprint": source_fingerprint,
        "executable": executable, "build_id": build_id,
        "compute": normalized, "paths": paths, "plan_hash": plan_hash,
    }


def _run_spec(derived):
    return {"executable": derived["executable"], "compute": derived["compute"],
            "input_name": "input.toml"}


def render_run(store, project_root, input_value, site_id, gpus, walltime,
               precision, executable):
    """Pure preview: render the submit script and the derived run paths
    without touching controller or Site state (no confirmation gate)."""
    compute = _compute_request(gpus, walltime, precision)
    derived = _derive_run(
        store, project_root, input_value, site_id, compute, executable)
    try:
        script = RENDER_BACKENDS[derived["scheduler_kind"]](_run_spec(derived))
    except ExecutorError as exc:
        raise PlanError(str(exc))
    paths = derived["paths"]
    return {
        "schema_version": 1,
        "kind": "entity-ledger.render-run",
        "ok": True,
        "state_mutated": False,
        "case_uid": derived["case"]["case_uid"],
        "run_id": paths["run_id"],
        "site_id": site_id,
        "scheduler": derived["scheduler_kind"],
        "run_root": paths["run_root"],
        "submit_script": paths["submit_script"],
        "script": script,
        "compute": derived["compute"],
        "executable": derived["executable"],
        "build_id": derived["build_id"],
        "input": derived["input_path"],
    }


def _source_identity_payload(case, source_id, fingerprint):
    return {
        "id": source_id, "kind": "source",
        "site_id": case["source"]["authority"]["site_id"],
        "root": case["source"]["authority"],
        "fingerprint": fingerprint,
    }


def _check_receipt_identity(envelope, verified):
    receipt = verified.get("receipt", {})
    for key in ["operation_id", "plan_hash", "step_index", "step_id", "kind"]:
        if receipt.get(key) != envelope.get(key):
            raise OperationError("verified receipt identity differs from request")


def _book_run(store, case, identity, readiness_state, current_updates,
              event_type, event_payload, actor, extra_identities=None,
              create_case=False):
    """Atomically book a run identity, the Case current projection, and the
    audit event — the record-path equivalent of _identity_projection.  With
    ``create_case`` the Case row itself (plus its case.created event) joins
    the same transaction, so a failed executor call leaves the store
    completely untouched."""
    current = dict(case["current"])
    current.update(current_updates)
    current["run_id"] = identity["id"]
    current["active_run"] = identity["root"]
    readiness = dict(current.get("readiness", {}))
    readiness["run"] = readiness_state
    current["readiness"] = readiness
    with store.transaction() as connection:
        if create_case:
            store.upsert_case(
                case["case_uid"], case["case_id"], case["project_root"],
                case["source"], case["current"], {}, connection=connection)
            store._event(connection, case["case_uid"], None, "case.created",
                         {}, actor)
        for dimension, identity_id, payload in extra_identities or []:
            store.add_identity(
                case["case_uid"], dimension, identity_id, payload, True, connection)
        store.add_identity(
            case["case_uid"], "run", identity["id"], identity, True, connection)
        connection.execute(
            "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
            (canonical_json(current), now_utc(), case["case_uid"]),
        )
        store.record_event(
            case["case_uid"], None, event_type, event_payload, actor, connection)


def record_run_prepare(store, project_root, input_value, site_id, gpus,
                       walltime, precision, executable, actor):
    """Prepare a run root on its Site and book the run identity as prepared.

    Gates (all before any state write): the pgen simulation confirmation must
    match the current input bytes, and an existing run identity that already
    advanced past ``prepared`` is never rewound.  The Case is created on first
    use in the same transaction as the run booking — after the executor
    succeeded — and the executor receipt makes re-runs idempotent."""
    compute = _compute_request(gpus, walltime, precision)
    derived = _derive_run(
        store, project_root, input_value, site_id, compute, executable)
    confirmation = _simulation_confirmation(derived["input_path"])
    case = derived["case"]
    paths = derived["paths"]
    existing = _run_identity(case, paths["run_id"])
    if existing is not None and existing.get("status", "") != "prepared":
        raise PlanError(
            "run %s is already %s; re-preparing it would rewind an advanced "
            "run — change the input or compute to derive a new run"
            % (paths["run_id"], existing.get("status") or "unknown"),
            "needs_decision",
            [{"field": "run",
              "question": "change the parameters so a new run is derived"}],
        )
    source_identity = _source_identity_payload(
        case, derived["source_id"], derived["source_fingerprint"])
    created_case = derived["create_case"]
    client = ExecutorClient(derived["profile"])
    client.stage_payload({"source": derived["input_path"],
                          "target": paths["staged_input"],
                          "sha256": derived["input_sha256"]})
    manifest_payload = {
        "schema_version": 3, "case_uid": case["case_uid"],
        "run_id": paths["run_id"], "source_id": derived["source_id"],
        "build_id": derived["build_id"], "site_id": site_id,
        "input_sha256": derived["input_sha256"],
        "executable": derived["executable"], "compute": derived["compute"],
        "created_by_operation": paths["operation_id"],
    }
    envelope = {
        "schema_version": 1,
        "operation_id": paths["operation_id"],
        "plan_hash": derived["plan_hash"],
        "step_index": 1,
        "step_id": "prepare",
        "kind": "run.prepare.v2",
        "site_id": site_id,
        "receipt": paths["prepare_receipt"],
        "allowed_roots": [paths["staging_root"], paths["run_root"]],
        "request": {
            "scheduler": derived["scheduler_kind"],
            "run_root": paths["run_root"],
            "manifest": paths["manifest"],
            "manifest_payload": manifest_payload,
            "submit_script": paths["submit_script"],
            "run_spec": _run_spec(derived),
            "staging_root": paths["staging_root"],
            "staged_input": paths["staged_input"],
        },
    }
    client.invoke("execute", envelope)
    verified = client.invoke("verify", envelope)
    _check_receipt_identity(envelope, verified)
    identity = {
        "id": paths["run_id"], "kind": "run", "site_id": site_id,
        "root": {"site_id": site_id, "path": paths["run_root"]},
        "parents": {"source_id": derived["source_id"],
                    "build_id": derived["build_id"]},
        "input_sha256": derived["input_sha256"],
        "compute": derived["compute"],
        "executable": derived["executable"],
        "operation_id": paths["operation_id"],
        "plan_hash": derived["plan_hash"],
        "staging_root": paths["staging_root"],
        "status": "prepared",
    }
    _book_run(
        store, case, identity, "ready",
        {"source_id": derived["source_id"]},
        "record.run-prepare",
        {"run_id": paths["run_id"], "site_id": site_id,
         "run_root": paths["run_root"], "created_case": created_case},
        actor,
        extra_identities=[("source", source_identity["id"], source_identity)],
        create_case=created_case)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.run-prepare",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "run_id": paths["run_id"],
        "site_id": site_id,
        "run_root": paths["run_root"],
        "created_case": created_case,
        "confirmation": {"confirmed_by": confirmation.get("confirmed_by", ""),
                         "confirmed_at": confirmation.get("confirmed_at", "")},
    }


def _site_process_cwd(profile, pid):
    """Working directory of a live process via lsof (Linux Sites and macOS
    controllers alike, no /proc dependency); None when undetermined."""
    try:
        code, stdout, unused = run_on_site(
            profile, ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    except OSError:
        return None
    if code != 0:
        return None
    for line in stdout.splitlines():
        if line.startswith("n") and len(line) > 1:
            return line[1:]
    return None


def _probe_adopt_slurm(profile, job_id, run_root):
    """Verify an out-of-band Slurm job before adoption: it must exist (in
    squeue, or in sacct once it left the queue) and work in the run root."""
    try:
        code, stdout, unused = run_on_site(
            profile, ["squeue", "-h", "-j", job_id, "-o", "%i|%T|%Z"])
    except OSError as exc:
        raise PlanError("cannot query Slurm for job %s: %s" % (job_id, exc))
    if code == 0:
        for line in stdout.splitlines():
            fields = line.strip().split("|")
            if (len(fields) == 3 and fields[0] == job_id
                    and _same_path(fields[2], run_root)):
                return {"scheduler": "slurm", "job_id": job_id,
                        "run_root": run_root, "state": fields[1].upper()}
    try:
        code, stdout, stderr = run_on_site(
            profile, ["sacct", "-n", "-X", "-j", job_id,
                      "--format=JobID,State,WorkDir"])
    except OSError as exc:
        raise PlanError("cannot query Slurm accounting for job %s: %s"
                        % (job_id, exc))
    if code != 0:
        raise PlanError(
            "cannot verify job %s on Site %s: %s"
            % (job_id, profile["site_id"], stderr.strip() or "sacct failed"))
    for line in stdout.splitlines():
        fields = [item.strip() for item in line.split("|")]
        if (len(fields) >= 3 and fields[0] == job_id
                and _same_path(fields[2], run_root)):
            return {"scheduler": "slurm", "job_id": job_id,
                    "run_root": run_root,
                    "state": fields[1].split()[0].upper() if fields[1] else ""}
    raise PlanError(
        "job %s was not found working in the run root %s on Site %s; "
        "refusing to adopt" % (job_id, run_root, profile["site_id"]))


def _probe_adopt_direct(profile, pid, run_root):
    """Verify an out-of-band scheduler-less process before adoption: it must
    be alive and its working directory must be the run root."""
    pid_text = str(pid)
    if not pid_text.isdigit():
        raise PlanError("--adopt-pid must be a numeric process id")
    try:
        code, unused, unused_err = run_on_site(profile, ["kill", "-0", pid_text])
    except OSError as exc:
        raise PlanError("cannot probe process %s: %s" % (pid_text, exc))
    if code != 0:
        raise PlanError("process %s is not alive on Site %s; refusing to adopt"
                        % (pid_text, profile["site_id"]))
    cwd = _site_process_cwd(profile, pid_text)
    if cwd is None:
        raise PlanError("cannot determine the working directory of process %s; "
                        "refusing to adopt" % pid_text)
    if not _same_path(cwd, run_root):
        raise PlanError(
            "process %s works in %s, not the run root %s; refusing to adopt"
            % (pid_text, cwd, run_root))
    return {"scheduler": "direct", "pid": int(pid_text), "pgid": int(pid_text),
            "run_root": run_root,
            "log": os.path.join(run_root, "run.log"),
            "exit_file": os.path.join(run_root, ".entity-exit-code")}


def record_run_launch(store, project_root, run_id, adopt_job, adopt_pid, actor):
    """Submit a prepared run exactly once (executor receipt) or adopt an
    out-of-band job after probing it, then book the run as submitted.  On
    Slurm Sites the scheduler first validates the rendered submission
    (run.preflight.v1 / sbatch --test-only); a rejection fails with the
    executor's remediation hint before any state is written.  Scheduler-less
    Sites have no scheduler to consult and skip the preflight."""
    case = _require_case(store, project_root)
    run_id = run_id or case.get("current", {}).get("run_id", "")
    if not run_id:
        raise PlanError(
            "Case has no current run",
            "needs_decision",
            [{"field": "run", "question": "select the run to launch"}],
        )
    identity = _run_identity(case, run_id)
    if identity is None:
        raise PlanError(
            "unknown run identity: %s" % run_id,
            "needs_decision",
            [{"field": "run", "question": "select a known run id"}],
        )
    status = identity.get("status", "")
    if status not in {"prepared", "submitted"}:
        raise PlanError("run %s is %s; only a prepared run can be launched"
                        % (run_id, status or "unknown"))
    root = identity.get("root", {})
    site_id = root.get("site_id") or identity.get("site_id", "")
    run_root = root.get("path", "")
    if not site_id or not run_root:
        raise PlanError("run identity has no usable root locator")
    profile = store.get_site(site_id)
    unused_kind, backend = _run_backend(profile)
    scheduler_kind = backend["scheduler"]
    adopted = bool(adopt_job or adopt_pid)
    if adopted:
        if adopt_job:
            if scheduler_kind != "slurm":
                raise PlanError("--adopt-job requires a Slurm execution Site")
            effect = _probe_adopt_slurm(profile, adopt_job, run_root)
        else:
            if scheduler_kind != "direct":
                raise PlanError("--adopt-pid requires a scheduler-less Site")
            effect = _probe_adopt_direct(profile, adopt_pid, run_root)
        effect["adopted"] = True
    else:
        recorded_scheduler = identity.get("scheduler", {})
        if recorded_scheduler.get("job_id") or recorded_scheduler.get("pid"):
            # The run already carries a scheduler identity — submitted by an
            # earlier launch or adopted out-of-band (adoption leaves no
            # executor receipt to make a re-run idempotent).  Re-running the
            # launch without adopt flags must claim the recorded effect
            # instead of submitting a second job.
            return {
                "schema_version": 1,
                "kind": "entity-ledger.record.run-launch",
                "ok": True,
                "state_mutated": False,
                "case_uid": case["case_uid"],
                "run_id": run_id,
                "site_id": site_id,
                "status": identity.get("status", ""),
                "adopted": bool(recorded_scheduler.get("adopted")),
                "scheduler": recorded_scheduler,
                "detail": "run already has a recorded scheduler identity; "
                          "no new submission",
            }
        for key in ["operation_id", "plan_hash", "staging_root"]:
            if not identity.get(key):
                raise PlanError(
                    "run identity lacks the launch derivation; it was not "
                    "prepared by record run-prepare — prepare it again")
        submit_script = os.path.join(
            run_root, "run.sbatch" if scheduler_kind == "slurm" else "run.sh")
        client = ExecutorClient(profile)
        if scheduler_kind == "slurm":
            # Gate: let the scheduler validate the rendered submission
            # (sbatch --test-only) before anything is booked, through the
            # same synthetic envelope discipline as prepare/launch.  A
            # rejection (invalid qos/partition, ...) raises with the
            # executor's remediation hint and leaves the store untouched.
            executable = identity.get("executable", "")
            if not executable:
                raise PlanError(
                    "run identity lacks the executable record; it was not "
                    "prepared by record run-prepare — prepare it again")
            preflight = {
                "schema_version": 1,
                "operation_id": identity["operation_id"],
                "plan_hash": identity["plan_hash"],
                "step_index": 0,
                "step_id": "preflight",
                "kind": "run.preflight.v1",
                "site_id": site_id,
                "receipt": os.path.join(
                    identity["staging_root"], "receipts", "run-preflight.json"),
                "allowed_roots": [identity["staging_root"]],
                "request": {
                    "scheduler": scheduler_kind,
                    "run_spec": {"executable": executable,
                                 "compute": identity.get("compute", {}),
                                 "input_name": "input.toml"},
                    "job_name": "entity-%s" % identity["operation_id"],
                    "staging_root": identity["staging_root"],
                },
            }
            try:
                client.invoke("execute", preflight)
                verified = client.invoke("verify", preflight)
                _check_receipt_identity(preflight, verified)
            except OperationError as exc:
                raise PlanError("run preflight failed on Site %s: %s"
                                % (site_id, exc))
        envelope = {
            "schema_version": 1,
            "operation_id": identity["operation_id"],
            "plan_hash": identity["plan_hash"],
            "step_index": 2,
            "step_id": "launch",
            "kind": "run.launch.v2",
            "site_id": site_id,
            "receipt": os.path.join(
                identity["staging_root"], "receipts", "run-launch.json"),
            "allowed_roots": [identity["staging_root"], run_root],
            "request": {
                "scheduler": scheduler_kind,
                "run_root": run_root,
                "submit_script": submit_script,
                "job_name": "entity-%s" % identity["operation_id"],
                "submit_user": identity.get("compute", {}).get("submit_user", ""),
            },
        }
        client.invoke("execute", envelope)
        verified = client.invoke("verify", envelope)
        _check_receipt_identity(envelope, verified)
        effect = verified.get("effect", {})
        if not (effect.get("job_id") or effect.get("pid")):
            raise OperationError(
                "launch verification returned no scheduler identity")
    identity = dict(identity)
    identity["status"] = "submitted"
    identity["scheduler"] = effect
    _book_run(
        store, case, identity, "submitted", {},
        "record.run-launch",
        {"run_id": run_id, "site_id": site_id, "adopted": adopted,
         "scheduler": effect},
        actor)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.run-launch",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "run_id": run_id,
        "site_id": site_id,
        "status": "submitted",
        "adopted": adopted,
        "scheduler": effect,
    }


def _direct_exit_probe(profile, scheduler):
    """Terminal probe for a scheduler-less run: the exit file decides the
    terminal state, kill -0 on the recorded pid decides still-running, and a
    dead process without an exit file is reported gone.  An exit file that
    exists but holds no numeric code (a partial write) is reported unknown —
    there is evidence, just not enough of it.  Returns (state, exit_code)
    with state in {terminal, running, gone, unknown}."""
    exit_file = scheduler.get("exit_file", "")
    pid = scheduler.get("pid")
    corrupt_exit = False
    if exit_file:
        try:
            code, unused, unused_err = run_on_site(
                profile, ["test", "-f", exit_file])
        except OSError as exc:
            raise PlanError("cannot probe run exit file: %s" % exc)
        if code == 0:
            code, stdout, stderr = run_on_site(profile, ["cat", exit_file])
            if code != 0:
                raise PlanError("cannot read run exit file %s: %s"
                                % (exit_file, stderr.strip() or "read failed"))
            text = stdout.strip()
            if text.isdigit():
                return "terminal", int(text)
            corrupt_exit = True
    if pid:
        try:
            code, unused, unused_err = run_on_site(
                profile, ["kill", "-0", str(pid)])
        except OSError as exc:
            raise PlanError("cannot probe run process: %s" % exc)
        if code == 0:
            return "running", None
    if corrupt_exit:
        return "unknown", None
    return "gone", None


def _slurm_exit_probe(profile, job_id):
    """Terminal probe for a Slurm run: a live squeue row means still-running;
    otherwise sacct decides the terminal state.  Returns
    (state, scheduler_state, exit_code)."""
    try:
        code, stdout, unused = run_on_site(
            profile, ["squeue", "-h", "-j", job_id, "-o", "%T"])
    except OSError as exc:
        raise PlanError("cannot query Slurm for job %s: %s" % (job_id, exc))
    if code == 0 and stdout.strip():
        return "running", stdout.strip().splitlines()[0].upper(), None
    try:
        code, stdout, stderr = run_on_site(
            profile, ["sacct", "-n", "-X", "-j", job_id,
                      "--format=State,ExitCode"])
    except OSError as exc:
        raise PlanError("cannot query Slurm accounting for job %s: %s"
                        % (job_id, exc))
    if code != 0 or not stdout.strip():
        raise PlanError(
            "cannot determine the terminal state of job %s on Site %s: %s"
            % (job_id, profile["site_id"],
               stderr.strip() or "sacct has no record"))
    fields = [item.strip() for item in
              stdout.strip().splitlines()[0].split("|")]
    scheduler_state = fields[0].split()[0].upper() if fields and fields[0] else ""
    if not scheduler_state:
        raise PlanError("cannot determine the terminal state of job %s on "
                        "Site %s" % (job_id, profile["site_id"]))
    exit_code = None
    if len(fields) > 1:
        try:
            exit_code = int(fields[1].split(":", 1)[0])
        except ValueError:
            exit_code = None
    if scheduler_state == "COMPLETED":
        return "terminal", scheduler_state, 0 if exit_code is None else exit_code
    return "terminal", scheduler_state, exit_code


def record_run_exit(store, project_root, run_id, actor):
    """Probe a submitted run's terminal state and book it.  A still-running
    run is reported without mutating state; an unreachable Site fails with
    exit 2 and no write."""
    case = _require_case(store, project_root)
    run_id = run_id or case.get("current", {}).get("run_id", "")
    if not run_id:
        raise PlanError(
            "Case has no current run",
            "needs_decision",
            [{"field": "run", "question": "select the run to probe"}],
        )
    identity = _run_identity(case, run_id)
    if identity is None:
        raise PlanError(
            "unknown run identity: %s" % run_id,
            "needs_decision",
            [{"field": "run", "question": "select a known run id"}],
        )
    status = identity.get("status", "")
    if status in {"completed", "failed"}:
        return {
            "schema_version": 1,
            "kind": "entity-ledger.record.run-exit",
            "ok": True,
            "state_mutated": False,
            "case_uid": case["case_uid"],
            "run_id": run_id,
            "state": status,
            "exit_code": identity.get("exit_code"),
        }
    if status != "submitted":
        raise PlanError("run %s is %s; only a submitted run has a terminal "
                        "state to record" % (run_id, status or "unknown"))
    scheduler = identity.get("scheduler", {})
    site_id = identity.get("root", {}).get("site_id") or identity.get("site_id", "")
    profile = store.get_site(site_id)
    kind = scheduler.get("scheduler", "")
    if kind == "direct":
        state, exit_code = _direct_exit_probe(profile, scheduler)
        scheduler_state = ""
    elif kind == "slurm":
        job_id = scheduler.get("job_id", "")
        if not job_id:
            raise PlanError("run identity has no Slurm job id to probe")
        state, scheduler_state, exit_code = _slurm_exit_probe(profile, job_id)
    else:
        raise PlanError("run identity has an unsupported scheduler record: %s"
                        % (kind or "none"))
    if state == "running":
        return {
            "schema_version": 1,
            "kind": "entity-ledger.record.run-exit",
            "ok": True,
            "state_mutated": False,
            "case_uid": case["case_uid"],
            "run_id": run_id,
            "state": "running",
            "scheduler_state": scheduler_state,
        }
    if state == "gone":
        return {
            "schema_version": 1,
            "kind": "entity-ledger.record.run-exit",
            "ok": True,
            "state_mutated": False,
            "case_uid": case["case_uid"],
            "run_id": run_id,
            "state": "gone",
            "detail": "recorded process is gone and no exit file was written",
        }
    if state == "unknown":
        return {
            "schema_version": 1,
            "kind": "entity-ledger.record.run-exit",
            "ok": True,
            "state_mutated": False,
            "case_uid": case["case_uid"],
            "run_id": run_id,
            "state": "unknown",
            "detail": "exit file holds no numeric exit code (partial write) "
                      "and the recorded process is gone",
        }
    final = "completed" if exit_code == 0 else "failed"
    identity = dict(identity)
    identity["status"] = final
    identity["exit_code"] = exit_code
    identity["observed_at"] = now_utc()
    if scheduler_state:
        scheduler = dict(scheduler)
        scheduler["state"] = scheduler_state
        identity["scheduler"] = scheduler
    _book_run(
        store, case, identity, final, {},
        "record.run-exit",
        {"run_id": run_id, "site_id": site_id, "status": final,
         "exit_code": exit_code},
        actor)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.run-exit",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "run_id": run_id,
        "state": final,
        "exit_code": exit_code,
    }


def snapshot_source(store, project_root, actor):
    """Freeze the project source into a content-addressed snapshot archive
    under the controller's snapshots root.  When a Case covers the project,
    the snapshot is also registered as the current source identity; without
    a Case the command is a pure generator (state_mutated=false)."""
    project_root = absolute(project_root)
    if not os.path.isdir(project_root):
        raise PlanError("project root does not exist: %s" % project_root)
    probe = make_manifest(project_root)
    snapshots_root = os.path.join(store.home, "snapshots")
    archive = os.path.join(snapshots_root, probe["snapshot_id"] + ".tar")
    archived = False
    manifest = None
    if os.path.isfile(archive):
        # An existing archive is trusted only after its recorded manifest is
        # readable and matches the content address; a truncated tar (an
        # interrupted earlier run) is regenerated.
        try:
            manifest = archive_manifest(archive)
        except ValueError:
            manifest = None
        if manifest is not None and manifest.get("snapshot_id") != probe["snapshot_id"]:
            manifest = None
    if manifest is None:
        # snapshot_archive prints the manifest to stdout; capture it so the
        # CLI's JSON output stays clean.  The returned manifest is the one
        # actually archived — use it rather than recomputing (TOCTOU).
        request = argparse.Namespace(source=project_root, archive=archive)
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = snapshot_archive(request)
        archived = True
    snapshot_id = manifest["snapshot_id"]
    try:
        case = store.resolve_project(project_root)
    except StoreError:
        case = None
    recorded = False
    identity_id = "source-" + snapshot_id[:16]
    if case is not None:
        authority = case.get("source", {}).get("authority", {})
        payload = {
            "id": identity_id, "kind": "source",
            "site_id": authority.get("site_id", ""),
            "root": authority,
            "fingerprint": snapshot_id,
            "archive": archive,
            "files": len(manifest.get("files", [])),
            "base_revision": manifest.get("base_revision", {}),
            "status": "snapshotted",
        }
        current = dict(case["current"])
        readiness = dict(current.get("readiness", {}))
        current["source_id"] = identity_id
        readiness["source"] = "established"
        current["readiness"] = readiness
        with store.transaction() as connection:
            store.add_identity(
                case["case_uid"], "source", identity_id, payload, True, connection)
            connection.execute(
                "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
                (canonical_json(current), now_utc(), case["case_uid"]),
            )
            store.record_event(
                case["case_uid"], None, "record.snapshot-source",
                {"snapshot_id": snapshot_id, "archive": archive}, actor, connection)
        recorded = True
    return {
        "schema_version": 1,
        "kind": "entity-ledger.snapshot-source",
        "ok": True,
        "state_mutated": recorded,
        "snapshot_id": snapshot_id,
        "archive": archive,
        "archived": archived,
        "files": len(manifest.get("files", [])),
        "base_revision": manifest.get("base_revision", {}),
        "recorded": recorded,
    }
