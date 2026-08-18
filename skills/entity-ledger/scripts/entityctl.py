#!/usr/bin/env python3
"""Compact public control-plane entrypoint for Entity simulation projects.

Read-only commands return controller-local summaries. The SQLite ledger.db in
the Ledger home is the sole structured controller authority.
"""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import sys
import tarfile
import tempfile

from entity_ledger_common import (
    LedgerError,
    absolute,
    active_workspace_pointer,
    actor_identity,
    atomic_write_json,
    load_json,
    now_utc,
    require_attributed_actor,
    run_command,
    run_on_site,
    sha256_file,
    site_file_sha256,
    source_manifest,
    valid_gres,
    validate_site_profile,
    validate_slug,
    write_active_workspace,
)
from entity_ledger_dashboard import build_dashboard, render_text
from entity_ledger_facts import (
    PlanError,
    _git_revision,
    _source_site,
    require_verified_checkpoint,
)
from entity_ledger_operation import status_for_project
from entity_ledger_record import (
    TERMINAL_RUN_STATES,
    record_analysis,
    record_build,
    record_data,
    record_intent,
    record_relocate,
    record_run_abort,
    record_run_correct,
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
    SCHEMA_V2,
    STORE_SCHEMA_VERSION,
    _migrate_legacy_db,
    canonical_hash,
    resolve_ledger_home,
    store_path,
    workspace_ledger_home,
)
from entity_ledger_workspace import (
    PROJECT_FIELDS,
    SITE_MARKER,
    SITE_MARKER_FIELDS,
    SITE_TREE_DIRS,
    STACK_YAML_FIELDS,
    derive_stack_id,
    init_case,
    init_project,
    init_workspace,
    list_site_archives,
    load_flat_yaml,
    load_project_yaml,
    load_site_yaml,
    load_workspace_yaml,
    parse_flat_yaml_text,
    profile_from_archive,
    require_workspace,
    site_marker_record,
    site_yaml_path,
    stack_packages,
    stack_signature,
    upsert_deps_stack,
    workspace_for_ledger_home,
    write_flat_yaml,
    write_site_yaml,
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
    providers = []
    wanted = set(args.provider or [])
    for provider, client_root in installed_bundle_roots():
        if wanted and provider not in wanted:
            continue
        provider_projections, provider_backups = project_client_install(
            client_root, current, backup_root, provider,
        )
        providers.append(provider)
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
        "providers": providers,
        "client_projections": projections,
        "backup_root": backup_root,
        "backups": backups,
    }


def doctor(args):
    if getattr(args, "project_root", None):
        # doctor inspects the controller/workspace as a whole (store schema,
        # bundle drift, site profiles); nothing in it is project-filterable
        raise PlanError(
            "doctor is workspace-scoped; use status --project-root %s"
            % args.project_root, "invalid_request")
    home, resolution = resolve_ledger_home(args.ledger_home)
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
            # an unmigrated legacy store must be a doctor FINDING, never a
            # crash: skip the export and report the migration path instead
            warnings.append(
                "store schema %s differs from runtime schema %s; run "
                "entityctl store migrate" % (store_schema, STORE_SCHEMA_VERSION)
            )
        else:
            exported = OperationStore(home, create=False).export()
            profiles = exported["sites"]
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
                "reinstall with entityctl install" % (provider, path)
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not failures,
        "kind": "entityctl.doctor",
        "state_mutated": False,
        "controller": {
            "ledger_home": home,
            "ledger_home_resolution": resolution,
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


def _site_view(store):
    """Merged site view: the workspace archives are the authority; sites
    known only to the db are marked db-only (never auto-deleted)."""
    workspace = workspace_for_ledger_home(store.home)
    archives = list_site_archives(workspace) if workspace else {}
    db_sites = store.export()["sites"]
    return workspace, archives, db_sites


def site_sync(args):
    """Refresh the db sites table from the workspace archives (archive ->
    db).  Sites present only in the db are reported, never deleted."""
    actor = require_attributed_actor(actor_identity(args))
    home, unused_resolution = resolve_ledger_home(args.ledger_home)
    workspace = require_workspace(home)
    store = OperationStore(home)
    archives = list_site_archives(workspace)
    if args.site_id:
        if args.site_id not in archives:
            raise EntityCtlError(
                "no site archive for %s under %s"
                % (args.site_id, os.path.join(workspace, "sites")))
        selected = {args.site_id: archives[args.site_id]}
    else:
        selected = archives
    synced = []
    for site_id, record in sorted(selected.items()):
        profile = validate_site_profile(profile_from_archive(record))
        store.upsert_site(profile)
        synced.append(site_id)
    db_only = sorted(
        site["site_id"] for site in store.export()["sites"]
        if site["site_id"] not in archives)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.sync",
        "state_mutated": bool(synced),
        "actor": actor,
        "workspace": workspace,
        "synced": synced,
        "db_only": db_only,
    }


def site_list(args):
    store = OperationStore(args.ledger_home, create=False)
    workspace, archives, db_sites = _site_view(store)
    db_by_id = dict((site["site_id"], site) for site in db_sites)
    entries = []
    for site_id in sorted(set(archives) | set(db_by_id)):
        archive = archives.get(site_id)
        profile = db_by_id.get(site_id) or {}
        source = archive or profile
        transport = source.get("transport", {})
        scheduler = source.get("scheduler", {})
        entries.append({
            "site_id": site_id,
            "origin": "archive" if archive else "db-only",
            "transport": transport.get("kind", ""),
            "scheduler": scheduler.get("kind", ""),
            "site_root": source.get("site_root", ""),
            "projects": source.get("projects", []),
            "deps": len(source.get("deps", []) or []),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.list",
        "state_mutated": False,
        "workspace": workspace,
        "sites": entries,
    }


def site_show(args):
    store = OperationStore(args.ledger_home, create=False)
    workspace, archives, db_sites = _site_view(store)
    archive = archives.get(args.site_id)
    profile = next((site for site in db_sites
                    if site["site_id"] == args.site_id), None)
    if archive is None and profile is None:
        raise EntityCtlError("unknown site_id: %s" % args.site_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.show",
        "state_mutated": False,
        "site_id": args.site_id,
        "origin": "archive" if archive else "db-only",
        "archive": archive,
        "archive_path": site_yaml_path(workspace, args.site_id)
        if workspace and archive else "",
        "profile": profile,
        "effective_profile": profile_from_archive(archive)
        if archive else profile,
    }


def _scp_to_site(profile, source, target):
    code, unused, stderr = run_command([
        "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--",
        source, "%s:%s" % (profile["transport"]["ssh_alias"], shlex.quote(target)),
    ])
    if code != 0:
        raise EntityCtlError("cannot stage file to Site: %s" % stderr.strip())


def _read_site_marker(profile, marker_path):
    """Read entity-site.yaml off a Site; returns the parsed record, None
    when absent.  A transport failure is an error (never silently treated
    as "absent", which would make site init overwrite a live marker)."""
    if profile.get("transport", {}).get("kind") == "local":
        if not os.path.isfile(marker_path):
            return None
        return load_flat_yaml(marker_path, "site marker")
    code, stdout, stderr = run_on_site(profile, [
        "bash", "-c",
        'if [ -f "$1" ]; then echo __PRESENT__; cat "$1"; '
        'else echo __ABSENT__; fi', "bash", marker_path,
    ])
    if code != 0:
        raise EntityCtlError(
            "cannot read the site marker on %s: %s"
            % (profile["site_id"], stderr.strip() or stdout.strip()))
    lines = stdout.splitlines()
    if lines and lines[0].strip() == "__ABSENT__":
        return None
    return parse_flat_yaml_text("\n".join(lines[1:]), marker_path)


def site_init_command(args):
    """Create the Computation Site tree skeleton (<site_root>/{deps,
    checkouts, projects}) plus the entity-site.yaml marker on the target
    machine.  Idempotent: an existing marker is validated, never
    overwritten; a marker for another site_id is refused."""
    actor = require_attributed_actor(actor_identity(args))
    home, unused_resolution = resolve_ledger_home(args.ledger_home)
    workspace = require_workspace(home)
    store = OperationStore(home)
    archives = list_site_archives(workspace)
    record = archives.get(args.site_id)
    if record is not None:
        profile = profile_from_archive(record)
    else:
        try:
            profile = store.get_site(args.site_id)
        except LedgerError:
            raise EntityCtlError(
                "unknown site: %s (no archive under %s, not in the store)"
                % (args.site_id, os.path.join(workspace, "sites")))
    site_root = (record or {}).get("site_root") or profile.get("site_root", "")
    if not site_root:
        raise EntityCtlError(
            "site %s has no site_root; add it to sites/%s.yaml first"
            % (args.site_id, args.site_id))
    marker_path = os.path.join(site_root, SITE_MARKER)
    local = profile.get("transport", {}).get("kind") == "local"
    existing = _read_site_marker(profile, marker_path)
    marker_created = False
    if existing is not None:
        if existing.get("site_id") != args.site_id:
            raise EntityCtlError(
                "%s already holds an entity-site.yaml for site %s; refusing "
                "to adopt it for %s"
                % (site_root, existing.get("site_id"), args.site_id))
    if local:
        for name in SITE_TREE_DIRS:
            target = os.path.join(site_root, name)
            if not os.path.isdir(target):
                os.makedirs(target)
        if existing is None:
            write_flat_yaml(marker_path, SITE_MARKER_FIELDS,
                            site_marker_record(args.site_id, site_root))
            marker_created = True
    else:
        directories = [os.path.join(site_root, name) for name in SITE_TREE_DIRS]
        code, unused, stderr = run_on_site(
            profile, ["mkdir", "-p"] + directories)
        if code != 0:
            raise EntityCtlError(
                "cannot create the site tree on %s: %s"
                % (args.site_id, stderr.strip()))
        if existing is None:
            descriptor, temporary = tempfile.mkstemp(prefix=".site-marker-")
            try:
                os.close(descriptor)
                write_flat_yaml(temporary, SITE_MARKER_FIELDS,
                                site_marker_record(args.site_id, site_root))
                _scp_to_site(profile, temporary, marker_path)
                if site_file_sha256(profile, marker_path) != sha256_file(temporary):
                    raise EntityCtlError("staged site marker failed identity check")
            finally:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            marker_created = True
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.init",
        "state_mutated": marker_created,
        "actor": actor,
        "site_id": args.site_id,
        "site_root": site_root,
        "tree": [os.path.join(site_root, name) for name in SITE_TREE_DIRS],
        "marker": marker_path,
        "marker_created": marker_created,
    }


def site_discover(args):
    """Probe a Site so policy defaults are chosen from facts, not guesses.
    The probe itself is read-only; when the workspace holds an archive for
    the Site, the machine section is refreshed from the probe."""
    store = OperationStore(args.ledger_home, create=False)
    profile = store.get_site(args.site_id)
    kind = profile.get("scheduler", {}).get("kind")
    backend = DISCOVER_BACKENDS.get(kind)
    if backend is None:
        raise EntityCtlError(
            "site discovery currently supports scheduler kinds: %s (got '%s')"
            % (", ".join(sorted(DISCOVER_BACKENDS)), kind)
        )
    result = backend(profile)
    machine, machine_calls = _machine_probe(profile, result)
    result["machine"] = machine
    result["remote_calls"] = result.get("remote_calls", 0) + machine_calls
    marker, marker_calls = _site_marker_probe(profile)
    result["site_marker"] = marker
    result["remote_calls"] += marker_calls
    if (marker.get("marker_found") and marker.get("site_id")
            and marker["site_id"] != args.site_id):
        result["warnings"].append(
            "site_root marker belongs to site %s" % marker["site_id"])
    archive_state = {"path": "", "machine_updated": False}
    workspace = workspace_for_ledger_home(store.home)
    if workspace:
        archives = list_site_archives(workspace)
        record = archives.get(args.site_id)
        if record is not None and record.get("machine") != machine:
            record["machine"] = machine
            write_site_yaml(workspace, record)
            archive_state = {
                "path": site_yaml_path(workspace, args.site_id),
                "machine_updated": True,
            }
            result["state_mutated"] = True
    result["archive"] = archive_state
    return result


def _machine_probe(profile, result):
    """One bounded probe for the archive machine section (os/arch; GPUs are
    reused from the scheduler-kind probe when it already collected them)."""
    calls = 0
    ssh = profile.get("transport", {}).get("kind") == "ssh"
    machine = {"os": "", "arch": "", "gpus": list(result.get("gpus") or [])}
    code, stdout, unused = run_on_site(profile, ["uname", "-srm"])
    if ssh:
        calls += 1
    if code == 0:
        parts = stdout.strip().split()
        if parts:
            machine["os"] = parts[0]
            machine["arch"] = parts[-1] if len(parts) > 1 else ""
    if not machine["gpus"]:
        try:
            code, stdout, unused = run_on_site(
                profile, ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
        except OSError:
            code, stdout = 127, ""
        if ssh:
            calls += 1
        if code == 0:
            machine["gpus"] = [line.strip() for line in stdout.splitlines()
                               if line.strip()]
    return machine, calls


def _site_marker_probe(profile):
    """Report (never modify) an existing entity-site.yaml under the
    profile's site_root — adoption of the tree is the user's call."""
    site_root = profile.get("site_root", "")
    marker = {"site_root": site_root, "marker_found": False, "site_id": ""}
    if not site_root:
        return marker, 0
    try:
        record = _read_site_marker(
            profile, os.path.join(site_root, SITE_MARKER))
    except LedgerError as exc:
        marker["error"] = str(exc)
        return marker, 1
    if record is not None:
        marker["marker_found"] = True
        marker["site_id"] = str(record.get("site_id", ""))
    return marker, 1


def _render_deps_text(site_id, origin, stacks):
    lines = ["Site %s deps 注册表（%s）" % (site_id, origin)]
    if not stacks:
        lines.append("  （空）新栈验证通过后用 entityctl site deps-add 落账")
    for stack in stacks:
        kind = stack.get("kind", "build")
        tag = "  [%s]" % kind if kind != "build" else ""
        lines.append("  %s  %s%s" % (stack.get("stack_id", "?"),
                                     stack.get("status", "?"), tag))
        packages = ", ".join(
            "%s %s" % (package.get("name", "?"), package.get("version", "?"))
            for package in stack.get("packages", []))
        if packages:
            lines.append("    packages: %s" % packages)
        if stack.get("env_sh"):
            lines.append("    env: %s" % stack["env_sh"])
    return "\n".join(lines)


def site_deps(args):
    """List the site deps registry (human view by default, --json for the
    machine contract consumed by env-build's --from-registry)."""
    store = OperationStore(args.ledger_home, create=False)
    workspace, archives, db_sites = _site_view(store)
    record = archives.get(args.site_id)
    if record is not None:
        origin = "archive"
        stacks = record.get("deps") or []
    else:
        profile = next((site for site in db_sites
                        if site["site_id"] == args.site_id), None)
        if profile is None:
            raise EntityCtlError("unknown site_id: %s" % args.site_id)
        origin = "db-only"
        stacks = profile.get("deps") or []
    payload = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.deps",
        "state_mutated": False,
        "site_id": args.site_id,
        "origin": origin,
        "stacks": stacks,
    }
    if not args.json:
        payload["_entityctl_text"] = _render_deps_text(
            args.site_id, origin, stacks)
    return payload


def _require_site_file(profile, path, label):
    """Evidence gate: the file must exist on the Site before any write."""
    if profile.get("transport", {}).get("kind") == "local":
        if os.path.isfile(path):
            return
    else:
        code, unused, unused_err = run_on_site(profile, ["test", "-f", path])
        if code == 0:
            return
    raise EntityCtlError(
        "%s not found on Site %s: %s; refusing to register (zero writes)"
        % (label, profile["site_id"], path))


def _write_site_file(profile, path, fields, record):
    """Write a small flat-YAML file onto the Site (local direct, ssh via a
    staged temp file + identity check), creating the parent directory."""
    if profile.get("transport", {}).get("kind") == "local":
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        write_flat_yaml(path, fields, record)
        return
    parent = os.path.dirname(path)
    code, unused, stderr = run_on_site(profile, ["mkdir", "-p", parent])
    if code != 0:
        raise EntityCtlError(
            "cannot create %s on Site: %s" % (parent, stderr.strip()))
    descriptor, temporary = tempfile.mkstemp(prefix=".site-file-")
    try:
        os.close(descriptor)
        write_flat_yaml(temporary, fields, record)
        _scp_to_site(profile, temporary, path)
        if site_file_sha256(profile, path) != sha256_file(temporary):
            raise EntityCtlError("staged %s failed identity check" % path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _require_site_path(profile, path, label):
    """Evidence gate for either a file or a directory on the Site."""
    if profile.get("transport", {}).get("kind") == "local":
        if os.path.exists(path):
            return
    else:
        code, unused, unused_err = run_on_site(profile, ["test", "-e", path])
        if code == 0:
            return
    raise EntityCtlError(
        "%s not found on Site %s: %s; refusing to register (zero writes)"
        % (label, profile["site_id"], path))


def site_deps_add(args):
    """Register a verified dependency stack into the site archive registry
    and write deps/<stack_id>/stack.yaml on the Site.  Gates (zero writes
    on failure): a ``build`` stack needs a confirmed checkpoint with
    compatibility pass plus deps/<stack_id>/env.sh on the Site; an
    ``analysis`` stack (Python environment) skips the build gates and only
    requires its interpreter path to really exist on the Site."""
    actor = require_attributed_actor(actor_identity(args))
    home, unused_resolution = resolve_ledger_home(args.ledger_home)
    workspace = require_workspace(home)
    store = OperationStore(home)
    archives = list_site_archives(workspace)
    record = archives.get(args.site_id)
    if record is None:
        raise EntityCtlError(
            "no site archive for %s; create sites/%s.yaml first "
            "(site import-notes or an editor)" % (args.site_id, args.site_id))
    checkpoint = load_json(args.from_checkpoint, "build checkpoint")
    if args.kind == "build":
        require_verified_checkpoint(checkpoint)
    embedded = checkpoint.get("requirements", {}).get("embedded", {})
    entity = embedded.get("entity", {})
    if entity.get("site_id") and entity["site_id"] != args.site_id:
        raise EntityCtlError(
            "checkpoint belongs to site %s, not %s"
            % (entity["site_id"], args.site_id))
    selected = checkpoint.get("selected", {})
    if not isinstance(selected, dict) or not selected:
        raise EntityCtlError("checkpoint has no selected dependencies")
    signature = stack_signature(
        embedded.get("environment", {}), entity,
        embedded.get("compile", {}))
    stack_id = derive_stack_id(selected, signature)
    site_root = record.get("site_root", "")
    if not site_root:
        raise EntityCtlError(
            "site %s has no site_root; the stack tree cannot be placed"
            % args.site_id)
    profile = profile_from_archive(record)
    env_sh = ""
    if args.kind == "build":
        env_sh = os.path.join(site_root, "deps", stack_id, "env.sh")
        _require_site_file(profile, env_sh, "stack env.sh")
    else:
        python = selected.get("python", {})
        interpreter = ""
        if isinstance(python, dict):
            interpreter = python.get("bin") or python.get("prefix") or ""
        if not interpreter:
            raise EntityCtlError(
                "analysis stack checkpoint has no python entry with bin/"
                "prefix; record the interpreter in selected.python")
        _require_site_path(profile, interpreter, "analysis interpreter")
    stack_entry = {
        "stack_id": stack_id,
        "kind": args.kind,
        "status": "verified",
        "signature": signature,
        "packages": stack_packages(selected),
        "recipe": {
            "providers": dict((name, str(entry.get("provider", "")))
                              for name, entry in sorted(selected.items())
                              if isinstance(entry, dict)),
            "parameter_digest": checkpoint.get("decisions", {}).get(
                "parameters", {}).get("digest", ""),
        },
        "recorded_at": now_utc(),
        "recorded_by": actor.get("run_id", ""),
    }
    if env_sh:
        stack_entry["env_sh"] = env_sh
    # write order: the on-site stack.yaml first, then the archive, then the
    # db mirror — a failed site write leaves every record untouched
    stack_yaml = os.path.join(site_root, "deps", stack_id, "stack.yaml")
    _write_site_file(profile, stack_yaml, STACK_YAML_FIELDS,
                     dict(stack_entry, schema_version=1, site_id=args.site_id))
    updated = upsert_deps_stack(workspace, args.site_id, stack_entry)
    store.upsert_site(validate_site_profile(profile_from_archive(updated)))
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.deps-add",
        "state_mutated": True,
        "actor": actor,
        "site_id": args.site_id,
        "stack_id": stack_id,
        "stack_kind": args.kind,
        "packages": len(stack_entry["packages"]),
        "archive": site_yaml_path(workspace, args.site_id),
        "stack_yaml": stack_yaml,
        "env_sh": env_sh,
    }


def _convert_site_notes(workspace, notes_dir, site_ids=None, overwrite=True):
    """Shared site-notes -> archive conversion.  With ``overwrite=False``
    (workspace import) an existing archive is left untouched and reported
    in ``skipped`` instead of being rebuilt."""
    archives = list_site_archives(workspace)
    if site_ids is None:
        site_ids = sorted(
            name[:-3] for name in os.listdir(notes_dir)
            if name.endswith(".md") and os.path.isfile(
                os.path.join(notes_dir, name)))
    imported = []
    skipped = []
    for site_id in site_ids:
        notes_path = os.path.join(notes_dir, site_id + ".md")
        if not os.path.isfile(notes_path):
            continue
        if not overwrite and site_id in archives:
            skipped.append({"site_id": site_id, "reason": "archive exists"})
            continue
        record = dict(archives.get(site_id) or {"site_id": site_id})
        with open(notes_path, "r") as handle:
            record["notes"] = handle.read().rstrip("\n")
        profile_path = os.path.join(
            notes_dir, site_id + "-site-profile.json")
        profile_source = ""
        if os.path.isfile(profile_path):
            notes_profile = load_json(profile_path, "site profile notes")
            transport = notes_profile.get("transport")
            if transport:
                transport = dict(transport)
                if "ssh_alias" in transport and "alias" not in transport:
                    transport["alias"] = transport.pop("ssh_alias")
                record["transport"] = transport
            for key in ("scheduler", "roots", "policy", "shared_mappings",
                        "site_root", "machine", "deps", "projects"):
                if notes_profile.get(key) not in (None, "", [], {}):
                    record[key] = notes_profile[key]
            profile_source = profile_path
        created = site_id not in archives
        write_site_yaml(workspace, record)
        imported.append({
            "site_id": site_id,
            "created": created,
            "notes_from": notes_path,
            "profile_from": profile_source,
        })
    return imported, skipped


def _site_paths_exist(profile, paths):
    """Bounded existence probe for many paths at once (one remote call)."""
    paths = [path for path in paths if path]
    if not paths:
        return set()
    if profile.get("transport", {}).get("kind") == "local":
        return set(path for path in paths if os.path.exists(path))
    code, stdout, stderr = run_on_site(profile, [
        "bash", "-c",
        'for p in "$@"; do [ -e "$p" ] && echo "$p"; done; true', "bash",
    ] + paths)
    if code != 0:
        raise EntityCtlError(
            "path probe failed on Site %s: %s"
            % (profile["site_id"], stderr.strip()))
    return set(line.strip() for line in stdout.splitlines() if line.strip())


def _scan_root_two_levels(profile, root):
    """List <root>/<case>/<id> directories of a legacy root (one bounded
    find on ssh Sites); empty when the root is absent."""
    if profile.get("transport", {}).get("kind") == "local":
        found = []
        if not os.path.isdir(root):
            return found
        for case_dir in sorted(os.listdir(root)):
            case_path = os.path.join(root, case_dir)
            if not os.path.isdir(case_path):
                continue
            for id_dir in sorted(os.listdir(case_path)):
                id_path = os.path.join(case_path, id_dir)
                if os.path.isdir(id_path):
                    found.append(id_path)
        return found
    code, stdout, stderr = run_on_site(profile, [
        "find", root, "-mindepth", "2", "-maxdepth", "2", "-type", "d",
    ])
    if code != 0:
        return []
    return sorted(line.strip() for line in stdout.splitlines() if line.strip())


def site_plan_migration(args):
    """Inventory a Site's legacy tree against the recorded identities and
    emit an old-path -> new-path migration plan.  Pure read-only: nothing
    is moved, booked, or rewritten."""
    store = OperationStore(args.ledger_home, create=False)
    profile = store.get_site(args.site_id)
    workspace, archives, unused_db = _site_view(store)
    archive = archives.get(args.site_id)
    site_root = ((archive or {}).get("site_root")
                 or profile.get("site_root", ""))
    if not site_root:
        raise EntityCtlError(
            "site %s has no site_root; the new tree cannot be planned"
            % args.site_id)
    exported = store.export()
    slugs = dict((project["project_uid"], project["slug"])
                 for project in exported["projects"])
    items = []
    recorded_paths = set()
    for case in exported["cases"]:
        slug = slugs.get(case.get("project_uid") or "") \
            or os.path.basename(case.get("project_root") or "") \
            or case["case_uid"]
        for dimension in ("build", "run", "data"):
            dimension_info = case.get("identities", {}).get(dimension, {})
            for identity in dimension_info.get("items", []):
                root = identity.get("root", {})
                old_path = root.get("path", "")
                if root.get("site_id") != args.site_id or not old_path:
                    continue
                recorded_paths.add(os.path.normpath(old_path))
                identity_id = identity.get("id") or identity.get("identity_id", "")
                if dimension == "data":
                    # the data root is the run root: it moves to the same
                    # new-tree location as its parent run
                    run_id = identity.get("parents", {}).get("run_id") \
                        or identity_id
                    new_path = os.path.join(
                        site_root, "projects", slug, "runs",
                        case["case_id"], run_id)
                else:
                    new_path = os.path.join(
                        site_root, "projects", slug,
                        "builds" if dimension == "build" else "runs",
                        case["case_id"], identity_id)
                action = "move"
                reason = ""
                if identity.get("layout") == "site-tree":
                    action, reason = "skip", "已在新树"
                elif (dimension == "run"
                      and identity.get("status", "") not in TERMINAL_RUN_STATES):
                    action, reason = "skip", "在途 run(等 record run-exit 终态)"
                items.append({
                    "dimension": dimension,
                    "identity_id": identity_id,
                    "case_uid": case["case_uid"],
                    "project": slug,
                    "status": identity.get("status", ""),
                    "old": {"site_id": args.site_id, "path": old_path},
                    "new": {"site_id": args.site_id, "path": new_path},
                    "action": action,
                    "reason": reason,
                    "exists_on_site": None,
                })
    existing = _site_paths_exist(
        profile, [item["old"]["path"] for item in items])
    for item in items:
        item["exists_on_site"] = os.path.normpath(item["old"]["path"]) in existing \
            or item["old"]["path"] in existing
    legacy_roots = []
    for key in ("build_root", "run_root"):
        root = profile.get("roots", {}).get(key)
        if root and root not in legacy_roots:
            legacy_roots.append(root)
    untracked = []
    for root in legacy_roots:
        for path in _scan_root_two_levels(profile, root):
            if os.path.normpath(path) not in recorded_paths:
                untracked.append(path)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.plan-migration",
        "state_mutated": False,
        "site_id": args.site_id,
        "site_root": site_root,
        "layout": "legacy-roots",
        "items": items,
        "untracked": untracked,
        "moves": len([item for item in items if item["action"] == "move"]),
        "skips": len([item for item in items if item["action"] == "skip"]),
    }


def site_import_notes(args):
    """Convert env-build site-notes into workspace site archives: the prose
    goes verbatim into the notes section, a ``<site>-site-profile.json``
    next to it maps into the structured sections.  The db is untouched —
    run ``entityctl site sync`` afterwards."""
    actor = require_attributed_actor(actor_identity(args))
    home, unused_resolution = resolve_ledger_home(args.ledger_home)
    workspace = require_workspace(home)
    notes_dir = absolute(args.notes_dir)
    if not os.path.isdir(notes_dir):
        raise EntityCtlError("site-notes directory does not exist: %s" % notes_dir)
    targets = None
    if args.site_id:
        validate_slug(args.site_id, "site_id")
        if not os.path.isfile(os.path.join(notes_dir, args.site_id + ".md")):
            raise EntityCtlError("no site notes for %s in %s"
                                 % (args.site_id, notes_dir))
        targets = [args.site_id]
    imported, unused_skipped = _convert_site_notes(
        workspace, notes_dir, targets)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.import-notes",
        "state_mutated": bool(imported),
        "actor": actor,
        "workspace": workspace,
        "imported": imported,
    }



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
    chosen = next((item for item in partitions
                   if item["name"] == suggested.get("default_partition")), None)
    gres_offers = [entry for entry in (chosen or {}).get("gres", "").split(",")
                   if valid_gres(entry)]
    typed_offers = [entry for entry in gres_offers if entry.count(":") == 2]
    if len(gres_offers) == 1 and typed_offers:
        # exactly one GPU type on the suggested partition: safe to pin
        suggested["default_gres"] = gres_offers[0]
    elif len(typed_offers) > 1:
        warnings.append(
            "partition %s offers several GPU types (%s); set "
            "policy.default_gres explicitly"
            % (chosen["name"], chosen["gres"]))
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
    return show_case(store, args.project_root, args.case_slug)


def render_run_command(args):
    store = OperationStore(args.ledger_home, create=False)
    return render_run(
        store, args.project_root, args.toml, args.site, args.gpus,
        args.walltime, args.precision, args.executable, gres=args.gres,
        case_slug=args.case_slug)


def record_run_prepare_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_run_prepare(
        store, args.project_root, args.toml, args.site, args.gpus,
        args.walltime, args.precision, args.executable, actor, gres=args.gres,
        run_id=args.run_id, case_slug=args.case_slug)


def record_run_launch_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_run_launch(
        store, args.project_root, args.run_id, args.adopt_job, args.adopt_pid,
        actor, case_slug=args.case_slug, resubmit=args.resubmit)


def record_run_correct_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_run_correct(store, args.project_root, args.run_id,
                              args.status, args.reason, actor,
                              case_slug=args.case_slug)


def record_run_exit_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_run_exit(store, args.project_root, args.run_id, actor,
                           reclassify=args.reclassify,
                           case_slug=args.case_slug)


def record_run_abort_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_run_abort(store, args.project_root, args.run_id,
                            args.reason, actor, case_slug=args.case_slug)


def record_analysis_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_analysis(
        store, args.project_root, args.case_slug, args.script, args.data,
        args.params, args.output_root, args.env_stack, args.hardcoded_paths,
        actor)


def record_build_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_build(
        store, args.project_root, args.site, args.checkpoint, args.executable,
        actor, case_slug=args.case_slug)


def record_data_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_data(store, args.project_root, args.run_id, actor,
                       case_slug=args.case_slug)


def snapshot_source_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return snapshot_source(store, args.project_root, actor,
                           case_slug=args.case_slug)


def record_intent_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_intent(store, args.project_root, args.text, actor,
                         case_slug=args.case_slug)


def record_relocate_command(args):
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.ledger_home, create=False)
    return record_relocate(
        store, args.project_root, args.dimension, args.identity_id, args.to,
        actor, case_slug=args.case_slug)


def project_status(args):
    store = OperationStore(args.ledger_home, create=False)
    result = status_for_project(
        store, args.project_root, args.live, case_slug=args.case_slug)
    if args.json:
        return result
    dashboard = build_dashboard(
        store, args.project_root, result, case_slug=args.case_slug)
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
        target.executescript(SCHEMA_V2)
        for name in ["meta", "sites", "cases", "projects", "identities", "events"]:
            columns, rows = tables[name]
            placeholders = ",".join(["?"] * len(columns.split(",")))
            target.executemany(
                "INSERT INTO %s(%s) VALUES(%s)" % (name, columns, placeholders),
                rows)
        target.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
            ("2",))
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
        "state_mutated": True, "store_schema_version": 2,
        "message": "migrated store schema 1 -> 2",
        "operations_archive": archive, "operations_archived": operation_count,
        "database_backup": backup, "rows_copied": counts,
    }


def _migrate_v2_to_v3(database, home):
    """Migrate a v2 store to v3: projects becomes a Project entity
    (project_uid + slug + root) and every case gains a project_uid
    reference.  Each v2 root->case 1:1 binding becomes one Project with its
    single case attached; unbound cases keep a NULL project_uid.  The
    original file is backed up under archive/ before the rebuild."""
    archive_dir = os.path.join(home, "archive")
    if not os.path.isdir(archive_dir):
        os.makedirs(archive_dir)
    stamp = now_utc().replace(":", "-").replace("Z", "")
    source = sqlite3.connect(database)
    source.row_factory = sqlite3.Row
    try:
        tables = {}
        for name, columns in [
                ("meta", "key,value"),
                ("sites", "site_id,profile_json,updated_at"),
                ("cases", "case_uid,case_id,project_root,source_json,current_json,"
                          "legacy_json,created_at,updated_at"),
                ("identities", "case_uid,dimension,identity_id,payload_json,"
                                "is_current,created_at"),
                ("events", "case_uid,operation_id,event_type,payload_json,"
                           "actor_json,created_at")]:
            tables[name] = [tuple(row) for row in source.execute(
                "SELECT %s FROM %s" % (columns, name))]
        bindings = [tuple(row) for row in source.execute(
            "SELECT project_root,case_uid,updated_at FROM projects")]
    finally:
        source.close()
    # one Project per v2 binding; the uid is deterministic in the root.
    # Roots are normalized first — trailing-slash/casing variants of the
    # same directory merge into one Project instead of splitting.
    case_project = {}
    projects = []
    merged_roots = {}
    for root, case_uid, updated_at in bindings:
        normalized_root = absolute(root) if root else None
        if normalized_root and normalized_root in merged_roots:
            project_uid = merged_roots[normalized_root]
        else:
            seed = {"project_root": normalized_root or "", "case_uid": case_uid}
            project_uid = "project-" + canonical_hash(seed).split(":", 1)[1][:16]
            slug = (os.path.basename(normalized_root)
                    if normalized_root else "") or case_uid
            projects.append((project_uid, slug, normalized_root,
                             updated_at, updated_at))
            if normalized_root:
                merged_roots[normalized_root] = project_uid
        case_project[case_uid] = project_uid
    backup = os.path.join(archive_dir, "ledger-v2-%s.db" % stamp)
    shutil.copy2(database, backup)
    temporary = database + ".migrate-v3"
    if os.path.isfile(temporary):
        os.unlink(temporary)
    target = sqlite3.connect(temporary)
    try:
        target.executescript(STORE_SCHEMA)
        target.executemany(
            "INSERT INTO projects(project_uid,slug,project_root,created_at,"
            "updated_at) VALUES(?,?,?,?,?)", projects)
        cases_v3 = [
            (row[0], row[1], case_project.get(row[0])) + tuple(row[2:])
            for row in tables["cases"]
        ]
        target.executemany(
            "INSERT INTO cases(case_uid,case_id,project_uid,project_root,"
            "source_json,current_json,legacy_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)", cases_v3)
        for name, columns in [
                ("meta", "key,value"),
                ("sites", "site_id,profile_json,updated_at"),
                ("identities", "case_uid,dimension,identity_id,payload_json,"
                                "is_current,created_at"),
                ("events", "case_uid,operation_id,event_type,payload_json,"
                           "actor_json,created_at")]:
            placeholders = ",".join(["?"] * len(columns.split(",")))
            target.executemany(
                "INSERT INTO %s(%s) VALUES(%s)" % (name, columns, placeholders),
                tables[name])
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
    return {
        "schema_version": 1, "kind": "entity-ledger.store.migrate", "ok": True,
        "state_mutated": True, "store_schema_version": STORE_SCHEMA_VERSION,
        "message": "migrated store schema 2 -> %s" % STORE_SCHEMA_VERSION,
        "database_backup": backup,
        "projects_created": len(projects),
        "cases_linked": len(case_project),
        "rows_copied": dict((name, len(rows)) for name, rows in tables.items()),
    }


def _store_schema_version(database):
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        return int(row[0]) if row else None
    finally:
        connection.close()


def _migrate_store_to_current(database, home):
    """Chain the v1 -> v2 -> v3 migrations on one store file.  Returns
    (steps, original_version); a store already at the current schema yields
    no steps.  Shared by ``store migrate`` and ``workspace import``."""
    original = _store_schema_version(database)
    if original is not None and original > STORE_SCHEMA_VERSION:
        raise EntityCtlError(
            "store schema %s is newer than this bundle supports (%s); use a "
            "newer bundle" % (original, STORE_SCHEMA_VERSION)
        )
    current = original
    steps = []
    if current == 1:
        steps.append(_migrate_v1_to_v2(database, home))
        current = 2
    if current == 2:
        steps.append(_migrate_v2_to_v3(database, home))
        current = 3
    if not steps and current != STORE_SCHEMA_VERSION:
        raise EntityCtlError(
            "no migration path from store schema %s to %s is implemented yet"
            % (original, STORE_SCHEMA_VERSION)
        )
    return steps, original


def store_migrate(args):
    home, unused_resolution = resolve_ledger_home(args.ledger_home)
    if os.path.isdir(home):
        _migrate_legacy_db(home)
    database = store_path(home)
    if not os.path.isfile(database):
        raise EntityCtlError(
            "store does not exist; nothing to migrate (register a Site with "
            "entityctl site add)"
        )
    original = _store_schema_version(database)
    if original == STORE_SCHEMA_VERSION:
        return {
            "schema_version": 1, "kind": "entity-ledger.store.migrate", "ok": True,
            "state_mutated": False, "store_schema_version": original,
            "message": "store is already at the current schema",
        }
    steps, original = _migrate_store_to_current(database, home)
    result = dict(steps[-1])
    result["message"] = "migrated store schema %s -> %s" % (
        original, STORE_SCHEMA_VERSION)
    # keep the v1 archive keys on the chained payload: they are the only
    # pointer to the retired operations history
    for key in ("operations_archive", "operations_archived"):
        if key in steps[0]:
            result[key] = steps[0][key]
    result["migrations"] = [
        {"message": step["message"], "database_backup": step["database_backup"]}
        for step in steps
    ]
    return result


def workspace_init(args):
    result = init_workspace(args.path)
    record = result["record"]
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.workspace.init",
        "state_mutated": result["created"],
        "workspace": result["workspace"],
        "workspace_id": record["workspace_id"],
        "created": result["created"],
        "ledger_home": result["ledger_home"],
    }


def workspace_adopt(args):
    workspace = absolute(args.path)
    # A corrupt or missing workspace.yaml fails loudly here; the pointer is
    # only written for a validated workspace.
    record = load_workspace_yaml(workspace)
    pointer = write_active_workspace(workspace)
    hint = ""
    legacy_db = os.path.join(absolute("~/.entity-ledger"), "ledger.db")
    workspace_db = os.path.join(workspace_ledger_home(workspace), "ledger.db")
    if os.path.isfile(legacy_db) and not os.path.isfile(workspace_db):
        # Moving the controller data is a later migration stage; adopting
        # must never copy it implicitly.
        hint = (
            "检测到旧控制器数据 %s,而 workspace 的 %s 尚不存在;"
            "搬运数据属于后续迁移阶段(workspace import),本次未搬动任何数据。"
            "在搬完之前,既有命令仍可用 --ledger-home %s 指向旧数据"
            % (legacy_db, workspace_db, os.path.dirname(legacy_db))
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.workspace.adopt",
        "state_mutated": True,
        "workspace": workspace,
        "workspace_id": record["workspace_id"],
        "pointer": active_workspace_pointer(),
        "adopted_at": pointer["adopted_at"],
        "hint": hint,
    }


def workspace_where(args):
    home, source = resolve_ledger_home(args.ledger_home)
    workspace = None
    if source in ("environment", "pointer"):
        workspace = os.path.dirname(home)
    database = os.path.join(home, "ledger.db")
    pointer = active_workspace_pointer()
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.workspace.where",
        "state_mutated": False,
        "workspace": workspace,
        "workspace_valid": bool(
            workspace and os.path.isfile(
                os.path.join(workspace, "workspace.yaml"))),
        "source": source,
        "ledger_home": home,
        "ledger_db": database,
        "ledger_db_exists": os.path.isfile(database),
        "snapshots": os.path.join(home, "snapshots"),
        "pointer": pointer,
        "pointer_exists": os.path.isfile(pointer),
    }


def _import_file_step(kind, source, target, empty_target_ok=False):
    """Plan one file copy with the import conflict policy: identical ->
    skip, an empty target store may be replaced, anything else conflicts
    and is never overwritten."""
    step = {"kind": kind, "source": source, "target": target, "reason": ""}
    if not os.path.exists(target):
        step["action"] = "copy"
    elif sha256_file(source) == sha256_file(target):
        step["action"] = "skip-identical"
        step["reason"] = "目标内容相同"
    elif empty_target_ok:
        step["action"] = "replace"
        step["reason"] = "目标是空库,备份后替换"
    else:
        step["action"] = "skip-conflict"
        step["reason"] = "目标已存在且内容不同"
    return step


def _store_is_empty(database):
    connection = sqlite3.connect(database)
    try:
        for table in ("sites", "cases", "events", "projects", "identities"):
            row = connection.execute(
                "SELECT COUNT(*) FROM %s" % table).fetchone()
            if row and row[0]:
                return False
        return True
    finally:
        connection.close()


def _workspace_import_plan(args, workspace, ledger):
    steps = []
    for projects_dir in args.projects_dir or []:
        source_root = absolute(projects_dir)
        if not os.path.isdir(source_root):
            raise EntityCtlError(
                "projects dir does not exist: %s" % source_root)
        for name in sorted(os.listdir(source_root)):
            source = os.path.join(source_root, name)
            if not os.path.isdir(source):
                continue
            try:
                slug = validate_slug(name, "project slug")
            except LedgerError:
                steps.append({"kind": "project", "source": source,
                              "target": "", "action": "skip",
                              "reason": "目录名不是合法 slug", "slug": ""})
                continue
            target = os.path.join(workspace, "projects", slug)
            step = {"kind": "project", "source": source, "target": target,
                    "slug": slug, "reason": ""}
            if os.path.exists(target):
                identical = (source_manifest(source)["snapshot_id"]
                             == source_manifest(target)["snapshot_id"])
                step["action"] = "skip-identical" if identical else "skip-conflict"
                step["reason"] = ("目标内容相同" if identical
                                  else "目标已存在且内容不同")
            else:
                step["action"] = "copy"
            steps.append(step)
    if args.from_ledger_home:
        old_home = absolute(args.from_ledger_home)
        old_db = os.path.join(old_home, "ledger.db")
        if not os.path.isfile(old_db):
            raise EntityCtlError(
                "old ledger.db does not exist: %s" % old_db)
        new_db = os.path.join(ledger, "ledger.db")
        step = _import_file_step(
            "ledger.db", old_db, new_db,
            empty_target_ok=os.path.isfile(new_db)
            and sha256_file(old_db) != sha256_file(new_db)
            and _store_is_empty(new_db))
        steps.append(step)
        old_snapshots = os.path.join(old_home, "snapshots")
        if os.path.isdir(old_snapshots):
            for name in sorted(os.listdir(old_snapshots)):
                source = os.path.join(old_snapshots, name)
                if not os.path.isfile(source):
                    continue
                steps.append(_import_file_step(
                    "snapshot", source,
                    os.path.join(ledger, "snapshots", name)))
    if args.site_notes:
        notes_dir = absolute(args.site_notes)
        if not os.path.isdir(notes_dir):
            raise EntityCtlError(
                "site-notes directory does not exist: %s" % notes_dir)
        archives = list_site_archives(workspace)
        for name in sorted(os.listdir(notes_dir)):
            if not name.endswith(".md"):
                continue
            site_id = name[:-3]
            step = {"kind": "site-notes",
                    "source": os.path.join(notes_dir, name),
                    "target": site_yaml_path(workspace, site_id),
                    "site_id": site_id, "reason": ""}
            if site_id in archives:
                step["action"] = "skip-exists"
                step["reason"] = "档案已存在"
            else:
                step["action"] = "convert"
            steps.append(step)
    return steps


def _register_imported_projects(workspace, store, eligible_slugs):
    """After the store migration, bind project entities to project.yaml
    files (and register copied projects that have no entity yet).  Only
    directories that were copied cleanly or verified identical are
    eligible; conflicted directories are left alone."""
    bindings = []
    projects = store.find_projects()
    bound_slugs = set()
    for project in projects:
        slug = project["slug"]
        project_dir = os.path.join(workspace, "projects", slug)
        if not os.path.isdir(project_dir):
            continue
        yaml_path = os.path.join(project_dir, "project.yaml")
        entry = {"slug": slug, "project_uid": project["project_uid"]}
        if os.path.isfile(yaml_path):
            record = load_project_yaml(project_dir)
            if record["project_uid"] != project["project_uid"]:
                entry.update({"action": "skip-conflict",
                              "reason": "project.yaml 的 project_uid 与 db 不一致"})
            else:
                entry["action"] = "ok"
                bound_slugs.add(slug)
        elif slug not in eligible_slugs:
            entry.update({"action": "skip-conflict",
                          "reason": "目录未通过冲突检查,未登记"})
        else:
            write_flat_yaml(yaml_path, PROJECT_FIELDS, {
                "project_uid": project["project_uid"],
                "slug": slug,
                "schema_version": 1,
                "created_at": now_utc(),
                "source": "source" if os.path.isdir(
                    os.path.join(project_dir, "source")) else "",
            })
            entry["action"] = "registered"
            bound_slugs.add(slug)
        if entry["action"] in ("ok", "registered"):
            # re-point the binding at the workspace copy: the Project root
            # and every Case project_root move off the old layout paths
            store.upsert_project(
                project["project_uid"], slug, project_dir)
            for case in store.project_cases(project["project_uid"]):
                if (case.get("project_root") or "") != absolute(project_dir):
                    store.upsert_case(
                        case["case_uid"], case["case_id"], project_dir,
                        case["source"], case["current"], case["legacy"],
                        project_uid=project["project_uid"])
        bindings.append(entry)
    for name in sorted(eligible_slugs):
        project_dir = os.path.join(workspace, "projects", name)
        if not os.path.isdir(project_dir) or name in bound_slugs:
            continue
        yaml_path = os.path.join(project_dir, "project.yaml")
        if os.path.isfile(yaml_path):
            project_uid = load_project_yaml(project_dir)["project_uid"]
        else:
            project_uid = "project-" + canonical_hash(
                {"project_root": project_dir}).split(":", 1)[1][:16]
            write_flat_yaml(yaml_path, PROJECT_FIELDS, {
                "project_uid": project_uid, "slug": name,
                "schema_version": 1, "created_at": now_utc(),
                "source": "source" if os.path.isdir(
                    os.path.join(project_dir, "source")) else "",
            })
        store.upsert_project(project_uid, name, project_dir)
        bindings.append({"slug": name, "project_uid": project_uid,
                         "action": "registered"})
    return bindings


def workspace_import(args):
    """One-shot local consolidation of the pre-workspace layout into a
    workspace: project directories, the old ledger.db + snapshots, and
    site-notes.  Dry-run by default; --apply executes.  Conflicts are
    reported and skipped, never overwritten."""
    actor = require_attributed_actor(actor_identity(args))
    workspace = absolute(args.path)
    # the target must be a workspace created by workspace init
    load_workspace_yaml(workspace)
    ledger = workspace_ledger_home(workspace)
    steps = _workspace_import_plan(args, workspace, ledger)
    conflicts = [step for step in steps if step["action"] == "skip-conflict"]
    if not args.apply:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "kind": "entityctl.workspace.import",
            "state_mutated": False,
            "apply": False,
            "workspace": workspace,
            "steps": steps,
            "conflicts": conflicts,
        }
    applied = []
    for step in steps:
        if step["kind"] == "project" and step["action"] == "copy":
            shutil.copytree(step["source"], step["target"])
            applied.append(step)
        elif step["kind"] == "snapshot" and step["action"] == "copy":
            parent = os.path.dirname(step["target"])
            if not os.path.isdir(parent):
                os.makedirs(parent)
            shutil.copy2(step["source"], step["target"])
            applied.append(step)
    migrations = []
    for step in [item for item in steps if item["kind"] == "ledger.db"]:
        if step["action"] == "replace":
            backup = step["target"] + ".pre-import"
            if os.path.isfile(backup):
                os.unlink(backup)
            os.rename(step["target"], backup)
            step["backup"] = backup
        if step["action"] in ("copy", "replace"):
            shutil.copy2(step["source"], step["target"])
            applied.append(step)
            migration_steps, unused_original = _migrate_store_to_current(
                step["target"], ledger)
            migrations.extend(migration_steps)
    notes_imported = []
    notes_skipped = []
    if args.site_notes:
        notes_imported, notes_skipped = _convert_site_notes(
            workspace, absolute(args.site_notes), None, overwrite=False)
    store = OperationStore(ledger)
    eligible = set(
        step["slug"] for step in steps
        if step["kind"] == "project"
        and step["action"] in ("copy", "skip-identical"))
    bindings = _register_imported_projects(workspace, store, eligible)
    registered = [entry for entry in bindings if entry["action"] == "registered"]
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.workspace.import",
        "state_mutated": bool(applied or notes_imported or registered),
        "apply": True,
        "actor": actor,
        "workspace": workspace,
        "steps": steps,
        "conflicts": conflicts,
        "applied": applied,
        "store_migrations": [
            {"message": step["message"],
             "database_backup": step["database_backup"]}
            for step in migrations
        ],
        "project_bindings": bindings,
        "notes_imported": notes_imported,
        "notes_skipped": notes_skipped,
    }


def project_init_command(args):
    """Create projects/<name>/ in the active workspace and register the
    Project entity in the store.  Idempotent."""
    actor = require_attributed_actor(actor_identity(args))
    home, unused_resolution = resolve_ledger_home(args.ledger_home)
    workspace = require_workspace(home)
    result = init_project(workspace, args.name, source=args.source or None)
    record = result["record"]
    store = OperationStore(home)
    store.upsert_project(
        record["project_uid"], record["slug"], result["project_dir"])
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.project.init",
        "state_mutated": result["created"],
        "actor": actor,
        "workspace": workspace,
        "project": {
            "project_uid": record["project_uid"],
            "slug": record["slug"],
            "project_root": result["project_dir"],
            "source": record.get("source", ""),
        },
        "created": result["created"],
    }


def case_init_command(args):
    """Create projects/<project>/cases/<name>/ (intent.md + decisions.json
    skeletons) and book the Case under its Project.  The case_uid is
    content-addressed from (project, slug), so re-runs are idempotent."""
    actor = require_attributed_actor(actor_identity(args))
    home, unused_resolution = resolve_ledger_home(args.ledger_home)
    workspace = require_workspace(home)
    store = OperationStore(home)
    matches = store.find_projects(slug=args.project)
    if not matches:
        raise EntityCtlError(
            "unknown project: %s (create it with entityctl project init)"
            % args.project)
    project = matches[0]
    result = init_case(workspace, project["slug"], args.name)
    case_slug = args.name
    case_uid = "case-" + canonical_hash(
        {"project_uid": project["project_uid"], "case_id": case_slug}
    ).split(":", 1)[1][:16]
    # re-running must never reset an existing Case's booked state: only the
    # directory skeleton is topped up, the store write is skipped
    try:
        store.get_case(case_uid)
        already_exists = True
    except LedgerError:
        already_exists = False
    if not already_exists:
        project_dir = os.path.join(workspace, "projects", project["slug"])
        source_rel = load_project_yaml(project_dir).get("source") or "source"
        source_path = os.path.join(project_dir, source_rel)
        source_site = _source_site(store, source_path)
        current = {"source_id": "", "build_id": "", "run_id": "",
                   "active_run": None, "data_id": "", "analysis_id": ""}
        store.upsert_case(
            case_uid, case_slug, project["project_root"],
            {"authority": {"site_id": source_site, "path": source_path},
             "transfer_policy": "snapshot",
             "revision": _git_revision(source_path)
             if os.path.isdir(source_path)
             else {"kind": "path", "root": source_path}},
            current,
            project_uid=project["project_uid"])
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.case.init",
        "state_mutated": result["created"] or not already_exists,
        "actor": actor,
        "workspace": workspace,
        "project_uid": project["project_uid"],
        "case_uid": case_uid,
        "case_id": case_slug,
        "case_dir": result["case_dir"],
        "created": result["created"] and not already_exists,
        "already_exists": already_exists,
    }


def _submission_body(store, project_root, artifacts, note, actor,
                     case_slug=None):
    status = status_for_project(store, project_root, case_slug=case_slug)
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
    body = _submission_body(store, args.project_root, artifacts, args.note,
                            actor, case_slug=args.case_slug)
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
    parser.add_argument("--walltime", default="",
                        help="HH:MM:SS or D-HH:MM:SS; empty (default) leaves "
                             "the time limit unset so the Site default applies")
    parser.add_argument("--gres", default="",
                        help="Slurm gres spec gpu[:type]:count (e.g. "
                             "gpu:V100:1); overrides the site policy "
                             "default_gres; empty falls back to the policy, "
                             "then to gpu:<N>. Ignored on scheduler-less Sites")
    parser.add_argument("--precision", default="double",
                        choices=["single", "double"])
    parser.add_argument("--executable", default="",
                        help="absolute path on the execution Site; defaults to "
                             "the current verified build identity")


def add_case_argument(parser):
    parser.add_argument("--case", dest="case_slug", default=None,
                        help="case slug inside the project; optional when the "
                             "project has exactly one case, required when it "
                             "has several")


def build_parser():
    parser = argparse.ArgumentParser(description="Entity public control-plane CLI")
    # Lazy default: resolving the Ledger home can trigger the one-time
    # ~/.entity-router -> ~/.entity-ledger migration, which must not run as a
    # side effect of merely building the parser (e.g. entityctl --help).
    parser.add_argument("--ledger-home", dest="ledger_home",
                        default=None)
    add_actor_arguments(parser)
    sub = parser.add_subparsers(
        dest="command",
        metavar="{doctor,status,show,render-run,snapshot-source,record,site,store,workspace,project,case,submission,export,install}"
    )
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument(
        "--project-root", default=None,
        help="rejected with guidance: doctor is workspace-scoped; use "
             "status --project-root <path> for project-level state")
    doctor_parser.set_defaults(func=doctor)

    snapshot = sub.add_parser("snapshot-source")
    snapshot.add_argument("--project-root", required=True)
    add_case_argument(snapshot)
    snapshot.set_defaults(func=snapshot_source_command)

    current_status = sub.add_parser("status")
    current_status.add_argument("--project-root", required=True)
    current_status.add_argument("--live", action="store_true")
    add_case_argument(current_status)
    current_status.add_argument(
        "--json", action="store_true",
        help="emit the machine-readable controller facts instead of the "
             "human-readable dashboard")
    current_status.set_defaults(func=project_status)

    show = sub.add_parser("show")
    show.add_argument("--project-root", required=True)
    add_case_argument(show)
    show.set_defaults(func=show_command)

    render = sub.add_parser("render-run")
    render.add_argument("--project-root", required=True)
    render.add_argument("--toml", required=True)
    render.add_argument("--site", required=True)
    add_run_compute_arguments(render)
    add_case_argument(render)
    render.set_defaults(func=render_run_command)

    record = sub.add_parser("record")
    record_sub = record.add_subparsers(dest="record_command")
    record_build_parser = record_sub.add_parser("build")
    record_build_parser.add_argument("--project-root", required=True)
    record_build_parser.add_argument("--site", required=True)
    record_build_parser.add_argument("--checkpoint", required=True)
    record_build_parser.add_argument("--executable", required=True)
    add_case_argument(record_build_parser)
    record_build_parser.set_defaults(func=record_build_command)
    record_data_parser = record_sub.add_parser("data")
    record_data_parser.add_argument("--project-root", required=True)
    record_data_parser.add_argument("--run-id", default="")
    add_case_argument(record_data_parser)
    record_data_parser.set_defaults(func=record_data_command)
    record_run_prepare_parser = record_sub.add_parser("run-prepare")
    record_run_prepare_parser.add_argument("--project-root", required=True)
    record_run_prepare_parser.add_argument("--toml", required=True)
    record_run_prepare_parser.add_argument("--site", required=True)
    record_run_prepare_parser.add_argument(
        "--run-id", default="",
        help="require the derived run to equal this render-run previewed id; "
             "a mismatch (inputs drifted since render) fails with zero writes")
    add_run_compute_arguments(record_run_prepare_parser)
    add_case_argument(record_run_prepare_parser)
    record_run_prepare_parser.set_defaults(func=record_run_prepare_command)
    record_run_launch_parser = record_sub.add_parser("run-launch")
    record_run_launch_parser.add_argument("--project-root", required=True)
    record_run_launch_parser.add_argument("--run-id", default="")
    add_case_argument(record_run_launch_parser)
    adopt = record_run_launch_parser.add_mutually_exclusive_group()
    adopt.add_argument("--adopt-job", default="",
                       help="adopt an out-of-band Slurm job id into the ledger")
    adopt.add_argument("--adopt-pid", default="",
                       help="adopt an out-of-band process id into the ledger")
    adopt.add_argument(
        "--resubmit", action="store_true",
        help="submit the run again after its recorded job probed terminal "
             "and failed; the new submission gets its own exactly-once "
             "receipt (exactly-once is per submission, not per run)")
    record_run_launch_parser.set_defaults(func=record_run_launch_command)
    record_run_correct_parser = record_sub.add_parser("run-correct")
    record_run_correct_parser.add_argument("--project-root", required=True)
    record_run_correct_parser.add_argument("--run-id", default="")
    record_run_correct_parser.add_argument(
        "--status", required=True, choices=["completed", "failed"],
        help="the terminal state the run is corrected to")
    record_run_correct_parser.add_argument(
        "--reason", required=True,
        help="why the booked state is wrong; recorded in the identity and "
             "the audit event")
    add_case_argument(record_run_correct_parser)
    record_run_correct_parser.set_defaults(func=record_run_correct_command)
    record_run_exit_parser = record_sub.add_parser("run-exit")
    record_run_exit_parser.add_argument("--project-root", required=True)
    record_run_exit_parser.add_argument("--run-id", default="")
    add_case_argument(record_run_exit_parser)
    record_run_exit_parser.add_argument(
        "--reclassify", action="store_true",
        help="re-judge a run booked failed from its log evidence alone "
             "(skip the scheduler probe); rewrites to completed only when "
             "a known harmless teardown abort is confirmed")
    record_run_exit_parser.set_defaults(func=record_run_exit_command)
    record_run_abort_parser = record_sub.add_parser("run-abort")
    record_run_abort_parser.add_argument("--project-root", required=True)
    record_run_abort_parser.add_argument("--run-id", default="")
    record_run_abort_parser.add_argument(
        "--reason", required=True,
        help="why the run is declared dead (e.g. the Site is permanently "
             "unreachable); recorded in the identity and the audit event")
    add_case_argument(record_run_abort_parser)
    record_run_abort_parser.set_defaults(func=record_run_abort_command)

    record_intent_parser = record_sub.add_parser("intent")
    record_intent_parser.add_argument("--project-root", required=True)
    record_intent_parser.add_argument("--text", required=True)
    add_case_argument(record_intent_parser)
    record_intent_parser.set_defaults(func=record_intent_command)

    record_relocate_parser = record_sub.add_parser("relocate")
    record_relocate_parser.add_argument("--project-root", required=True)
    record_relocate_parser.add_argument(
        "--dimension", required=True, choices=["build", "run", "data"])
    record_relocate_parser.add_argument("--identity-id", required=True)
    record_relocate_parser.add_argument(
        "--to", required=True,
        help="absolute path the resource was moved to (moving itself is "
             "performed by the agent; this command only re-probes evidence "
             "and re-books the Locator)")
    add_case_argument(record_relocate_parser)
    record_relocate_parser.set_defaults(func=record_relocate_command)

    record_analysis_parser = record_sub.add_parser("analysis")
    record_analysis_parser.add_argument("--project-root", required=True)
    record_analysis_parser.add_argument(
        "--script", required=True,
        help="script path relative to the project's analysis/scripts/ library")
    record_analysis_parser.add_argument(
        "--data", required=True, help="run_id or data_id the analysis consumed")
    record_analysis_parser.add_argument("--params", default="{}",
                                        help="JSON object of analysis parameters")
    record_analysis_parser.add_argument(
        "--output-root", required=True,
        help="absolute output directory on the data Site holding "
             "analysis-manifest.json")
    record_analysis_parser.add_argument(
        "--env-stack", default="",
        help="stack_id of the registered analysis environment (optional)")
    record_analysis_parser.add_argument(
        "--hardcoded-paths", action="store_true",
        help="mark a legacy script whose data paths are not CLI-parameterized")
    add_case_argument(record_analysis_parser)
    record_analysis_parser.set_defaults(func=record_analysis_command)

    site = sub.add_parser("site")
    site_sub = site.add_subparsers(dest="site_command")
    site_add_parser = site_sub.add_parser("add")
    site_add_parser.add_argument("--profile", required=True)
    site_add_parser.set_defaults(func=site_add)
    site_list_parser = site_sub.add_parser("list")
    site_list_parser.set_defaults(func=site_list)
    site_show_parser = site_sub.add_parser("show")
    site_show_parser.add_argument("site_id")
    site_show_parser.set_defaults(func=site_show)
    site_sync_parser = site_sub.add_parser("sync")
    site_sync_parser.add_argument("site_id", nargs="?", default=None)
    site_sync_parser.set_defaults(func=site_sync)
    site_init_parser = site_sub.add_parser("init")
    site_init_parser.add_argument("site_id")
    site_init_parser.set_defaults(func=site_init_command)
    site_discover_parser = site_sub.add_parser("discover")
    site_discover_parser.add_argument("site_id")
    site_discover_parser.set_defaults(func=site_discover)
    site_import_notes_parser = site_sub.add_parser("import-notes")
    site_import_notes_parser.add_argument("--site", dest="site_id", default=None)
    site_import_notes_parser.add_argument(
        "--notes-dir", default="~/.entity-env-build/site-notes")
    site_import_notes_parser.set_defaults(func=site_import_notes)
    site_deps_parser = site_sub.add_parser("deps")
    site_deps_parser.add_argument("site_id")
    site_deps_parser.add_argument(
        "--json", action="store_true",
        help="emit the machine-readable registry (the contract consumed by "
             "entity_checkpoint.py create --from-registry)")
    site_deps_parser.set_defaults(func=site_deps)
    site_deps_add_parser = site_sub.add_parser("deps-add")
    site_deps_add_parser.add_argument("site_id")
    site_deps_add_parser.add_argument("--from-checkpoint", required=True,
                                      help="verified entity-deps.local.json")
    site_deps_add_parser.add_argument(
        "--kind", default="build", choices=["build", "analysis"],
        help="build: toolchain stack (default; requires confirmed + compat "
             "pass checkpoint and env.sh on the Site); analysis: Python "
             "environment (only requires the interpreter to exist on-site)")
    site_deps_add_parser.set_defaults(func=site_deps_add)
    site_plan_migration_parser = site_sub.add_parser("plan-migration")
    site_plan_migration_parser.add_argument("site_id")
    site_plan_migration_parser.set_defaults(func=site_plan_migration)

    store_cmd = sub.add_parser("store")
    store_sub = store_cmd.add_subparsers(dest="store_command")
    migrate = store_sub.add_parser("migrate")
    migrate.set_defaults(func=store_migrate)

    workspace = sub.add_parser("workspace")
    workspace_sub = workspace.add_subparsers(dest="workspace_command")
    workspace_init_parser = workspace_sub.add_parser("init")
    workspace_init_parser.add_argument("path")
    workspace_init_parser.set_defaults(func=workspace_init)
    workspace_adopt_parser = workspace_sub.add_parser("adopt")
    workspace_adopt_parser.add_argument("path")
    workspace_adopt_parser.set_defaults(func=workspace_adopt)
    workspace_where_parser = workspace_sub.add_parser("where")
    workspace_where_parser.set_defaults(func=workspace_where)
    workspace_import_parser = workspace_sub.add_parser("import")
    workspace_import_parser.add_argument("path")
    workspace_import_parser.add_argument(
        "--projects-dir", action="append", default=[],
        help="directory whose immediate subdirectories are projects to "
             "consolidate (repeatable)")
    workspace_import_parser.add_argument(
        "--from-ledger-home", default="",
        help="old controller home holding ledger.db (+ snapshots/)")
    workspace_import_parser.add_argument(
        "--site-notes", default="",
        help="site-notes directory to convert into sites/*.yaml")
    workspace_import_parser.add_argument(
        "--apply", action="store_true",
        help="execute the plan (default is a dry-run that only prints it)")
    workspace_import_parser.set_defaults(func=workspace_import)

    project = sub.add_parser("project")
    project_sub = project.add_subparsers(dest="project_command")
    project_init_parser = project_sub.add_parser("init")
    project_init_parser.add_argument("name")
    project_init_parser.add_argument(
        "--source", default="",
        help="source authority path relative to the project directory "
             "(default: source; only registered in project.yaml, the "
             "directory itself is not created)")
    project_init_parser.set_defaults(func=project_init_command)

    case_cmd = sub.add_parser("case")
    case_sub = case_cmd.add_subparsers(dest="case_command")
    case_init_parser = case_sub.add_parser("init")
    case_init_parser.add_argument("project")
    case_init_parser.add_argument("name")
    case_init_parser.set_defaults(func=case_init_command)

    submission = sub.add_parser("submission")
    submission_sub = submission.add_subparsers(dest="submission_command")
    submission_create_parser = submission_sub.add_parser("create")
    submission_create_parser.add_argument("--project-root", required=True)
    submission_create_parser.add_argument("--output", required=True)
    submission_create_parser.add_argument("--artifact", action="append", default=[])
    submission_create_parser.add_argument("--note", default="")
    add_case_argument(submission_create_parser)
    submission_create_parser.set_defaults(func=submission_create)
    submission_verify_parser = submission_sub.add_parser("verify")
    submission_verify_parser.add_argument("--submission", required=True)
    submission_verify_parser.set_defaults(func=submission_verify)

    export = sub.add_parser("export")
    export.add_argument("--output", required=True)
    export.set_defaults(func=export_store)

    direct_install = sub.add_parser("install")
    direct_install.add_argument("--source-root", default=DEFAULT_BUNDLE_ROOT)
    direct_install.add_argument(
        "--provider", action="append", choices=["codex", "claude", "kimi"],
        default=None,
        help="project only onto this client (repeatable); default projects "
             "onto every installed client root")
    direct_install.set_defaults(func=install_bundle)
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
              "decisions": exc.decisions, "state_mutated": False,
              # only an anomaly (transient/external failure) is worth
              # retrying unchanged; every other status needs new input
              # or a human decision
              "retryable": exc.status == "anomaly"})
        return 2
    except (IOError, OSError, ValueError, KeyError, TypeError, LedgerError,
            sqlite3.Error, tarfile.TarError) as exc:
        emit({"ok": False, "status": "anomaly", "error": str(exc),
              "state_mutated": False, "retryable": True})
        return 2


if __name__ == "__main__":
    from _invocation_log import trace_invocation
    with trace_invocation("entity-ledger", "entityctl.py", sys.argv[1:], script_file=__file__):
        sys.exit(main())
