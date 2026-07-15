#!/usr/bin/env python3
"""Fail-closed registry/Locator preflight for Entity PGen work.

Read-only and truly standalone PGen work may run directly.  A write to a
source tree registered by Router v3 requires the controller-owned active PGen
Action request.  No source/control ancestor relationship is assumed.
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
    canonical_locator,
    load_json,
    load_registry,
    locator_within,
    locators_overlap,
    parse_locator,
    router_home,
)


def target_locator(value, default_site, home=None):
    if isinstance(value, dict) or ":" in value:
        item = parse_locator(value)
        return canonical_locator(home, item) if home else item
    path = absolute(value)
    item = {"site_id": default_site, "path": path}
    return canonical_locator(home, item) if home else item


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
    registry = load_registry(home)
    cases = []
    for record in registry.get("cases", {}).values():
        control_root = absolute(record.get("control_root", ""))
        path = os.path.join(control_root, "case.json")
        if not os.path.isfile(path):
            continue
        state = load_json(path, "Case state")
        if state.get("schema_version") != 3:
            continue
        cases.append({
            "case_uid": state.get("case_uid", ""),
            "control_root": control_root,
            "state": state,
        })
    return cases


def case_covers_target(case, target):
    state = case["state"]
    roots = [state.get("source", {}).get("authority")]
    roots.extend(state.get("source", {}).get("replicas", []))
    roots.extend(state.get("artifacts", {}).values())
    return any(root and locator_within(target, root) for root in roots)


def find_cases(home, target):
    return [case for case in registered_cases(home) if case_covers_target(case, target)]


def case_for_request(home, request_path):
    request_path = absolute(request_path)
    matches = []
    for case in registered_cases(home):
        root = os.path.join(case["control_root"], "actions")
        try:
            inside = os.path.commonpath([request_path, root]) == root
        except ValueError:
            inside = False
        if inside:
            matches.append(case)
    return matches[0] if len(matches) == 1 else None


def validate_managed_write(home, target, case, request_path):
    if not request_path:
        return result(False, "router-required", target, case,
                      "registered source write requires --action-request")
    request_path = absolute(request_path)
    try:
        request = load_json(request_path, "Action request")
    except RouterError as exc:
        return result(False, "router-required", target, case, str(exc))
    state = case["state"]
    action_id = request.get("action_id", "")
    expected = absolute(os.path.join(
        case["control_root"], "actions", action_id, "request.json"
    )) if action_id else ""
    checks = [
        (bool(action_id), "Action request has no action_id"),
        (request_path == expected, "request is not the controller-owned Action request"),
        (request.get("schema_version") == 2, "Action request schema is not v2"),
        (request.get("case_uid") == state.get("case_uid"), "Action case_uid does not match"),
        (request.get("workflow_id") == state.get("workflow", {}).get("workflow_id"),
         "Action workflow_id does not match"),
        (action_id == state.get("workflow", {}).get("active_action_id"),
         "Action is not active"),
        (request.get("owner") == "entity-pgen", "Action owner is not entity-pgen"),
        (request.get("execution_domain") == "entity-pgen",
         "Action execution_domain is not entity-pgen"),
        (str(request.get("action_type", "")).startswith("pgen."),
         "Action type is not pgen.*"),
        (request.get("execution_site_id") == target["site_id"],
         "target site differs from execution_site_id"),
        (request.get("execution_site_id") == state["source"]["authority"]["site_id"],
         "PGen Action is not executing on the source authority site"),
        (request.get("case_revision") == state.get("revision", -1) - 1,
         "Action request revision is stale"),
    ]
    for passed, reason in checks:
        if not passed:
            return result(False, "router-required", target, case, reason, action_id)

    control = {"site_id": state["control"]["site_id"], "path": state["control"]["root"]}
    if locators_overlap(target, control):
        return result(False, "router-required", target, case,
                      "entity-pgen may never write Router control state", action_id)
    write_roots = [parse_locator(item) for item in request.get("write_roots", [])]
    if not write_roots or not any(locator_within(target, root) for root in write_roots):
        return result(False, "router-required", target, case,
                      "target is outside Action write_roots", action_id)
    protected = [parse_locator(item) for item in request.get("protected_paths", [])]
    if any(locators_overlap(target, item) for item in protected):
        return result(False, "router-required", target, case,
                      "target overlaps a protected locator", action_id)
    return result(True, "managed-write", target, case,
                  "active PGen Action authorizes this locator", action_id)


def evaluate(args):
    home = router_home(args.router_home)
    target = target_locator(args.target, args.site_id, home)
    matches = find_cases(home, target)
    request_case = case_for_request(home, args.action_request) if args.action_request else None
    if len(matches) > 1:
        return result(False, "ambiguous", target, reason=(
            "locator is registered by multiple Cases; use distinct source authority roots"
        ))
    case = matches[0] if matches else None

    if args.operation == "read":
        return result(True, "managed-readonly" if case else "standalone-readonly",
                      target, case, "read-only operation")
    if args.action_request and not request_case:
        return result(False, "router-required", target,
                      reason="Action request is not owned by a registered v3 Case")
    if request_case and case and request_case["case_uid"] != case["case_uid"]:
        return result(False, "router-required", target, case,
                      reason="target and Action request belong to different Cases")
    if request_case and not case:
        return result(False, "router-required", target, request_case,
                      reason="PGen Action target is outside its registered Case source")
    if not case:
        return result(True, "standalone-write", target,
                      reason="locator is not registered by Router")
    return validate_managed_write(home, target, case, args.action_request)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate whether entity-pgen may read or write a Locator"
    )
    parser.add_argument("--router-home", default=router_home())
    parser.add_argument("--operation", choices=["read", "write"], required=True)
    parser.add_argument("--target", required=True,
                        help="SITE_ID:/absolute/path; plain path uses --site-id")
    parser.add_argument("--site-id", default="local")
    parser.add_argument("--action-request")
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
