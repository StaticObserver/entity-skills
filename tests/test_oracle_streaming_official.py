#!/usr/bin/env python3

import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "e2e-streaming-official"))

from oracle_streaming import gate_b_official, gate_c_base, gate_c_job_data, gate_d_physics  # noqa: E402
import redact_spec  # noqa: E402

SPEC_PATH = ROOT / "evals" / "e2e-streaming-official" / "physics-spec.json"
SPEC = json.loads(SPEC_PATH.read_text())

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

_GOOD_TOML_TEXT = """
[simulation]
engine = "srpic"
runtime = 50.0

[grid]
resolution = [128]
extent = [[0.0, 16.0]]
[grid.boundaries]
fields = [["PERIODIC"]]
particles = [["PERIODIC"]]

[particles]
ppc0 = 32.0
[[particles.species]]
charge = -1.0
mass = 1.0
[[particles.species]]
charge = 1.0
mass = 1.0
[[particles.species]]
charge = -1.0
mass = 1.0
[[particles.species]]
charge = 1.0
mass = 1.0

[setup]
drifts_in_x = [0.2, 0.0, -0.2, 0.0]
drifts_in_y = [0.0, 0.0, 0.0, 0.0]
drifts_in_z = [0.0, 0.0, 0.0, 0.0]
temperatures = [0.0001, 0.0001, 0.0001, 0.0001]
densities = [0.5, 0.5]

[output]
interval_time = 5.0
[output.particles]
species = [1, 3]
stride = 10
"""

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


class GateBProjectLayoutTest(unittest.TestCase):
    def test_toml_and_design_discovered_under_source(self):
        root = Path(tempfile.mkdtemp(prefix="oracle-gateb-"))
        (root / "source" / "docs").mkdir(parents=True)
        (root / "source" / "input.toml").write_text(_GOOD_TOML_TEXT)
        parsed = tomllib.loads(_GOOD_TOML_TEXT)
        self.assertEqual(
            [c for c in gate_b_official.compare_streaming_toml(parsed, SPEC)
             if c["status"] != "pass"],
            [])
        (root / "source" / "docs" / "design.md").write_text("# rationale\n")
        result = statuses(gate_b_official.run(root, SPEC, GOOD_SUBMISSION)["checks"])
        self.assertEqual(result.get("design_md"), "pass")
        self.assertEqual(result.get("resolution"), "pass")

    def test_missing_toml_fails_cleanly(self):
        # regression: no TOML anywhere must produce a fail check, not an
        # IndexError from indexing an empty candidate list
        root = Path(tempfile.mkdtemp(prefix="oracle-gateb-"))
        result = gate_b_official.run(root, SPEC, GOOD_SUBMISSION)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(statuses(result["checks"])["input_toml"], "fail")


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


SLURM_SUBMISSION = {
    "experiment_id": "e2e-streaming-official-v1",
    "physics_spec": SPEC,
    "run": {
        "scheduler": {"kind": "slurm", "job_id": "12345"},
        "partition": "fat",
        "resources": {"tasks": 1, "nodes": 1, "gpus": 1},
        "data_root": "/remote/run",
    },
}


def _sacct_record(**overrides):
    record = {
        "job_id": "12345", "name": "entity-streaming", "partition": "fat",
        "state": "COMPLETED", "exit_code": "0:0", "nodes": "1", "tasks": "1",
        "elapsed": "00:05:00",
        "tres": "billing=32,cpu=32,gres/gpu=1,mem=64G",
        "records": 1,
    }
    record.update(overrides)
    return record


class SlurmGateCTest(unittest.TestCase):
    def _run(self, record, submission=None):
        with mock.patch.object(gate_c_job_data, "sacct_job",
                               return_value=record) as mocked:
            result = gate_c_job_data.run(
                "astro", submission or SLURM_SUBMISSION, {}, None)
        mocked.assert_called_once_with("astro", "12345")
        return statuses(result["checks"])

    def test_happy_path_all_job_checks_pass(self):
        result = self._run(_sacct_record())
        for name in ("job_terminal_state", "job_partition", "job_tasks",
                     "job_nodes", "job_walltime", "single_job", "job_gres"):
            self.assertEqual(result[name], "pass", f"{name}: {result[name]}")

    def test_failed_job_fails(self):
        result = self._run(_sacct_record(state="FAILED", exit_code="1:0"))
        self.assertEqual(result["job_terminal_state"], "fail")

    def test_partition_mismatch_fails(self):
        result = self._run(_sacct_record(partition="intelhigh"))
        self.assertEqual(result["job_partition"], "fail")

    def test_elapsed_above_ceiling_fails(self):
        result = self._run(_sacct_record(elapsed="00:11:00"))
        self.assertEqual(result["job_walltime"], "fail")

    def test_multiple_records_fail(self):
        result = self._run(_sacct_record(records=2))
        self.assertEqual(result["single_job"], "fail")

    def test_gres_above_ceiling_fails(self):
        result = self._run(_sacct_record(
            tres="billing=64,cpu=64,gres/gpu=2,mem=128G"))
        self.assertEqual(result["job_gres"], "fail")

    def test_typed_gres_token_parsed(self):
        result = self._run(_sacct_record(
            tres="billing=32,cpu=32,gres/gpu:V100=1,mem=64G"))
        self.assertEqual(result["job_gres"], "pass")

    def test_no_sacct_record_is_unknown(self):
        result = self._run(None)
        self.assertEqual(result["job_facts"], "unknown")
        self.assertNotIn("single_job", result)

    def test_missing_job_id_is_unknown(self):
        submission = json.loads(json.dumps(SLURM_SUBMISSION))
        submission["run"]["scheduler"] = {"kind": "slurm"}
        with mock.patch.object(gate_c_job_data, "sacct_job") as mocked:
            result = gate_c_job_data.run("astro", submission, {}, None)
        mocked.assert_not_called()
        self.assertEqual(statuses(result["checks"])["job_facts"], "unknown")

    def test_direct_branch_still_dispatched(self):
        root = Path(tempfile.mkdtemp(prefix="oracle-direct-"))
        (root / ".entity-exit-code").write_text("0\n")
        # evaluate_data is the nt2py probe (heavy local import); the dispatch
        # semantics under test live in the scheduler branch, so stub it out.
        with mock.patch.object(gate_c_job_data, "evaluate_data", return_value=[]):
            result = gate_c_job_data.run("m87", GOOD_SUBMISSION, {}, root)
        self.assertEqual(statuses(result["checks"])["exit_evidence"], "pass")

    TEARDOWN_LOG = (
        "Step: 799.......................[of 800]\n"
        "malloc_consolidate(): unaligned fastbin chunk detected\n"
        "srun: error: gpu1: task 0: Aborted\n")

    def test_teardown_abort_overrides_terminal_fail(self):
        submission = json.loads(json.dumps(SLURM_SUBMISSION))
        submission["run"]["run_root"] = "/remote/run"
        record = _sacct_record(state="FAILED", exit_code="6:0")
        with mock.patch.object(gate_c_job_data, "sacct_job", return_value=record), \
                mock.patch.object(gate_c_job_data, "_slurm_log_tail",
                                  return_value=self.TEARDOWN_LOG):
            result = gate_c_job_data.run("astro", submission, {}, None)
        result = statuses(result["checks"])
        self.assertEqual(result["job_terminal_state"], "pass")
        self.assertEqual(result["teardown_anomaly"], "pass")

    def test_real_failure_keeps_terminal_fail(self):
        submission = json.loads(json.dumps(SLURM_SUBMISSION))
        submission["run"]["run_root"] = "/remote/run"
        record = _sacct_record(state="FAILED", exit_code="1:0")
        with mock.patch.object(gate_c_job_data, "sacct_job", return_value=record), \
                mock.patch.object(gate_c_job_data, "_slurm_log_tail",
                                  return_value="Step: 12 [of 800]\nsegfault\n"):
            result = gate_c_job_data.run("astro", submission, {}, None)
        result = statuses(result["checks"])
        self.assertEqual(result["job_terminal_state"], "fail")
        self.assertEqual(result["teardown_anomaly"], "unknown")

    def test_teardown_anomaly_pure(self):
        anomaly = gate_c_job_data.teardown_anomaly(self.TEARDOWN_LOG)
        self.assertEqual(anomaly, {"last_step": 799, "total_steps": 800})
        self.assertIsNone(gate_c_job_data.teardown_anomaly(
            "Step: 10 [of 800]\nmalloc_consolidate(): invalid chunk size\nAborted\n"))
        self.assertIsNone(gate_c_job_data.teardown_anomaly(
            "Step: 799 [of 800]\nsome other crash\nAborted\n"))
        self.assertIsNone(gate_c_job_data.teardown_anomaly(""))



class RedactSpecTest(unittest.TestCase):
    """The agent-facing spec must not leak the Slurm self-discovery answers."""

    def setUp(self):
        self.redacted = redact_spec.redact(SPEC)

    def test_slurm_details_removed(self):
        run_job = self.redacted["resources"]["run_job"]
        for key in ("partition", "gres", "qos", "time_limit"):
            self.assertNotIn(key, run_job)
        self.assertNotIn("partition", self.redacted["resources"]["build_job"])
        self.assertNotIn("partitions", self.redacted["resources"]["analysis_job"])

    def test_no_site_answers_anywhere(self):
        text = json.dumps(self.redacted)
        for leaked in ("fat", "V100", "qos512", "intelhigh", "amdlow",
                       "entity-compute", "site_root"):
            self.assertNotIn(leaked, text)

    def test_physics_and_budget_kept(self):
        self.assertEqual(len(self.redacted["species"]), 4)
        self.assertEqual(self.redacted["runtime"]["final_time"], 50.0)
        run_job = self.redacted["resources"]["run_job"]
        self.assertEqual(run_job["gpus"], 1)
        self.assertEqual(run_job["walltime_ceiling"], "00:10:00")
        self.assertEqual(self.redacted["resources"]["scheduler"], "slurm")
        self.assertEqual(self.redacted["compile"]["arch"], "VOLTA70")

    def test_cli_roundtrip(self):
        out = Path(tempfile.mkdtemp(prefix="redact-")) / "spec.json"
        rc = redact_spec.main_with((str(SPEC_PATH), str(out)))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.read_text()), self.redacted)


class FixturesTest(unittest.TestCase):
    def test_spec_slurm_layout(self):
        self.assertEqual(SPEC["site"]["name"], "astro-streaming")
        self.assertEqual(SPEC["site"]["scheduler"], "slurm")
        self.assertEqual(SPEC["compile"]["arch"], "VOLTA70")
        run_job = SPEC["resources"]["run_job"]
        self.assertEqual(run_job["partition"], "fat")
        self.assertEqual(run_job["gres"], "gpu:V100:1")
        self.assertEqual(run_job["qos"], "qos512")
        self.assertIsNone(run_job["time_limit"])
        self.assertEqual(SPEC["resources"]["analysis_job"]["partitions"],
                         ["intelhigh", "amdlow"])
        self.assertEqual(SPEC["runtime"]["status"],
                         "calibrated-gold-run-2026-08-09")

    def test_fixtures_are_valid_json(self):
        for name in ("physics-spec.json", "oracle_streaming/thresholds.json",
                     "fixtures/submission.schema.json"):
            path = ROOT / "evals" / "e2e-streaming-official" / name
            json.loads(path.read_text(encoding="utf-8"))

    def test_thresholds_keep_gate_d_metric_keys(self):
        thresholds = json.loads(
            (ROOT / "evals" / "e2e-streaming-official" / "oracle_streaming"
             / "thresholds.json").read_text())
        for key in ("particle_count_conservation", "min_particles_per_species",
                    "stats_time_monotonic", "energy_relative_drift",
                    "e1_growth_rate", "e1_squared_growth_factor",
                    "saturation_before_final"):
            self.assertIn(key, thresholds["metrics"])
        self.assertEqual(thresholds["calibration"], "gold-run-2026-08-09")


THRESHOLDS = json.loads(
    (ROOT / "evals" / "e2e-streaming-official" / "oracle_streaming"
     / "thresholds.json").read_text())

GOLD_METRICS = {
    "particle_counts": {"1": (102, 102), "3": (102, 102)},
    "min_particles_per_species": 102,
    "stats_time_monotonic": True,
    "energy_relative_drift_max": 0.002000950315674284,
    "e1_growth_rate": 0.13656367393336358,
    "e1_growth_window": [0.6875, 13.8125],
    "e1_growth_window_points": 22,
    "e1_squared_growth_factor": 7079.335872129105,
    "saturation_time": 13.8125,
    "saturated_before_final": True,
}


class SacctParseTest(unittest.TestCase):
    def _fake_proc(self, stdout, rc=0):
        import subprocess
        return subprocess.CompletedProcess(args=[], returncode=rc,
                                           stdout=stdout, stderr="")

    def test_batch_step_fills_blank_ntasks(self):
        stdout = (
            "357003|entity-op|fat|FAILED|6:0|1||00:00:02|billing=32,gres/gpu=1\n"
            "357003.batch|batch||FAILED|6:0|1|1|00:00:02|\n"
            "357003.0|entity.xc||CANCELLED|0:6|1|1|00:00:01|\n")
        with mock.patch("oracle_streaming.gate_c_base.subprocess.run",
                        return_value=self._fake_proc(stdout)):
            job = gate_c_base.sacct_job("astro", "357003")
        self.assertEqual(job["tasks"], "1")
        self.assertEqual(job["records"], 1)

    def test_step_rows_do_not_count_as_jobs(self):
        stdout = (
            "100|a|fat|FAILED|1:0|1|1|00:00:01|\n"
            "100.batch|batch||FAILED|1:0|1|1|00:00:01|\n"
            "100|a|fat|COMPLETED|0:0|1|1|00:00:02|\n"
            "100.batch|batch||COMPLETED|0:0|1|1|00:00:02|\n")
        with mock.patch("oracle_streaming.gate_c_base.subprocess.run",
                        return_value=self._fake_proc(stdout)):
            job = gate_c_base.sacct_job("astro", "100")
        self.assertEqual(job["records"], 2)


class GateDFrozenTest(unittest.TestCase):
    def test_gold_metrics_pass_every_check(self):
        checks = gate_d_physics.evaluate(GOLD_METRICS, THRESHOLDS)
        failed = [c for c in checks if c["status"] != "pass"]
        self.assertEqual(failed, [],
                         json.dumps(checks, indent=2, ensure_ascii=False))

    def test_growth_rate_outside_band_fails(self):
        metrics = dict(GOLD_METRICS, e1_growth_rate=0.5)
        result = statuses(gate_d_physics.evaluate(metrics, THRESHOLDS))
        self.assertEqual(result["e1_growth_rate"], "fail")

    def test_no_growth_fails_factor_and_growth(self):
        metrics = dict(GOLD_METRICS, e1_squared_growth_factor=3.0,
                       e1_growth_rate=None, saturation_time=None,
                       saturated_before_final=None)
        result = statuses(gate_d_physics.evaluate(metrics, THRESHOLDS))
        self.assertEqual(result["e1_squared_growth_factor"], "fail")
        self.assertEqual(result["e1_growth_rate"], "unknown")

    def test_late_saturation_fails(self):
        metrics = dict(GOLD_METRICS, saturated_before_final=False,
                       saturation_time=49.4375)
        result = statuses(gate_d_physics.evaluate(metrics, THRESHOLDS))
        self.assertEqual(result["saturation_before_final"], "fail")

    def test_energy_drift_above_tolerance_fails(self):
        metrics = dict(GOLD_METRICS, energy_relative_drift_max=0.05)
        result = statuses(gate_d_physics.evaluate(metrics, THRESHOLDS))
        self.assertEqual(result["energy_relative_drift"], "fail")

    def test_fit_growth_recovers_synthetic_rate(self):
        import math
        time = [0.0625 * i for i in range(1, 801)]
        # gamma_field = 0.15 -> E^2 slope 0.3, saturating at t=20
        e1sq = [1e-7 * math.exp(0.3 * t) if t <= 20 else 1e-7 * math.exp(6.0)
                for t in time]
        growth = gate_d_physics.fit_growth(time, e1sq)
        self.assertIsNotNone(growth)
        self.assertAlmostEqual(growth["gamma_field"], 0.15, places=2)
        self.assertLess(growth["peak_time"], time[-1])
        self.assertGreater(growth["growth_factor"], 300.0)

    def test_fit_growth_returns_none_without_growth(self):
        time = [0.0625 * i for i in range(1, 101)]
        self.assertIsNone(gate_d_physics.fit_growth(time, [1e-7] * 100))


if __name__ == "__main__":
    unittest.main()
