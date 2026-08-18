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

import glob
import json
import os
import re

from entity_ledger_common import (
    absolute,
    find_identity,
    now_utc,
    run_on_site,
    sha256_file,
    site_file_sha256,
    valid_gres,
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
    case_path_segment,
    case_resolution_plan_error,
    derive_run_paths,
    merged_execution_profile,
    require_verified_checkpoint,
)
from entity_ledger_operation import ExecutorClient, OperationError, _same_path
from entity_ledger_remote import archive_manifest, make_manifest, snapshot_archive
from entity_ledger_store import (
    CaseResolutionError,
    StoreError,
    canonical_hash,
    canonical_json,
)
from entity_ledger_workspace import (
    derive_stack_id,
    list_site_archives,
    stack_signature,
    workspace_for_ledger_home,
)


def show_case(store, project_root, case_slug=None):
    """Read-only Case fact detail: the full controller-local projection."""
    case = store.resolve_project(project_root, case_slug)
    project = None
    if case.get("project_uid"):
        project = store.get_project(case["project_uid"])
    current_data = case.get("current", {}).get("data_id", "")
    analyses = []
    for item in case.get("identities", {}).get("analysis", {}).get(
            "items", []):
        parent_data = item.get("parents", {}).get("data_id", "")
        analyses.append({
            "analysis_id": item.get("id", ""),
            "script": item.get("script", ""),
            "params": item.get("params", {}),
            "data_id": parent_data,
            "env_stack": item.get("env_stack", ""),
            "hardcoded_paths": bool(item.get("hardcoded_paths")),
            "status": item.get("status", ""),
            "stale": bool(parent_data) and parent_data != current_data,
        })
    return {
        "schema_version": 1,
        "kind": "entity-ledger.show",
        "ok": True,
        "state_mutated": False,
        "case_uid": case["case_uid"],
        "case_id": case["case_id"],
        "project_uid": case.get("project_uid"),
        "project": project,
        "project_root": case["project_root"],
        "source": case["source"],
        "current": case["current"],
        "identities": case["identities"],
        "analyses": analyses,
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
    }


def _registered_project_candidates(store, project_root):
    """Basename match over the registered projects: a moved project keeps
    its directory name, so the registry usually still holds its new path."""
    wanted = os.path.basename(absolute(project_root))
    found = []
    for project in store.find_projects():
        root = project.get("project_root") or ""
        if project.get("slug") == wanted or (
                root and os.path.basename(root) == wanted):
            found.append("%s (%s)" % (project["slug"], root))
    return sorted(found)


def _require_case(store, project_root, case_slug=None):
    try:
        return store.resolve_project(project_root, case_slug)
    except CaseResolutionError as exc:
        if exc.reason != "no_project":
            raise case_resolution_plan_error(exc)
        message = (
            "no project is registered at %s; if the project moved, use the "
            "new path or entityctl workspace import" % absolute(project_root))
        candidates = _registered_project_candidates(store, project_root)
        if candidates:
            message += ("; registered projects with the same name: %s"
                        % ", ".join(candidates))
        raise PlanError(
            message,
            "needs_decision",
            [{"field": "project",
              "question": "point --project-root at a registered project path"}],
        )
    except StoreError:
        raise PlanError(
            "no Case covers the project; create it with "
            "entityctl case init <project> <name>",
            "needs_decision",
            [{"field": "case",
              "question": "create the Case with "
                          "entityctl case init <project> <name>"}],
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
    return path, checkpoint


def _checkpoint_stack_id(checkpoint):
    """The deps stack a checkpoint was built from, derived with the same
    deterministic rule as site deps-add; "" when the checkpoint has no
    selected dependencies (old checkpoints simply carry no reference)."""
    selected = checkpoint.get("selected", {})
    if not isinstance(selected, dict) or not selected:
        return ""
    embedded = checkpoint.get("requirements", {}).get("embedded", {})
    signature = stack_signature(
        embedded.get("environment", {}), embedded.get("entity", {}),
        embedded.get("compile", {}))
    return derive_stack_id(selected, signature)


def _stack_registry_hint(store, site_id, stack_id):
    """Advisory only: suggest deps-add when the build's stack is not in the
    site registry yet.  Never blocks the record."""
    if not stack_id:
        return ""
    workspace = workspace_for_ledger_home(store.home)
    if not workspace:
        return ""
    archives = list_site_archives(workspace)
    record = archives.get(site_id)
    if record is None:
        return ""
    registered = any(stack.get("stack_id") == stack_id
                     for stack in record.get("deps") or [])
    if registered:
        return ""
    return ("build stack %s is not registered in the deps registry of "
            "Site %s; after verification passes, record it with entityctl "
            "site deps-add %s --from-checkpoint <entity-deps.local.json>"
            % (stack_id, site_id, site_id))


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


def _sync_intent_file(store, case, text):
    """Best-effort mirror of the db intent into the case's intent.md (the db
    stays the authority).  Only writes when the case lives in a workspace
    case directory; returns the file path or ""."""
    workspace = workspace_for_ledger_home(store.home)
    if not workspace or not case.get("project_uid"):
        return ""
    try:
        project = store.get_project(case["project_uid"])
    except StoreError:
        return ""
    case_dir = os.path.join(
        workspace, "projects", project["slug"], "cases", case["case_id"])
    if not os.path.isdir(case_dir):
        return ""
    path = os.path.join(case_dir, "intent.md")
    with open(path, "w") as handle:
        handle.write(text.strip() + "\n")
    return path


def _rewrite_locator_paths(value, old_root, new_root):
    """Recursively rewrite payload strings that point at (or under) the old
    resource root; sibling trees (e.g. staging roots) stay untouched."""
    if isinstance(value, str):
        if value == old_root:
            return new_root
        if value.startswith(old_root + os.sep):
            return new_root + value[len(old_root):]
        return value
    if isinstance(value, list):
        return [_rewrite_locator_paths(item, old_root, new_root)
                for item in value]
    if isinstance(value, dict):
        return dict((key, _rewrite_locator_paths(item, old_root, new_root))
                    for key, item in value.items())
    return value


# Run states from which a resource may be relocated; anything else is an
# in-flight run and must reach its terminal state first (record run-exit).
# "aborted" is the human-declared terminal state (record run-abort).
TERMINAL_RUN_STATES = {"completed", "failed", "exited", "aborted"}


def _read_site_json(profile, path, label):
    if profile.get("transport", {}).get("kind") == "local":
        if not os.path.isfile(path):
            raise PlanError(
                "%s not found at the new location: %s" % (label, path))
        try:
            with open(path, "r") as handle:
                return json.load(handle)
        except (IOError, OSError, ValueError) as exc:
            raise PlanError("cannot read %s: %s" % (label, exc))
    code, stdout, unused = run_on_site(profile, ["cat", path])
    if code != 0:
        raise PlanError(
            "%s not found at the new location: %s" % (label, path))
    try:
        return json.loads(stdout)
    except ValueError as exc:
        raise PlanError("cannot parse %s: %s" % (label, exc))


def _site_path_exists(profile, path):
    if profile.get("transport", {}).get("kind") == "local":
        return os.path.exists(path)
    code, unused, unused_err = run_on_site(profile, ["test", "-e", path])
    return code == 0


def _relocate_evidence(profile, identity, new_root):
    """Re-probe the moved resource at its new root; any mismatch aborts
    before a single store write."""
    kind = identity.get("kind")
    if kind == "run":
        manifest = _read_site_json(
            profile, os.path.join(new_root, "run-manifest.json"),
            "run manifest")
        if manifest.get("run_id") != identity.get("id"):
            raise PlanError(
                "run manifest at the new location names %s, not %s"
                % (manifest.get("run_id"), identity.get("id")))
        return {"run_manifest": os.path.join(new_root, "run-manifest.json")}
    if kind == "build":
        outputs = identity.get("outputs", [])
        locator = outputs[0].get("locator", {}) if outputs else {}
        name = os.path.basename(locator.get("path", "")) or "entity.xc"
        executable = os.path.join(new_root, name)
        expected = identity.get("executable_sha256", "")
        if expected:
            digest = site_file_sha256(profile, executable)
            if digest != expected:
                raise PlanError(
                    "executable fingerprint mismatch at the new location: "
                    "%s (expected %s, got %s)" % (executable, expected, digest))
            return {"executable": executable, "executable_sha256": digest}
        if not _site_path_exists(profile, executable):
            raise PlanError(
                "executable not found at the new location: %s" % executable)
        return {"executable": executable}
    if kind == "data":
        manifest = os.path.join(new_root, "data-inventory.json")
        _read_site_json(profile, manifest, "data inventory manifest")
        return {"manifest": manifest}
    raise PlanError(
        "relocate supports build/run/data identities (got %s)" % kind)


def _relocated_layout(profile, new_root):
    """site-tree only when the new root sits under the site tree's
    <site_root>/projects convention; anything else stays legacy-roots."""
    site_root = profile.get("site_root", "")
    if site_root:
        convention = os.path.join(os.path.normpath(site_root), "projects")
        try:
            if os.path.commonpath([new_root, convention]) == convention:
                return "site-tree"
        except ValueError:
            pass
    return "legacy-roots"


def record_relocate(store, project_root, dimension, identity_id, new_root,
                    actor, case_slug=None):
    """Re-register a moved resource: after the agent moved the files, probe
    the evidence at the new root and only then update the identity Locator
    plus the current projection, with an audit event.  Evidence mismatch
    means zero writes; in-flight runs are refused."""
    if dimension not in ("build", "run", "data"):
        raise PlanError(
            "relocate dimension must be build, run or data (got %s)" % dimension)
    case = _require_case(store, project_root, case_slug)
    identity = find_identity(
        case.get("identities", {}).get(dimension, {}).get("items", []),
        identity_id)
    if identity is None:
        raise PlanError(
            "unknown %s identity: %s" % (dimension, identity_id),
            "needs_decision",
            [{"field": "identity",
              "question": "select a recorded %s identity" % dimension}],
        )
    root = identity.get("root", {})
    old_root = root.get("path", "")
    site_id = root.get("site_id") or identity.get("site_id", "")
    if not old_root or not site_id:
        raise PlanError("identity has no usable root locator")
    if not new_root or not str(new_root).startswith("/"):
        raise PlanError("relocate target must be an absolute path")
    new_root = os.path.normpath(new_root)
    old_root = os.path.normpath(old_root)
    if (dimension == "run"
            and identity.get("status", "") not in TERMINAL_RUN_STATES):
        raise PlanError(
            "run %s is in flight (status=%s); relocate after record "
            "run-exit books the terminal state"
            % (identity_id, identity.get("status", "")),
            "needs_decision",
            [{"field": "run",
              "question": "wait for the terminal state, then relocate"}],
        )
    if new_root == old_root:
        return {
            "schema_version": 1,
            "kind": "entity-ledger.record.relocate",
            "ok": True,
            "state_mutated": False,
            "case_uid": case["case_uid"],
            "dimension": dimension,
            "identity_id": identity_id,
            "message": "identity already locates at %s" % new_root,
        }
    profile = store.get_site(site_id)
    if not _site_path_exists(profile, new_root):
        raise PlanError(
            "new location does not exist on Site %s: %s" % (site_id, new_root))
    evidence = _relocate_evidence(profile, identity, new_root)
    payload = _rewrite_locator_paths(identity, old_root, new_root)
    payload["root"] = {"site_id": site_id, "path": new_root}
    payload["layout"] = _relocated_layout(profile, new_root)
    current = _rewrite_locator_paths(case["current"], old_root, new_root)
    with store.transaction() as connection:
        connection.execute(
            "UPDATE identities SET payload_json=? WHERE case_uid=? AND "
            "dimension=? AND identity_id=?",
            (canonical_json(payload), case["case_uid"], dimension, identity_id),
        )
        connection.execute(
            "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
            (canonical_json(current), now_utc(), case["case_uid"]),
        )
        store.record_event(
            case["case_uid"], None, "record.relocate",
            {"dimension": dimension, "identity_id": identity_id,
             "from": old_root, "to": new_root, "evidence": evidence},
            actor, connection)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.relocate",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "dimension": dimension,
        "identity_id": identity_id,
        "from": {"site_id": site_id, "path": old_root},
        "to": {"site_id": site_id, "path": new_root},
        "evidence": evidence,
    }


def record_intent(store, project_root, text, actor, case_slug=None):
    """Record the current research intent of a Case.  The intent is the only
    stored pointer: it cannot be derived from artifacts, so it is written
    explicitly and shown on the dashboard.  Recording a new intent replaces
    the previous one (history stays in the audit events).  The db is the
    authority; the case directory's intent.md is rewritten as a mirror."""
    if not text or not text.strip():
        raise PlanError("intent text must be non-empty")
    case = _require_case(store, project_root, case_slug)
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
        "intent_file": _sync_intent_file(store, case, text),
    }


def record_build(store, project_root, site_id, checkpoint, executable, actor,
                 case_slug=None):
    """Register a verified build identity.  The build_id is content-addressed
    from (case, checkpoint, executable, site), so recording the same build
    twice is a successful no-op."""
    case = _require_case(store, project_root, case_slug)
    profile = store.get_site(site_id)
    checkpoint_path, checkpoint = _load_checkpoint(checkpoint)
    executable, executable_sha256 = _probe_executable(profile, executable)
    checkpoint_sha256 = sha256_file(checkpoint_path)
    stack_id = _checkpoint_stack_id(checkpoint)
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
    if stack_id:
        identity["stack_id"] = stack_id
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
    warnings = []
    hint = _stack_registry_hint(store, site_id, stack_id)
    if hint:
        warnings.append(hint)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.build",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "build_id": build_id,
        "site_id": site_id,
        "stack_id": stack_id,
        "warnings": warnings,
        "evidence": {
            "executable": executable,
            "executable_sha256": executable_sha256,
            "checkpoint": checkpoint_path,
            "checkpoint_sha256": checkpoint_sha256,
        },
    }


def _run_identity(case, run_id):
    return find_identity(
        case.get("identities", {}).get("run", {}).get("items", []), run_id)


def _inventory_envelope(case_uid, run_id, site_id, staging_root, run_root,
                        case_segment=None):
    digest = canonical_hash({"case_uid": case_uid, "run_id": run_id})
    digest = digest.split(":", 1)[1][:16]
    staging = os.path.join(staging_root, case_segment or case_uid, "op-" + digest)
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


def record_data(store, project_root, run_id, actor, case_slug=None):
    """Inventory a run's outputs and book the data identity.  The data_id is
    content-addressed from (case, run), so re-inventorying the same run is
    idempotent and refreshes the recorded file count."""
    case = _require_case(store, project_root, case_slug)
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
    profile, layout = merged_execution_profile(
        store, store.get_site(site_id), case)
    staging_root = profile.get("roots", {}).get("staging_root")
    if not staging_root:
        raise PlanError("execution Site is missing staging_root")
    data_id, manifest, envelope = _inventory_envelope(
        case["case_uid"], run_id, site_id, staging_root, run_root,
        case_segment=case_path_segment(layout, case))
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


def _compute_request(gpus, walltime, precision, gres=""):
    """Validate the CLI compute overrides before site policy fills the rest.
    An empty walltime means no time limit: the sbatch carries no --time and
    the direct backend runs without a timeout wrapper.  An empty gres defers
    to the site policy default_gres, then to the generic gpu:<gpus> form;
    the direct backend ignores gres entirely."""
    if not isinstance(gpus, int) or isinstance(gpus, bool) or gpus < 1:
        raise PlanError("gpus must be a positive integer")
    if walltime and not re.match(r"^[0-9]+(?:-[0-9]{2})?:[0-9]{2}:[0-9]{2}$",
                                 walltime):
        raise PlanError("walltime must use HH:MM:SS or D-HH:MM:SS")
    if precision not in {"single", "double"}:
        raise PlanError("precision must be single or double")
    if gres and not valid_gres(gres):
        raise PlanError("gres must match gpu[:type]:count (e.g. gpu:V100:1)")
    return {"gpus": gpus, "walltime": walltime, "precision": precision,
            "gres": gres}


def _derive_run(store, project_root, input_value, site_id, compute, executable,
                case_slug=None):
    """Content-addressed run derivation shared by render-run and record
    run-prepare: identical inputs always yield the same run_id, paths, and
    synthetic executor envelope identity."""
    project_root = absolute(project_root)
    if not os.path.isdir(project_root):
        raise PlanError("project root does not exist: %s" % project_root)
    case, create_case = _resolve_case(store, project_root, {}, case_slug)
    profile, layout = merged_execution_profile(
        store, store.get_site(site_id), case)
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
        input_sha256, executable, build_id, normalized,
        case_segment=case_path_segment(layout, case))
    plan_hash = canonical_hash({"kind": "entity-ledger.record.run",
                                "seed": paths["seed"]})
    return {
        "case": case, "create_case": create_case, "profile": profile,
        "layout": layout,
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
               precision, executable, gres="", case_slug=None):
    """Pure preview: render the submit script and the derived run paths
    without touching controller or Site state (no confirmation gate)."""
    compute = _compute_request(gpus, walltime, precision, gres)
    derived = _derive_run(
        store, project_root, input_value, site_id, compute, executable,
        case_slug)
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
        "layout": derived["layout"],
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
                       walltime, precision, executable, actor, gres="",
                       run_id="", case_slug=None):
    """Prepare a run root on its Site and book the run identity as prepared.

    Gates (all before any state write): the pgen simulation confirmation must
    match the current input bytes, and an existing run identity that already
    advanced past ``prepared`` is never rewound.  The Case is created on first
    use in the same transaction as the run booking — after the executor
    succeeded — and the executor receipt makes re-runs idempotent.

    With ``--run-id`` (the id a preceding render-run previewed) the freshly
    derived run must equal it: the run_id is content-addressed from source,
    TOML, compute and build, so a mismatch proves the inputs drifted between
    render and prepare — the call fails with zero writes instead of silently
    preparing a second, different run.  A match means the render's previewed
    run root/script/manifest are exactly the ones prepare materializes."""
    compute = _compute_request(gpus, walltime, precision, gres)
    derived = _derive_run(
        store, project_root, input_value, site_id, compute, executable,
        case_slug)
    paths = derived["paths"]
    if run_id and paths["run_id"] != run_id:
        raise PlanError(
            "derived run %s differs from --run-id %s: the inputs (source, "
            "TOML, compute or build) drifted since render-run — re-render "
            "and use the new id" % (paths["run_id"], run_id))
    confirmation = _simulation_confirmation(derived["input_path"])
    case = derived["case"]
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
        "layout": derived["layout"],
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
        "layout": derived["layout"],
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


def record_run_launch(store, project_root, run_id, adopt_job, adopt_pid, actor,
                      case_slug=None, resubmit=False):
    """Submit a prepared run exactly once (executor receipt) or adopt an
    out-of-band job after probing it, then book the run as submitted.  On
    Slurm Sites the scheduler first validates the rendered submission
    (run.preflight.v1 / sbatch --test-only); a rejection fails with the
    executor's remediation hint before any state is written.  Scheduler-less
    Sites have no scheduler to consult and skip the preflight.

    With ``resubmit`` a run whose recorded job died (the ledger-submitted
    job that failed before or at ``record run-exit``) is submitted again:
    eligibility requires a recorded scheduler identity whose job probes
    terminal *and* failed, and the run status must be submitted (died
    before run-exit) or failed (run-exit already booked it).  The new
    submission gets its own exactly-once receipt (run-relaunch-<n>.json,
    n counting earlier resubmissions), the previous scheduler record moves
    to ``prior_submissions``, and the launch event is marked
    ``resubmit: true``.  Exactly-once is per submission, not per run."""
    case = _require_case(store, project_root, case_slug)
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
    if resubmit:
        if status not in {"submitted", "failed"}:
            raise PlanError(
                "run %s is %s; --resubmit applies to a submitted or failed "
                "run whose recorded job died" % (run_id, status or "unknown"))
    elif status not in {"prepared", "submitted"}:
        raise PlanError("run %s is %s; only a prepared run can be launched"
                        % (run_id, status or "unknown"))
    root = identity.get("root", {})
    site_id = root.get("site_id") or identity.get("site_id", "")
    run_root = root.get("path", "")
    if not site_id or not run_root:
        raise PlanError("run identity has no usable root locator")
    profile = store.get_site(site_id)
    # Site-tree profiles (site_root, no explicit roots) need the derived
    # roots filled in — prepare/data go through merged_execution_profile;
    # launch must too, or ExecutorClient finds no staging_root.
    profile, unused_layout = merged_execution_profile(store, profile, case)
    unused_kind, backend = _run_backend(profile)
    scheduler_kind = backend["scheduler"]
    adopted = bool(adopt_job or adopt_pid)
    if adopted and resubmit:
        raise PlanError("--resubmit cannot be combined with adoption")
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
        prior_submissions = []
        if recorded_scheduler.get("job_id") or recorded_scheduler.get("pid"):
            if not resubmit:
                # The run already carries a scheduler identity — submitted
                # by an earlier launch or adopted out-of-band (adoption
                # leaves no executor receipt to make a re-run idempotent).
                # Re-running the launch without adopt flags must claim the
                # recorded effect instead of submitting a second job.
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
            # --resubmit: the recorded job must probe terminal AND failed —
            # a live or unprobeable job is never displaced by a second
            # submission (record run-exit it first).
            previous_scheduler = recorded_scheduler
            probe_kind = recorded_scheduler.get("scheduler", "")
            if probe_kind == "slurm":
                probe_state, probe_sched_state, probe_exit = _slurm_exit_probe(
                    profile, recorded_scheduler.get("job_id", ""))
            elif probe_kind == "direct":
                probe_state, probe_exit = _direct_exit_probe(
                    profile, recorded_scheduler)
                probe_sched_state = ""
            else:
                raise PlanError(
                    "run identity has an unsupported scheduler record: %s"
                    % (probe_kind or "none"))
            if probe_state != "terminal":
                raise PlanError(
                    "the recorded job of run %s probes '%s', not terminal; "
                    "--resubmit only replaces a dead job — record run-exit "
                    "first (or wait for it)" % (run_id, probe_state))
            if probe_sched_state:
                job_failed = (probe_sched_state != "COMPLETED"
                              or (probe_exit or 0) != 0)
            else:
                job_failed = probe_exit is not None and probe_exit != 0
            if not job_failed:
                raise PlanError(
                    "the recorded job of run %s reached a successful "
                    "terminal state; there is nothing to resubmit" % run_id)
            prior_submissions = (
                list(identity.get("prior_submissions", []))
                + [previous_scheduler])
        elif resubmit:
            raise PlanError(
                "run %s has no recorded scheduler identity; there is no "
                "dead submission to replace — use plain record run-launch"
                % run_id)
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
        # each submission gets its own exactly-once receipt: the first
        # launch uses run-launch.json, resubmission n run-relaunch-<n>.json
        receipt_name = "run-launch.json"
        step_id = "launch"
        if resubmit:
            receipt_name = "run-relaunch-%d.json" % len(prior_submissions)
            step_id = "relaunch"
        envelope = {
            "schema_version": 1,
            "operation_id": identity["operation_id"],
            "plan_hash": identity["plan_hash"],
            "step_index": 2,
            "step_id": step_id,
            "kind": "run.launch.v2",
            "site_id": site_id,
            "receipt": os.path.join(
                identity["staging_root"], "receipts", receipt_name),
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
    if resubmit:
        identity["prior_submissions"] = prior_submissions
    event_payload = {"run_id": run_id, "site_id": site_id, "adopted": adopted,
                     "scheduler": effect}
    if resubmit:
        event_payload["resubmit"] = True
        event_payload["previous_scheduler"] = prior_submissions[-1]
    _book_run(
        store, case, identity, "submitted", {},
        "record.run-launch",
        event_payload,
        actor)
    result = {
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
    if resubmit:
        result["resubmit"] = True
        result["previous_scheduler"] = prior_submissions[-1]
    return result


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
_STEP_PATTERN = re.compile(r"Step:\s*(\d+)")
_OF_PATTERN = re.compile(r"\[of\s*(\d+)\]")

# Known Entity teardown abort signatures: glibc heap-consolidation aborts
# raised while the runtime tears down after the final step.  Both observed
# variants ("invalid chunk size", "unaligned fastbin chunk detected") share
# the malloc_consolidate() prefix.  New signatures are added here as they
# are observed and confirmed harmless.
_TEARDOWN_ABORT_SIGNATURES = ("malloc_consolidate()",)
_ABORT_MARKERS = ("Aborted", "SIGABRT")

_LOG_TAIL_BYTES = 262144


def classify_teardown_abort(err_text, out_text):
    """Classify whether a non-zero exit is a known harmless teardown abort.
    Pure function, no I/O.  Both evidence groups must hold: the stderr tail
    carries a known teardown signature plus an abort marker, and the last
    ``Step: N ... [of M]`` pair in the stdout log (ANSI escapes stripped)
    satisfies ``N >= M - 1`` (Entity prints the final step as M-1).  Returns
    the anomaly record, or None when any evidence is missing."""
    if not err_text or not out_text:
        return None
    signature = None
    for candidate in _TEARDOWN_ABORT_SIGNATURES:
        if candidate in err_text:
            signature = candidate
            break
    if signature is None:
        return None
    if not any(marker in err_text for marker in _ABORT_MARKERS):
        return None
    last_step = None
    total_steps = None
    for line in _ANSI_ESCAPE.sub("", out_text).splitlines():
        step_match = _STEP_PATTERN.search(line)
        of_match = _OF_PATTERN.search(line)
        if step_match is not None and of_match is not None:
            last_step = int(step_match.group(1))
            total_steps = int(of_match.group(1))
    if last_step is None or total_steps is None:
        return None
    if last_step < total_steps - 1:
        return None
    return {
        "kind": "exit-teardown-abort",
        "signature": signature,
        "last_step": last_step,
        "total_steps": total_steps,
    }


def _tail_log(profile, path):
    """Read the tail of a log file on its Site.  A missing file or any read
    failure yields an empty string — log probing must never crash the record
    path; missing evidence simply means no reclassification."""
    try:
        code, stdout, unused = run_on_site(
            profile, ["tail", "-c", str(_LOG_TAIL_BYTES), path])
    except OSError:
        return ""
    if code != 0:
        return ""
    return stdout


def _glob_run_logs(profile, run_root, pattern):
    """Glob log files at the run root or one level below — Entity names its
    own logs after simulation.name (``<name>.err``/``<name>.out`` inside the
    ``<name>/`` output subdirectory), so fixed filenames alone miss them."""
    if profile.get("transport", {}).get("kind") == "local":
        return sorted(
            glob.glob(os.path.join(run_root, pattern))
            + glob.glob(os.path.join(run_root, "*", pattern)))
    code, stdout, unused = run_on_site(profile, [
        "bash", "-c",
        'ls -1 "$1"/' + pattern + ' "$1"/*/' + pattern + ' 2>/dev/null; true',
        "bash", run_root])
    if code != 0:
        return []
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def _probe_run_logs(profile, identity):
    """Collect (stderr_text, stdout_text) tails from the run's log files.
    simulation.err, Entity's <name>.err and the direct-backend run.log count
    as stderr evidence; simulation.out, <name>.out, slurm-<job_id>.out and
    run.log count as stdout evidence.  Slurm merges stderr into the out file
    unless --error is given, so slurm-<job_id>.out is evidence for both."""
    scheduler = identity.get("scheduler", {})
    run_root = identity.get("root", {}).get("path", "") \
        or scheduler.get("run_root", "")
    if not run_root:
        return "", ""
    err_paths = [os.path.join(run_root, name)
                 for name in ("simulation.err", "run.log")]
    out_paths = [os.path.join(run_root, "simulation.out")]
    job_id = scheduler.get("job_id", "")
    if job_id:
        slurm_out = os.path.join(run_root, "slurm-%s.out" % job_id)
        out_paths.append(slurm_out)
        err_paths.append(slurm_out)
    out_paths.append(os.path.join(run_root, "run.log"))
    for path in _glob_run_logs(profile, run_root, "*.err"):
        if path not in err_paths:
            err_paths.append(path)
    for path in _glob_run_logs(profile, run_root, "*.out"):
        if path not in out_paths and path not in err_paths:
            out_paths.append(path)
    err_text = "\n".join(text for text in (
        _tail_log(profile, path) for path in err_paths) if text)
    out_text = "\n".join(text for text in (
        _tail_log(profile, path) for path in out_paths) if text)
    return err_text, out_text


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
            profile, ["sacct", "-n", "-X", "-P", "-j", job_id,
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


def record_run_exit(store, project_root, run_id, actor, reclassify=False,
                    case_slug=None):
    """Probe a submitted run's terminal state and book it.  A still-running
    run is reported without mutating state; an unreachable Site fails with
    exit 2 and no write.  A non-COMPLETED scheduler word (CANCELLED,
    TIMEOUT, OUT_OF_MEMORY, ...) books failed regardless of the exit code;
    otherwise the exit code classifies.  When the terminal exit code is
    non-zero, the run's log tails are checked for a known harmless teardown
    abort (see classify_teardown_abort); with both evidence groups the run
    is booked completed with an exit_anomaly note, the real exit code
    preserved.

    With ``reclassify`` the scheduler probe is skipped and a run already
    booked failed is re-judged from its logs alone: a match rewrites the
    identity to completed with exit_anomaly, a miss reports state_mutated
    false.  Any status other than failed is an error with zero writes."""
    case = _require_case(store, project_root, case_slug)
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
    if reclassify:
        if status != "failed":
            raise PlanError(
                "run %s is %s; --reclassify only applies to a failed run"
                % (run_id, status or "unknown"))
        site_id = identity.get("root", {}).get("site_id") \
            or identity.get("site_id", "")
        profile = store.get_site(site_id)
        err_text, out_text = _probe_run_logs(profile, identity)
        anomaly = classify_teardown_abort(err_text, out_text)
        if anomaly is None:
            return {
                "schema_version": 1,
                "kind": "entity-ledger.record.run-exit",
                "ok": True,
                "state_mutated": False,
                "case_uid": case["case_uid"],
                "run_id": run_id,
                "state": "failed",
                "exit_code": identity.get("exit_code"),
                "detail": "log evidence does not match a known harmless "
                          "teardown abort; the run stays failed",
            }
        identity = dict(identity)
        identity["status"] = "completed"
        identity["exit_anomaly"] = anomaly
        identity["observed_at"] = now_utc()
        _book_run(
            store, case, identity, "completed", {},
            "record.run-exit",
            {"run_id": run_id, "site_id": site_id, "status": "completed",
             "exit_code": identity.get("exit_code"),
             "exit_anomaly": anomaly, "reclassified": True},
            actor)
        return {
            "schema_version": 1,
            "kind": "entity-ledger.record.run-exit",
            "ok": True,
            "state_mutated": True,
            "case_uid": case["case_uid"],
            "run_id": run_id,
            "state": "completed",
            "exit_code": identity.get("exit_code"),
            "exit_anomaly": anomaly,
            "reclassified": True,
        }
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
            "detail": "run is still running; no state written",
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
    # The scheduler's terminal word outranks the process exit code: a
    # scancel'ed, timed-out or OOM-killed job can still report 0:0, and
    # booking that as completed corrupts the ledger (the polar_cap OOM
    # incident).  COMPLETED (or no scheduler word at all, e.g. direct)
    # keeps the exit-code classification.
    if scheduler_state and scheduler_state != "COMPLETED":
        final = "failed"
    else:
        final = "completed" if exit_code == 0 else "failed"
    anomaly = None
    if final == "failed":
        err_text, out_text = _probe_run_logs(profile, identity)
        anomaly = classify_teardown_abort(err_text, out_text)
        if anomaly is not None:
            final = "completed"
    identity = dict(identity)
    identity["status"] = final
    identity["exit_code"] = exit_code
    identity["observed_at"] = now_utc()
    if anomaly is not None:
        identity["exit_anomaly"] = anomaly
    if scheduler_state:
        scheduler = dict(scheduler)
        scheduler["state"] = scheduler_state
        identity["scheduler"] = scheduler
    event_payload = {"run_id": run_id, "site_id": site_id, "status": final,
                     "exit_code": exit_code}
    if scheduler_state:
        event_payload["scheduler_state"] = scheduler_state
    if anomaly is not None:
        event_payload["exit_anomaly"] = anomaly
    _book_run(
        store, case, identity, final, {},
        "record.run-exit",
        event_payload,
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
        "exit_anomaly": anomaly,
    }


def record_run_abort(store, project_root, run_id, reason, actor,
                     case_slug=None):
    """Declare an in-flight run dead by human decision — the escape hatch
    for a run whose Site is permanently unreachable (retired machine, dead
    SSH), where no exit evidence can ever be probed.  Gates before any
    write: the run must exist and be in flight; a terminal run fails with
    zero writes.  ``reason`` is mandatory and lands in the identity payload
    and the audit event.  Aborted is terminal: the run can be relocated and
    migrated, and live status no longer probes it.  ``--reclassify`` does
    not apply to an aborted run; if the Site comes back, the outputs can
    still be inventoried with ``record data``."""
    if not reason or not reason.strip():
        raise PlanError("--reason must be non-empty")
    case = _require_case(store, project_root, case_slug)
    run_id = run_id or case.get("current", {}).get("run_id", "")
    if not run_id:
        raise PlanError(
            "Case has no current run",
            "needs_decision",
            [{"field": "run", "question": "select the run to abort"}],
        )
    identity = _run_identity(case, run_id)
    if identity is None:
        raise PlanError(
            "unknown run identity: %s" % run_id,
            "needs_decision",
            [{"field": "run", "question": "select a known run id"}],
        )
    status = identity.get("status", "")
    if status in TERMINAL_RUN_STATES:
        raise PlanError(
            "run %s is already terminal (%s); run-abort only applies to an "
            "in-flight run" % (run_id, status))
    payload = dict(identity)
    payload["status"] = "aborted"
    payload["abort"] = {"reason": reason.strip(),
                        "aborted_at": now_utc(),
                        "aborted_by": actor.get("run_id", "")}
    current = dict(case["current"])
    active = current.get("active_run") or {}
    if active.get("path") == identity.get("root", {}).get("path", ""):
        current["active_run"] = None
    readiness = dict(current.get("readiness", {}))
    readiness["run"] = "aborted"
    current["readiness"] = readiness
    with store.transaction() as connection:
        connection.execute(
            "UPDATE identities SET payload_json=? WHERE case_uid=? AND "
            "dimension='run' AND identity_id=?",
            (canonical_json(payload), case["case_uid"], run_id),
        )
        connection.execute(
            "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
            (canonical_json(current), now_utc(), case["case_uid"]),
        )
        store.record_event(
            case["case_uid"], None, "record.run-abort",
            {"run_id": run_id, "reason": reason.strip(),
             "previous_status": status},
            actor, connection)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.run-abort",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "run_id": run_id,
        "state": "aborted",
        "reason": reason.strip(),
        "previous_status": status,
    }


def record_run_correct(store, project_root, run_id, status, reason, actor,
                       case_slug=None):
    """Human correction between the two booked terminal states
    (completed <-> failed) — the counterpart of ``--reclassify``: that one
    re-judges a failed run from log evidence, this one records a human
    declaration (e.g. a run booked completed before the scheduler word was
    consulted, see the CANCELLED 0:0 incident).  Gates before any write:
    ``--reason`` is mandatory (it lands in the identity payload and the
    audit event), the run must exist and already be terminal — an
    in-flight run must reach its terminal state through ``record
    run-exit`` first.  Correcting to the same state is a no-op."""
    if status not in {"completed", "failed"}:
        raise PlanError("--status must be one of: completed, failed")
    if not reason or not reason.strip():
        raise PlanError("--reason must be non-empty")
    case = _require_case(store, project_root, case_slug)
    run_id = run_id or case.get("current", {}).get("run_id", "")
    if not run_id:
        raise PlanError(
            "Case has no current run",
            "needs_decision",
            [{"field": "run", "question": "select the run to correct"}],
        )
    identity = _run_identity(case, run_id)
    if identity is None:
        raise PlanError(
            "unknown run identity: %s" % run_id,
            "needs_decision",
            [{"field": "run", "question": "select a known run id"}],
        )
    previous = identity.get("status", "")
    if previous not in {"completed", "failed"}:
        raise PlanError(
            "run %s is %s; run-correct only rewrites a terminal state "
            "(completed/failed) — record run-exit first"
            % (run_id, previous or "unknown"))
    if previous == status:
        return {
            "schema_version": 1,
            "kind": "entity-ledger.record.run-correct",
            "ok": True,
            "state_mutated": False,
            "case_uid": case["case_uid"],
            "run_id": run_id,
            "state": status,
            "detail": "run is already %s; nothing to correct" % status,
        }
    payload = dict(identity)
    payload["status"] = status
    payload["correction"] = {"from": previous, "to": status,
                             "reason": reason.strip(),
                             "corrected_at": now_utc(),
                             "corrected_by": actor.get("run_id", "")}
    current = dict(case["current"])
    readiness = dict(current.get("readiness", {}))
    if current.get("run_id") == run_id:
        readiness["run"] = status
        current["readiness"] = readiness
    with store.transaction() as connection:
        connection.execute(
            "UPDATE identities SET payload_json=? WHERE case_uid=? AND "
            "dimension='run' AND identity_id=?",
            (canonical_json(payload), case["case_uid"], run_id),
        )
        connection.execute(
            "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
            (canonical_json(current), now_utc(), case["case_uid"]),
        )
        store.record_event(
            case["case_uid"], None, "record.run-correct",
            {"run_id": run_id, "from": previous, "to": status,
             "reason": reason.strip()},
            actor, connection)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.run-correct",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "run_id": run_id,
        "state": status,
        "previous_status": previous,
        "reason": reason.strip(),
    }


def _resolve_analysis_data(case, data_ref):
    """--data accepts a data_id directly or a run_id, which resolves to that
    run's recorded data identity (record data first otherwise)."""
    data_items = case.get("identities", {}).get("data", {}).get("items", [])
    identity = find_identity(data_items, data_ref)
    if identity is not None:
        return identity
    run = find_identity(
        case.get("identities", {}).get("run", {}).get("items", []), data_ref)
    if run is None:
        raise PlanError(
            "unknown run/data identity: %s" % data_ref,
            "needs_decision",
            [{"field": "data",
              "question": "select a recorded run or data identity"}],
        )
    for item in data_items:
        if item.get("parents", {}).get("run_id") == run.get("id"):
            return item
    raise PlanError(
        "run %s has no recorded data identity" % data_ref,
        "needs_decision",
        [{"field": "data",
          "question": "run entityctl record data first"}],
    )


def _analysis_script(store, case, script):
    """The script must live in the project's analysis script library
    (projects/<p>/analysis/scripts/); returns (normalized relative path,
    sha256)."""
    if not script or os.path.isabs(script):
        raise PlanError("--script must be a path relative to analysis/scripts/")
    script = os.path.normpath(script)
    if ".." in script.split(os.sep):
        raise PlanError("--script must be a path relative to analysis/scripts/")
    project_root = case.get("project_root") or ""
    if case.get("project_uid"):
        try:
            project_root = store.get_project(
                case["project_uid"]).get("project_root") or project_root
        except StoreError:
            pass
    if not project_root:
        raise PlanError("case has no project root for the script library")
    scripts_root = os.path.join(absolute(project_root), "analysis", "scripts")
    path = os.path.join(scripts_root, script)
    try:
        inside = os.path.commonpath(
            [os.path.realpath(path), os.path.realpath(scripts_root)]
        ) == os.path.realpath(scripts_root)
    except ValueError:
        inside = False
    if not inside or not os.path.isfile(path):
        raise PlanError(
            "analysis script not found in the project script library: %s "
            "(expected under %s)" % (script, scripts_root))
    return script, sha256_file(path)


def record_analysis(store, project_root, case_slug, script, data_ref, params,
                    output_root, env_stack, hardcoded_paths, actor):
    """Book an analysis execution (identity chain dimension 6).  Execution
    itself is the agent's free exploration; this primitive only re-probes
    the evidence and registers the fact — zero writes on any mismatch.

    Evidence gates: the script must exist in the project script library
    (content-hashed at booking time); ``<output_root>/analysis-manifest.json``
    must exist on its Site and name the claimed data_id (and, when the
    manifest carries script/params fields, they must match).  The
    analysis_id is derived deterministically from (data_id, script hash,
    params), so re-registering the same analysis is idempotent."""
    case = _require_case(store, project_root, case_slug)
    try:
        params = json.loads(params) if isinstance(params, str) else params
    except ValueError as exc:
        raise PlanError("--params must be a JSON object: %s" % exc)
    if not isinstance(params, dict):
        raise PlanError("--params must be a JSON object")
    data_identity = _resolve_analysis_data(case, data_ref)
    data_id = data_identity.get("id") or data_identity.get("identity_id", "")
    script, script_sha256 = _analysis_script(store, case, script)
    if not output_root or not str(output_root).startswith("/"):
        raise PlanError("--output-root must be an absolute path on its Site")
    output_root = os.path.normpath(output_root)
    site_id = data_identity.get("root", {}).get("site_id") \
        or data_identity.get("site_id", "")
    profile = store.get_site(site_id)
    manifest_path = os.path.join(output_root, "analysis-manifest.json")
    manifest = _read_site_json(profile, manifest_path, "analysis manifest")
    if manifest.get("data_id") != data_id:
        raise PlanError(
            "analysis manifest at the output root names data %s, not %s"
            % (manifest.get("data_id"), data_id))
    if manifest.get("script") and manifest["script"] != script:
        raise PlanError(
            "analysis manifest names script %s, not %s"
            % (manifest["script"], script))
    if manifest.get("script_sha256") \
            and manifest["script_sha256"] != script_sha256:
        raise PlanError("analysis manifest script hash differs from the "
                        "script library copy")
    if manifest.get("params") is not None \
            and manifest["params"] != params:
        raise PlanError("analysis manifest params differ from --params")
    analysis_id = "analysis-" + canonical_hash({
        "data_id": data_id, "script_sha256": script_sha256,
        "params": params,
    }).split(":", 1)[1][:16]
    run_id = data_identity.get("parents", {}).get("run_id", "")
    profile_merged, layout = merged_execution_profile(store, profile, case)
    conventional = ""
    if layout == "site-tree":
        conventional = os.path.normpath(os.path.join(
            profile_merged["roots"]["analysis_root"],
            case_path_segment(layout, case), analysis_id))
    identity = {
        "id": analysis_id, "kind": "analysis", "site_id": site_id,
        "root": {"site_id": site_id, "path": output_root},
        "parents": {"data_id": data_id, "run_id": run_id},
        "script": script,
        "script_sha256": script_sha256,
        "params": params,
        "env_stack": env_stack or "",
        "hardcoded_paths": bool(hardcoded_paths),
        "manifest": manifest_path,
        "status": "registered",
    }
    # A parent that already left current still records (history has value),
    # but as a historical entry: current.analysis_id and the is_current
    # marker are not rolled back to it.
    parent_current = data_id == case.get("current", {}).get("data_id", "")
    warnings = []
    if not parent_current:
        warnings.append(
            "parent data %s is no longer current; recorded as a historical "
            "entry, current.analysis_id unchanged" % data_id)
    current = dict(case["current"])
    with store.transaction() as connection:
        store.add_identity(
            case["case_uid"], "analysis", analysis_id, identity,
            parent_current, connection)
        if parent_current:
            current["analysis_id"] = analysis_id
            connection.execute(
                "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
                (canonical_json(current), now_utc(), case["case_uid"]),
            )
        store.record_event(
            case["case_uid"], None, "record.analysis",
            {"analysis_id": analysis_id, "data_id": data_id,
             "script": script, "env_stack": env_stack or "",
             "hardcoded_paths": bool(hardcoded_paths),
             "parent_current": parent_current},
            actor, connection)
    return {
        "schema_version": 1,
        "kind": "entity-ledger.record.analysis",
        "ok": True,
        "state_mutated": True,
        "case_uid": case["case_uid"],
        "analysis_id": analysis_id,
        "data_id": data_id,
        "run_id": run_id,
        "script": script,
        "script_sha256": script_sha256,
        "output_root": output_root,
        "env_stack": env_stack or "",
        "hardcoded_paths": bool(hardcoded_paths),
        "parent_current": parent_current,
        "warnings": warnings,
        "conventional_root": conventional,
        "at_conventional_root": bool(conventional) and output_root == conventional,
    }


def snapshot_source(store, project_root, actor, case_slug=None):
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
        # The returned manifest is the one actually archived — use it rather
        # than recomputing (TOCTOU).
        manifest = snapshot_archive(project_root, archive)
        archived = True
    snapshot_id = manifest["snapshot_id"]
    try:
        case = store.resolve_project(project_root, case_slug)
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
