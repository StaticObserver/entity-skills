#!/usr/bin/env python3
"""Registry/Locator preflight for Entity PGen work.

Read-only and truly standalone PGen work may run directly.  A write inside a
Case's registered source authority is a managed write and is allowed: the
Ledger does not intervene in the PGen process; once the change settles,
``entityctl snapshot-source`` re-probes the tree and books the new source
identity.  Recorded artifact roots (build/run/data identities and the active
run) are Ledger evidence and stay fail-closed.  No source/control ancestor
relationship is assumed.

Subcommands:

- ``card <input.toml>``: extract a best-effort simulation parameter card
  (JSON on stdout) with a stable digest over the extracted fields.
- ``confirm <input.toml> --by <actor> [--confirm-defaults]``: write an
  atomic confirmation record to ``<input.toml>.decisions.json`` recording
  who confirmed which exact input file.  The Ledger record run-prepare gate
  reads this record and matches ``input_sha256`` before booking the run.
"""

from __future__ import print_function

import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import sys
import tempfile


LEDGER_SCRIPTS = os.path.realpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "entity-ledger", "scripts"
))
if LEDGER_SCRIPTS not in sys.path:
    sys.path.insert(0, LEDGER_SCRIPTS)

from entity_ledger_common import (  # noqa: E402
    LedgerError,
    absolute,
    locator_within,
    parse_locator,
    ledger_home,
)
from entity_ledger_store import OperationStore, StoreError  # noqa: E402


# --- Simulation parameter card / confirmation record -----------------------

CARD_SCHEMA_VERSION = 1
CARD_KIND = "entity-parameter-card"
RECORD_KIND = "entity-pgen.simulation-confirmation"

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None


def _fallback_parse_value(text):
    """Best-effort TOML scalar/array parser; only what the card needs."""
    text = text.strip()
    if not text:
        return None
    if text.startswith('"') or text.startswith("'"):
        quote = text[0]
        end = text.rfind(quote)
        return text[1:end] if end > 0 else text.strip(quote)
    if text.startswith("["):
        inner = text.strip()[1:-1]
        items, depth, current, quote = [], 0, "", None
        for char in inner:
            if quote:
                current += char
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
                current += char
            elif char == "[":
                depth += 1
                current += char
            elif char == "]":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                items.append(_fallback_parse_value(current))
                current = ""
            else:
                current += char
        if current.strip():
            items.append(_fallback_parse_value(current))
        return items
    if text.startswith("{"):
        inner = text.strip()[1:-1]
        table = {}
        for part in inner.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                table[key.strip()] = _fallback_parse_value(value)
        return table
    if text in ("true", "false"):
        return text == "true"
    try:
        return int(text.replace("_", ""))
    except ValueError:
        pass
    try:
        return float(text.replace("_", ""))
    except ValueError:
        pass
    return text


def fallback_parse_toml(text):
    """Best-effort TOML parser used only when tomllib is unavailable.

    Handles comments, [table] / [dotted.table] headers, [[array.of.tables]],
    and string/number/boolean/array/inline-table values.  It is intentionally
    small and only meant to cover the fields the parameter card extracts.

    Known limitations (accepted, since tomllib covers Python >= 3.11):
    inline comment stripping is skipped for any value containing a double
    quote (so ``#`` inside single-quoted strings still truncates), and
    inline tables are split on bare commas without tracking nested
    tables/arrays or quoted commas.
    """
    root = {}
    current = root
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[["):
            path = line.strip("[] ").split(".")
            parent = root
            for part in path[:-1]:
                parent = parent.setdefault(part, {})
                if isinstance(parent, list):
                    parent = parent[-1]
            bucket = parent.setdefault(path[-1], [])
            if not isinstance(bucket, list):
                bucket = parent[path[-1]] = []
            bucket.append({})
            current = bucket[-1]
        elif line.startswith("["):
            path = line.strip("[] ").split(".")
            current = root
            for part in path:
                current = current.setdefault(part, {})
        elif "=" in line:
            key, value = line.split("=", 1)
            value = value.split(" #", 1)[0].strip() if '"' not in value else value.strip()
            current[key.strip()] = _fallback_parse_value(value)
    return root


def load_toml(raw):
    text = raw.decode("utf-8")
    if tomllib is not None:
        return tomllib.loads(text)
    return fallback_parse_toml(text)


def _table(data, *path):
    node = data
    for part in path:
        if not isinstance(node, dict):
            return {}
        node = node.get(part) or {}
    return node if isinstance(node, dict) else {}


def _species_list(particles):
    species = particles.get("species")
    if isinstance(species, list):
        return [item for item in species if isinstance(item, dict)]
    if isinstance(species, dict):
        return [species]
    return []


def _add_field(fields, key, value, tier):
    fields[key] = {"value": value, "tier": tier}


def _flatten_tier2(fields, prefix, table):
    for key in sorted(table):
        value = table[key]
        dotted = "%s.%s" % (prefix, key) if prefix else key
        if isinstance(value, dict):
            _flatten_tier2(fields, dotted, value)
        elif not isinstance(value, list) or not any(isinstance(v, dict) for v in value):
            _add_field(fields, dotted, value, 2)


SETUP_PHYSICS_HINTS = ("density", "drift", "temp")


def extract_fields(data):
    """Best-effort, display-oriented extraction; missing tier-1 categories
    are reported as warnings instead of failing."""
    fields = {}
    warnings = []

    grid = _table(data, "grid")
    found = False
    for key in ("resolution", "cells", "extent", "extents"):
        if key in grid:
            _add_field(fields, "grid.%s" % key, grid[key], 1)
            found = True
    if not found:
        warnings.append("tier-1 missing: grid extent/resolution (grid.resolution, grid.extent)")

    particles = _table(data, "particles")
    species = _species_list(particles)
    found = False
    if "ppc0" in particles:
        _add_field(fields, "particles.ppc0", particles["ppc0"], 1)
        found = True
    for index, item in enumerate(species):
        if "maxnpart" in item:
            _add_field(fields, "particles.species.%d.maxnpart" % index,
                       item["maxnpart"], 1)
            found = True
    if not found:
        warnings.append("tier-1 missing: particle count (particles.ppc0, particles.species.*.maxnpart)")

    found = False
    if "nspec" in particles:
        _add_field(fields, "particles.nspec", particles["nspec"], 1)
        found = True
    for index, item in enumerate(species):
        for key in ("label", "mass", "charge", "density", "drift", "temperature"):
            if key in item:
                _add_field(fields, "particles.species.%d.%s" % (index, key),
                           item[key], 1)
                found = True
    setup = _table(data, "setup")
    for key in sorted(setup):
        if any(hint in key.lower() for hint in SETUP_PHYSICS_HINTS):
            _add_field(fields, "setup.%s" % key, setup[key], 1)
            found = True
    if not found:
        warnings.append("tier-1 missing: species/injection (particles.nspec, species mass/charge, setup density/drift/temperature)")

    boundaries = _table(data, "boundaries")
    if boundaries.get("fields") is not None or boundaries.get("particles") is not None:
        for key in ("fields", "particles"):
            if boundaries.get(key) is not None:
                _add_field(fields, "boundaries.%s" % key, boundaries[key], 1)
    else:
        warnings.append("tier-1 missing: boundary conditions (boundaries.fields, boundaries.particles)")

    simulation = _table(data, "simulation")
    timestep = _table(data, "algorithms", "timestep")
    found = False
    for key in ("runtime", "t_end", "steps"):
        if key in simulation:
            _add_field(fields, "simulation.%s" % key, simulation[key], 1)
            found = True
    for key in ("dt", "CFL"):
        if key in timestep:
            _add_field(fields, "algorithms.timestep.%s" % key, timestep[key], 1)
            found = True
    if not found:
        warnings.append("tier-1 missing: timestep (simulation.runtime/steps, algorithms.timestep.dt/CFL)")

    for key in ("name", "engine"):
        if key in simulation:
            _add_field(fields, "simulation.%s" % key, simulation[key], 2)
    _flatten_tier2(fields, "output", _table(data, "output"))

    return fields, warnings


def build_card(path):
    with open(path, "rb") as handle:
        raw = handle.read()
    input_sha256 = hashlib.sha256(raw).hexdigest()
    fields, warnings = extract_fields(load_toml(raw))
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "schema_version": CARD_SCHEMA_VERSION,
        "kind": CARD_KIND,
        "domain": "simulation",
        "input_sha256": input_sha256,
        "fields": fields,
        "digest": digest,
        "warnings": warnings,
    }


def build_record(card, actor, confirm_defaults):
    return {
        "schema_version": CARD_SCHEMA_VERSION,
        "kind": RECORD_KIND,
        "input_sha256": card["input_sha256"],
        "card": card,
        "confirmed_by": actor,
        "confirmed_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "defaults": bool(confirm_defaults),
    }


def atomic_write_json(path, payload):
    handle, temp_path = tempfile.mkstemp(
        dir=os.path.dirname(os.path.abspath(path)) or ".",
        prefix=".decisions-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def card_main(argv):
    parser = argparse.ArgumentParser(
        prog="pgen_preflight.py card",
        description="Extract a simulation parameter card from an Entity TOML")
    parser.add_argument("input", help="path to the simulation input TOML")
    args = parser.parse_args(argv)
    try:
        card = build_card(args.input)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(card, indent=2, sort_keys=True))
    return 0


def confirm_main(argv):
    parser = argparse.ArgumentParser(
        prog="pgen_preflight.py confirm",
        description="Record simulation parameter confirmation for an Entity TOML")
    parser.add_argument("input", help="path to the simulation input TOML")
    parser.add_argument("--by", dest="actor", required=True,
                        help="actor confirming the parameters (required)")
    parser.add_argument("--confirm-defaults", action="store_true",
                        help="accept defaults without item-by-item review (audit flag)")
    args = parser.parse_args(argv)
    record_path = args.input + ".decisions.json"
    try:
        card = build_card(args.input)
        record = build_record(card, args.actor, args.confirm_defaults)
        atomic_write_json(record_path, record)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True))
        return 2
    payload = dict(record)
    payload["record_path"] = os.path.abspath(record_path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def target_locator(value, default_site, home=None):
    if isinstance(value, dict) or ":" in value:
        item = parse_locator(value)
    else:
        item = {"site_id": default_site, "path": absolute(value)}
    return canonical_locator(home, item) if home else item


def canonical_locator(home, locator):
    """Resolve local-site symlinks while preserving remote path semantics."""
    item = parse_locator(locator)
    try:
        profile = OperationStore(home, create=False).get_site(item["site_id"])
    except StoreError:
        return item
    if profile.get("transport", {}).get("kind") == "local":
        item["path"] = absolute(item["path"])
    return item


def result(allowed, mode, target, case=None, reason="", action_id="",
           store_present=None):
    return {
        "allowed": allowed,
        "mode": mode,
        "target": parse_locator(target),
        "case_uid": case.get("case_uid", "") if case else "",
        "control_root": case.get("control_root", "") if case else "",
        "action_id": action_id,
        "reason": reason,
        # True: registry queried and the outcome is authoritative.
        # False: store missing/unreadable, "standalone" means "unqueried".
        # None: evaluation failed before the store was queried.
        "store_present": store_present,
    }


def registered_cases(home):
    """Return (cases, store_present); store_present is False when the
    registry could not be opened, so callers can tell "confirmed
    unregistered" apart from "could not query"."""
    try:
        store = OperationStore(home, create=False)
    except StoreError:
        return [], False
    return store.export()["cases"], True


def case_match(home, case, target):
    """Classify how a Case covers target: "artifact" for recorded evidence
    roots (non-source identities, the active run), "source" for the editable
    source authority, or None.  Artifact roots win over the authority so a
    run/build/data root inside the checkout stays protected.  Source
    identities are skipped: their root IS the authority."""
    protected = []
    for dimension, bucket in (case.get("identities") or {}).items():
        if dimension == "source":
            continue
        for item in bucket.get("items", []):
            if item.get("root"):
                protected.append(item["root"])
    current = case.get("current") or {}
    if current.get("active_run"):
        protected.append(current["active_run"])
    for root in protected:
        if locator_within(target, canonical_locator(home, root)):
            return "artifact"
    authority = (case.get("source") or {}).get("authority")
    if authority and locator_within(target, canonical_locator(home, authority)):
        return "source"
    return None


def find_cases(home, target):
    cases, store_present = registered_cases(home)
    matches = [case for case in cases if case_match(home, case, target)]
    return matches, store_present


def evaluate(args):
    home = ledger_home(args.ledger_home)
    target = target_locator(args.target, args.site_id, home)
    matches, store_present = find_cases(home, target)
    if len(matches) > 1:
        return result(False, "ambiguous", target, store_present=store_present,
                      reason=(
            "locator is registered by multiple Cases; use distinct source authority roots"
        ))
    case = matches[0] if matches else None

    if args.operation == "read":
        return result(True, "managed-readonly" if case else "standalone-readonly",
                      target, case, "read-only operation",
                      store_present=store_present)
    if not case:
        reason = "locator is not registered by Ledger"
        if not store_present:
            reason = ("Ledger store is missing or unreadable; registration "
                      "could not be checked, treating target as standalone")
        return result(True, "standalone-write", target,
                      reason=reason, store_present=store_present)
    if case_match(home, case, target) == "source":
        return result(True, "managed-write", target, case,
                      "target is inside the Case source authority; write freely, "
                      "then book the settled source with entityctl snapshot-source "
                      "(re-run pgen_preflight.py confirm on the input TOML before "
                      "record run-prepare)",
                      store_present=store_present)
    # "router-required" is a stable contract string shared with the
    # observability evidence validator (validate_pgen_preflight); it
    # intentionally keeps the pre-rename router name.
    return result(False, "router-required", target, case,
                  "target is under a recorded Ledger artifact root (build/run/data "
                  "identity or the active run); recorded evidence is not editable, "
                  "route to entity-ledger",
                  store_present=store_present)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate whether entity-pgen may read or write a Locator"
    )
    # Lazy default: resolving the Ledger home can trigger the one-time
    # ~/.entity-router -> ~/.entity-ledger migration, which must not run as a
    # side effect of merely building the parser.
    parser.add_argument("--ledger-home", "--router-home", dest="ledger_home",
                        default=None)
    parser.add_argument("--operation", choices=["read", "write"], required=True)
    parser.add_argument("--target", required=True,
                        help="SITE_ID:/absolute/path; plain path uses --site-id")
    parser.add_argument("--site-id", default="local")
    return parser


def _safe_target(args):
    """Best-effort target locator for error payloads; never raises.

    Falls back to a placeholder when ``--target`` itself is the cause of
    the failure (for example ``site:relative/path``).
    """
    try:
        return target_locator(args.target, args.site_id)
    except Exception:
        return {"site_id": args.site_id or "unknown", "path": "/invalid-target"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "card":
        return card_main(argv[1:])
    if argv and argv[0] == "confirm":
        return confirm_main(argv[1:])
    args = build_parser().parse_args(argv)
    try:
        payload = evaluate(args)
    except (LedgerError, OSError, ValueError, KeyError,
            sqlite3.DatabaseError) as exc:
        payload = result(False, "router-required", _safe_target(args),
                         reason="%s [target: %s]" % (exc, args.target))
    except Exception as exc:
        # Fail-closed contract: every failure still prints JSON, exit 2.
        payload = result(False, "router-required", _safe_target(args),
                         reason="unexpected %s: %s [target: %s]" % (
                             type(exc).__name__, exc, args.target))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["allowed"] else 2


if __name__ == "__main__":
    sys.exit(main())
