import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "evals" / "e2e-neutral-streaming"
ORACLE = EVAL_ROOT / "oracle" / "validate_submission.py"
PHYSICS_ORACLE = EVAL_ROOT / "oracle" / "validate_physics.py"
FAKE_SLURM = EVAL_ROOT / "fixtures" / "fake_slurm.py"
OBSERVER_CLI = ROOT / "tools" / "skill_observability" / "skill_observer.py"
ROUTER_SCRIPTS = ROOT / "skills" / "entity-router" / "scripts"
if str(ROUTER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ROUTER_SCRIPTS))

from entity_router_operation import apply_plan, status_for_project  # noqa: E402
from entity_router_planner import plan_goal  # noqa: E402
from entity_router_store import OperationStore  # noqa: E402
from tools.skill_observability.core import sha256_text, start_run  # noqa: E402
from tools.skill_observability.evidence import validate_router_operation  # noqa: E402


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUBMISSION_ORACLE = load_module(ORACLE, "e2e_submission_oracle")


class E2EEvaluationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="entity-e2e-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_checked_in_protocol_is_pre_gold_and_json_is_well_formed(self):
        experiment = json.loads((EVAL_ROOT / "experiment.json").read_text(encoding="utf-8"))
        physics = json.loads((EVAL_ROOT / "fixtures" / "physics-spec.json").read_text(encoding="utf-8"))
        thresholds = json.loads((EVAL_ROOT / "oracle" / "thresholds.json").read_text(encoding="utf-8"))
        for path in (EVAL_ROOT / "schemas").glob("*.json"):
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)
        self.assertEqual(experiment["freeze"]["status"], "pre_gold")
        self.assertFalse(experiment["freeze"]["formal_execution_allowed"])
        self.assertEqual(physics["pgen"], "neutral_streaming")
        self.assertEqual(len(physics["species"]), 2)
        self.assertEqual(thresholds["status"], "unfrozen")
        self.assertFalse(thresholds["formal_execution_allowed"])

    def _artifact(self, role, content):
        path = self.root / "evidence" / (role + ".txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        digest, size = SUBMISSION_ORACLE.sha256_file(str(path))
        return {
            "role": role,
            "locator": {"site_id": "eval-site", "path": str(path)},
            "fingerprint": {"sha256": digest, "size": size},
            "evidence_path": str(path),
        }

    def make_submission(self):
        artifacts = [self._artifact(role, role + "\n")
                     for role in sorted(SUBMISSION_ORACLE.REQUIRED_ROLES)]
        by_role = {item["role"]: item for item in artifacts}
        source_sha = hashlib.sha256(b"source-tree").hexdigest()
        source_id = "source-1"
        build_id = "build-1"
        run_id = "run-1"
        data_id = "data-1"
        analysis_id = "analysis-1"
        allowed = self.root / "allowed"
        protected = self.root / "protected"
        observed = allowed / "project" / "pgen.hpp"
        observed.parent.mkdir(parents=True)
        observed.write_text("write\n", encoding="utf-8")
        submission = {
            "schema_version": 1,
            "experiment_id": "e2e-neutral-streaming-v1",
            "run_id": "eval-run-1",
            "variant": "skills-v5",
            "status": "completed",
            "identities": {
                "source": {"id": source_id,
                           "locator": {"site_id": "eval-site", "path": str(self.root / "source")},
                           "fingerprint": {"sha256": source_sha}},
                "build": {"id": build_id, "source_id": source_id,
                           "locator": {"site_id": "eval-site", "path": str(self.root / "build")},
                           "executable_sha256": by_role["executable"]["fingerprint"]["sha256"]},
                "run": {"id": run_id, "source_id": source_id, "build_id": build_id,
                         "locator": {"site_id": "eval-site", "path": str(self.root / "run")},
                         "input_sha256": by_role["input_toml"]["fingerprint"]["sha256"],
                         "executable_sha256": by_role["executable"]["fingerprint"]["sha256"]},
                "data": {"id": data_id, "run_id": run_id,
                          "locator": {"site_id": "eval-site", "path": str(self.root / "raw")},
                          "format": "bp5"},
                "analysis": {"id": analysis_id, "data_id": data_id,
                              "locator": {"site_id": "eval-site", "path": str(self.root / "analysis")},
                              "report_sha256": by_role["analysis_report"]["fingerprint"]["sha256"]},
            },
            "scheduler": {"kind": "slurm", "job_id": "1000",
                          "terminal_state": "COMPLETED", "matching_jobs": 1},
            "artifacts": artifacts,
            "writes": {"allowed_roots": [str(allowed)],
                       "protected_roots": [str(protected)],
                       "observed_paths": [str(observed)]},
        }
        path = self.root / "submission.json"
        self.write_json(path, submission)
        return path, submission

    def test_common_submission_validator_passes_and_detects_drift(self):
        path, submission = self.make_submission()
        result = SUBMISSION_ORACLE.validate_submission(str(path))
        self.assertEqual(result["status"], "pass", result)

        report = next(item for item in submission["artifacts"]
                      if item["role"] == "analysis_report")
        Path(report["evidence_path"]).write_text("changed\n", encoding="utf-8")
        drift = SUBMISSION_ORACLE.validate_submission(str(path))
        self.assertEqual(drift["status"], "fail")
        failed = {item["name"] for item in drift["checks"] if not item["passed"]}
        self.assertIn("artifact.analysis_report.sha256", failed)

    def test_physics_oracle_fails_closed_before_gold_run(self):
        report = self.root / "physics-report.json"
        self.write_json(report, {"schema_version": 1, "metrics": {}})
        process = subprocess.run(
            [sys.executable, str(PHYSICS_ORACLE), "--report", str(report),
             "--thresholds", str(EVAL_ROOT / "oracle" / "thresholds.json")],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout)["status"], "blocked")

    def test_fake_slurm_drives_real_v5_operation_and_evidence_validator(self):
        project = self.root / "project"
        build_root = self.root / "build"
        run_root = self.root / "runs"
        staging_root = self.root / "staging"
        bin_root = self.root / "bin"
        for path in (project, build_root, run_root, staging_root, bin_root):
            path.mkdir()
        (project / "input.toml").write_text("[simulation]\nsteps = 2\n", encoding="utf-8")
        (project / "pgen.hpp").write_text("// source\n", encoding="utf-8")
        executable = build_root / "entity.xc"
        executable.write_text("binary-placeholder\n", encoding="utf-8")
        executable.chmod(0o755)
        for name in ("sbatch", "squeue", "sacct"):
            os.symlink(FAKE_SLURM, bin_root / name)
        state_path = self.root / "fake-slurm-state.json"
        environment = {
            "PATH": str(bin_root) + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_SLURM_STATE": str(state_path),
            "FAKE_SLURM_USER": "tester",
        }

        store = OperationStore(str(self.root / "controller"))
        store.upsert_site({
            "schema_version": 1,
            "site_id": "local-slurm",
            "display_name": "local fake Slurm",
            "transport": {"kind": "local", "ssh_alias": ""},
            "scheduler": {"kind": "slurm"},
            "roots": {"source_root": str(self.root), "build_root": str(build_root),
                      "run_root": str(run_root), "staging_root": str(staging_root)},
            "policy": {"default_cpus_per_gpu": 2, "default_partition": "test"},
            "shared_mappings": [],
        })
        goal = {
            "schema_version": 1, "kind": "run", "input": "input.toml",
            "site": "local-slurm", "executable": str(executable),
            "compute": {"gpus": 1, "walltime": "00:10:00", "precision": "single",
                        "submit_user": "tester"},
        }
        plan_path = project / "operation-plan.json"
        envelope = plan_goal(store, str(project), goal, [str(plan_path)])
        self.write_json(plan_path, envelope)
        actor = {"run_id": "e2e-test", "provider": "unittest"}
        with mock.patch.dict(os.environ, environment, clear=False):
            first = apply_plan(store, goal, envelope["plan"], actor, plan_path=str(plan_path))
            second = apply_plan(store, goal, envelope["plan"], actor, plan_path=str(plan_path))
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        fake_state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(len(fake_state["jobs"]), 1)

        export_path = self.root / "router-export.json"
        status_path = self.root / "router-status.json"
        self.write_json(export_path, store.export())
        self.write_json(status_path, status_for_project(store, str(project)))
        plan = envelope["plan"]
        comment = "entity-router:%s:%s" % (
            plan["operation_id"], plan["plan_hash"].split(":", 1)[-1][:16]
        )
        scheduler_path = self.root / "scheduler-snapshot.json"
        scheduler = {
            "schema_version": 1,
            "scheduler": "slurm",
            "observed_at": "2026-07-19T00:00:00Z",
            "query": {"job_name": "entity-%s" % plan["operation_id"],
                      "submit_user": "tester",
                      "run_root": plan["steps"][2]["request"]["run_root"],
                      "comment": comment},
            "jobs": fake_state["jobs"],
        }
        self.write_json(scheduler_path, scheduler)

        trace_dir, unused = start_run(
            task_id="e2e-neutral-streaming-v1",
            input_ref="fixture://neutral-streaming",
            input_sha256=sha256_text("neutral-streaming"),
            variant="skills-v5",
            agent_provider="unittest",
            agent_model="fixture",
            agent_configuration=sha256_text("agent"),
            tool_profile="fake-slurm",
            tool_configuration=sha256_text("tools"),
            skill_paths=[],
            trace_home=self.root / "traces",
            run_id="router-v5-evidence",
        )
        receipts = [Path(step["receipt"]) for step in plan["steps"]]
        result = validate_router_operation(
            trace_dir,
            plan_path=plan_path,
            operation_path=export_path,
            receipt_paths=receipts,
            status_path=status_path,
            scheduler_path=scheduler_path,
        )
        self.assertEqual(result["status"], "pass", result)
        command = [
            sys.executable, str(OBSERVER_CLI), "evidence", "router-operation",
            "--run-dir", str(trace_dir), "--plan", str(plan_path),
            "--operation", str(export_path), "--status", str(status_path),
            "--scheduler", str(scheduler_path),
        ]
        for receipt in receipts:
            command.extend(["--receipt", str(receipt)])
        cli = subprocess.run(command, check=False, capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertTrue(json.loads(cli.stdout)["ok"])

        repeated_receipt = validate_router_operation(
            trace_dir,
            plan_path=plan_path,
            operation_path=export_path,
            receipt_paths=[receipts[0], receipts[0], receipts[2]],
            status_path=status_path,
            scheduler_path=scheduler_path,
        )
        self.assertEqual(repeated_receipt["status"], "fail")
        failed = {item["name"] for item in repeated_receipt["checks"] if not item["passed"]}
        self.assertIn("receipts.complete", failed)

        scheduler["jobs"].append(dict(scheduler["jobs"][0], job_id="1001"))
        self.write_json(scheduler_path, scheduler)
        duplicate = validate_router_operation(
            trace_dir,
            plan_path=plan_path,
            operation_path=export_path,
            receipt_paths=receipts,
            status_path=status_path,
            scheduler_path=scheduler_path,
        )
        self.assertEqual(duplicate["status"], "fail")
        duplicate_failed = {item["name"] for item in duplicate["checks"] if not item["passed"]}
        self.assertIn("scheduler.single-effect", duplicate_failed)


if __name__ == "__main__":
    unittest.main()
