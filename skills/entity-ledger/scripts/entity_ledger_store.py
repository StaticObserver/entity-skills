#!/usr/bin/env python3
"""Transactional controller store for Entity Ledger Case facts.

The database contains only compact control facts and evidence references.  Raw
simulation data, long logs, build trees, and run artifacts remain on their
owner sites.  This module is standard-library only and Python 3.6 compatible.

Schema v3 (2026-08): the projects table becomes a Project entity
(project_uid + slug + root) and every case carries a project_uid
reference, splitting the retired root->case 1:1 binding into Project
1:N Case.  ``entityctl store migrate`` upgrades v2 stores in place (and
chains v1 -> v2 -> v3); the v1 archive step is unchanged.

Schema v2 (2026-07): the retired plan/apply protocol tables (operations,
steps) and the cases.active_operation_id column are gone; the record
primitives book identities/current/events directly.  Concurrency control
degrades to the BEGIN IMMEDIATE file lock in ``transaction`` — there is no
claim/lease mechanism anymore.  ``entityctl store migrate`` archives a v1
database's operations/steps to JSON before rebuilding the store (see
entityctl.py).
"""

from __future__ import print_function

import contextlib
import hashlib
import json
import os
import sqlite3
import sys

from entity_ledger_common import (
    LedgerError,
    absolute,
    now_utc,
    ledger_home,
    read_active_workspace,
)


STORE_SCHEMA_VERSION = 3


class StoreError(LedgerError):
    pass


class CaseResolutionError(StoreError):
    """Project->Case addressing failure with a machine-readable reason:
    ``no_project`` (nothing covers the path), ``no_cases`` (project has no
    cases yet), ``ambiguous`` (several cases, none selected), or
    ``unknown_case`` (the requested slug is not in the project)."""
    def __init__(self, message, reason, cases=None):
        StoreError.__init__(self, message)
        self.reason = reason
        self.cases = cases or []


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def canonical_hash(value):
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def workspace_ledger_home(workspace):
    """Controller home inside a Workspace: ``<workspace>/.ledger``."""
    return os.path.join(absolute(workspace), ".ledger")


# The legacy fallback warning is process-global: one deprecation notice per
# process no matter how many stores are opened.
_legacy_fallback_warned = False


def _warn_legacy_fallback_once(home):
    global _legacy_fallback_warned
    if _legacy_fallback_warned:
        return
    _legacy_fallback_warned = True
    sys.stderr.write(
        "entity-ledger: 正在使用旧版控制器目录 %s(已 deprecated);"
        "请用 entityctl workspace init <path> 创建 workspace 并 "
        "entityctl workspace adopt <path> 激活,此后控制器状态解析到 "
        "<workspace>/.ledger\n" % home
    )


def _require_valid_workspace(workspace, source):
    """environment/pointer sources must name a valid workspace — never
    silently create a fresh empty store at a dangling path (split-brain).
    Checked lazily to avoid a store <-> workspace module import cycle."""
    from entity_ledger_workspace import WorkspaceError, is_workspace
    path = absolute(workspace)
    if not is_workspace(path):
        raise WorkspaceError(
            "解析来源 %s 指向的 workspace 无效(不存在或已损坏): %s;"
            "请用 entityctl workspace init <path> 重建后 adopt,或修正/"
            "删除该来源(环境变量 ENTITY_WORKSPACE 或 "
            "~/.entity-ledger/active-workspace 指针)" % (source, path))
    return workspace_ledger_home(path)


def resolve_ledger_home(explicit=None):
    """Resolve the controller home (the directory holding ledger.db).

    Resolution order: an explicit argument (``--ledger-home`` or the
    ``ENTITY_LEDGER_HOME``/``ENTITY_ROUTER_HOME`` variables) >
    ``ENTITY_WORKSPACE`` environment variable > the
    ``~/.entity-ledger/active-workspace`` pointer > the legacy
    ``~/.entity-ledger`` home (compatibility fallback, warns once on
    stderr).  environment/pointer sources must name a valid workspace.
    Returns ``(home, source)`` where source is one of
    ``explicit``, ``environment``, ``pointer``, ``legacy``.
    """
    if (explicit or os.environ.get("ENTITY_LEDGER_HOME")
            or os.environ.get("ENTITY_ROUTER_HOME")):
        return ledger_home(explicit), "explicit"
    workspace = os.environ.get("ENTITY_WORKSPACE")
    if workspace:
        return _require_valid_workspace(workspace, "environment"), "environment"
    pointer = read_active_workspace()
    if pointer:
        return _require_valid_workspace(pointer, "pointer"), "pointer"
    home = ledger_home(None)
    _warn_legacy_fallback_once(home)
    return home, "legacy"


def store_path(home):
    return os.path.join(ledger_home(home), "ledger.db")


def _migrate_legacy_db(home):
    """One-time storage migration from the pre-rename Router layout: if the
    home holds only a legacy ``router.db``, rename it to ``ledger.db``."""
    legacy = os.path.join(home, "router.db")
    current = os.path.join(home, "ledger.db")
    if os.path.isfile(legacy) and not os.path.exists(current):
        os.rename(legacy, current)


def _json(value):
    return canonical_json(value if value is not None else {})


def _load(value, default=None):
    if value is None or value == "":
        return {} if default is None else default
    return json.loads(value)


# v2: no operations/steps tables and no cases.active_operation_id; events
# keeps its operation_id column as a passive audit field only.  Kept as the
# target of the v1 -> v2 migration step; new stores use SCHEMA (v3).
SCHEMA_V2 = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sites (
    site_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    case_uid TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    project_root TEXT,
    source_json TEXT NOT NULL,
    current_json TEXT NOT NULL,
    legacy_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_root TEXT PRIMARY KEY,
    case_uid TEXT NOT NULL REFERENCES cases(case_uid),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identities (
    case_uid TEXT NOT NULL REFERENCES cases(case_uid),
    dimension TEXT NOT NULL,
    identity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_uid, dimension, identity_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_current_identity
ON identities(case_uid, dimension) WHERE is_current = 1;

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_uid TEXT NOT NULL REFERENCES cases(case_uid),
    operation_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    actor_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


# v3: projects is a Project entity (project_uid + slug + root, 1:N cases);
# cases.project_uid references it.  The project_root columns keep absolute
# paths so the existing path-covering lookup semantics are unchanged.
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sites (
    site_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_uid TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    project_root TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    case_uid TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    project_uid TEXT REFERENCES projects(project_uid),
    project_root TEXT,
    source_json TEXT NOT NULL,
    current_json TEXT NOT NULL,
    legacy_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identities (
    case_uid TEXT NOT NULL REFERENCES cases(case_uid),
    dimension TEXT NOT NULL,
    identity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_uid, dimension, identity_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_current_identity
ON identities(case_uid, dimension) WHERE is_current = 1;

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_uid TEXT NOT NULL REFERENCES cases(case_uid),
    operation_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    actor_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class OperationStore(object):
    def __init__(self, home=None, create=True):
        self.home, self.resolution = resolve_ledger_home(home)
        if os.path.isdir(self.home):
            _migrate_legacy_db(self.home)
        self.path = store_path(self.home)
        if create:
            if not os.path.isdir(self.home):
                os.makedirs(self.home)
            self._initialize()
        elif not os.path.isfile(self.path):
            raise StoreError(
                "Entity Ledger store does not exist; initialize it with "
                "entityctl site add (run entityctl doctor for diagnostics)"
            )

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self):
        connection = self._connect()
        try:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version',?)",
                (str(STORE_SCHEMA_VERSION),),
            )
            current = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()[0]
            if int(current) != STORE_SCHEMA_VERSION:
                raise StoreError(
                    "unsupported Ledger store schema: %s (expected %s; run "
                    "entityctl store migrate)" % (current, STORE_SCHEMA_VERSION))
            connection.commit()
        finally:
            connection.close()

    @contextlib.contextmanager
    def transaction(self, immediate=True):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def upsert_site(self, profile, connection=None):
        owns = connection is None
        connection = connection or self._connect()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO sites(site_id,profile_json,updated_at) VALUES(?,?,?)",
                (profile["site_id"], _json(profile), now_utc()),
            )
            if owns:
                connection.commit()
        finally:
            if owns:
                connection.close()

    def get_site(self, site_id):
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT profile_json FROM sites WHERE site_id=?", (site_id,)
            ).fetchone()
            if row is None:
                raise StoreError("unknown site_id: %s" % site_id)
            return _load(row["profile_json"])
        finally:
            connection.close()

    def upsert_project(self, project_uid, slug, project_root,
                       created_at=None, connection=None):
        owns = connection is None
        connection = connection or self._connect()
        timestamp = now_utc()
        normalized_root = absolute(project_root) if project_root else None
        try:
            existing = connection.execute(
                "SELECT created_at FROM projects WHERE project_uid=?",
                (project_uid,)).fetchone()
            if existing:
                connection.execute(
                    "UPDATE projects SET slug=?,project_root=?,updated_at=? "
                    "WHERE project_uid=?",
                    (slug, normalized_root, timestamp, project_uid),
                )
            else:
                connection.execute(
                    """INSERT INTO projects(
                           project_uid,slug,project_root,created_at,updated_at)
                       VALUES(?,?,?,?,?)""",
                    (project_uid, slug, normalized_root,
                     created_at or timestamp, timestamp),
                )
            if owns:
                connection.commit()
        finally:
            if owns:
                connection.close()

    def _project_from_row(self, row):
        return {
            "project_uid": row["project_uid"], "slug": row["slug"],
            "project_root": row["project_root"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def get_project(self, project_uid):
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_uid=?",
                (project_uid,)).fetchone()
            if row is None:
                raise StoreError("unknown Project: %s" % project_uid)
            return self._project_from_row(row)
        finally:
            connection.close()

    def find_projects(self, slug=None):
        connection = self._connect()
        try:
            if slug is None:
                rows = connection.execute(
                    "SELECT * FROM projects ORDER BY slug").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM projects WHERE slug=? ORDER BY project_uid",
                    (slug,)).fetchall()
            return [self._project_from_row(row) for row in rows]
        finally:
            connection.close()

    def project_cases(self, project_uid):
        connection = self._connect()
        try:
            return [
                self._case_from_row(connection, row)
                for row in connection.execute(
                    "SELECT * FROM cases WHERE project_uid=? ORDER BY case_id",
                    (project_uid,))
            ]
        finally:
            connection.close()

    def _ensure_project(self, project_root, connection, timestamp):
        """Find-or-create the implicit Project entity for a root, so the
        retired root->case 1:1 call pattern keeps working unchanged."""
        row = connection.execute(
            "SELECT project_uid FROM projects WHERE project_root=?",
            (project_root,)).fetchone()
        if row:
            return row["project_uid"]
        project_uid = "project-" + canonical_hash(
            {"project_root": project_root}).split(":", 1)[1][:16]
        slug = os.path.basename(project_root) or project_root
        connection.execute(
            """INSERT INTO projects(
                   project_uid,slug,project_root,created_at,updated_at)
               VALUES(?,?,?,?,?)""",
            (project_uid, slug, project_root, timestamp, timestamp),
        )
        return project_uid

    def upsert_case(self, case_uid, case_id, project_root, source, current,
                    legacy=None, created_at=None, project_uid=None,
                    connection=None):
        owns = connection is None
        connection = connection or self._connect()
        timestamp = now_utc()
        normalized_project = absolute(project_root) if project_root else None
        try:
            if project_uid is None and normalized_project:
                project_uid = self._ensure_project(
                    normalized_project, connection, timestamp)
            existing = connection.execute(
                "SELECT created_at,project_uid FROM cases WHERE case_uid=?",
                (case_uid,),
            ).fetchone()
            if existing:
                # UPDATE in place: INSERT OR REPLACE is DELETE+INSERT, which
                # can trip the foreign keys from projects/identities/events.
                # A call without project context (project_uid=None) keeps the
                # existing binding instead of silently unbinding the Case.
                if project_uid is None:
                    project_uid = existing["project_uid"]
                connection.execute(
                    """UPDATE cases SET case_id=?,project_uid=?,project_root=?,
                           source_json=?,current_json=?,legacy_json=?,updated_at=?
                       WHERE case_uid=?""",
                    (case_id, project_uid, normalized_project, _json(source),
                     _json(current), _json(legacy or {}), timestamp, case_uid),
                )
            else:
                connection.execute(
                    """INSERT INTO cases(
                           case_uid,case_id,project_uid,project_root,source_json,
                           current_json,legacy_json,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (case_uid, case_id, project_uid, normalized_project,
                     _json(source), _json(current), _json(legacy or {}),
                     created_at or timestamp, timestamp),
                )
            if owns:
                connection.commit()
        finally:
            if owns:
                connection.close()

    def add_identity(self, case_uid, dimension, identity_id, payload, current=False,
                     connection=None):
        if dimension not in {"source", "build", "run", "data", "analysis"}:
            raise StoreError("invalid identity dimension: %s" % dimension)
        owns = connection is None
        connection = connection or self._connect()
        try:
            if current:
                connection.execute(
                    "UPDATE identities SET is_current=0 WHERE case_uid=? AND dimension=?",
                    (case_uid, dimension),
                )
            connection.execute(
                """INSERT OR REPLACE INTO identities(
                       case_uid,dimension,identity_id,payload_json,is_current,created_at)
                   VALUES(?,?,?,?,?,COALESCE((SELECT created_at FROM identities
                       WHERE case_uid=? AND dimension=? AND identity_id=?),?))""",
                (case_uid, dimension, identity_id, _json(payload), 1 if current else 0,
                 case_uid, dimension, identity_id, now_utc()),
            )
            if owns:
                connection.commit()
        finally:
            if owns:
                connection.close()

    def _case_from_row(self, connection, row):
        identities = {}
        for item in connection.execute(
                "SELECT dimension,identity_id,payload_json,is_current FROM identities "
                "WHERE case_uid=? ORDER BY dimension,created_at", (row["case_uid"],)):
            dimension = item["dimension"]
            identities.setdefault(dimension, {"current_id": "", "items": []})
            payload = _load(item["payload_json"])
            identities[dimension]["items"].append(payload)
            if item["is_current"]:
                identities[dimension]["current_id"] = item["identity_id"]
        return {
            "case_uid": row["case_uid"], "case_id": row["case_id"],
            "project_uid": row["project_uid"],
            "project_root": row["project_root"], "source": _load(row["source_json"]),
            "current": _load(row["current_json"]), "identities": identities,
            "legacy": _load(row["legacy_json"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def get_case(self, case_uid):
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM cases WHERE case_uid=?", (case_uid,)).fetchone()
            if row is None:
                raise StoreError("unknown Case: %s" % case_uid)
            return self._case_from_row(connection, row)
        finally:
            connection.close()

    def resolve_project(self, path, case_slug=None):
        """Resolve the Case for a project path: the longest covering Project
        root wins, then ``case_slug`` selects within it.  Without a slug a
        single-case Project resolves implicitly; several cases (or none)
        raise CaseResolutionError with the available slugs."""
        query = absolute(path)
        connection = self._connect()
        try:
            matches = []
            for row in connection.execute(
                    "SELECT project_uid,project_root FROM projects"):
                if not row["project_root"]:
                    # Legacy rows may carry a NULL/empty root; they can never
                    # cover a query path and must not be absolutized.
                    continue
                root = absolute(row["project_root"])
                try:
                    within = os.path.commonpath([query, root]) == root
                except ValueError:
                    within = False
                if within:
                    matches.append((len(root), row["project_uid"]))
            if not matches:
                raise CaseResolutionError(
                    "no Case covers project path: %s" % query, "no_project")
            matches.sort(reverse=True)
            project_uid = matches[0][1]
            rows = connection.execute(
                "SELECT * FROM cases WHERE project_uid=? ORDER BY case_id",
                (project_uid,)).fetchall()
            available = [row["case_id"] for row in rows]
            if case_slug:
                for row in rows:
                    if row["case_id"] == case_slug or row["case_uid"] == case_slug:
                        return self._case_from_row(connection, row)
                raise CaseResolutionError(
                    "project has no case '%s' (available: %s)"
                    % (case_slug, ", ".join(available) or "none"),
                    "unknown_case", available)
            if not rows:
                raise CaseResolutionError(
                    "the Project covering %s has no cases yet; create one "
                    "with entityctl case init" % query, "no_cases", [])
            if len(rows) > 1:
                raise CaseResolutionError(
                    "the Project has multiple cases; select one with --case "
                    "(available: %s)" % ", ".join(available),
                    "ambiguous", available)
            return self._case_from_row(connection, rows[0])
        finally:
            connection.close()

    def record_event(self, case_uid, operation_id, event_type, payload, actor,
                     connection=None):
        """Public event writer for the primitive record commands, which book
        Case facts outside the Operation protocol.  Pass ``connection`` to
        join an open transaction so the event commits atomically with the
        identity and current writes."""
        owns = connection is None
        connection = connection or self._connect()
        try:
            self._event(connection, case_uid, operation_id, event_type, payload, actor)
            if owns:
                connection.commit()
        finally:
            if owns:
                connection.close()

    def _event(self, connection, case_uid, operation_id, event_type, payload, actor):
        connection.execute(
            """INSERT INTO events(case_uid,operation_id,event_type,payload_json,actor_json,created_at)
               VALUES(?,?,?,?,?,?)""",
            (case_uid, operation_id, event_type, _json(payload), _json(actor), now_utc()),
        )

    def export(self):
        connection = self._connect()
        try:
            result = {"schema_version": STORE_SCHEMA_VERSION, "sites": [], "cases": [],
                      "projects": [], "events": []}
            result["sites"] = [_load(row["profile_json"]) for row in
                               connection.execute("SELECT profile_json FROM sites ORDER BY site_id")]
            result["projects"] = [dict(row) for row in
                                  connection.execute("SELECT * FROM projects ORDER BY project_root")]
            for row in connection.execute("SELECT * FROM cases ORDER BY case_uid"):
                result["cases"].append(self._case_from_row(connection, row))
            for row in connection.execute("SELECT * FROM events ORDER BY event_id"):
                item = dict(row)
                item["payload"] = _load(item.pop("payload_json"))
                item["actor"] = _load(item.pop("actor_json"))
                result["events"].append(item)
            return result
        finally:
            connection.close()
