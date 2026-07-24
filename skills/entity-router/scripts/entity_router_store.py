#!/usr/bin/env python3
"""Transactional controller store for Entity Router Case facts.

The database contains only compact control facts and evidence references.  Raw
simulation data, long logs, build trees, and run artifacts remain on their
owner sites.  This module is standard-library only and Python 3.6 compatible.

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

from entity_router_common import (
    RouterError,
    absolute,
    now_utc,
    router_home,
)


STORE_SCHEMA_VERSION = 2


class StoreError(RouterError):
    pass


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def canonical_hash(value):
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def store_path(home):
    return os.path.join(router_home(home), "router.db")


def _json(value):
    return canonical_json(value if value is not None else {})


def _load(value, default=None):
    if value is None or value == "":
        return {} if default is None else default
    return json.loads(value)


# v2: no operations/steps tables and no cases.active_operation_id; events
# keeps its operation_id column as a passive audit field only.
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


class OperationStore(object):
    def __init__(self, home=None, create=True):
        self.home = router_home(home)
        self.path = store_path(self.home)
        if create:
            if not os.path.isdir(self.home):
                os.makedirs(self.home)
            self._initialize()
        elif not os.path.isfile(self.path):
            raise StoreError(
                "Entity Router store does not exist; initialize it with "
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
                    "unsupported Router store schema: %s (expected %s; run "
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

    def has_cases(self):
        connection = self._connect()
        try:
            return connection.execute("SELECT 1 FROM cases LIMIT 1").fetchone() is not None
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

    def upsert_case(self, case_uid, case_id, project_root, source, current,
                    legacy=None, created_at=None, connection=None):
        owns = connection is None
        connection = connection or self._connect()
        timestamp = now_utc()
        normalized_project = absolute(project_root) if project_root else None
        try:
            existing = connection.execute(
                "SELECT created_at FROM cases WHERE case_uid=?", (case_uid,)
            ).fetchone()
            connection.execute(
                """INSERT OR REPLACE INTO cases(
                       case_uid,case_id,project_root,source_json,current_json,legacy_json,
                       created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (case_uid, case_id, normalized_project, _json(source), _json(current),
                 _json(legacy or {}),
                 existing["created_at"] if existing else (created_at or timestamp), timestamp),
            )
            if normalized_project:
                connection.execute(
                    "INSERT OR REPLACE INTO projects(project_root,case_uid,updated_at) VALUES(?,?,?)",
                    (normalized_project, case_uid, timestamp),
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

    def resolve_project(self, path):
        query = absolute(path)
        connection = self._connect()
        try:
            matches = []
            for row in connection.execute("SELECT project_root,case_uid FROM projects"):
                root = absolute(row["project_root"])
                try:
                    within = os.path.commonpath([query, root]) == root
                except ValueError:
                    within = False
                if within:
                    matches.append((len(root), row["case_uid"]))
            if not matches:
                raise StoreError("no Case covers project path: %s" % query)
            matches.sort(reverse=True)
            row = connection.execute(
                "SELECT * FROM cases WHERE case_uid=?", (matches[0][1],)
            ).fetchone()
            return self._case_from_row(connection, row)
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
