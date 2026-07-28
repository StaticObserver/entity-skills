#!/usr/bin/env python3
"""Fact derivation shared by the planner and the primitive commands.

Pure derivation helpers: confirmation gates, site policy defaults, and
identity/path derivation.  This module must never import the planner;
the dependency direction is planner -> facts."""

from __future__ import print_function

import getpass
import json
import os
import re
import subprocess

from entity_ledger_common import (
    LedgerError,
    absolute,
    run_on_site,
    sha256_file,
    source_manifest,
)
from entity_ledger_store import StoreError, canonical_hash


class PlanError(LedgerError):
    def __init__(self, message, status="invalid_request", decisions=None):
        LedgerError.__init__(self, message)
        self.status = status
        self.decisions = decisions or []


def _git_revision(path):
    process = subprocess.Popen(
        ["git", "-C", path, "rev-parse", "HEAD", "HEAD^{tree}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    stdout, unused = process.communicate()
    if process.returncode != 0:
        return {"kind": "path", "root": path}
    values = [line.strip() for line in stdout.splitlines() if line.strip()]
    dirty = subprocess.Popen(
        ["git", "-C", path, "status", "--porcelain"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    dirty_out, unused = dirty.communicate()
    return {"kind": "git", "commit": values[0], "tree": values[1],
            "dirty": dirty.returncode != 0 or bool(dirty_out.strip())}


def _sites(store):
    connection = store._connect()
    try:
        return [json.loads(row[0]) for row in connection.execute(
            "SELECT profile_json FROM sites ORDER BY site_id"
        )]
    finally:
        connection.close()


def _source_site(store, project_root):
    matches = []
    for profile in _sites(store):
        if profile.get("transport", {}).get("kind") != "local":
            continue
        root = profile.get("roots", {}).get("source_root")
        if not root:
            continue
        try:
            if os.path.commonpath([project_root, absolute(root)]) == absolute(root):
                matches.append((len(absolute(root)), profile["site_id"]))
        except ValueError:
            pass
    if not matches:
        raise PlanError(
            "no local Site source_root covers the project",
            "needs_decision",
            [{"field": "site", "question": "register a local source Site for the project"}],
        )
    matches.sort(reverse=True)
    return matches[0][1]


def _resolve_input(project_root, value):
    path = absolute(value if os.path.isabs(value) else os.path.join(project_root, value))
    try:
        inside = os.path.commonpath([path, project_root]) == project_root
    except ValueError:
        inside = False
    if not inside:
        raise PlanError("input is outside the project root")
    if not os.path.isfile(path):
        raise PlanError("input does not exist: %s" % path)
    return path


def _remote_file(profile, path):
    if profile.get("transport", {}).get("kind") == "local":
        return os.path.isfile(path)
    code, unused, unused_err = run_on_site(profile, ["test", "-f", path])
    return code == 0


def _current_build_executable(case, profile, explicit):
    if explicit:
        build_root = profile.get("roots", {}).get("build_root")
        if not build_root:
            raise PlanError("execution Site is missing build_root")
        path = explicit if os.path.isabs(explicit) else os.path.join(build_root, explicit)
        path = os.path.normpath(path)
        try:
            inside = os.path.commonpath([path, os.path.normpath(build_root)]) == os.path.normpath(build_root)
        except ValueError:
            inside = False
        if not inside:
            raise PlanError("explicit executable is outside the Site build_root")
        if not _remote_file(profile, path):
            raise PlanError("executable does not exist on execution Site: %s" % path)
        return path, ""
    current_id = case.get("current", {}).get("build_id", "")
    identities = case.get("identities", {}).get("build", {}).get("items", [])
    current = None
    for item in identities:
        if item.get("id") == current_id or item.get("identity_id") == current_id:
            current = item
            break
    if current is None:
        raise PlanError(
            "no verified current build executable is available",
            "needs_decision",
            [{"field": "executable", "question": "provide or build an executable"}],
        )
    candidates = []
    for output in current.get("outputs", current.get("evidence", [])):
        locator = output.get("locator", {}) if isinstance(output, dict) else {}
        path = locator.get("path", "")
        if locator.get("site_id") == profile["site_id"] and path:
            name = os.path.basename(path)
            if name == "entity.xc" or name.endswith(".xc"):
                candidates.append(path)
    if not candidates:
        raise PlanError(
            "current build identity has no executable evidence",
            "needs_decision",
            [{"field": "executable", "question": "select the verified executable"}],
        )
    candidates = sorted(set(candidates), key=lambda item: (os.path.basename(item) != "entity.xc", item))
    if not _remote_file(profile, candidates[0]):
        raise PlanError("current build executable is no longer present: %s" % candidates[0])
    return candidates[0], current_id


def _slurm_site_policy(profile, compute):
    policy = profile.get("policy", {})
    normalized = dict(compute)
    normalized.setdefault("nodes", 1)
    normalized.setdefault("tasks", int(normalized["gpus"]))
    normalized.setdefault("cpus_per_task", int(policy.get("default_cpus_per_gpu", 1)))
    normalized.setdefault("partition", policy.get("default_partition", ""))
    normalized.setdefault("qos", policy.get("default_qos", ""))
    if "submit_user" not in normalized:
        if policy.get("default_submit_user"):
            normalized["submit_user"] = policy["default_submit_user"]
        elif profile.get("transport", {}).get("kind") == "local":
            normalized["submit_user"] = getpass.getuser()
        else:
            raise PlanError(
                "SSH Slurm Site has no default_submit_user",
                "needs_decision",
                [{"field": "compute.submit_user",
                  "question": "confirm the scheduler user for Site %s" % profile["site_id"]}],
            )
    if (profile.get("scheduler", {}).get("kind") == "slurm"
            and not normalized.get("partition")):
        raise PlanError(
            "Slurm Site has no default_partition",
            "needs_decision",
            [{"field": "compute.partition",
              "question": "select a Slurm partition for Site %s" % profile["site_id"]}],
        )
    maximum = policy.get("max_cpu_per_gpu")
    if maximum is not None and normalized["cpus_per_task"] > int(maximum):
        raise PlanError(
            "compute.cpus_per_task exceeds Site max_cpu_per_gpu=%s" % maximum,
            "needs_decision",
            [{"field": "compute.cpus_per_task",
              "question": "choose no more than %s CPUs per GPU" % maximum}],
        )
    for field in ["partition", "qos", "submit_user"]:
        if (not isinstance(normalized[field], str)
                or not re.match(r"^[A-Za-z0-9_.@+-]*$", normalized[field])):
            raise PlanError("Site policy produced invalid compute.%s" % field)
    return normalized


def _direct_site_policy(profile, compute):
    """Policy for scheduler-less Sites: no partition/QoS/scheduler account
    exists, so those fields normalize to empty strings and the submit user
    defaults to the current user without a needs_decision round-trip."""
    policy = profile.get("policy", {})
    normalized = dict(compute)
    normalized.setdefault("nodes", 1)
    normalized.setdefault("tasks", 1)
    normalized.setdefault("cpus_per_task", int(policy.get("default_cpus_per_gpu", 1)))
    normalized.setdefault("partition", "")
    normalized.setdefault("qos", "")
    if "submit_user" not in normalized:
        if policy.get("default_submit_user"):
            normalized["submit_user"] = policy["default_submit_user"]
        else:
            normalized["submit_user"] = getpass.getuser()
    maximum = policy.get("max_cpu_per_gpu")
    if maximum is not None and normalized["cpus_per_task"] > int(maximum):
        raise PlanError(
            "compute.cpus_per_task exceeds Site max_cpu_per_gpu=%s" % maximum,
            "needs_decision",
            [{"field": "compute.cpus_per_task",
              "question": "choose no more than %s CPUs per GPU" % maximum}],
        )
    for field in ["partition", "qos", "submit_user"]:
        if (not isinstance(normalized[field], str)
                or not re.match(r"^[A-Za-z0-9_.@+-]*$", normalized[field])):
            raise PlanError("Site policy produced invalid compute.%s" % field)
    return normalized


RUN_BACKENDS = {
    "slurm": {"scheduler": "slurm", "validate_policy": _slurm_site_policy},
    "none": {"scheduler": "direct", "validate_policy": _direct_site_policy},
}


def _run_backend(profile):
    kind = profile.get("scheduler", {}).get("kind")
    backend = RUN_BACKENDS.get(kind)
    if backend is None:
        raise PlanError(
            "run Goal currently supports scheduler kinds: %s (got '%s')"
            % (", ".join(sorted(RUN_BACKENDS)), kind)
        )
    return kind, backend


def _site_policy(profile, compute):
    unused_kind, backend = _run_backend(profile)
    return backend["validate_policy"](profile, compute)


def _content_sha256(profile, path):
    """Fingerprint an executable on its execution Site, locally or over SSH."""
    if profile.get("transport", {}).get("kind") == "local":
        return sha256_file(path)
    script = (
        "import hashlib,os,sys; p=sys.argv[1]; "
        "print(hashlib.sha256(open(p,'rb').read()).hexdigest() if os.path.isfile(p) else '')"
    )
    code, stdout, stderr = run_on_site(profile, ["python3", "-c", script, path])
    digest = stdout.strip()
    if code != 0 or not digest:
        raise PlanError(
            "cannot fingerprint executable on execution Site: %s"
            % (stderr.strip() or stdout.strip() or path)
        )
    return digest


def _operation_id(seed):
    return "op-" + canonical_hash(seed).split(":", 1)[1][:16]


def derive_run_paths(case_uid, site_id, roots, scheduler_kind, source_id,
                     input_sha256, executable, build_id, compute):
    """Derive the content-addressed run identity and every path a run
    Operation touches from the run seed and the Site roots."""
    seed = {
        "case_uid": case_uid, "source_id": source_id,
        "input_sha256": input_sha256,
        "site_id": site_id, "executable": executable, "build_id": build_id,
        "compute": compute,
    }
    run_id = "run-" + canonical_hash(seed).split(":", 1)[1][:16]
    operation_id = _operation_id(seed)
    run_root = os.path.join(roots["run_root"], case_uid, run_id)
    staging_root = os.path.join(roots["staging_root"], case_uid, operation_id)
    return {
        "seed": seed,
        "run_id": run_id,
        "operation_id": operation_id,
        "run_root": run_root,
        "staging_root": staging_root,
        "manifest": os.path.join(run_root, "run-manifest.json"),
        "submit_script": os.path.join(
            run_root, "run.sbatch" if scheduler_kind == "slurm" else "run.sh"),
        "staged_input": os.path.join(staging_root, "payloads", "input.toml"),
        "prepare_receipt": os.path.join(staging_root, "receipts", "run-prepare.json"),
    }


def _source_identity(source_root, controller_artifacts=None):
    source_root = absolute(source_root)
    manifest = source_manifest(source_root)
    ignored = set()
    for path in controller_artifacts or []:
        path = absolute(path)
        try:
            if os.path.commonpath([path, source_root]) == source_root:
                ignored.add(os.path.relpath(path, source_root))
        except ValueError:
            pass
    files = [item for item in manifest.get("files", []) if item.get("path") not in ignored]
    identity = {"base_revision": manifest.get("base_revision", {}), "files": files}
    return {
        "snapshot_id": canonical_hash(identity).split(":", 1)[1],
        "base_revision": identity["base_revision"],
        "files": len(files),
    }, sorted(ignored)


def _simulation_confirmation(input_path):
    """Hard gate: the simulation parameter confirmation recorded by
    pgen_preflight.py confirm must exist and match the current input bytes."""
    path = input_path + ".decisions.json"
    question = (
        "show the parameter card to the user and record confirmation with "
        "pgen_preflight.py confirm %s --by <actor>" % input_path
    )
    if not os.path.isfile(path):
        raise PlanError(
            "simulation parameters have not been confirmed",
            "needs_decision",
            [{"field": "input", "question": question}],
        )
    try:
        with open(path, "r") as handle:
            record = json.load(handle)
    except (IOError, OSError, ValueError) as exc:
        raise PlanError("cannot read simulation confirmation: %s" % exc)
    if (not isinstance(record, dict)
            or record.get("kind") != "entity-pgen.simulation-confirmation"
            or record.get("input_sha256") != sha256_file(input_path)):
        raise PlanError(
            "simulation parameters changed since they were confirmed",
            "needs_decision",
            [{"field": "input", "question": question}],
        )
    return record


def _resolve_case(store, project_root, goal):
    try:
        return store.resolve_project(project_root), False
    except StoreError:
        source_site = _source_site(store, project_root)
        case_uid = "case-" + canonical_hash({"project_root": project_root}).split(":", 1)[1][:16]
        case = {
            "case_uid": case_uid,
            "case_id": goal.get("case_id") or os.path.basename(project_root),
            "project_root": project_root,
            "source": {
                "authority": {"site_id": source_site, "path": project_root},
                "transfer_policy": goal.get("source_mode", "snapshot"),
                "revision": _git_revision(project_root),
            },
            "current": {"source_id": "", "build_id": "", "run_id": "",
                        "active_run": None, "data_id": "", "analysis_id": ""},
            "identities": {}, "legacy": {},
        }
        return case, True


def require_verified_checkpoint(checkpoint):
    """Hard gate: a build Goal only registers checkpoints that env-build has
    verified (compatibility pass) and whose parameters were confirmed."""
    compatibility = checkpoint.get("compatibility", {})
    if not isinstance(compatibility, dict) or compatibility.get("status") != "pass":
        raise PlanError(
            "build checkpoint compatibility is not pass",
            "needs_decision",
            [{"field": "checkpoint",
              "question": "run entity_compat.py and resolve the failures"}],
        )
    parameters = checkpoint.get("decisions", {}).get("parameters", {})
    if not isinstance(parameters, dict) or not parameters.get("digest"):
        raise PlanError(
            "build parameters have not been confirmed",
            "needs_decision",
            [{"field": "checkpoint",
              "question": "record build parameter confirmation with "
                          "entity_checkpoint.py confirm"}],
        )
