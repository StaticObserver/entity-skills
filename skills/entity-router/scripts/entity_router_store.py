#!/usr/bin/env python3
"""Transactional v5 controller store for Entity Router operations.

The database contains only compact control facts and evidence references.  Raw
simulation data, long logs, build trees, and run artifacts remain on their
owner sites.  This module is standard-library only and Python 3.6 compatible.
"""

from __future__ import print_function

import contextlib
import datetime
import hashlib
import json
import os
import sqlite3
import uuid

from entity_router_common import (
    RouterError,
    absolute,
    ensure_home,
    list_site_profiles,
    load_json,
    load_registry,
    now_utc,
    router_home,
)


STORE_SCHEMA_VERSION = 1


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


def _utc_after(seconds):
    value = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    active_operation_id TEXT,
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

CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    case_uid TEXT NOT NULL REFERENCES cases(case_uid),
    goal_hash TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    goal_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    actor_json TEXT NOT NULL,
    claim_token TEXT,
    claim_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(case_uid, plan_hash)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_operation
ON operations(case_uid) WHERE status IN ('pending','running');

CREATE TABLE IF NOT EXISTS steps (
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    step_index INTEGER NOT NULL,
    step_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    status TEXT NOT NULL,
    effect_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    error_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (operation_id, step_index),
    UNIQUE(operation_id, step_id)
);

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
            ensure_home(self.home)
            self._initialize()
        elif not os.path.isfile(self.path):
            raise StoreError("Router v5 store does not exist; run entityctl migrate")

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
                raise StoreError("unsupported Router store schema: %s" % current)
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
                raise StoreError("unknown v5 site_id: %s" % site_id)
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
                       active_operation_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,
                       COALESCE((SELECT active_operation_id FROM cases WHERE case_uid=?),NULL),?,?)""",
                (case_uid, case_id, normalized_project, _json(source), _json(current),
                 _json(legacy or {}), case_uid,
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
        active = None
        if row["active_operation_id"]:
            active = self._operation_from_row(connection, connection.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (row["active_operation_id"],),
            ).fetchone(), include_plan=False)
        return {
            "case_uid": row["case_uid"], "case_id": row["case_id"],
            "project_root": row["project_root"], "source": _load(row["source_json"]),
            "current": _load(row["current_json"]), "identities": identities,
            "legacy": _load(row["legacy_json"]), "active_operation": active,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def get_case(self, case_uid):
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM cases WHERE case_uid=?", (case_uid,)).fetchone()
            if row is None:
                raise StoreError("unknown v5 Case: %s" % case_uid)
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
                raise StoreError("no v5 Case covers project path: %s" % query)
            matches.sort(reverse=True)
            row = connection.execute(
                "SELECT * FROM cases WHERE case_uid=?", (matches[0][1],)
            ).fetchone()
            return self._case_from_row(connection, row)
        finally:
            connection.close()

    def create_operation(self, case_uid, goal, plan, actor):
        plan_hash = plan["plan_hash"]
        goal_hash = canonical_hash(goal)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE case_uid=? AND plan_hash=?",
                (case_uid, plan_hash),
            ).fetchone()
            if row is not None:
                return self._operation_from_row(connection, row)
            active = connection.execute(
                "SELECT operation_id,plan_hash FROM operations WHERE case_uid=? "
                "AND status IN ('pending','running')",
                (case_uid,),
            ).fetchone()
            if active is not None:
                raise StoreError(
                    "Case has another active Operation: %s" % active["operation_id"]
                )
            operation_id = plan["operation_id"]
            timestamp = now_utc()
            connection.execute(
                """INSERT INTO operations(
                       operation_id,case_uid,goal_hash,plan_hash,goal_json,plan_json,
                       status,result_json,actor_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (operation_id, case_uid, goal_hash, plan_hash, _json(goal), _json(plan),
                 "pending", _json({}), _json(actor), timestamp, timestamp),
            )
            for index, step in enumerate(plan["steps"]):
                connection.execute(
                    """INSERT INTO steps(operation_id,step_index,step_id,kind,spec_json,
                           status,effect_json,evidence_json,error_json,updated_at)
                       VALUES(?,?,?,?,?,'pending','{}','[]','{}',?)""",
                    (operation_id, index, step["step_id"], step["kind"], _json(step), timestamp),
                )
            connection.execute(
                "UPDATE cases SET active_operation_id=?,updated_at=? WHERE case_uid=?",
                (operation_id, timestamp, case_uid),
            )
            self._event(connection, case_uid, operation_id, "operation.created",
                        {"plan_hash": plan_hash}, actor)
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            return self._operation_from_row(connection, row)

    def _operation_from_row(self, connection, row, include_plan=True):
        if row is None:
            return None
        steps = []
        for item in connection.execute(
                "SELECT * FROM steps WHERE operation_id=? ORDER BY step_index",
                (row["operation_id"],)):
            step = {
                "index": item["step_index"], "step_id": item["step_id"],
                "kind": item["kind"], "status": item["status"],
                "effect": _load(item["effect_json"]),
                "evidence": _load(item["evidence_json"], []),
                "error": _load(item["error_json"]), "updated_at": item["updated_at"],
            }
            if include_plan:
                step["spec"] = _load(item["spec_json"])
            steps.append(step)
        result = {
            "operation_id": row["operation_id"], "case_uid": row["case_uid"],
            "goal_hash": row["goal_hash"], "plan_hash": row["plan_hash"],
            "status": row["status"], "result": _load(row["result_json"]),
            "actor": _load(row["actor_json"]), "steps": steps,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        if include_plan:
            result["goal"] = _load(row["goal_json"])
            result["plan"] = _load(row["plan_json"])
        return result

    def get_operation(self, operation_id):
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise StoreError("unknown Operation: %s" % operation_id)
            return self._operation_from_row(connection, row)
        finally:
            connection.close()

    def claim_operation(self, operation_id, actor, ttl_seconds=3600):
        token = str(uuid.uuid4())
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status,claim_token,claim_expires_at FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise StoreError("unknown Operation: %s" % operation_id)
            if row["status"] in {"completed", "needs_decision", "blocked", "anomaly", "cancelled"}:
                return ""
            now = now_utc()
            if (row["claim_token"] and row["claim_expires_at"]
                    and row["claim_expires_at"] > now):
                raise StoreError("Operation is already being applied")
            connection.execute(
                "UPDATE operations SET claim_token=?,claim_expires_at=?,status='running',updated_at=? "
                "WHERE operation_id=?",
                (token, _utc_after(ttl_seconds), now, operation_id),
            )
            case_uid = connection.execute(
                "SELECT case_uid FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()[0]
            self._event(connection, case_uid, operation_id, "operation.claimed",
                        {"claim_token": token, "ttl_seconds": ttl_seconds}, actor)
        return token

    def renew_claim(self, operation_id, token, ttl_seconds=90):
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE operations SET claim_expires_at=?,updated_at=? "
                "WHERE operation_id=? AND claim_token=?",
                (_utc_after(ttl_seconds), now_utc(), operation_id, token),
            ).rowcount
            if changed != 1:
                raise StoreError("Operation claim is no longer held")

    def release_claim(self, operation_id, token, actor):
        if not token:
            return
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT case_uid,claim_token FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None or row["claim_token"] != token:
                return
            connection.execute(
                "UPDATE operations SET claim_token=NULL,claim_expires_at=NULL,updated_at=? "
                "WHERE operation_id=?", (now_utc(), operation_id),
            )
            self._event(connection, row["case_uid"], operation_id,
                        "operation.claim_released", {}, actor)

    def update_step(self, operation_id, step_index, status, effect=None,
                    evidence=None, error=None, actor=None):
        allowed = {"pending", "intent_written", "effect_observed", "verified",
                   "committed", "needs_decision", "blocked", "anomaly"}
        if status not in allowed:
            raise StoreError("invalid Step status: %s" % status)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT o.case_uid,s.step_id FROM steps s JOIN operations o "
                "ON o.operation_id=s.operation_id WHERE s.operation_id=? AND s.step_index=?",
                (operation_id, step_index),
            ).fetchone()
            if row is None:
                raise StoreError("unknown Operation Step")
            connection.execute(
                """UPDATE steps SET status=?,effect_json=?,evidence_json=?,error_json=?,updated_at=?
                   WHERE operation_id=? AND step_index=?""",
                (status, _json(effect or {}), _json(evidence or []), _json(error or {}),
                 now_utc(), operation_id, step_index),
            )
            self._event(connection, row["case_uid"], operation_id,
                        "step.%s" % status,
                        {"step_index": step_index, "step_id": row["step_id"]}, actor or {})

    def commit_step(self, operation_id, step_index, effect, evidence, identities,
                    current, actor):
        """Atomically commit one verified Step and all controller projections."""
        with self.transaction() as connection:
            operation = connection.execute(
                "SELECT case_uid FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if operation is None:
                raise StoreError("unknown Operation: %s" % operation_id)
            case_uid = operation["case_uid"]
            step = connection.execute(
                "SELECT step_id FROM steps WHERE operation_id=? AND step_index=?",
                (operation_id, step_index),
            ).fetchone()
            if step is None:
                raise StoreError("unknown Operation Step")
            for item in identities or []:
                self.add_identity(
                    case_uid, item["dimension"], item["identity_id"], item["payload"],
                    bool(item.get("current", True)), connection,
                )
            connection.execute(
                "UPDATE cases SET current_json=?,updated_at=? WHERE case_uid=?",
                (_json(current), now_utc(), case_uid),
            )
            connection.execute(
                """UPDATE steps SET status='committed',effect_json=?,evidence_json=?,
                       error_json='{}',updated_at=? WHERE operation_id=? AND step_index=?""",
                (_json(effect or {}), _json(evidence or []), now_utc(), operation_id, step_index),
            )
            connection.execute(
                "UPDATE operations SET updated_at=? WHERE operation_id=?",
                (now_utc(), operation_id),
            )
            self._event(connection, case_uid, operation_id, "step.committed",
                        {"step_index": step_index, "step_id": step["step_id"]}, actor)

    def finish_operation(self, operation_id, status, result, actor):
        if status not in {"completed", "needs_decision", "blocked", "anomaly", "cancelled"}:
            raise StoreError("invalid Operation terminal status: %s" % status)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT case_uid FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise StoreError("unknown Operation: %s" % operation_id)
            connection.execute(
                """UPDATE operations SET status=?,result_json=?,claim_token=NULL,
                       claim_expires_at=NULL,updated_at=? WHERE operation_id=?""",
                (status, _json(result or {}), now_utc(), operation_id),
            )
            connection.execute(
                "UPDATE cases SET active_operation_id=NULL,updated_at=? WHERE case_uid=?",
                (now_utc(), row["case_uid"]),
            )
            self._event(connection, row["case_uid"], operation_id,
                        "operation.%s" % status, result or {}, actor)

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
                      "projects": [], "operations": [], "events": []}
            result["sites"] = [_load(row["profile_json"]) for row in
                               connection.execute("SELECT profile_json FROM sites ORDER BY site_id")]
            result["projects"] = [dict(row) for row in
                                  connection.execute("SELECT * FROM projects ORDER BY project_root")]
            for row in connection.execute("SELECT * FROM cases ORDER BY case_uid"):
                result["cases"].append(self._case_from_row(connection, row))
            for row in connection.execute("SELECT * FROM operations ORDER BY created_at"):
                result["operations"].append(self._operation_from_row(connection, row))
            for row in connection.execute("SELECT * FROM events ORDER BY event_id"):
                item = dict(row)
                item["payload"] = _load(item.pop("payload_json"))
                item["actor"] = _load(item.pop("actor_json"))
                result["events"].append(item)
            return result
        finally:
            connection.close()


def _legacy_project_bindings(home):
    path = os.path.join(router_home(home), "project-bindings.json")
    if not os.path.isfile(path):
        return {}
    payload = load_json(path, "legacy project bindings")
    return payload.get("projects", {})


def migrate_v3(home=None, dry_run=False):
    """Import v3 controller facts once without changing preserved v3 files."""
    home = router_home(home)
    database = store_path(home)
    if os.path.isfile(database):
        existing_store = OperationStore(home, create=False)
        connection = existing_store._connect()
        try:
            imported = connection.execute(
                "SELECT value FROM meta WHERE key='v3_imported_at'"
            ).fetchone()
        finally:
            connection.close()
        if imported is not None:
            exported = existing_store.export()
            return {
                "schema_version": 1, "kind": "entity-router.v3-migration",
                "router_home": home, "sites": len(exported["sites"]),
                "cases": len(exported["cases"]), "projects": len(exported["projects"]),
                "dry_run": bool(dry_run), "already_imported": True,
                "imported_at": imported["value"], "state_mutated": False,
            }
    registry = load_registry(home)
    sites = list_site_profiles(home)
    bindings = _legacy_project_bindings(home)
    summary = {
        "schema_version": 1, "kind": "entity-router.v3-migration",
        "router_home": home, "sites": len(sites), "cases": len(registry.get("cases", {})),
        "projects": len(bindings), "dry_run": bool(dry_run), "state_mutated": not dry_run,
        "already_imported": False,
    }
    if dry_run:
        return summary
    store = OperationStore(home, create=True)
    with store.transaction() as connection:
        for profile in sites:
            store.upsert_site(profile, connection)
        project_by_case = {}
        for root, record in bindings.items():
            project_by_case.setdefault(record.get("case_uid", ""), []).append(root)
        for case_uid, record in registry.get("cases", {}).items():
            case_path = os.path.join(record["control_root"], "case.json")
            state = load_json(case_path, "legacy Case")
            roots = project_by_case.get(case_uid, [])
            project_root = sorted(roots, key=len)[0] if roots else None
            resources = state.get("resources", {})
            current = {
                "source_id": canonical_hash(state.get("source", {}).get("revision", {})),
                "build_id": resources.get("build", {}).get("current_id", ""),
                "run_id": resources.get("run", {}).get("current_id", ""),
                "active_run": resources.get("run", {}).get("active"),
                "data_id": resources.get("data", {}).get("current_id", ""),
                "analysis_id": resources.get("analysis", {}).get("current_id", ""),
                "readiness": dict((key, value.get("status", ""))
                                  for key, value in state.get("readiness", {}).items()),
            }
            active_action = state.get("workflow", {}).get("active_action_id", "")
            result_on_active = False
            if active_action:
                result_on_active = os.path.isfile(os.path.join(
                    record["control_root"], "actions", active_action, "result.json"
                ))
            legacy = {
                "schema_version": state.get("schema_version"),
                "control_root": record["control_root"],
                "revision": state.get("revision"),
                "workflow": state.get("workflow", {}),
                "readiness": state.get("readiness", {}),
                "result_on_active": result_on_active,
                "imported_at": now_utc(),
            }
            store.upsert_case(
                case_uid, state.get("case_id", record.get("case_id", case_uid)),
                project_root, state.get("source", {}), current, legacy,
                state.get("created_at"), connection,
            )
            source_revision = state.get("source", {}).get("revision", {})
            if source_revision:
                source_id = current["source_id"]
                store.add_identity(case_uid, "source", source_id, {
                    "id": source_id, "identity_id": source_id, "dimension": "source",
                    "payload": source_revision,
                }, True, connection)
            for dimension in ["build", "run", "data", "analysis"]:
                resource = resources.get(dimension, {})
                for identity in resource.get("identities", []):
                    store.add_identity(
                        case_uid, dimension, identity.get("id", ""), identity,
                        identity.get("id", "") == resource.get("current_id", ""), connection,
                    )
            store._event(connection, case_uid, None, "case.v3_imported", {
                "legacy_revision": state.get("revision"),
                "result_on_active": result_on_active,
            }, {"run_id": "migration", "provider": "entityctl"})
        for root, record in bindings.items():
            if record.get("case_uid") in registry.get("cases", {}):
                connection.execute(
                    "INSERT OR REPLACE INTO projects(project_root,case_uid,updated_at) VALUES(?,?,?)",
                    (absolute(root), record["case_uid"], now_utc()),
                )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('v3_imported_at',?)", (now_utc(),)
        )
    return summary
