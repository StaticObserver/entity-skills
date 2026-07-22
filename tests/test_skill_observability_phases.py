import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "skill_observability" / "skill_observer.py"

from tools.skill_observability.core import sha256_text, start_run  # noqa: E402
from tools.skill_observability.adapters.claude_phases import (  # noqa: E402
    PHASE_ORDER,
    TraceError,
    segment_transcript,
)


def assistant(ts, tools, usage=None, session="s1"):
    content = [
        {"type": "tool_use", "id": tid, "name": name, "input": tool_input}
        for tid, name, tool_input in tools
    ]
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": session,
        "message": {
            "role": "assistant",
            "content": content,
            "usage": usage or {},
        },
    }


def user_result(ts, call_id, is_error=False):
    return {
        "type": "user",
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": call_id, "is_error": is_error}
            ],
        },
    }


def write_transcript(path, records):
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


class PhaseSegmentationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transcript = self.root / "session.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def full_lifecycle_records(self):
        return [
            assistant(
                "2026-07-21T08:00:00Z",
                [("t1", "Bash", {"command": "ssh siyuan ls ~"})],
                {"input_tokens": 10, "output_tokens": 5,
                 "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20},
            ),
            user_result("2026-07-21T08:00:05Z", "t1"),
            assistant(
                "2026-07-21T08:05:00Z",
                [("t2", "Write", {"file_path": "pgens/neutral_streaming/pgen.hpp"})],
                {"input_tokens": 12, "output_tokens": 50},
            ),
            user_result("2026-07-21T08:05:03Z", "t2"),
            assistant(
                "2026-07-21T08:10:00Z",
                [("t3", "Bash", {"command": "ssh siyuan 'cmake --build build -j'"})],
                {"input_tokens": 8, "output_tokens": 4},
            ),
            user_result("2026-07-21T08:10:30Z", "t3", is_error=True),
            assistant(
                "2026-07-21T08:20:00Z",
                [("t4", "Bash", {"command": "python3 scripts/entityctl.py apply --plan plan.json"})],
                {"input_tokens": 6, "output_tokens": 3},
            ),
            user_result("2026-07-21T08:20:10Z", "t4"),
            assistant(
                "2026-07-21T08:30:00Z",
                [("t5", "Bash", {"command": "python3 -c 'import nt2; print(nt2.__version__)'"})],
                {"input_tokens": 7, "output_tokens": 6},
            ),
            user_result("2026-07-21T08:30:05Z", "t5"),
            assistant(
                "2026-07-21T08:40:00Z",
                [("t6", "Write", {"file_path": "submission.json"})],
                {"input_tokens": 9, "output_tokens": 12},
            ),
            user_result("2026-07-21T08:40:02Z", "t6"),
        ]

    def phases_by_name(self, report):
        return {p["name"]: p for p in report["phases"]}

    def test_full_lifecycle_segments_in_order(self):
        write_transcript(self.transcript, self.full_lifecycle_records())
        report = segment_transcript(self.transcript)
        phases = self.phases_by_name(report)

        self.assertEqual(report["phase_order"], PHASE_ORDER)
        self.assertTrue(report["comparable"])
        self.assertEqual(report["unclassified"]["records"], 0)

        discover = phases["discover"]
        self.assertEqual(discover["records"], 2)
        self.assertEqual(discover["usage"]["input_tokens"], 10)
        self.assertEqual(discover["usage"]["cache_read_input_tokens"], 100)
        self.assertEqual(discover["usage"]["cache_creation_input_tokens"], 20)
        self.assertEqual(discover["ssh_calls"], 1)
        self.assertEqual(discover["wall_time_ms"], 5000)

        pgen = phases["pgen"]
        self.assertEqual(pgen["usage"]["output_tokens"], 50)

        env = phases["env-build"]
        self.assertEqual(env["ssh_calls"], 1)  # ssh in a later phase does not regress
        self.assertEqual(env["tool_calls"]["failed"], 1)

        run = phases["run"]
        self.assertEqual(run["tool_calls"]["total"], 1)

        analysis = phases["analysis"]
        self.assertEqual(analysis["usage"]["input_tokens"], 7)

        submission = phases["submission"]
        self.assertEqual(submission["usage"]["output_tokens"], 12)

        totals = report["totals"]
        self.assertEqual(totals["tool_calls"]["total"], 6)
        self.assertEqual(totals["tool_calls"]["failed"], 1)
        self.assertEqual(totals["ssh_calls"], 2)
        self.assertEqual(
            totals["usage"]["input_tokens"],
            sum(p["usage"]["input_tokens"] for p in report["phases"]),
        )

    def test_records_before_first_match_are_unclassified(self):
        records = [
            assistant("2026-07-21T08:00:00Z", [],
                      {"input_tokens": 1000, "output_tokens": 10}),
            assistant("2026-07-21T08:01:00Z",
                      [("t1", "Write", {"file_path": "submission.json"})],
                      {"input_tokens": 10, "output_tokens": 5}),
        ]
        write_transcript(self.transcript, records)
        report = segment_transcript(self.transcript)
        self.assertEqual(report["unclassified"]["records"], 1)
        self.assertEqual(report["unclassified"]["usage"]["input_tokens"], 1000)
        # 1010 / 1025 tokens unclassified -> far above 10% limit
        self.assertFalse(report["comparable"])
        self.assertGreater(report["unclassified_token_share"], 0.10)

    def test_no_skill_variant_segments_identically(self):
        # N 组（no-entity-skills）：没有 entityctl/preflight 等 skill 调用，
        # 只有任务交付物驱动的通用命令。切分必须给出与 S 组相同的阶段序列。
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "ssh siyuan 'module avail'"})],
                      {"input_tokens": 10, "output_tokens": 5}),
            user_result("2026-07-21T08:00:05Z", "t1"),
            assistant("2026-07-21T08:05:00Z",
                      [("t2", "Write", {"file_path": "docs/design.md"}),
                       ("t3", "Write", {"file_path": "pgen.hpp"})],
                      {"input_tokens": 20, "output_tokens": 80}),
            assistant("2026-07-21T08:15:00Z",
                      [("t4", "Bash", {"command": "ssh siyuan 'cd build && make -j8'"})],
                      {"input_tokens": 8, "output_tokens": 3}),
            assistant("2026-07-21T08:25:00Z",
                      [("t5", "Bash", {"command": "ssh siyuan 'sbatch run.sbatch && squeue -u $USER'"})],
                      {"input_tokens": 6, "output_tokens": 3}),
            assistant("2026-07-21T08:35:00Z",
                      [("t6", "Bash", {"command": "python3 analyze.py  # import nt2"})],
                      {"input_tokens": 7, "output_tokens": 6}),
            assistant("2026-07-21T08:45:00Z",
                      [("t7", "Write", {"file_path": "submission.json"})],
                      {"input_tokens": 9, "output_tokens": 12}),
        ]
        write_transcript(self.transcript, records)
        report = segment_transcript(self.transcript)
        self.assertTrue(report["comparable"])
        names = [p["name"] for p in report["phases"] if p["records"] > 0]
        self.assertEqual(
            names,
            ["discover", "pgen", "env-build", "run", "analysis", "submission"],
        )

    def test_content_mentions_do_not_trigger_phase(self):
        # 文档/计划正文中提到 submission.json 不得触发 submission 阶段；
        # 只有 file_path 目标是 submission.json 才算。
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "ssh siyuan ls"})]),
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Write", {
                          "file_path": "plan.md",
                          "content": "deliverables: pgen.hpp, build, run, submission.json",
                      })]),
            assistant("2026-07-21T08:02:00Z",
                      [("t3", "Bash", {"command": "ssh siyuan 'sbatch run.sbatch'"})]),
            assistant("2026-07-21T08:03:00Z",
                      [("t4", "Write", {"file_path": "submission.json",
                                        "content": "{}"})]),
        ]
        write_transcript(self.transcript, records)
        report = segment_transcript(self.transcript)
        phases = self.phases_by_name(report)
        self.assertEqual(phases["discover"]["records"], 2)
        self.assertEqual(phases["run"]["records"], 1)
        self.assertEqual(phases["submission"]["records"], 1)

    def test_phase_never_regresses(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "sbatch run.sbatch"})]),
            # exploratory-looking command after run must stay in `run`
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Bash", {"command": "ssh siyuan ls run/"})]),
        ]
        write_transcript(self.transcript, records)
        report = segment_transcript(self.transcript)
        phases = self.phases_by_name(report)
        self.assertEqual(phases["discover"]["records"], 0)
        self.assertEqual(phases["run"]["records"], 2)
        self.assertEqual(phases["run"]["ssh_calls"], 1)

    def test_custom_rules_override(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "frobnicate the widget"})],
                      {"input_tokens": 5, "output_tokens": 5}),
        ]
        write_transcript(self.transcript, records)
        report = segment_transcript(
            self.transcript,
            rules=[{"phase": "env-build", "pattern": "frobnicate"}],
        )
        phases = self.phases_by_name(report)
        self.assertEqual(phases["env-build"]["records"], 1)
        self.assertEqual(phases["discover"]["records"], 0)

    def test_invalid_rule_phase_rejected(self):
        write_transcript(self.transcript, self.full_lifecycle_records())
        with self.assertRaises(TraceError):
            segment_transcript(
                self.transcript,
                rules=[{"phase": "not-a-phase", "pattern": "x"}],
            )


class SkillAdoptionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transcript = self.root / "session.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def adoption(self, report):
        return report["skill_adoption"]

    def test_skill_and_raw_calls_counted(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "python3 scripts/entityctl.py apply --plan plan.json"})]),
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Bash", {"command": "bash entity-build.sh --deps"})]),
            assistant("2026-07-21T08:02:00Z",
                      [("t3", "Bash", {"command": "python3 scripts/pgen_preflight.py pgens/x"})]),
            assistant("2026-07-21T08:03:00Z",
                      [("t4", "Bash", {"command": "python3 -c 'import nt2; print(nt2.Data)'"})]),
            assistant("2026-07-21T08:04:00Z",
                      [("t5", "Bash", {"command": "ssh siyuan 'sbatch run.sbatch'"})]),
            assistant("2026-07-21T08:05:00Z",
                      [("t6", "Bash", {"command": "ssh siyuan 'squeue -u $USER'"})]),
            assistant("2026-07-21T08:06:00Z",
                      [("t7", "Bash", {"command": "sqlite3 control.db 'select 1'"})]),
        ]
        write_transcript(self.transcript, records)
        adoption = self.adoption(segment_transcript(self.transcript))

        skill = adoption["skill_calls"]
        self.assertEqual(skill["router"], 1)
        self.assertEqual(skill["env_build"], 1)
        self.assertEqual(skill["pgen"], 1)
        self.assertEqual(skill["nt2py"], 1)
        self.assertEqual(skill["total"], 4)

        raw = adoption["raw_calls"]
        self.assertEqual(raw["sbatch"], 1)
        self.assertEqual(raw["scheduler_poll"], 1)
        self.assertEqual(raw["srun"], 0)
        self.assertEqual(raw["scancel"], 0)
        self.assertEqual(raw["build"], 0)
        self.assertEqual(raw["total"], 2)

        self.assertEqual(adoption["control_plane_surgery_calls"], 1)
        self.assertEqual(adoption["skill_call_share"], round(4 / 6, 6))

    def test_first_match_wins_entity_build_not_raw_build(self):
        # entity-build.sh matches skill.env_build before raw.build could see
        # any of its tokens; a plain make still lands in raw.build.
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "./entity-build.sh"})]),
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Bash", {"command": "cmake --build build -j"})]),
        ]
        write_transcript(self.transcript, records)
        adoption = self.adoption(segment_transcript(self.transcript))
        self.assertEqual(adoption["skill_calls"]["env_build"], 1)
        self.assertEqual(adoption["raw_calls"]["build"], 1)
        self.assertEqual(adoption["skill_call_share"], 0.5)

    def test_skill_doc_reads_are_not_counted(self):
        # Reading an installed skill doc is orientation: the SKILL_DOC_RE
        # skip applies to adoption matching too, even when the path contains
        # a rule token such as inspect_nt2_data.
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Read", {
                          "file_path": "/home/x/.claude/skills/entity-nt2py/scripts/inspect_nt2_data.py",
                      })]),
        ]
        write_transcript(self.transcript, records)
        adoption = self.adoption(segment_transcript(self.transcript))
        self.assertEqual(adoption["skill_calls"]["nt2py"], 0)
        self.assertEqual(adoption["skill_calls"]["total"], 0)
        self.assertIsNone(adoption["skill_call_share"])

    def test_no_matches_share_is_none(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "ssh siyuan ls ~"})]),
        ]
        write_transcript(self.transcript, records)
        adoption = self.adoption(segment_transcript(self.transcript))
        self.assertEqual(adoption["skill_calls"]["total"], 0)
        self.assertEqual(adoption["raw_calls"]["total"], 0)
        self.assertEqual(adoption["control_plane_surgery_calls"], 0)
        self.assertIsNone(adoption["skill_call_share"])


class PhasesCommandTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        run_dir, _ = start_run(
            task_id="case-001",
            input_ref="fixture://case-001",
            input_sha256=sha256_text("test task"),
            variant="full",
            agent_provider="test-provider",
            agent_model="test-model",
            agent_configuration=sha256_text("agent-config"),
            tool_profile="test-tools",
            tool_configuration=sha256_text("tool-config"),
            skill_paths=[],
            trace_home=self.root / "traces",
            run_id="phases-cli",
        )
        self.run_dir = run_dir

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(CLI), *argv],
            capture_output=True, text=True,
        )

    def test_phases_command_writes_report_and_artifact(self):
        transcript = self.root / "session.jsonl"
        write_transcript(transcript, [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "ssh siyuan ls"})],
                      {"input_tokens": 10, "output_tokens": 5}),
            assistant("2026-07-21T08:05:00Z",
                      [("t2", "Write", {"file_path": "submission.json"})],
                      {"input_tokens": 10, "output_tokens": 5}),
        ])
        proc = self.run_cli(
            "phases", "--run-dir", str(self.run_dir),
            "--transcript", str(transcript),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        outcome = json.loads(proc.stdout)
        self.assertTrue(outcome["ok"])
        self.assertTrue(outcome["comparable"])

        report_path = self.run_dir / "phases.json"
        self.assertTrue(report_path.is_file())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 1)
        names = [p["name"] for p in report["phases"] if p["records"] > 0]
        self.assertEqual(names, ["discover", "submission"])

        artifacts = [
            json.loads(line)
            for line in (self.run_dir / "artifacts.jsonl").read_text().splitlines()
            if line.strip()
        ]
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["role"], "phases-report")


if __name__ == "__main__":
    unittest.main()
