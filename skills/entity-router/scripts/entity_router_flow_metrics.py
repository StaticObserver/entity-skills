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
    for path in args.result:
        result = load(path)
        metrics = result.get("metrics", {})
        totals["tool_roundtrips"] += int(metrics.get("tool_calls", 0))
        totals["remote_calls"] += int(metrics.get("remote_calls", 0))
        totals["tool_output_bytes_injected"] += int(metrics.get("output_bytes", 0))
        totals["unchanged_polls_suppressed"] += int(
            metrics.get("unchanged_polls_suppressed", 0)
        )
        reason = wakeup_status.get(result.get("status"))
        if reason:
            totals["model_wakeups"]["total"] += 1
            by_reason = totals["model_wakeups"]["by_reason"]
            by_reason[reason] = by_reason.get(reason, 0) + 1
    assessment = {
        "correctness_gate": "not_assessed",
        "model_wakeups_le_6": totals["model_wakeups"]["total"] <= 6,
        "tool_output_bytes_le_64k": totals["tool_output_bytes_injected"] <= 65536,
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
    print(json.dumps({"schema_version": 1, "metrics": totals,
                      "assessment": assessment}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
