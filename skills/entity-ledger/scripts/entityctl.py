#!/usr/bin/env python3
"""Compact public control-plane entrypoint for Entity simulation projects.

Read-only commands return controller-local summaries. The SQLite ledger.db in
the Ledger home is the sole structured controller authority.
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile

from entity_ledger_common import (
    LedgerError,
    absolute,
    actor_identity,
    atomic_write_json,
    load_json,
    now_utc,
    require_attributed_actor,
    ledger_home,
    run_on_site,
    sha256_file,
    validate_site_profile,
)
from entity_ledger_dashboard import build_dashboard, render_text
from entity_ledger_facts import PlanError
from entity_ledger_operation import status_for_project
from entity_ledger_record import (
    record_build,
    record_data,
    record_intent,
    record_run_exit,
    record_run_launch,
    record_run_prepare,
    render_run,
    show_case,
    snapshot_source,
)
from entity_ledger_store import (
    OperationStore,
    SCHEMA as STORE_SCHEMA,
    STORE_SCHEMA_VERSION,
    _migrate_legacy_db,
    canonical_hash,
    store_path,
)


SCHEMA_VERSION = 1
ENTITY_SKILLS = ("entity-ledger", "entity-pgen", "entity-env-build", "entity-nt2py")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_BUNDLE_ROOT = os.path.dirname(SKILL_ROOT)


class EntityCtlError(LedgerError):
    pass


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def trace_home():
    return absolute(os.environ.get(
        "ENTITY_SKILL_TRACE_HOME", "~/.entity-skills/observability"
    ))


def ignored_file(relative):
    parts = relative.split(os.sep)
    name = parts[-1]
    return (
        "__pycache__" in parts
        or name.endswith(".pyc")
        or name in {".DS_Store"}
    )


def bundle_version(root=SKILL_ROOT):
    try:
        with open(os.path.join(root, "VERSION"), "r") as handle:
            return handle.read().strip()
    except (IOError, OSError):
        return ""


def bundle_hash(root):
    root = absolute(root)
    digest = hashlib.sha256()
    files = 0
    for skill in ENTITY_SKILLS:
        skill_root = os.path.join(root, skill)
        if not os.path.isdir(skill_root):
            continue
        for current, directories, names in os.walk(skill_root):
            directories[:] = sorted(
                name for name in directories if name != "__pycache__"
            )
            for name in sorted(names):
                path = os.path.join(current, name)
                relative = os.path.relpath(path, root)
                if ignored_file(relative) or not os.path.isfile(path):
                    continue
                digest.update(relative.encode("utf-8"))
                digest.update(b"\0")
                with open(path, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                digest.update(b"\0")
                files += 1
    if not files:
        return {"hash": "", "files": 0}
    return {"hash": "sha256:" + digest.hexdigest(), "files": files}


def installed_bundle_roots():
    home = absolute("~")
    return [
        ("codex", os.path.join(home, ".codex", "skills")),
        ("claude", os.path.join(home, ".claude", "skills")),
        ("kimi", os.path.join(home, ".kimi-code", "skills")),
    ]


def copy_ignore(unused_directory, names):
    return [
        name for name in names
        if name == "__pycache__" or name == ".DS_Store" or name.endswith(".pyc")
    ]


def bundle_store_root():
    return absolute(os.environ.get("ENTITY_SKILLS_HOME", "~/.entity-skills"))


def unique_backup_root(product_home, bundle_id):
    stamp = now_utc().replace("-", "").replace(":", "")
    base = os.path.join(product_home, "backups", "%s-%s" % (stamp, bundle_id[:8]))
    candidate = base
    counter = 1
    while os.path.lexists(candidate):
        candidate = "%s-%d" % (base, counter)
        counter += 1
    return candidate


def materialize_bundle(source_root, product_home, identity):
    bundle_id = identity["hash"].split(":", 1)[1]
    bundles_root = os.path.join(product_home, "bundles")
    final_root = os.path.join(bundles_root, bundle_id)
    if os.path.isdir(final_root):
        installed = bundle_hash(final_root)
        if installed != identity:
            raise EntityCtlError("existing content-addressed bundle failed identity check")
        return final_root, False
    if os.path.lexists(final_root):
        raise EntityCtlError("bundle destination exists but is not a directory: %s" % final_root)
    if not os.path.isdir(bundles_root):
        os.makedirs(bundles_root)
    temporary = tempfile.mkdtemp(prefix=".bundle-", dir=bundles_root)
    try:
        for skill in ENTITY_SKILLS:
            source = os.path.join(source_root, skill)
            if not os.path.isdir(source):
                raise EntityCtlError("source bundle is missing skill: %s" % skill)
            shutil.copytree(
                source, os.path.join(temporary, skill), ignore=copy_ignore,
            )
        if bundle_hash(temporary) != identity:
            raise EntityCtlError("materialized bundle identity differs from source")
        os.rename(temporary, final_root)
    finally:
        if os.path.isdir(temporary):
            shutil.rmtree(temporary)
    return final_root, True


def activate_current(product_home, bundle_root):
    current = os.path.join(product_home, "current")
    if os.path.isdir(current) and not os.path.islink(current):
        raise EntityCtlError("shared current selector is a directory, refusing to replace it")
    temporary = os.path.join(product_home, ".current-%d" % os.getpid())
    if os.path.lexists(temporary):
        raise EntityCtlError("temporary current selector already exists: %s" % temporary)
    os.symlink(bundle_root, temporary)
    os.replace(temporary, current)
    return current


def project_client_install(client_root, current, backup_root, provider):
    if not os.path.isdir(client_root):
        os.makedirs(client_root)
    projected = []
    backed_up = []
    for skill in ENTITY_SKILLS:
        target = os.path.join(client_root, skill)
        desired = os.path.join(current, skill)
        if os.path.islink(target) and os.path.realpath(target) == os.path.realpath(desired):
            projected.append(target)
            continue
        backup = os.path.join(backup_root, provider, skill)
        if os.path.lexists(target):
            parent = os.path.dirname(backup)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            os.rename(target, backup)
            backed_up.append(backup)
        try:
            os.symlink(desired, target)
        except Exception:
            if os.path.lexists(backup) and not os.path.lexists(target):
                os.rename(backup, target)
            raise
        projected.append(target)
    return projected, backed_up


def install_bundle(args):
    actor = require_attributed_actor(actor_identity(args))
    source_root = absolute(args.source_root)
    identity = bundle_hash(source_root)
    if not identity["hash"] or identity["files"] == 0:
        raise EntityCtlError("source root does not contain an Entity skill bundle")
    product_home = bundle_store_root()
    if not os.path.isdir(product_home):
        os.makedirs(product_home)
    bundle_root, created = materialize_bundle(source_root, product_home, identity)
    current = activate_current(product_home, bundle_root)
    backup_root = unique_backup_root(
        product_home, identity["hash"].split(":", 1)[1]
    )
    projections = []
    backups = []
    for provider, client_root in installed_bundle_roots():
        provider_projections, provider_backups = project_client_install(
            client_root, current, backup_root, provider,
        )
        projections.extend(provider_projections)
        backups.extend(provider_backups)
    if not backups:
        backup_root = ""
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.bundle.install",
        "installation_state_mutated": True,
        "project_state_mutated": False,
        "case_state_mutated": False,
        "actor": actor,
        "source_root": source_root,
        "bundle_root": bundle_root,
        "bundle_version": bundle_version(os.path.join(source_root, "entity-ledger")),
        "bundle_hash": identity["hash"],
        "bundle_files": identity["files"],
        "bundle_created": created,
        "current": current,
        "client_projections": projections,
        "backup_root": backup_root,
        "backups": backups,
    }


def doctor(args):
    home = ledger_home(args.ledger_home)
    runtime_bundle = bundle_hash(DEFAULT_BUNDLE_ROOT)
    actor = actor_identity(args)
    expected_bundle = actor.get("bundle_hash", "")
    warnings = []
    failures = []
    if expected_bundle and expected_bundle != runtime_bundle["hash"]:
        warnings.append("ENTITY_SKILLS_BUNDLE_HASH differs from the loaded runtime bundle")
    if actor["run_id"] == "unattributed":
        warnings.append("mutations will be unattributed unless an Agent run ID is supplied")
    database = store_path(home)
    profiles = []
    store_schema = None
    if os.path.isfile(database):
        exported = OperationStore(home, create=False).export()
        profiles = exported["sites"]
        connection = sqlite3.connect(database)
        try:
            row = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            store_schema = int(row[0]) if row else None
        except Exception:
            store_schema = None
        finally:
            connection.close()
        if store_schema != STORE_SCHEMA_VERSION:
            warnings.append(
                "store schema %s differs from runtime schema %s; run "
                "entityctl store migrate" % (store_schema, STORE_SCHEMA_VERSION)
            )
    else:
        warnings.append("store is unavailable; register Sites with entityctl site add")
    for profile in profiles:
        try:
            validate_site_profile(profile)
        except Exception as exc:
            failures.append(
                "Site %s profile fails validation: %s"
                % (profile.get("site_id", "?"), exc)
            )
        policy = profile.get("policy", {})
        if (profile.get("scheduler", {}).get("kind") == "slurm"
                and not policy.get("default_partition")):
            warnings.append("Site %s has no policy.default_partition" % profile["site_id"])
        if (profile.get("transport", {}).get("kind") == "ssh"
                and profile.get("scheduler", {}).get("kind") == "slurm"
                and not policy.get("default_submit_user")):
            warnings.append("Site %s has no policy.default_submit_user" % profile["site_id"])
    installs = []
    for provider, path in installed_bundle_roots():
        identity = bundle_hash(path) if os.path.isdir(path) else {"hash": "", "files": 0}
        entry = {
            "provider": provider,
            "path": path,
            "exists": os.path.isdir(path),
            "bundle_version": bundle_version(os.path.join(path, "entity-ledger")),
            "bundle_hash": identity["hash"],
            "files": identity["files"],
            "matches_runtime": bool(identity["hash"] and identity["hash"] == runtime_bundle["hash"]),
        }
        installs.append(entry)
        if entry["exists"] and entry["bundle_hash"] and not entry["matches_runtime"]:
            failures.append(
                "client install %s (%s) has drifted from the runtime bundle; "
                "reinstall with entityctl bundle install" % (provider, path)
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not failures,
        "kind": "entityctl.doctor",
        "state_mutated": False,
        "controller": {
            "ledger_home": home,
            "available": os.path.isdir(home),
            "store": database,
            "store_available": os.path.isfile(database),
            "store_schema_version": store_schema,
        },
        "trace_home": trace_home(),
        "runtime_bundle": {
            "root": DEFAULT_BUNDLE_ROOT,
            "version": bundle_version(),
            "bundle_hash": runtime_bundle["hash"],
            "files": runtime_bundle["files"],
        },
        "actor": actor,
        "client_installs": installs,
        "failures": failures,
        "warnings": warnings,
    }


def site_add(args):
    actor = require_attributed_actor(actor_identity(args))
    profile = validate_site_profile(load_json(args.profile, "Site profile"))
    store = OperationStore(args.ledger_home)
    store.upsert_site(profile)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.add",
        "state_mutated": True,
        "actor": actor,
        "site_id": profile["site_id"],
    }


def site_list(args):
    store = OperationStore(args.ledger_home, create=False)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.list",
        "state_mutated": False,
        "sites": store.export()["sites"],
    }


def site_discover(args):
    """Probe a Site so policy defaults are chosen from facts, not guesses.
    Read-only; dispatched by the Site scheduler kind."""
    store = OperationStore(args.ledger_home, create=False)
    profile = store.get_site(args.site_id)
    kind = profile.get("scheduler", {}).get("kind")
    backend = DISCOVER_BACKENDS.get(kind)
    if backend is None:
        raise EntityCtlError(
            "site discovery currently supports scheduler kinds: %s (got '%s')"
            % (", ".join(sorted(DISCOVER_BACKENDS)), kind)
        )
    return backend(profile)


def _slurm_site_discover(profile):
    """Enumerate legal Slurm partitions/QoS on a Site so policy defaults are
    chosen from facts, not guesses. Read-only; at most two scheduler calls."""
    ssh = profile.get("transport", {}).get("kind") == "ssh"
    remote_calls = 0
    code, stdout, stderr = run_on_site(
        profile, ["sinfo", "-h", "-o", "%P|%a|%l|%G|%D|%c"]
    )
    if ssh:
        remote_calls += 1
    if code != 0:
        raise EntityCtlError(
            "sinfo failed on Site %s: %s"
            % (profile["site_id"], (stderr.strip() or stdout.strip()))
        )
    partitions = []
    for line in stdout.splitlines():
        fields = line.strip().split("|")
        if len(fields) < 6 or not fields[0]:
            continue
        partitions.append({
            "name": fields[0].rstrip("*"), "default": fields[0].endswith("*"),
            "state": fields[1], "timelimit": fields[2], "gres": fields[3],
            "nodes": fields[4], "cpus": fields[5],
        })
    warnings = []
    qos = []
    code, stdout, stderr = run_on_site(
        profile, ["sacctmgr", "-n", "list", "qos", "format=Name"]
    )
    if ssh:
        remote_calls += 1
    if code != 0:
        warnings.append(
            "sacctmgr failed; QoS list unavailable: %s"
            % (stderr.strip() or stdout.strip())
        )
    else:
        qos = sorted({line.strip() for line in stdout.splitlines() if line.strip()})
    suggested = {}
    defaults = [item["name"] for item in partitions if item["default"]]
    if defaults:
        suggested["default_partition"] = defaults[0]
    elif partitions:
        suggested["default_partition"] = partitions[0]["name"]
    if len(qos) == 1:
        suggested["default_qos"] = qos[0]
    elif qos:
        suggested["default_qos"] = ""
        warnings.append("multiple QoS available; choose one explicitly: %s" % ", ".join(qos))
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.discover",
        "state_mutated": False,
        "remote_calls": remote_calls,
        "site_id": profile["site_id"],
        "partitions": partitions,
        "qos": qos,
        "suggested_policy": suggested,
        "warnings": warnings,
    }


DISCOVER_BACKENDS = {"slurm": _slurm_site_discover}


def _direct_site_discover(profile):
    """Probe a scheduler-less Site: basic execution environment (bash,
    python3, timeout), GPU availability via nvidia-smi, and writability of
    the declared roots.  Read-only; at most three bounded probes."""
    ssh = profile.get("transport", {}).get("kind") == "ssh"
    remote_calls = 0
    warnings = []
    environment = {"bash": "", "python3": "", "timeout": ""}
    code, stdout, stderr = run_on_site(profile, [
        "bash", "-c",
        "bash --version | head -1; python3 --version 2>&1; "
        "command -v timeout || command -v gtimeout || true",
    ])
    if ssh:
        remote_calls += 1
    if code != 0:
        raise EntityCtlError(
            "environment probe failed on Site %s: %s"
            % (profile["site_id"], (stderr.strip() or stdout.strip()))
        )
    lines = [line.strip() for line in stdout.splitlines()]
    environment["bash"] = lines[0] if len(lines) > 0 else ""
    environment["python3"] = lines[1] if len(lines) > 1 else ""
    environment["timeout"] = lines[2] if len(lines) > 2 else ""
    if not environment["python3"].startswith("Python"):
        warnings.append("python3 is unavailable; the Site executor cannot run")
    if not environment["timeout"]:
        warnings.append(
            "no timeout/gtimeout on the Site; run.sh uses its embedded "
            "bash timeout for walltime enforcement"
        )
    gpus = []
    try:
        code, stdout, stderr = run_on_site(
            profile, ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]
        )
    except OSError as exc:
        code, stdout, stderr = 127, "", str(exc)
    if ssh:
        remote_calls += 1
    if code != 0:
        warnings.append(
            "nvidia-smi unavailable; GPU runs will fail preflight: %s"
            % (stderr.strip() or stdout.strip() or "exit %d" % code)
        )
    else:
        gpus = [line.strip() for line in stdout.splitlines() if line.strip()]
    roots = {}
    declared = sorted(
        (name, path) for name, path in profile.get("roots", {}).items() if path
    )
    if declared:
        code, stdout, stderr = run_on_site(profile, [
            "bash", "-c",
            'for d in "$@"; do probe="$d"; '
            'while [ ! -d "$probe" ]; do probe=$(dirname "$probe"); done; '
            'if [ -w "$probe" ]; then echo "$d|writable"; '
            'else echo "$d|readonly"; fi; done',
            "bash",
        ] + [path for unused_name, path in declared])
        if ssh:
            remote_calls += 1
        if code != 0:
            raise EntityCtlError(
                "root probe failed on Site %s: %s"
                % (profile["site_id"], (stderr.strip() or stdout.strip()))
            )
        writable = {}
        for line in stdout.splitlines():
            path, unused, state = line.rpartition("|")
            if path and state in {"writable", "readonly"}:
                writable[path] = state == "writable"
        for name, path in declared:
            roots[name] = {"path": path, "writable": writable.get(path, False)}
            if not roots[name]["writable"]:
                warnings.append("root %s is not writable: %s" % (name, path))
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.discover",
        "state_mutated": False,
        "remote_calls": remote_calls,
        "site_id": profile["site_id"],
        "environment": environment,
        "gpus": gpus,
        "roots": roots,
        "suggested_policy": {},
        "warnings": warnings,
    }


DISCOVER_BACKENDS["none"] = _direct_site_discover


def show_command(args):
    store = OperationStore(args.ledger_home, create=False)
    return show_case(store, args.project_root)


def render_run_command(args):
    store = OperationStore(args.ledger_home, create=False)
    return render_run(
        store, args.project_root, args.toml, args.site, args.gpus,
        args.walltime, args.precision, args.executable)


def record_run_prepare_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_run_prepare(
        store, args.project_root, args.toml, args.site, args.gpus,
        args.walltime, args.precision, args.executable, actor)


def record_run_launch_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_run_launch(
        store, args.project_root, args.run_id, args.adopt_job, args.adopt_pid,
        actor)


def record_run_exit_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_run_exit(store, args.project_root, args.run_id, actor)


def record_build_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_build(
        store, args.project_root, args.site, args.checkpoint, args.executable, actor)


def record_data_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_data(store, args.project_root, args.run_id, actor)


def snapshot_source_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return snapshot_source(store, args.project_root, actor)


def record_intent_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_intent(store, args.project_root, args.text, actor)


def project_status(args):
    store = OperationStore(args.ledger_home, create=False)
    result = status_for_project(store, args.project_root, args.live)
    if args.json:
        return result
    dashboard = build_dashboard(store, args.project_root, result)
    return {
        "schema_version": 1, "kind": "entity-ledger.status", "ok": True,
        "state_mutated": False,
        "remote_calls": dashboard["remote_calls"],
        "_entityctl_text": render_text(dashboard),
    }


def export_store(args):
    store = OperationStore(args.ledger_home, create=False)
    payload = store.export()
    atomic_write_json(args.output, payload)
    return {
        "schema_version": 1, "kind": "entity-ledger.export", "ok": True,
        "state_mutated": False, "output": absolute(args.output),
        "cases": len(payload["cases"]),
    }


def _archive_operations_v1(connection, archive_dir, stamp):
    """Export a v1 store's operations (with their steps) to a JSON archive so
    the retired plan/apply protocol history stays readable after migration."""
    operations = []
    for row in connection.execute(
            "SELECT * FROM operations ORDER BY created_at"):
        operation = dict(row)
        operation["goal"] = json.loads(operation.pop("goal_json"))
        operation["plan"] = json.loads(operation.pop("plan_json"))
        operation["result"] = json.loads(operation.pop("result_json"))
        operation["actor"] = json.loads(operation.pop("actor_json"))
        steps = []
        for step in connection.execute(
                "SELECT * FROM steps WHERE operation_id=? ORDER BY step_index",
                (operation["operation_id"],)):
            item = dict(step)
            for key in ["spec_json", "effect_json", "evidence_json", "error_json"]:
                item[key[:-5]] = json.loads(item.pop(key))
            steps.append(item)
        operation["steps"] = steps
        operations.append(operation)
    archive = os.path.join(archive_dir, "operations-v1-%s.json" % stamp)
    atomic_write_json(archive, {
        "schema_version": 1,
        "kind": "entity-ledger.operations-archive",
        "archived_at": now_utc(),
        "operations": operations,
    })
    return archive, len(operations)


def _migrate_v1_to_v2(database, home):
    """Migrate a v1 store to v2: archive operations/steps to JSON, back the
    original file up, then rebuild the store with the v2 schema and copy
    sites/cases/projects/identities/events over (cases loses
    active_operation_id; events keeps its operation_id audit column)."""
    archive_dir = os.path.join(home, "archive")
    if not os.path.isdir(archive_dir):
        os.makedirs(archive_dir)
    stamp = now_utc().replace(":", "-").replace("Z", "")
    source = sqlite3.connect(database)
    source.row_factory = sqlite3.Row
    try:
        archive, operation_count = _archive_operations_v1(source, archive_dir, stamp)
        tables = {}
        for name, columns in [
                ("meta", "key,value"),
                ("sites", "site_id,profile_json,updated_at"),
                ("cases", "case_uid,case_id,project_root,source_json,current_json,"
                          "legacy_json,created_at,updated_at"),
                ("projects", "project_root,case_uid,updated_at"),
                ("identities", "case_uid,dimension,identity_id,payload_json,"
                                "is_current,created_at"),
                ("events", "case_uid,operation_id,event_type,payload_json,"
                           "actor_json,created_at")]:
            tables[name] = (
                columns,
                [tuple(row) for row in source.execute(
                    "SELECT %s FROM %s" % (columns, name))],
            )
    finally:
        source.close()
    backup = os.path.join(archive_dir, "ledger-v1-%s.db" % stamp)
    shutil.copy2(database, backup)
    temporary = database + ".migrate-v2"
    if os.path.isfile(temporary):
        os.unlink(temporary)
    target = sqlite3.connect(temporary)
    try:
        target.executescript(STORE_SCHEMA)
        for name in ["meta", "sites", "cases", "projects", "identities", "events"]:
            columns, rows = tables[name]
            placeholders = ",".join(["?"] * len(columns.split(",")))
            target.executemany(
                "INSERT INTO %s(%s) VALUES(%s)" % (name, columns, placeholders),
                rows)
        target.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
            (str(STORE_SCHEMA_VERSION),))
        target.commit()
    except Exception:
        target.close()
        os.unlink(temporary)
        raise
    target.close()
    os.replace(temporary, database)
    counts = dict((name, len(rows)) for name, (unused, rows) in tables.items())
    return {
        "schema_version": 1, "kind": "entity-ledger.store.migrate", "ok": True,
        "state_mutated": True, "store_schema_version": STORE_SCHEMA_VERSION,
        "message": "migrated store schema 1 -> %s" % STORE_SCHEMA_VERSION,
        "operations_archive": archive, "operations_archived": operation_count,
        "database_backup": backup, "rows_copied": counts,
    }


def store_migrate(args):
    home = ledger_home(args.ledger_home)
    if os.path.isdir(home):
        _migrate_legacy_db(home)
    database = store_path(home)
    if not os.path.isfile(database):
        raise EntityCtlError(
            "store does not exist; nothing to migrate (register a Site with "
            "entityctl site add)"
        )
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        current = int(row[0]) if row else None
    finally:
        connection.close()
    if current == STORE_SCHEMA_VERSION:
        return {
            "schema_version": 1, "kind": "entity-ledger.store.migrate", "ok": True,
            "state_mutated": False, "store_schema_version": current,
            "message": "store is already at the current schema",
        }
    if current is not None and current > STORE_SCHEMA_VERSION:
        raise EntityCtlError(
            "store schema %s is newer than this bundle supports (%s); use a "
            "newer bundle" % (current, STORE_SCHEMA_VERSION)
        )
    if current == 1:
        return _migrate_v1_to_v2(database, ledger_home(args.ledger_home))
    raise EntityCtlError(
        "no migration path from store schema %s to %s is implemented yet"
        % (current, STORE_SCHEMA_VERSION)
    )


def _submission_body(store, project_root, artifacts, note, actor):
    status = status_for_project(store, project_root)
    current = status.get("current", {})
    identities = {
        key: current.get(key, "")
        for key in ["source_id", "build_id", "run_id", "data_id", "analysis_id"]
    }
    return {
        "schema_version": 1,
        "kind": "entity-ledger.submission",
        "case_uid": status["case_uid"],
        "project_root": absolute(project_root),
        "identities": identities,
        "run": status.get("run"),
        "artifacts": artifacts,
        "note": note,
        "actor": actor,
        "created_at": now_utc(),
    }


def submission_create(args):
    """Create a submission whose fingerprints are always recomputed by the
    tool from the final artifacts — never copied from older documents."""
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    artifacts = []
    for raw in args.artifact or []:
        path = absolute(raw)
        if not os.path.isfile(path):
            raise EntityCtlError("submission artifact does not exist: %s" % path)
        artifacts.append({
            "path": path,
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
        })
    artifacts.sort(key=lambda item: item["path"])
    body = _submission_body(store, args.project_root, artifacts, args.note, actor)
    body["fingerprint"] = canonical_hash(body)
    atomic_write_json(args.output, body)
    result = dict(body)
    result["ok"] = True
    result["state_mutated"] = False
    result["output"] = absolute(args.output)
    return result


def submission_verify(args):
    """Recompute every artifact fingerprint and the submission fingerprint;
    any drift since creation fails verification."""
    submission = load_json(args.submission, "submission")
    if submission.get("kind") != "entity-ledger.submission":
        raise EntityCtlError("not an entity-ledger.submission document")
    stale = []
    missing = []
    for item in submission.get("artifacts", []):
        path = item.get("path", "")
        if not os.path.isfile(path):
            missing.append(path)
        elif sha256_file(path) != item.get("sha256"):
            stale.append(path)
    body = dict(submission)
    expected = body.pop("fingerprint", "")
    fingerprint_match = canonical_hash(body) == expected
    ok = fingerprint_match and not stale and not missing
    return {
        "schema_version": 1,
        "kind": "entity-ledger.submission.verify",
        "ok": ok,
        "state_mutated": False,
        "fingerprint_match": fingerprint_match,
        "stale": stale,
        "missing": missing,
    }


def add_actor_arguments(parser):
    parser.add_argument("--actor-run-id")
    parser.add_argument("--actor-provider")
    parser.add_argument("--actor-client")
    parser.add_argument("--actor-session-id")
    parser.add_argument("--actor-model")
    parser.add_argument("--actor-bundle-hash")


def add_run_compute_arguments(parser):
    parser.add_argument("--gpus", type=int, default=1)
    parser.add_argument("--walltime", default="01:00:00",
                        help="HH:MM:SS or D-HH:MM:SS")
    parser.add_argument("--precision", default="double",
                        choices=["single", "double"])
    parser.add_argument("--executable", default="",
                        help="absolute path on the execution Site; defaults to "
                             "the current verified build identity")


def build_parser():
    parser = argparse.ArgumentParser(description="Entity public control-plane CLI")
    # Lazy default: resolving the Ledger home can trigger the one-time
    # ~/.entity-router -> ~/.entity-ledger migration, which must not run as a
    # side effect of merely building the parser (e.g. entityctl --help).
    parser.add_argument("--ledger-home", "--router-home", dest="ledger_home",
                        default=None)
    add_actor_arguments(parser)
    sub = parser.add_subparsers(
        dest="command",
        metavar="{doctor,status,show,render-run,snapshot-source,record,site,store,submission,export,install}"
    )
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.set_defaults(func=doctor)

    snapshot = sub.add_parser("snapshot-source")
    snapshot.add_argument("--project-root", required=True)
    snapshot.set_defaults(func=snapshot_source_command)

    current_status = sub.add_parser("status")
    current_status.add_argument("--project-root", required=True)
    current_status.add_argument("--live", action="store_true")
    current_status.add_argument(
        "--json", action="store_true",
        help="emit the machine-readable controller facts instead of the "
             "human-readable dashboard")
    current_status.set_defaults(func=project_status)

    show = sub.add_parser("show")
    show.add_argument("--project-root", required=True)
    show.set_defaults(func=show_command)

    render = sub.add_parser("render-run")
    render.add_argument("--project-root", required=True)
    render.add_argument("--toml", required=True)
    render.add_argument("--site", required=True)
    add_run_compute_arguments(render)
    render.set_defaults(func=render_run_command)

    record = sub.add_parser("record")
    record_sub = record.add_subparsers(dest="record_command")
    record_build_parser = record_sub.add_parser("build")
    record_build_parser.add_argument("--project-root", required=True)
    record_build_parser.add_argument("--site", required=True)
    record_build_parser.add_argument("--checkpoint", required=True)
    record_build_parser.add_argument("--executable", required=True)
    record_build_parser.set_defaults(func=record_build_command)
    record_data_parser = record_sub.add_parser("data")
    record_data_parser.add_argument("--project-root", required=True)
    record_data_parser.add_argument("--run-id", default="")
    record_data_parser.set_defaults(func=record_data_command)
    record_run_prepare_parser = record_sub.add_parser("run-prepare")
    record_run_prepare_parser.add_argument("--project-root", required=True)
    record_run_prepare_parser.add_argument("--toml", required=True)
    record_run_prepare_parser.add_argument("--site", required=True)
    add_run_compute_arguments(record_run_prepare_parser)
    record_run_prepare_parser.set_defaults(func=record_run_prepare_command)
    record_run_launch_parser = record_sub.add_parser("run-launch")
    record_run_launch_parser.add_argument("--project-root", required=True)
    record_run_launch_parser.add_argument("--run-id", default="")
    adopt = record_run_launch_parser.add_mutually_exclusive_group()
    adopt.add_argument("--adopt-job", default="",
                       help="adopt an out-of-band Slurm job id into the ledger")
    adopt.add_argument("--adopt-pid", default="",
                       help="adopt an out-of-band process id into the ledger")
    record_run_launch_parser.set_defaults(func=record_run_launch_command)
    record_run_exit_parser = record_sub.add_parser("run-exit")
    record_run_exit_parser.add_argument("--project-root", required=True)
    record_run_exit_parser.add_argument("--run-id", default="")
    record_run_exit_parser.set_defaults(func=record_run_exit_command)

    record_intent_parser = record_sub.add_parser("intent")
    record_intent_parser.add_argument("--project-root", required=True)
    record_intent_parser.add_argument("--text", required=True)
    record_intent_parser.set_defaults(func=record_intent_command)

    site = sub.add_parser("site")
    site_sub = site.add_subparsers(dest="site_command")
    site_add_parser = site_sub.add_parser("add")
    site_add_parser.add_argument("--profile", required=True)
    site_add_parser.set_defaults(func=site_add)
    site_list_parser = site_sub.add_parser("list")
    site_list_parser.set_defaults(func=site_list)
    site_discover_parser = site_sub.add_parser("discover")
    site_discover_parser.add_argument("site_id")
    site_discover_parser.set_defaults(func=site_discover)

    store_cmd = sub.add_parser("store")
    store_sub = store_cmd.add_subparsers(dest="store_command")
    migrate = store_sub.add_parser("migrate")
    migrate.set_defaults(func=store_migrate)

    submission = sub.add_parser("submission")
    submission_sub = submission.add_subparsers(dest="submission_command")
    submission_create_parser = submission_sub.add_parser("create")
    submission_create_parser.add_argument("--project-root", required=True)
    submission_create_parser.add_argument("--output", required=True)
    submission_create_parser.add_argument("--artifact", action="append", default=[])
    submission_create_parser.add_argument("--note", default="")
    submission_create_parser.set_defaults(func=submission_create)
    submission_verify_parser = submission_sub.add_parser("verify")
    submission_verify_parser.add_argument("--submission", required=True)
    submission_verify_parser.set_defaults(func=submission_verify)

    export = sub.add_parser("export")
    export.add_argument("--output", required=True)
    export.set_defaults(func=export_store)

    direct_install = sub.add_parser("install")
    direct_install.add_argument("--source-root", default=DEFAULT_BUNDLE_ROOT)
    direct_install.set_defaults(func=install_bundle)

    bundle = sub.add_parser("bundle")
    bundle_sub = bundle.add_subparsers(dest="bundle_command")
    install = bundle_sub.add_parser("install")
    install.add_argument("--source-root", default=DEFAULT_BUNDLE_ROOT)
    install.set_defaults(func=install_bundle)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.error("a command is required")
    try:
        payload = args.func(args)
        exit_code = payload.pop("_entityctl_exit_code", None)
        text = payload.pop("_entityctl_text", None)
        if text is not None:
            print(text)
        else:
            emit(payload)
        if exit_code is not None:
            return exit_code
        return 0 if payload.get("ok", True) else 2
    except PlanError as exc:
        emit({"ok": False, "status": exc.status, "error": str(exc),
              "decisions": exc.decisions, "state_mutated": False})
        return 2
    except (IOError, OSError, ValueError, KeyError, TypeError, LedgerError,
            sqlite3.Error, tarfile.TarError) as exc:
        emit({"ok": False, "status": "anomaly", "error": str(exc),
              "state_mutated": False})
        return 2


if __name__ == "__main__":
    sys.exit(main())
