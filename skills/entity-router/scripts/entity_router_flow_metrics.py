#!/usr/bin/env python3
"""Aggregate read-only Entity Router flow result metrics and assess efficiency gates."""

from __future__ import print_function

import argparse
import json
import os
import sys


def load(path):
    with open(os.path.realpath(os.path.abspath(os.path.expanduser(path))), "r") as handle:
        return json.load(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", action="append", default=[])
    parser.add_argument("--baseline")
    parser.add_argument("--correctness")
    parser.add_argument("--expected-invariants")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    totals = {
        "model_wakeups": {"total": 0, "by_reason": {}},
        "tool_roundtrips": 0, "remote_calls": 0, "approval_reviews": 0,
        "tool_output_bytes_injected": 0, "unchanged_polls_suppressed": 0,
        "retries": {"total": 0, "without_changed_evidence": 0},
        "usage": {"input_tokens": None, "cached_input_tokens": None,
                  "output_tokens": None, "wall_time_ms": None},
    }
    wakeup_status = {
        "needs_decision": "needs_decision", "anomaly": "anomaly",
        "blocked": "workflow_terminal",
    }
    usage_seen = {"input_tokens": False, "cached_input_tokens": False,
                  "output_tokens": False, "wall_time_ms": False}
    for path in args.result:
        result = load(path)
        metrics = result.get("metrics", {})
        totals["tool_roundtrips"] += int(
            metrics.get("tool_calls", metrics.get("tool_roundtrips", 0))
        )
        totals["remote_calls"] += int(metrics.get("remote_calls", 0))
        totals["tool_output_bytes_injected"] += int(
            metrics.get("output_bytes", metrics.get("tool_output_bytes_injected", 0))
        )
        totals["unchanged_polls_suppressed"] += int(
            metrics.get("unchanged_polls_suppressed", 0)
        )
        totals["approval_reviews"] += int(metrics.get("approval_reviews", 0))
        retries = metrics.get("retries", {})
        totals["retries"]["total"] += int(retries.get("total", 0))
        totals["retries"]["without_changed_evidence"] += int(
            retries.get("without_changed_evidence", 0)
        )
        observed_wakeups = metrics.get("model_wakeups")
        if isinstance(observed_wakeups, dict):
            totals["model_wakeups"]["total"] += int(observed_wakeups.get("total", 0))
            for key, value in observed_wakeups.get("by_reason", {}).items():
                by_reason = totals["model_wakeups"]["by_reason"]
                by_reason[key] = by_reason.get(key, 0) + int(value)
        result_usage = metrics.get("usage", result.get("usage", {}))
        if isinstance(result_usage, dict):
            for key in usage_seen:
                value = result_usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    if not usage_seen[key]:
                        totals["usage"][key] = 0
                    totals["usage"][key] += value
                    usage_seen[key] = True
        reason = wakeup_status.get(result.get("status"))
        if reason and not isinstance(observed_wakeups, dict):
            totals["model_wakeups"]["total"] += 1
            by_reason = totals["model_wakeups"]["by_reason"]
            by_reason[reason] = by_reason.get(reason, 0) + 1
    assessment = {
        "correctness_gate": "not_assessed",
        "model_wakeups_le_6": totals["model_wakeups"]["total"] <= 6,
        "tool_roundtrips_le_30": totals["tool_roundtrips"] <= 30,
        "approval_reviews_le_10": totals["approval_reviews"] <= 10,
        "tool_output_bytes_le_64k": totals["tool_output_bytes_injected"] <= 65536,
        "retries_without_changed_evidence_zero": (
            totals["retries"]["without_changed_evidence"] == 0
        ),
        "tool_roundtrip_reduction": "not_assessed",
        "output_byte_reduction": "not_assessed",
        "token_reduction": "not_assessed",
    }
    if args.baseline:
        baseline = load(args.baseline)
        for source, target in [
                ("tool_roundtrips", "tool_roundtrip_reduction"),
                ("tool_output_bytes_injected", "output_byte_reduction")]:
            before = baseline.get("metrics", {}).get(source)
            if isinstance(before, (int, float)) and before > 0:
                reduction = 1.0 - float(totals[source]) / float(before)
                assessment[target] = {"fraction": reduction, "pass": reduction >= 0.60}
        baseline_usage = baseline.get("metrics", {}).get("usage", {})
        before_tokens = None
        after_tokens = None
        if isinstance(baseline_usage, dict):
            before_values = [baseline_usage.get("input_tokens"),
                             baseline_usage.get("output_tokens")]
            after_values = [totals["usage"].get("input_tokens"),
                            totals["usage"].get("output_tokens")]
            if all(isinstance(item, (int, float)) for item in before_values + after_values):
                before_tokens = sum(before_values)
                after_tokens = sum(after_values)
        if before_tokens and before_tokens > 0:
            reduction = 1.0 - float(after_tokens) / float(before_tokens)
            assessment["token_reduction"] = {
                "fraction": reduction, "pass": reduction >= 0.60,
            }
    if args.correctness or args.expected_invariants:
        if not args.correctness or not args.expected_invariants:
            raise ValueError("--correctness and --expected-invariants must be used together")
        report = load(args.correctness)
        expected = load(args.expected_invariants).get("required", [])
        actual = report.get("invariants", {})
        missing = [name for name in expected if actual.get(name) is not True]
        assessment["correctness_gate"] = {
            "pass": not missing,
            "required": expected,
            "missing_or_failed": missing,
        }
    mandatory = [
        assessment["model_wakeups_le_6"],
        assessment["tool_roundtrips_le_30"],
        assessment["tool_output_bytes_le_64k"],
        assessment["retries_without_changed_evidence_zero"],
    ]
    if isinstance(assessment["correctness_gate"], dict):
        mandatory.append(assessment["correctness_gate"]["pass"])
    for key in ["tool_roundtrip_reduction", "output_byte_reduction", "token_reduction"]:
        if isinstance(assessment[key], dict):
            mandatory.append(assessment[key]["pass"])
    assessment["overall"] = "pass" if all(mandatory) else "fail"
    print(json.dumps({"schema_version": 1, "metrics": totals,
                      "assessment": assessment}, indent=2, sort_keys=True))
    return 1 if args.require_pass and assessment["overall"] != "pass" else 0


if __name__ == "__main__":
    sys.exit(main())
