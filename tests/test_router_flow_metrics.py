from __future__ import print_function

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METRICS = os.path.join(ROOT, "skills", "entity-router", "scripts", "entity_router_flow_metrics.py")


class RouterFlowMetricsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-flow-metrics-")

    def tearDown(self):
        shutil.rmtree(self.temp)

    def write(self, name, value):
        path = os.path.join(self.temp, name)
        with open(path, "w") as handle:
            json.dump(value, handle)
        return path

    def test_collector_uses_observed_counts_and_keeps_tokens_unassessed(self):
        result = self.write("result.json", {
            "status": "needs_decision",
            "metrics": {"tool_calls": 4, "remote_calls": 1, "output_bytes": 1024,
                        "unchanged_polls_suppressed": 7},
        })
        baseline = self.write("baseline.json", {
            "metrics": {"tool_roundtrips": 20, "tool_output_bytes_injected": 4096},
        })
        process = subprocess.run(
            [sys.executable, METRICS, "--result", result, "--baseline", baseline],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertEqual(payload["metrics"]["tool_roundtrips"], 4)
        self.assertEqual(payload["metrics"]["unchanged_polls_suppressed"], 7)
        self.assertEqual(payload["metrics"]["usage"]["input_tokens"], None)
        self.assertTrue(payload["assessment"]["tool_roundtrip_reduction"]["pass"])
        self.assertEqual(payload["assessment"]["token_reduction"], "not_assessed")


if __name__ == "__main__":
    unittest.main()
