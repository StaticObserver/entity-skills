#!/usr/bin/env python3
"""Compact public control-plane entrypoint for Entity simulation projects.

Read-only commands return controller-local summaries and never create Actions.
Mutating project bindings are stored in the shared Router home, not in source
checkouts or provider-specific directories.
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from entity_router_common import (
    RouterError,
    absolute,
    actor_identity,
    load_site_profile,
    now_utc,
    require_attributed_actor,
    router_home,
)
from entity_router_project import (
    bind_project,
    list_projects,
    project_registry_path,
    resolve_project,
    unbind_project,
)
from entity_router_state import load_state, resolve_case
from entity_router_status import build_config, build_profile, collect_site_status


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


def run_flow(args):
    values = list(args.flow_args)
    if values and values[0] == "--":
        values = values[1:]
    if not values:
        raise EntityCtlError("flow requires inspect, check, execute, or watch arguments")
    if values[0] in {"execute", "watch"}:
        require_attributed_actor(actor_identity(args))
        if not args.writer_lease_id:
            raise EntityCtlError(
                "mutating flow requires a writer lease; acquire one and pass --writer-lease-id"
            )
    script = os.path.join(SCRIPT_DIR, "entity_router_flow.py")
    environment = os.environ.copy()
    actor = actor_identity(args)
    for key, value in [
        ("ENTITY_AGENT_RUN_ID", actor["run_id"]),
        ("ENTITY_AGENT_PROVIDER", actor["provider"]),
        ("ENTITY_AGENT_CLIENT", actor["client"]),
        ("ENTITY_AGENT_SESSION_ID", actor["session_id"]),
        ("ENTITY_AGENT_MODEL", actor["model"]),
        ("ENTITY_SKILLS_BUNDLE_HASH", actor["bundle_hash"]),
        ("ENTITY_ROUTER_WRITER_LEASE_ID", args.writer_lease_id),
    ]:
        if value:
            environment[key] = value
    process = subprocess.Popen(
        [sys.executable, script, "--router-home", args.router_home] + values,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=environment,
    )
    stdout, stderr = process.communicate()
    try:
        payload = json.loads(stdout)
    except ValueError:
        raise EntityCtlError(
            "flow façade returned invalid JSON: %s" % (stderr.strip() or stdout.strip())
        )
    payload["_entityctl_exit_code"] = process.returncode
    return payload


def run_writer(args):
    values = list(args.writer_args)
    if values and values[0] == "--":
        values = values[1:]
    if not values:
        raise EntityCtlError("writer requires status, acquire, handoff, or release")
    aliases = {
        "status": "writer-status",
        "acquire": "acquire-writer",
        "handoff": "handoff-writer",
        "release": "release-writer",
    }
    if values[0] not in aliases:
        raise EntityCtlError("unknown writer command: %s" % values[0])
    state_command = aliases[values[0]]
    script = os.path.join(SCRIPT_DIR, "entity_router_state.py")
    environment = os.environ.copy()
    actor = actor_identity(args)
    for key, value in [
        ("ENTITY_AGENT_RUN_ID", actor["run_id"]),
        ("ENTITY_AGENT_PROVIDER", actor["provider"]),
        ("ENTITY_AGENT_CLIENT", actor["client"]),
        ("ENTITY_AGENT_SESSION_ID", actor["session_id"]),
        ("ENTITY_AGENT_MODEL", actor["model"]),
        ("ENTITY_SKILLS_BUNDLE_HASH", actor["bundle_hash"]),
        ("ENTITY_ROUTER_WRITER_LEASE_ID", args.writer_lease_id),
    ]:
        if value:
            environment[key] = value
    process = subprocess.Popen(
        [sys.executable, script, "--router-home", args.router_home, state_command] + values[1:],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        env=environment,
    )
    stdout, stderr = process.communicate()
    try:
        payload = json.loads(stdout)
    except ValueError:
        raise EntityCtlError(
            "writer command returned invalid JSON: %s" % (stderr.strip() or stdout.strip())
        )
    payload["_entityctl_exit_code"] = process.returncode
    return payload


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
            "case_registry": os.path.join(home, "registry.json"),
            "project_registry": project_registry_path(home),
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


def selected_case(home, case_value=None, project_root=None):
    if case_value and project_root:
        raise EntityCtlError("use either --case or --project-root, not both")
    binding = None
    if case_value:
        case_dir = resolve_case(home, case_value)
    else:
        binding = resolve_project(home, project_root or os.getcwd())
        case_dir = binding["case_dir"]
    return case_dir, load_state(case_dir), binding


def compact_case_summary(home, case_dir, state, binding=None):
    resources = state["resources"]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "kind": "entityctl.inspect",
        "state_mutated": False,
        "controller": {
            "router_home": router_home(home),
            "case_dir": case_dir,
            "source": "controller-local",
            "remote_contacted": False,
        },
        "writer": {
            "lease": state.get("control", {}).get("writer_lease"),
        },
        "project": None if not binding else {
            "project_id": binding["project_id"],
            "project_root": binding["project_root"],
        },
        "case": {
            "case_uid": state["case_uid"],
            "case_id": state["case_id"],
            "revision": state["revision"],
            "status": state["case_status"],
        },
        "workflow": {
            "workflow_id": state["workflow"]["workflow_id"],
            "status": state["workflow"]["status"],
            "phase": state["workflow"]["phase"],
            "owner": state["workflow"]["owner"],
            "active_action_id": state["workflow"].get("active_action_id", ""),
            "next_action": state["workflow"].get("next_action", ""),
            "allowed_actions": state["workflow"].get("allowed_actions", []),
            "blockers": state["workflow"].get("blockers", []),
        },
        "readiness": dict(
            (key, value.get("status", ""))
            for key, value in sorted(state["readiness"].items())
        ),
        "source": {
            "authority": state["source"]["authority"],
            "transfer_policy": state["source"].get("transfer_policy", ""),
        },
        "current": {
            "build_id": resources["build"].get("current_id", ""),
            "run_id": resources["run"].get("current_id", ""),
            "active_run": resources["run"].get("active"),
            "data_id": resources["data"].get("current_id", ""),
            "analysis_id": resources["analysis"].get("current_id", ""),
        },
        "artifacts": state["artifacts"],
        "offline_semantics": "cached evidence is readable but is not a current remote observation",
    }
    return summary


def bounded_summary(summary, max_bytes):
    rendered = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    if len(rendered.encode("utf-8")) <= max_bytes:
        summary["summary_bytes"] = len(rendered.encode("utf-8"))
        return summary
    compact = dict(summary)
    compact.pop("artifacts", None)
    compact["summary_truncated"] = True
    rendered = json.dumps(compact, sort_keys=True, separators=(",", ":"))
    compact["summary_bytes"] = len(rendered.encode("utf-8"))
    if compact["summary_bytes"] > max_bytes:
        raise EntityCtlError("compact Case summary exceeds --max-bytes")
    return compact


def inspect_case(args):
    home = router_home(args.router_home)
    case_dir, state, binding = selected_case(home, args.case, args.project_root)
    return bounded_summary(
        compact_case_summary(home, case_dir, state, binding), args.max_bytes
    )


def run_status(args):
    home = router_home(args.router_home)
    unused_case_dir, state, binding = selected_case(home, args.case, args.project_root)
    active = state["resources"]["run"].get("active")
    if not active:
        raise EntityCtlError("Case has no active run Locator")
    profile = load_site_profile(home, active["site_id"])
    status_args = argparse.Namespace(
        router_home=home,
        site_id=active["site_id"],
        ssh_alias=None,
        scheduler=args.scheduler,
        run_id=state["resources"]["run"].get("current_id", ""),
        run_root=active["path"],
        job_id=args.job_id,
        pid=args.pid,
        pid_start_ticks=args.pid_start_ticks,
        progress_log=args.progress_log,
        stderr_log=args.stderr_log,
        fields_root=args.fields_root,
        checkpoint_root=args.checkpoint_root,
        field_pattern=args.field_pattern,
        checkpoint_pattern=args.checkpoint_pattern,
        total_steps=args.total_steps,
        target_time=args.target_time,
        tail_bytes=args.tail_bytes,
        profile=args.profile,
    )
    unused_home, effective_profile = build_profile(status_args)
    config = build_config(status_args, effective_profile)
    result = collect_site_status(home, profile if not args.scheduler else effective_profile, config)
    result.update({
        "ok": True,
        "case_uid": state["case_uid"],
        "case_revision": state["revision"],
        "project_id": binding["project_id"] if binding else "",
        "state_mutated": False,
    })
    return result


def add_case_selector(parser):
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--case")
    selector.add_argument("--project-root")


def add_actor_arguments(parser):
    parser.add_argument("--actor-run-id")
    parser.add_argument("--actor-provider")
    parser.add_argument("--actor-client")
    parser.add_argument("--actor-session-id")
    parser.add_argument("--actor-model")
    parser.add_argument("--actor-bundle-hash")
    parser.add_argument(
        "--writer-lease-id", default=os.environ.get("ENTITY_ROUTER_WRITER_LEASE_ID", "")
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Entity public control-plane CLI")
    parser.add_argument("--router-home", default=router_home())
    add_actor_arguments(parser)
    sub = parser.add_subparsers(dest="command")
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.set_defaults(func=doctor)

    bundle = sub.add_parser("bundle")
    bundle_sub = bundle.add_subparsers(dest="bundle_command")
    install = bundle_sub.add_parser("install")
    install.add_argument("--source-root", default=DEFAULT_BUNDLE_ROOT)
    install.set_defaults(func=install_bundle)

    flow = sub.add_parser("flow")
    flow.add_argument("flow_args", nargs=argparse.REMAINDER)
    flow.set_defaults(func=run_flow)

    writer = sub.add_parser("writer")
    writer.add_argument("writer_args", nargs=argparse.REMAINDER)
    writer.set_defaults(func=run_writer)

    project = sub.add_parser("project")
    project_sub = project.add_subparsers(dest="project_command")
    bind = project_sub.add_parser("bind")
    bind.add_argument("--project-root", required=True)
    bind.add_argument("--case", required=True)
    bind.add_argument("--replace", action="store_true")
    bind.set_defaults(func=lambda args: bind_project(
        args.router_home, args.project_root, args.case, args.replace,
        actor_identity(args),
    ))
    resolve = project_sub.add_parser("resolve")
    resolve.add_argument("--project-root", required=True)
    resolve.set_defaults(func=lambda args: resolve_project(args.router_home, args.project_root))
    listing = project_sub.add_parser("list")
    listing.set_defaults(func=lambda args: list_projects(args.router_home))
    unbind = project_sub.add_parser("unbind")
    unbind.add_argument("--project-root", required=True)
    unbind.set_defaults(func=lambda args: unbind_project(
        args.router_home, args.project_root, actor_identity(args)
    ))

    inspect_parser = sub.add_parser("inspect")
    add_case_selector(inspect_parser)
    inspect_parser.add_argument("--max-bytes", type=int, default=4096)
    inspect_parser.set_defaults(func=inspect_case)

    status = sub.add_parser("run-status")
    add_case_selector(status)
    identity = status.add_mutually_exclusive_group(required=True)
    identity.add_argument("--job-id")
    identity.add_argument("--pid", type=int)
    status.add_argument("--pid-start-ticks")
    status.add_argument("--scheduler", choices=["none", "slurm", "pbs"])
    status.add_argument("--progress-log", default="logs/stdout.log")
    status.add_argument("--stderr-log", default="logs/stderr.log")
    status.add_argument("--fields-root", default="data/fields")
    status.add_argument("--checkpoint-root", default="data/checkpoints")
    status.add_argument("--field-pattern", default="fields.*.bp")
    status.add_argument("--checkpoint-pattern", default="step-*.bp")
    status.add_argument("--total-steps", type=int)
    status.add_argument("--target-time", type=float)
    status.add_argument("--tail-bytes", type=int, default=131072)
    status.add_argument("--profile", choices=["quick", "full"], default="quick")
    status.set_defaults(func=run_status)
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
    except (IOError, OSError, ValueError, KeyError, RouterError) as exc:
        emit({"ok": False, "error": str(exc), "state_mutated": False})
        return 2


if __name__ == "__main__":
    sys.exit(main())
