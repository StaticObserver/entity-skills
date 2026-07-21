#!/usr/bin/env python3
"""Fail-closed registry/Locator preflight for Entity PGen work.

Read-only and truly standalone PGen work may run directly.  A write to a
source tree registered by the Router v5 store is currently refused: managed
writes require a v5 pgen Goal, which is not yet implemented.  No
source/control ancestor relationship is assumed.
"""

from __future__ import print_function

import argparse
import json
import os
import sys


ROUTER_SCRIPTS = os.path.realpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "entity-router", "scripts"
))
if ROUTER_SCRIPTS not in sys.path:
    sys.path.insert(0, ROUTER_SCRIPTS)

from entity_router_common import (  # noqa: E402
    RouterError,
    absolute,
    locator_within,
    parse_locator,
    router_home,
)
from entity_router_store import OperationStore, StoreError  # noqa: E402


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


def result(allowed, mode, target, case=None, reason="", action_id=""):
    return {
        "allowed": allowed,
        "mode": mode,
        "target": parse_locator(target),
        "case_uid": case.get("case_uid", "") if case else "",
        "control_root": case.get("control_root", "") if case else "",
        "action_id": action_id,
        "reason": reason,
    }


def registered_cases(home):
    try:
        store = OperationStore(home, create=False)
    except StoreError:
        return []
    return store.export()["cases"]


def case_roots(home, case):
    roots = []
    authority = (case.get("source") or {}).get("authority")
    if authority:
        roots.append(authority)
    for dimension in (case.get("identities") or {}).values():
        for item in dimension.get("items", []):
            if item.get("root"):
                roots.append(item["root"])
    current = case.get("current") or {}
    if current.get("active_run"):
        roots.append(current["active_run"])
    return [canonical_locator(home, root) for root in roots]


def case_covers_target(home, case, target):
    return any(locator_within(target, root) for root in case_roots(home, case))


def find_cases(home, target):
    return [case for case in registered_cases(home)
            if case_covers_target(home, case, target)]


def evaluate(args):
    home = router_home(args.router_home)
    target = target_locator(args.target, args.site_id, home)
    matches = find_cases(home, target)
    if len(matches) > 1:
        return result(False, "ambiguous", target, reason=(
            "locator is registered by multiple Cases; use distinct source authority roots"
        ))
    case = matches[0] if matches else None

    if args.operation == "read":
        return result(True, "managed-readonly" if case else "standalone-readonly",
                      target, case, "read-only operation")
    if not case:
        return result(True, "standalone-write", target,
                      reason="locator is not registered by Router")
    return result(False, "router-required", target, case,
                  "managed source writes require a v5 pgen Goal, which is not yet implemented")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate whether entity-pgen may read or write a Locator"
    )
    parser.add_argument("--router-home", default=router_home())
    parser.add_argument("--operation", choices=["read", "write"], required=True)
    parser.add_argument("--target", required=True,
                        help="SITE_ID:/absolute/path; plain path uses --site-id")
    parser.add_argument("--site-id", default="local")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        payload = evaluate(args)
    except (RouterError, OSError, ValueError, KeyError) as exc:
        payload = result(False, "router-required",
                         target_locator(args.target, args.site_id), reason=str(exc))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["allowed"] else 2


if __name__ == "__main__":
    sys.exit(main())
