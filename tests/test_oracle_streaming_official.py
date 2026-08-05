#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "e2e-streaming-official"))

from oracle_streaming import gate_b_official, gate_c_job_data  # noqa: E402

SPEC = json.loads(
    (ROOT / "evals" / "e2e-streaming-official" / "physics-spec.json").read_text())

GOOD_TOML = {
    "simulation": {"engine": "srpic", "runtime": 50.0},
    "grid": {
        "resolution": [128],
        "extent": [[0.0, 16.0]],
        "boundaries": {"fields": [["PERIODIC"]], "particles": [["PERIODIC"]]},
    },
    "particles": {
        "ppc0": 32.0,
        "species": [
            {"charge": -1.0, "mass": 1.0},
            {"charge": 1.0, "mass": 1.0},
            {"charge": -1.0, "mass": 1.0},
            {"charge": 1.0, "mass": 1.0},
        ],
    },
    "setup": {
        "drifts_in_x": [0.2, 0.0, -0.2, 0.0],
        "drifts_in_y": [0.0, 0.0, 0.0, 0.0],
        "drifts_in_z": [0.0, 0.0, 0.0, 0.0],
        "temperatures": [0.0001, 0.0001, 0.0001, 0.0001],
        "densities": [0.5, 0.5],
    },
    "output": {"interval_time": 5.0, "particles": {"species": [1, 3], "stride": 10}},
}

GOOD_SUBMISSION = {
    "experiment_id": "e2e-streaming-official-v1",
    "official_pgen": {
        "name": "streaming",
        "sha256": SPEC["official_pgen"]["sha256"],
    },
    "run": {"scheduler": {"kind": "direct", "pid": 1234}, "exit_code": 0,
            "data_root": "/remote/run"},
    "analysis": {"report": "analysis/report.md",
                 "script": "analysis/scripts/analyze.py"},
}


def statuses(checks):
    return {c["name"]: c["status"] for c in checks}


class OfficialPgenFingerprintTest(unittest.TestCase):
    def test_pinned_hash_passes(self):
        check = gate_b_official.check_official_pgen(SPEC, GOOD_SUBMISSION)
        self.assertEqual(check["status"], "pass")

    def test_wrong_hash_fails(self):
        submission = dict(GOOD_SUBMISSION,
                          official_pgen={"name": "streaming",
                                         "sha256": "0" * 64})
        check = gate_b_official.check_official_pgen(SPEC, submission)
        self.assertEqual(check["status"], "fail")
        self.assertIn("unmodified", check["detail"])

    def test_wrong_pgen_name_fails(self):
        submission = dict(GOOD_SUBMISSION,
                          official_pgen={"name": "shock",
                                         "sha256": SPEC["official_pgen"]["sha256"]})
        check = gate_b_official.check_official_pgen(SPEC, submission)
        self.assertEqual(check["status"], "fail")

    def test_missing_pin_is_unknown(self):
        spec = dict(SPEC, official_pgen={})
        check = gate_b_official.check_official_pgen(spec, GOOD_SUBMISSION)
        self.assertEqual(check["status"], "unknown")


class StreamingTomlCompareTest(unittest.TestCase):
    def test_good_toml_passes_every_check(self):
        checks = gate_b_official.compare_streaming_toml(GOOD_TOML, SPEC)
        failed = [c for c in checks if c["status"] != "pass"]
        self.assertEqual(failed, [],
                         json.dumps(checks, indent=2, ensure_ascii=False))

    def test_drift_mismatch_fails(self):
        toml = json.loads(json.dumps(GOOD_TOML))
        toml["setup"]["drifts_in_x"] = [0.2, 0.0, -0.1, 0.0]
        result = statuses(gate_b_official.compare_streaming_toml(toml, SPEC))
        self.assertEqual(result["drifts_in_x"], "fail")

    def test_stride_above_max_fails(self):
        toml = json.loads(json.dumps(GOOD_TOML))
        toml["output"]["particles"]["stride"] = 50
        result = statuses(gate_b_official.compare_streaming_toml(toml, SPEC))
        self.assertEqual(result["particle_stride"], "fail")

    def test_nonzero_background_field_fails(self):
        toml = json.loads(json.dumps(GOOD_TOML))
        toml["setup"]["Bmag"] = 1.0
        result = statuses(gate_b_official.compare_streaming_toml(toml, SPEC))
        self.assertEqual(result["background_B"], "fail")

    def test_wrong_pairwise_density_fails(self):
        toml = json.loads(json.dumps(GOOD_TOML))
        toml["setup"]["densities"] = [1.0, 1.0]
        result = statuses(gate_b_official.compare_streaming_toml(toml, SPEC))
        self.assertEqual(result["densities"], "fail")

    def test_nspec_derived_from_species_array(self):
        result = statuses(gate_b_official.compare_streaming_toml(GOOD_TOML, SPEC))
        self.assertEqual(result["nspec"], "pass")


class DirectBackendGateCTest(unittest.TestCase):
    def _run_root(self, exit_text=None):
        root = Path(tempfile.mkdtemp(prefix="oracle-direct-"))
        if exit_text is not None:
            (root / ".entity-exit-code").write_text(exit_text)
        return root

    def test_zero_exit_passes(self):
        checks = gate_c_job_data.evaluate_exit_evidence(self._run_root("0\n"), 0)
        self.assertEqual([c["status"] for c in checks], ["pass"])

    def test_nonzero_exit_fails(self):
        checks = gate_c_job_data.evaluate_exit_evidence(self._run_root("1\n"), 1)
        self.assertEqual(checks[0]["status"], "fail")

    def test_declared_exit_mismatch_fails(self):
        checks = gate_c_job_data.evaluate_exit_evidence(self._run_root("1\n"), 0)
        self.assertEqual([c["status"] for c in checks], ["fail", "fail"])

    def test_missing_exit_file_is_unknown(self):
        checks = gate_c_job_data.evaluate_exit_evidence(self._run_root(), None)
        self.assertEqual(checks[0]["status"], "unknown")


class FixturesTest(unittest.TestCase):
    def test_fixtures_are_valid_json(self):
        for name in ("physics-spec.json", "oracle_streaming/thresholds.json",
                     "fixtures/submission.schema.json"):
            path = ROOT / "evals" / "e2e-streaming-official" / name
            json.loads(path.read_text(encoding="utf-8"))

    def test_thresholds_keep_gate_d_metric_keys(self):
        thresholds = json.loads(
            (ROOT / "evals" / "e2e-streaming-official" / "oracle_streaming"
             / "thresholds.json").read_text())
        for key in ("particle_count_conservation", "ux_drift_relative_max",
                    "min_particles_per_species", "b1_mean_absolute_deviation",
                    "b1_squared_relative_drift", "e_squared_noise_ceiling",
                    "energy_relative_drift", "stats_time_monotonic"):
            self.assertIn(key, thresholds["metrics"])
        self.assertEqual(thresholds["calibration"], "pending-gold-run")


if __name__ == "__main__":
    unittest.main()
