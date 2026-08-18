#!/usr/bin/env python3
"""Workspace container for the Entity Ledger controller.

A Workspace is the single working directory for development: it holds the
human-readable ``projects/`` and ``sites/`` trees plus the machine state
under ``.ledger/`` (ledger.db and content-addressed source snapshots).

``workspace.yaml`` deliberately uses only a small subset of YAML (top-level
``key: value`` pairs; values are flat scalars, JSON flow collections —
inline ``{...}``/``[...]``, themselves valid YAML — or ``|`` block text),
so reading and writing are implemented with the standard library alone —
no PyYAML dependency.  The same subset backs ``project.yaml``, the site
archives under ``sites/`` and the ``entity-site.yaml`` marker.  The module
stays Python 3.6 compatible like the rest of the Ledger runtime.
"""

from __future__ import print_function

import json
import os
import re
import uuid

from entity_ledger_common import (
    LedgerError,
    absolute,
    now_utc,
    validate_slug,
)
from entity_ledger_store import (
    OperationStore,
    canonical_hash,
    workspace_ledger_home,
)


WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_YAML = "workspace.yaml"
WORKSPACE_FIELDS = ("workspace_id", "schema_version", "created_at", "migrated_from")

PROJECT_SCHEMA_VERSION = 1
PROJECT_YAML = "project.yaml"
PROJECT_FIELDS = ("project_uid", "slug", "schema_version", "created_at", "source")


class WorkspaceError(LedgerError):
    pass


def workspace_yaml_path(workspace):
    return os.path.join(absolute(workspace), WORKSPACE_YAML)


def _format_value(value):
    """Render one value of the YAML subset: a flat scalar, a JSON flow
    collection (inline ``{...}``/``[...]`` — itself valid YAML), or a
    multi-line string rendered as a ``|`` block scalar by the caller."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    text = str(value)
    if (not text or text != text.strip() or "\r" in text
            or any(char in text for char in ":#\"'&*!|>%@`[]{}")
            or " " in text):
        return json.dumps(text)
    return text


def _parse_value(text, path):
    text = text.strip()
    if text.startswith('"'):
        try:
            return json.loads(text)
        except ValueError:
            raise WorkspaceError("invalid quoted scalar in %s: %s" % (path, text))
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except ValueError:
            raise WorkspaceError("invalid flow collection in %s: %s" % (path, text))
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1].replace("''", "'")
    return text


def write_flat_yaml(path, fields, record):
    lines = []
    for field in fields:
        value = record.get(field)
        if value is None or value == "":
            continue
        if isinstance(value, str) and "\n" in value:
            lines.append("%s: |" % field)
            lines.extend("  " + line for line in value.split("\n"))
            continue
        lines.append("%s: %s" % (field, _format_value(value)))
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")


def load_flat_yaml(path, label):
    """Parse the flat+flow YAML subset shared by workspace.yaml,
    project.yaml, site archives and the entity-site.yaml marker; raises
    WorkspaceError on anything outside the subset."""
    if not os.path.isfile(path):
        raise WorkspaceError("missing %s: %s" % (label, path))
    try:
        with open(path, "r") as handle:
            text = handle.read()
    except (IOError, OSError) as exc:
        raise WorkspaceError("cannot read %s: %s" % (path, exc))
    return parse_flat_yaml_text(text, path)


def parse_flat_yaml_text(text, path="<string>"):
    record = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            raise WorkspaceError(
                "unexpected indentation in %s: %s" % (path, line))
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise WorkspaceError("unparseable line in %s: %s" % (path, line))
        key = key.strip()
        if value.strip() == "|":
            block = []
            while index < len(lines) and (
                    lines[index].startswith("  ") or not lines[index].strip()):
                block.append(lines[index][2:] if lines[index].startswith("  ")
                             else "")
                index += 1
            while block and not block[-1]:
                block.pop()
            record[key] = "\n".join(block)
            continue
        record[key] = _parse_value(value, path)
    return record


def _require_int_version(record, path, label, expected):
    try:
        version = int(record.get("schema_version"))
    except (TypeError, ValueError):
        raise WorkspaceError(
            "%s has no integer schema_version: %s" % (label, path))
    if version != expected:
        raise WorkspaceError(
            "unsupported %s schema_version %s (expected %s): %s"
            % (label, version, expected, path))
    record["schema_version"] = version


def write_workspace_yaml(workspace, record):
    write_flat_yaml(workspace_yaml_path(workspace), WORKSPACE_FIELDS, record)


def load_workspace_yaml(workspace):
    """Read and validate ``<workspace>/workspace.yaml``.  Raises
    WorkspaceError when the file is missing, unparseable, or carries an
    unsupported schema version."""
    path = workspace_yaml_path(workspace)
    try:
        record = load_flat_yaml(path, WORKSPACE_YAML)
    except WorkspaceError as exc:
        if str(exc).startswith("missing"):
            raise WorkspaceError(
                "not a workspace (missing %s): %s"
                % (WORKSPACE_YAML, absolute(workspace)))
        raise
    _require_int_version(record, path, "workspace.yaml", WORKSPACE_SCHEMA_VERSION)
    if not str(record.get("workspace_id", "")).strip():
        raise WorkspaceError("workspace.yaml has no workspace_id: %s" % path)
    if not str(record.get("created_at", "")).strip():
        raise WorkspaceError("workspace.yaml has no created_at: %s" % path)
    return record


def is_workspace(path):
    try:
        load_workspace_yaml(path)
        return True
    except WorkspaceError:
        return False


def workspace_for_ledger_home(home):
    """The workspace a controller home belongs to: ``<workspace>/.ledger``
    with a valid workspace.yaml.  Returns None for any other home (legacy
    controller roots included)."""
    home = absolute(home)
    if os.path.basename(home) != ".ledger":
        return None
    candidate = os.path.dirname(home)
    return candidate if is_workspace(candidate) else None


def require_workspace(home):
    workspace = workspace_for_ledger_home(home)
    if workspace is None:
        raise WorkspaceError(
            "controller home is not a workspace .ledger directory: %s; run "
            "entityctl workspace init/adopt first (or point --ledger-home at "
            "<workspace>/.ledger)" % absolute(home))
    return workspace


def load_project_yaml(project_dir):
    """Read and validate ``<project>/project.yaml`` (same flat subset)."""
    path = os.path.join(absolute(project_dir), PROJECT_YAML)
    record = load_flat_yaml(path, PROJECT_YAML)
    _require_int_version(record, path, "project.yaml", PROJECT_SCHEMA_VERSION)
    if not str(record.get("project_uid", "")).strip():
        raise WorkspaceError("project.yaml has no project_uid: %s" % path)
    if not str(record.get("slug", "")).strip():
        raise WorkspaceError("project.yaml has no slug: %s" % path)
    return record


def init_project(workspace, slug, source=None):
    """Create ``projects/<slug>/`` (project.yaml + cases/) inside a
    workspace.  The source authority is only registered in project.yaml
    (relative path, default ``source``); its directory is not created —
    snapshot-source semantics stay with the Case source record.

    Idempotent: an existing valid project.yaml is kept untouched; a
    non-empty directory without project.yaml is refused."""
    workspace = absolute(workspace)
    load_workspace_yaml(workspace)
    slug = validate_slug(slug, "project slug")
    project_dir = os.path.join(workspace, "projects", slug)
    yaml_path = os.path.join(project_dir, PROJECT_YAML)
    record = None
    if os.path.exists(project_dir):
        if not os.path.isdir(project_dir):
            raise WorkspaceError(
                "project path exists and is not a directory: %s" % project_dir)
        if os.path.isfile(yaml_path):
            record = load_project_yaml(project_dir)
        elif os.listdir(project_dir):
            raise WorkspaceError(
                "directory exists and is not a project (no %s): %s"
                % (PROJECT_YAML, project_dir))
    else:
        os.makedirs(project_dir)
    created = record is None
    if created:
        record = {
            "project_uid": "project-" + uuid.uuid4().hex[:16],
            "slug": slug,
            "schema_version": PROJECT_SCHEMA_VERSION,
            "created_at": now_utc(),
            "source": source or "source",
        }
        write_flat_yaml(yaml_path, PROJECT_FIELDS, record)
    cases_dir = os.path.join(project_dir, "cases")
    if not os.path.isdir(cases_dir):
        os.makedirs(cases_dir)
    return {
        "project_dir": project_dir,
        "record": record,
        "created": created,
    }


def init_case(workspace, project_slug, case_slug):
    """Create ``projects/<project>/cases/<case>/`` with the intent.md and
    decisions.json skeletons.  Never overwrites existing files; booking the
    Case in the store is the caller's job (entityctl case init)."""
    workspace = absolute(workspace)
    project_slug = validate_slug(project_slug, "project slug")
    case_slug = validate_slug(case_slug, "case slug")
    project_dir = os.path.join(workspace, "projects", project_slug)
    load_project_yaml(project_dir)
    case_dir = os.path.join(project_dir, "cases", case_slug)
    created = not os.path.exists(case_dir)
    if not os.path.isdir(case_dir):
        os.makedirs(case_dir)
    intent_path = os.path.join(case_dir, "intent.md")
    if not os.path.isfile(intent_path):
        with open(intent_path, "w") as handle:
            handle.write(
                "# %s\n\nWrite the research intent of this case here; record "
                "it with entityctl record intent (record intent rewrites "
                "this file to match the db).\n" % case_slug)
    decisions_path = os.path.join(case_dir, "decisions.json")
    if not os.path.isfile(decisions_path):
        with open(decisions_path, "w") as handle:
            json.dump({
                "schema_version": 1,
                "kind": "entity-pgen.decision-card",
                "case": case_slug,
                "parameters": {},
            }, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return {
        "case_dir": case_dir,
        "intent": intent_path,
        "decisions": decisions_path,
        "created": created,
    }


def init_workspace(path, migrated_from=None):
    """Create the workspace skeleton at ``path``: workspace.yaml,
    projects/, sites/, and .ledger/ with an initialized empty ledger.db
    and a snapshots/ directory.

    Idempotent: re-running on an existing valid workspace only ensures the
    skeleton pieces exist and never rewrites workspace.yaml.  An existing
    non-empty directory that is not a workspace is refused."""
    path = absolute(path)
    record = None
    if os.path.exists(path):
        if not os.path.isdir(path):
            raise WorkspaceError(
                "workspace path exists and is not a directory: %s" % path)
        if os.path.isfile(workspace_yaml_path(path)):
            # validate, then keep the existing identity untouched
            record = load_workspace_yaml(path)
        elif os.listdir(path):
            if os.path.isfile(os.path.join(path, SITE_MARKER)):
                raise WorkspaceError(
                    "%s holds an %s — this is a Computation Site root, not a "
                    "workspace: the workspace (with the entityctl controller) "
                    "belongs on the development machine; a Site is only an "
                    "ssh execution endpoint"
                    % (path, SITE_MARKER))
            raise WorkspaceError(
                "directory exists and is not a workspace (no %s): %s; "
                "choose an empty directory or adopt an existing workspace"
                % (WORKSPACE_YAML, path))
    else:
        os.makedirs(path)
    created = record is None
    if created:
        record = {
            "workspace_id": str(uuid.uuid4()),
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "created_at": now_utc(),
        }
        if migrated_from:
            record["migrated_from"] = absolute(migrated_from)
        write_workspace_yaml(path, record)
    for name in ("projects", "sites"):
        target = os.path.join(path, name)
        if not os.path.isdir(target):
            os.makedirs(target)
    ledger = workspace_ledger_home(path)
    # OperationStore(create=True) applies the store schema idempotently —
    # an existing ledger.db is opened, never rebuilt.
    OperationStore(ledger)
    snapshots = os.path.join(ledger, "snapshots")
    if not os.path.isdir(snapshots):
        os.makedirs(snapshots)
    return {
        "workspace": path,
        "record": record,
        "created": created,
        "ledger_home": ledger,
    }


# --- Site archives (sites/<site>.yaml) and the entity-site.yaml marker -----

SITE_SCHEMA_VERSION = 1
SITE_FIELDS = (
    "site_id", "schema_version", "transport", "scheduler", "machine",
    "site_root", "projects", "deps", "policy", "roots", "shared_mappings",
    "notes",
)
SITE_MARKER = "entity-site.yaml"
SITE_MARKER_FIELDS = ("site_id", "schema_version", "roots")
SITE_TREE_DIRS = ("deps", "checkouts", "projects")


def site_yaml_path(workspace, site_id):
    return os.path.join(absolute(workspace), "sites", site_id + ".yaml")


def write_site_yaml(workspace, record):
    site_id = validate_slug(record.get("site_id"), "site_id")
    record = dict(record, site_id=site_id,
                  schema_version=SITE_SCHEMA_VERSION)
    path = site_yaml_path(workspace, site_id)
    write_flat_yaml(path, SITE_FIELDS,
                    validate_site_archive(record, path))
    return record


def validate_site_archive(record, path):
    _require_int_version(record, path, "site archive", SITE_SCHEMA_VERSION)
    site_id = validate_slug(record.get("site_id"), "site_id")
    transport = record.get("transport") or {}
    if not isinstance(transport, dict):
        raise WorkspaceError("site archive transport must be a mapping: %s" % path)
    kind = transport.get("kind", "local")
    if kind not in ("local", "ssh"):
        raise WorkspaceError(
            "site archive transport.kind must be local or ssh: %s" % path)
    site_root = record.get("site_root")
    if site_root and not str(site_root).startswith("/"):
        raise WorkspaceError("site archive site_root must be absolute: %s" % path)
    for key in ("projects", "deps"):
        value = record.get(key)
        if value is not None and not isinstance(value, list):
            raise WorkspaceError(
                "site archive %s must be a list: %s" % (key, path))
    record["site_id"] = site_id
    return record


def load_site_yaml(path):
    """Read and validate one site archive file (any absolute path)."""
    return validate_site_archive(
        load_flat_yaml(absolute(path), "site archive"), absolute(path))


def list_site_archives(workspace):
    """All site archives of a workspace as ``{site_id: record}``."""
    sites_dir = os.path.join(absolute(workspace), "sites")
    archives = {}
    if not os.path.isdir(sites_dir):
        return archives
    for name in sorted(os.listdir(sites_dir)):
        if not name.endswith(".yaml"):
            continue
        path = os.path.join(sites_dir, name)
        record = load_site_yaml(path)
        archives[record["site_id"]] = record
    return archives


def profile_from_archive(record):
    """Map a site archive to the db site profile.  The archive is the
    authority; the profile keeps its v1 shape (transport.ssh_alias, roots,
    policy) and additionally carries site_root/machine/projects/deps so
    consumers of the store see the same facts."""
    transport = dict(record.get("transport") or {})
    if "alias" in transport and "ssh_alias" not in transport:
        transport["ssh_alias"] = transport.pop("alias")
    transport.setdefault("kind", "local")
    profile = {
        "schema_version": SITE_SCHEMA_VERSION,
        "site_id": record["site_id"],
        "transport": transport,
        "scheduler": record.get("scheduler") or {"kind": "none"},
        "roots": record.get("roots") or {},
        "policy": record.get("policy") or {},
        "shared_mappings": record.get("shared_mappings") or [],
    }
    for key in ("site_root", "machine", "projects", "deps", "notes"):
        if record.get(key) not in (None, "", [], {}):
            profile[key] = record[key]
    return profile


def site_marker_record(site_id, site_root):
    return {
        "site_id": site_id,
        "schema_version": SITE_SCHEMA_VERSION,
        "roots": dict((name, os.path.join(site_root, name))
                      for name in SITE_TREE_DIRS),
    }


# --- deps registry (sites/<site>.yaml deps[] + deps/<stack_id>/stack.yaml) --

STACK_SCHEMA_VERSION = 1
STACK_YAML_FIELDS = (
    "stack_id", "schema_version", "site_id", "kind", "status", "signature",
    "packages", "recipe", "env_sh", "recorded_at", "recorded_by",
)
# Shared contract with entity_checkpoint.py (env-build side, which stays
# ledger-independent and re-implements the few lines): a registry stack
# matches a requirements.json only when every signature field is equal.
STACK_SIGNATURE_FIELDS = (
    "backend", "mpi", "gpu_aware_mpi", "output", "cxx_standard",
    "dependency_profile",
)
# Package keys preserved between a checkpoint's selected entries and the
# registry; discovery_from_stack (env-build) copies exactly these back so a
# deps-add -> export -> --from-registry round trip keeps the same stack_id.
STACK_PACKAGE_KEYS = (
    "version", "prefix", "provider", "bin", "include", "lib",
    "cmake_config", "modules",
)
# Mirror of entity_schema.PROFILES[*]["cxx_standard"] (env-build is the
# single source; only "modern" exists today).  Used to normalize the
# signature when requirements omit cxx_standard.
_PROFILE_CXX_DEFAULTS = {"modern": "20"}


def stack_signature(environment, entity, compile_cfg):
    """Effective toolchain signature: omitted cxx_standard /
    dependency_profile resolve to the version-profile defaults (never ""
    for a buildable request), so equivalent requests sign identically."""
    environment = environment or {}
    entity = entity or {}
    compile_cfg = compile_cfg or {}
    profile = str(entity.get("dependency_profile") or "") or "modern"
    cxx_standard = str(compile_cfg.get("cxx_standard") or "") \
        or _PROFILE_CXX_DEFAULTS.get(profile, "")
    output = environment.get("output", True)
    return {
        "backend": str(environment.get("backend", "")),
        "mpi": bool(environment.get("mpi", False)),
        "gpu_aware_mpi": bool(environment.get("gpu_aware_mpi", False)),
        "output": bool(True if output is None else output),
        "cxx_standard": cxx_standard,
        "dependency_profile": profile,
    }


def stack_packages(selected):
    """Normalize a checkpoint's selected dependencies into registry
    packages: sorted, one entry per dependency, preserving every reuse key
    (prefix stays absent when the dependency is cmake-config-only — no
    prefix<-bin fallback)."""
    packages = []
    for name in sorted(selected):
        entry = selected[name]
        if not isinstance(entry, dict):
            continue
        package = {"name": name}
        for key in STACK_PACKAGE_KEYS:
            value = entry.get(key)
            if value in (None, "", []):
                continue
            package[key] = str(value) if key == "version" else value
        packages.append(package)
    return packages


def _compact(text):
    return re.sub(r"[^A-Za-z0-9.]+", "", str(text))


def derive_stack_id(selected, signature):
    """Deterministic, human-readable stack id: toolchain prefix (dependency
    keys + versions, never the free-form entry name, which does not survive
    a registry round trip) plus 12 hex chars of the (signature, packages)
    content hash — collision-resistant within one site registry."""
    parts = []
    for dep in ("compiler", "mpi", "kokkos"):
        entry = selected.get(dep)
        if isinstance(entry, dict) and entry.get("version"):
            parts.append(_compact(dep) + _compact(entry["version"]))
    base = "-".join(parts) if parts else "stack"
    digest = canonical_hash({
        "signature": signature,
        "packages": stack_packages(selected),
    }).split(":", 1)[1][:12]
    return "%s-%s" % (base, digest)


def upsert_deps_stack(workspace, site_id, stack_entry):
    """Insert or replace one stack entry in the site archive's deps
    registry; returns the updated archive record."""
    path = site_yaml_path(workspace, site_id)
    record = load_site_yaml(path)
    deps = [stack for stack in (record.get("deps") or [])
            if stack.get("stack_id") != stack_entry["stack_id"]]
    deps.append(stack_entry)
    deps.sort(key=lambda stack: str(stack.get("stack_id", "")))
    record["deps"] = deps
    write_site_yaml(workspace, record)
    return record
