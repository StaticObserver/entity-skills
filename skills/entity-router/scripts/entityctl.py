#!/usr/bin/env python3
"""Compact public control-plane entrypoint for Entity simulation projects.

Read-only commands return controller-local summaries. The SQLite router.db in
the Router home is the sole structured controller authority.
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile

from entity_router_common import (
    RouterError,
    absolute,
    actor_identity,
    atomic_write_json,
    load_json,
    now_utc,
    require_attributed_actor,
    router_home,
    validate_site_profile,
)
from entity_router_operation import apply_plan, status_for_project
from entity_router_planner import PlanError, load_goal, plan_goal
from entity_router_store import OperationStore, store_path


SCHEMA_VERSION = 1
ENTITY_SKILLS = ("entity-router", "entity-pgen", "entity-env-build", "entity-nt2py")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_BUNDLE_ROOT = os.path.dirname(SKILL_ROOT)


class EntityCtlError(RouterError):
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
        "bundle_hash": identity["hash"],
        "bundle_files": identity["files"],
        "bundle_created": created,
        "current": current,
        "client_projections": projections,
        "backup_root": backup_root,
        "backups": backups,
    }


def doctor(args):
    home = router_home(args.router_home)
    runtime_bundle = bundle_hash(DEFAULT_BUNDLE_ROOT)
    expected_bundle = actor_identity(args).get("bundle_hash", "")
    warnings = []
    if expected_bundle and expected_bundle != runtime_bundle["hash"]:
        warnings.append("ENTITY_SKILLS_BUNDLE_HASH differs from the loaded runtime bundle")
    actor = actor_identity(args)
    if actor["run_id"] == "unattributed":
        warnings.append("mutations will be unattributed unless an Agent run ID is supplied")
    database = store_path(home)
    profiles = []
    if os.path.isfile(database):
        profiles = OperationStore(home, create=False).export()["sites"]
    else:
        warnings.append("v5 store is unavailable; register Sites with entityctl site add")
    for profile in profiles:
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
        installs.append({
            "provider": provider,
            "path": path,
            "exists": os.path.isdir(path),
            "bundle_hash": identity["hash"],
            "files": identity["files"],
            "matches_runtime": bool(identity["hash"] and identity["hash"] == runtime_bundle["hash"]),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.doctor",
        "state_mutated": False,
        "controller": {
            "router_home": home,
            "available": os.path.isdir(home),
            "v5_store": database,
            "v5_store_available": os.path.isfile(database),
        },
        "trace_home": trace_home(),
        "runtime_bundle": {
            "root": DEFAULT_BUNDLE_ROOT,
            "bundle_hash": runtime_bundle["hash"],
            "files": runtime_bundle["files"],
        },
        "actor": actor,
        "client_installs": installs,
        "warnings": warnings,
    }


def site_add(args):
    actor = require_attributed_actor(actor_identity(args))
    profile = validate_site_profile(load_json(args.profile, "Site profile"))
    store = OperationStore(args.router_home)
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
    store = OperationStore(args.router_home, create=False)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.site.list",
        "state_mutated": False,
        "sites": store.export()["sites"],
    }


def plan_operation(args):
    store = OperationStore(args.router_home, create=False)
    goal = load_goal(args.goal)
    result = plan_goal(store, args.project_root, goal, [args.output])
    atomic_write_json(args.output, result)
    result["output"] = absolute(args.output)
    result["artifact_written"] = True
    return result


def apply_operation(args):
    envelope = load_json(args.plan, "Operation Plan")
    if (envelope.get("kind") != "entity-router.plan"
            or not isinstance(envelope.get("goal"), dict)
            or not isinstance(envelope.get("plan"), dict)):
        raise EntityCtlError("--plan must be an entity-router.plan envelope")
    actor = require_attributed_actor(actor_identity(args))
    store = OperationStore(args.router_home, create=False)
    operation = apply_plan(
        store, envelope["goal"], envelope["plan"], actor, plan_path=args.plan
    )
    return {
        "schema_version": 1, "kind": "entity-router.apply", "ok": True,
        "state_mutated": True, "operation": operation,
    }


def project_status(args):
    store = OperationStore(args.router_home, create=False)
    return status_for_project(store, args.project_root, args.live)


def export_store(args):
    store = OperationStore(args.router_home, create=False)
    payload = store.export()
    atomic_write_json(args.output, payload)
    return {
        "schema_version": 1, "kind": "entity-router.export", "ok": True,
        "state_mutated": False, "output": absolute(args.output),
        "cases": len(payload["cases"]), "operations": len(payload["operations"]),
    }


def add_actor_arguments(parser):
    parser.add_argument("--actor-run-id")
    parser.add_argument("--actor-provider")
    parser.add_argument("--actor-client")
    parser.add_argument("--actor-session-id")
    parser.add_argument("--actor-model")
    parser.add_argument("--actor-bundle-hash")


def build_parser():
    parser = argparse.ArgumentParser(description="Entity public control-plane CLI")
    parser.add_argument("--router-home", default=router_home())
    add_actor_arguments(parser)
    sub = parser.add_subparsers(
        dest="command", metavar="{doctor,plan,apply,status,site,export,install}"
    )
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.set_defaults(func=doctor)

    plan = sub.add_parser("plan")
    plan.add_argument("--project-root", required=True)
    plan.add_argument("--goal", required=True)
    plan.add_argument("--output", required=True)
    plan.set_defaults(func=plan_operation)

    apply = sub.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.set_defaults(func=apply_operation)

    current_status = sub.add_parser("status")
    current_status.add_argument("--project-root", required=True)
    current_status.add_argument("--live", action="store_true")
    current_status.set_defaults(func=project_status)

    site = sub.add_parser("site")
    site_sub = site.add_subparsers(dest="site_command")
    site_add_parser = site_sub.add_parser("add")
    site_add_parser.add_argument("--profile", required=True)
    site_add_parser.set_defaults(func=site_add)
    site_list_parser = site_sub.add_parser("list")
    site_list_parser.set_defaults(func=site_list)

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
        emit(payload)
        if exit_code is not None:
            return exit_code
        return 0 if payload.get("ok", True) else 2
    except PlanError as exc:
        emit({"ok": False, "status": exc.status, "error": str(exc),
              "decisions": exc.decisions, "state_mutated": False})
        return 2
    except (IOError, OSError, ValueError, KeyError, RouterError) as exc:
        emit({"ok": False, "status": "anomaly", "error": str(exc),
              "state_mutated": False})
        return 2


if __name__ == "__main__":
    sys.exit(main())
