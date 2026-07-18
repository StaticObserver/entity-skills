#!/usr/bin/env python3
"""Shared controller-local project bindings for Entity Router Cases.

Bindings live under ``ENTITY_ROUTER_HOME`` rather than inside a source checkout
or a provider-specific directory.  They contain only project-root -> Case UID
identity; Case state remains authoritative in the controller registry.
"""

from __future__ import print_function

import argparse
import fcntl
import hashlib
import json
import os
import sys
from contextlib import contextmanager

from entity_router_common import (
    RouterError,
    absolute,
    actor_identity,
    atomic_write_json,
    ensure_home,
    load_json,
    now_utc,
    require_attributed_actor,
    router_home,
)
from entity_router_state import load_state, resolve_case


PROJECT_REGISTRY_SCHEMA_VERSION = 1


class ProjectBindingError(RouterError):
    pass


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def project_registry_path(home):
    return os.path.join(router_home(home), "project-bindings.json")


def project_lock_path(home):
    return os.path.join(ensure_home(home), ".project-bindings.lock")


def empty_registry():
    return {
        "schema_version": PROJECT_REGISTRY_SCHEMA_VERSION,
        "updated_at": now_utc(),
        "projects": {},
    }


def ensure_project_registry(home):
    home = ensure_home(home)
    path = project_registry_path(home)
    if not os.path.isfile(path):
        atomic_write_json(path, empty_registry())
    return path


def load_project_registry(home):
    path = project_registry_path(home)
    if not os.path.isfile(path):
        return empty_registry()
    value = load_json(path, "project binding registry")
    if value.get("schema_version") != PROJECT_REGISTRY_SCHEMA_VERSION:
        raise ProjectBindingError("unsupported project binding registry schema")
    if not isinstance(value.get("projects"), dict):
        raise ProjectBindingError("project binding registry projects must be an object")
    return value


@contextmanager
def locked_project_registry(home):
    handle = open(project_lock_path(home), "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def normalize_project_root(value, require_directory=True):
    root = absolute(value)
    if require_directory and not os.path.isdir(root):
        raise ProjectBindingError("project root is not a directory: %s" % root)
    return root


def project_id(root):
    digest = hashlib.sha256(root.encode("utf-8")).hexdigest()
    return "project-" + digest[:16]


def binding_result(home, root, record):
    case_dir = resolve_case(home, record["case_uid"])
    state = load_state(case_dir)
    return {
        "project_id": record["project_id"],
        "project_root": root,
        "case_uid": state["case_uid"],
        "case_id": state["case_id"],
        "case_dir": case_dir,
        "revision": state["revision"],
        "bound_at": record.get("bound_at", ""),
        "updated_at": record.get("updated_at", ""),
    }


def bind_project(home, project_root, case_value, replace=False, actor=None):
    home = ensure_home(home)
    actor = require_attributed_actor(actor or actor_identity())
    root = normalize_project_root(project_root)
    case_dir = resolve_case(home, case_value)
    state = load_state(case_dir)
    with locked_project_registry(home):
        registry = load_project_registry(home)
        current = registry["projects"].get(root)
        if current and current.get("case_uid") != state["case_uid"] and not replace:
            raise ProjectBindingError(
                "project is already bound to another Case; use --replace explicitly"
            )
        timestamp = now_utc()
        record = {
            "project_id": project_id(root),
            "case_uid": state["case_uid"],
            "case_id": state["case_id"],
            "bound_at": current.get("bound_at", timestamp) if current else timestamp,
            "updated_at": timestamp,
            "updated_by": actor,
        }
        registry["projects"][root] = record
        registry["updated_at"] = timestamp
        atomic_write_json(project_registry_path(home), registry)
    result = binding_result(home, root, record)
    result.update({"ok": True, "binding_state_mutated": True, "case_state_mutated": False})
    return result


def matching_binding(registry, path):
    matches = []
    for root, record in registry["projects"].items():
        normalized = absolute(root)
        try:
            within = os.path.commonpath([path, normalized]) == normalized
        except ValueError:
            within = False
        if within:
            matches.append((len(normalized), normalized, record))
    if not matches:
        raise ProjectBindingError("no Router Case binding covers project path: %s" % path)
    matches.sort(reverse=True, key=lambda item: item[0])
    unused_length, root, record = matches[0]
    return root, record


def resolve_project(home, project_root):
    home = ensure_home(home)
    path = normalize_project_root(project_root)
    registry = load_project_registry(home)
    root, record = matching_binding(registry, path)
    result = binding_result(home, root, record)
    result.update({"ok": True, "query_path": path, "state_mutated": False})
    return result


def list_projects(home):
    home = ensure_home(home)
    registry = load_project_registry(home)
    projects = []
    for root, record in sorted(registry["projects"].items()):
        try:
            projects.append(binding_result(home, root, record))
        except RouterError as exc:
            projects.append({
                "project_id": record.get("project_id", project_id(root)),
                "project_root": root,
                "case_uid": record.get("case_uid", ""),
                "error": str(exc),
            })
    return {"ok": True, "projects": projects, "state_mutated": False}


def unbind_project(home, project_root, actor=None):
    home = ensure_home(home)
    actor = require_attributed_actor(actor or actor_identity())
    root = normalize_project_root(project_root)
    with locked_project_registry(home):
        registry = load_project_registry(home)
        record = registry["projects"].get(root)
        if not record:
            raise ProjectBindingError("project root has no exact binding: %s" % root)
        del registry["projects"][root]
        registry["updated_at"] = now_utc()
        atomic_write_json(project_registry_path(home), registry)
    return {
        "ok": True,
        "project_root": root,
        "case_uid": record.get("case_uid", ""),
        "binding_state_mutated": True,
        "case_state_mutated": False,
        "actor": actor,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Shared controller-local project -> Entity Router Case bindings."
    )
    parser.add_argument("--router-home", default=router_home())
    parser.add_argument("--actor-run-id")
    parser.add_argument("--actor-provider")
    parser.add_argument("--actor-client")
    parser.add_argument("--actor-session-id")
    parser.add_argument("--actor-model")
    parser.add_argument("--actor-bundle-hash")
    sub = parser.add_subparsers(dest="command")
    bind = sub.add_parser("bind")
    bind.add_argument("--project-root", required=True)
    bind.add_argument("--case", required=True)
    bind.add_argument("--replace", action="store_true")
    bind.set_defaults(func=lambda args: bind_project(
        args.router_home, args.project_root, args.case, args.replace,
        actor_identity(args),
    ))
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--project-root", required=True)
    resolve.set_defaults(func=lambda args: resolve_project(args.router_home, args.project_root))
    listing = sub.add_parser("list")
    listing.set_defaults(func=lambda args: list_projects(args.router_home))
    unbind = sub.add_parser("unbind")
    unbind.add_argument("--project-root", required=True)
    unbind.set_defaults(func=lambda args: unbind_project(
        args.router_home, args.project_root, actor_identity(args)
    ))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.error("a command is required")
    try:
        if args.command in {"bind", "unbind"}:
            require_attributed_actor(actor_identity(args))
        payload = args.func(args)
        emit(payload)
        return 0 if payload.get("ok", True) else 2
    except (IOError, OSError, ValueError, KeyError, RouterError) as exc:
        emit({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
