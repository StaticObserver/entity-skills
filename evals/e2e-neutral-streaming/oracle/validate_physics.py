#!/usr/bin/env python3
"""Validate oracle-computed metrics against thresholds frozen before A/B runs."""

from __future__ import print_function

import argparse
import json
import math
import sys


def load(path, label):
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("%s must be an object" % label)
    return value


def validate(report_path, thresholds_path):
    report = load(report_path, "physics report")
    thresholds = load(thresholds_path, "thresholds")
    if thresholds.get("status") != "frozen" or not thresholds.get("formal_execution_allowed"):
        return {
            "schema_version": 1,
            "validator": "neutral-streaming-physics-v1",
            "status": "blocked",
            "reason": "physics thresholds are not frozen by a maintainer gold run",
            "checks": [],
        }
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    contracts = thresholds.get("metrics") if isinstance(thresholds.get("metrics"), dict) else {}
    checks = []
    for name in sorted(contracts):
        contract = contracts[name]
        value = metrics.get(name)
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        passed = numeric
        if passed and contract.get("min") is not None:
            passed = value >= contract["min"]
        if passed and contract.get("max") is not None:
            passed = value <= contract["max"]
        checks.append({
            "name": name,
            "passed": bool(passed),
            "value": value,
            "min": contract.get("min"),
            "max": contract.get("max"),
            "definition": contract.get("definition", ""),
        })
    if not contracts:
        return {"schema_version": 1, "validator": "neutral-streaming-physics-v1",
                "status": "blocked", "reason": "frozen thresholds contain no metrics",
                "checks": []}
    return {
        "schema_version": 1,
        "validator": "neutral-streaming-physics-v1",
        "status": "pass" if all(item["passed"] for item in checks) else "fail",
        "checks": checks,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--thresholds", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        result = validate(args.report, args.thresholds)
    except (OSError, ValueError) as exc:
        result = {"schema_version": 1, "validator": "neutral-streaming-physics-v1",
                  "status": "error", "error": str(exc), "checks": []}
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    print(text, end="")
    return {"pass": 0, "fail": 1, "blocked": 2}.get(result.get("status"), 1)


if __name__ == "__main__":
    sys.exit(main())
