import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "skill_observability" / "skill_observer.py"

from tools.skill_observability.core import sha256_text, start_run  # noqa: E402
from tools.skill_observability.adapters.claude_activities import (  # noqa: E402
    CATEGORIES,
    TraceError,
    analyze_transcript,
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


class ActivityTaggingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transcript = self.root / "session.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def categories_by_name(self, report):
        return {c["name"]: c for c in report["categories"]}

    def test_interleaved_pgen_after_build_still_counted(self):
        # 旧状态机里 build 信号先于 pgen 写作会让 pgen 阶段归零；
        # 活动标注下两者各自独立计数。
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "ssh siyuan 'cmake --build build -j'"})],
                      {"input_tokens": 8, "output_tokens": 4}),
            user_result("2026-07-21T08:00:30Z", "t1"),
            assistant("2026-07-21T08:05:00Z",
                      [("t2", "Write", {"file_path": "pgens/neutral_streaming/pgen.hpp"})],
                      {"input_tokens": 12, "output_tokens": 50}),
            user_result("2026-07-21T08:05:03Z", "t2"),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        cats = self.categories_by_name(report)

        self.assertEqual(cats["build"]["tool_calls"], 1)
        self.assertEqual(cats["build"]["records"], 1)
        self.assertEqual(cats["pgen-authoring"]["tool_calls"], 1)
        self.assertEqual(cats["pgen-authoring"]["records"], 1)
        self.assertEqual(cats["pgen-authoring"]["usage"]["output_tokens"], 50)

    def test_backtrack_build_after_analysis_counted(self):
        # analysis 之后回退到 build：无顺序假设，两类都计数。
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "python3 -c 'import nt2; print(nt2.Data)'"})]),
            assistant("2026-07-21T08:10:00Z",
                      [("t2", "Bash", {"command": "ssh siyuan 'cd build && make -j8'"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        cats = self.categories_by_name(report)

        self.assertEqual(cats["data-analysis"]["tool_calls"], 1)
        self.assertEqual(cats["build"]["tool_calls"], 1)

    def test_multi_category_record_attributes_to_each(self):
        # 一条 record 同时写 pgen 并跑 cmake：归因允许重叠，
        # 两个类别各自获得该 record 的 token。
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Write", {"file_path": "pgen.hpp"}),
                       ("t2", "Bash", {"command": "cmake --build build -j"})],
                      {"input_tokens": 10, "output_tokens": 20}),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        cats = self.categories_by_name(report)

        self.assertEqual(cats["pgen-authoring"]["usage"]["input_tokens"], 10)
        self.assertEqual(cats["build"]["usage"]["input_tokens"], 10)
        # totals 只计一次
        self.assertEqual(report["totals"]["usage"]["input_tokens"], 10)
        self.assertEqual(report["totals"]["tool_calls"], 2)

    def test_documentation_vs_pgen_authoring(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Write", {"file_path": "docs/design.md"})]),
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Write", {"file_path": "input.toml"})]),
            assistant("2026-07-21T08:02:00Z",
                      [("t3", "Write", {"file_path": "report.md"})]),
            assistant("2026-07-21T08:03:00Z",
                      [("t4", "Write", {"file_path": "submission.json"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        cats = self.categories_by_name(report)

        self.assertEqual(cats["pgen-authoring"]["tool_calls"], 2)
        self.assertEqual(cats["documentation"]["tool_calls"], 2)

    def test_unclassified_share_reported_not_fatal(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "frobnicate --widget"})]),
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Bash", {"command": "ssh siyuan ls"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        self.assertEqual(report["unclassified_tool_share"], 0.5)
        # 无 comparable 硬判定字段
        self.assertNotIn("comparable", report)

    def test_custom_rules_override_with_category_key(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "frobnicate the widget"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(
            self.transcript,
            rules=[{"category": "build", "pattern": "frobnicate"}],
        )
        cats = self.categories_by_name(report)
        self.assertEqual(cats["build"]["tool_calls"], 1)
        self.assertEqual(report["unclassified_tool_share"], 0.0)

    def test_invalid_rule_category_rejected(self):
        write_transcript(self.transcript, [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "ls"})]),
        ])
        with self.assertRaises(TraceError):
            analyze_transcript(
                self.transcript,
                rules=[{"category": "not-a-category", "pattern": "x"}],
            )


class JobLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transcript = self.root / "session.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_sbatch_submissions_grouped_by_job_name(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "ssh siyuan 'sbatch --job-name=ns-sim run.sbatch'"})]),
            assistant("2026-07-21T08:05:00Z",
                      [("t2", "Bash", {"command": "sbatch -J ns-sim run2.sbatch"})]),
            assistant("2026-07-21T08:10:00Z",
                      [("t3", "Bash", {"command": "sbatch other.sbatch"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        lifecycle = report["job_lifecycle"]

        self.assertEqual(lifecycle["submissions_total"], 3)
        self.assertEqual(lifecycle["sim_submissions"], 3)
        self.assertEqual(lifecycle["build_submissions"], 0)

        ns_sim = lifecycle["jobs"]["ns-sim"]
        self.assertEqual(ns_sim["job_class"], "sim")
        self.assertEqual(len(ns_sim["submissions"]), 2)
        self.assertEqual(ns_sim["submissions"][0]["timestamp"], "2026-07-21T08:00:00Z")
        self.assertEqual(ns_sim["submissions"][1]["timestamp"], "2026-07-21T08:05:00Z")
        self.assertIsNone(ns_sim["first_success_attempt"])

        # 无 --job-name 时用脚本 basename
        self.assertIn("other.sbatch", lifecycle["jobs"])

    def test_heredoc_with_cmake_is_build_class(self):
        # sbatch 提交编译作业：heredoc 内容调 cmake -> build 类，
        # 且该 tool_use 归入 build 类别而非 job-submit。
        command = (
            "ssh siyuan 'sbatch --job-name=entity-build <<\"EOF\"\n"
            "#!/bin/bash\n"
            "cmake --build . -j 16\n"
            "EOF'"
        )
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": command})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        lifecycle = report["job_lifecycle"]

        self.assertEqual(lifecycle["submissions_total"], 1)
        self.assertEqual(lifecycle["build_submissions"], 1)
        self.assertEqual(lifecycle["sim_submissions"], 0)
        job = lifecycle["jobs"]["entity-build"]
        self.assertEqual(job["job_class"], "build")

        cats = {c["name"]: c for c in report["categories"]}
        self.assertEqual(cats["build"]["tool_calls"], 1)
        self.assertEqual(cats["job-submit"]["tool_calls"], 0)

    def test_build_named_job_without_cmake_is_build_class(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "sbatch --job-name=kk-deps-rebuild setup.sbatch"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        lifecycle = report["job_lifecycle"]
        self.assertEqual(lifecycle["build_submissions"], 1)
        self.assertEqual(lifecycle["jobs"]["kk-deps-rebuild"]["job_class"], "build")

    def test_sbatch_script_name_strips_ssh_quotes(self):
        # ssh 包装的命令以引号收尾："sbatch build_job.slurm" —— 引号不得混入作业名。
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": 'ssh siyuan "cd $HOME/entity-run && sbatch build_job.slurm"'})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        lifecycle = report["job_lifecycle"]
        self.assertEqual(lifecycle["submissions_total"], 1)
        self.assertIn("build_job.slurm", lifecycle["jobs"])

    def test_sbatch_text_mention_not_counted(self):
        # echo 文本里提到 sbatch 不是提交（S1 transcript 真实案例）。
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": 'echo "=== sbatch ===" && squeue -u $USER'})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        self.assertEqual(report["job_lifecycle"]["submissions_total"], 0)

    def test_sbatch_qos_equals_form(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": 'ssh siyuan "sbatch --qos=debug run_sim.slurm 2>&1"'})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        lifecycle = report["job_lifecycle"]
        self.assertEqual(lifecycle["submissions_total"], 1)
        self.assertIn("run_sim.slurm", lifecycle["jobs"])

    def test_sbatch_wrap_multiword_payload(self):
        # --wrap 带引号多词负载 + 尾部重定向：不得把负载词或 2>&1 当脚本名；
        # 负载里启动 entity.xc（即便同时 module load cmake）应判 sim 类。
        cmd = ('ssh siyuan \'sbatch --partition=debuga100 --qos=debug '
               '--wrap="module load cmake/3.29.4 cuda/12.2.2 && '
               'mpirun -np 2 ~/build/src/entity.xc -input x.toml" 2>&1\'')
        records = [
            assistant("2026-07-21T08:00:00Z", [("t1", "Bash", {"command": cmd})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        lifecycle = report["job_lifecycle"]
        self.assertEqual(lifecycle["submissions_total"], 1)
        [(job_name, job)] = lifecycle["jobs"].items()
        self.assertTrue(job_name.startswith("wrap:"), job_name)
        self.assertEqual(job["job_class"], "sim")

    def test_sbatch_redirect_tokens_not_script_names(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": 'sbatch --wrap="hostname" 2>&1'})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        jobs = report["job_lifecycle"]["jobs"]
        self.assertNotIn("2>&1", jobs)
        self.assertEqual(list(jobs), ["wrap:hostname"])

    def test_scheduler_polls_counted_per_command(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "ssh siyuan 'squeue -u $USER'"})]),
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Bash", {"command": "ssh siyuan 'sacct -j 123 && squeue -j 123'"})]),
            assistant("2026-07-21T08:02:00Z",
                      [("t3", "Bash", {"command": "ssh siyuan 'scontrol show job 123'"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        polls = report["job_lifecycle"]["polls"]

        self.assertEqual(polls["squeue"], 2)
        self.assertEqual(polls["sacct"], 1)
        self.assertEqual(polls["scontrol"], 1)

        cats = {c["name"]: c for c in report["categories"]}
        self.assertEqual(cats["job-monitor"]["tool_calls"], 3)

    def test_entityctl_submit_and_monitor_categories(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "python3 scripts/entityctl.py record run-launch --project-root ."})]),
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Bash", {"command": "python3 scripts/entityctl.py status op-1"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        cats = {c["name"]: c for c in report["categories"]}
        self.assertEqual(cats["job-submit"]["tool_calls"], 1)
        self.assertEqual(cats["job-monitor"]["tool_calls"], 1)


class ActivitiesSkillAdoptionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transcript = self.root / "session.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_mixed_skill_and_raw_share(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "python3 scripts/entityctl.py record run-launch --project-root ."})]),
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Bash", {"command": "ssh siyuan 'sbatch run.sbatch'"})]),
            assistant("2026-07-21T08:02:00Z",
                      [("t3", "Bash", {"command": "ssh siyuan 'squeue -u $USER'"})]),
        ]
        write_transcript(self.transcript, records)
        adoption = analyze_transcript(self.transcript)["skill_adoption"]

        self.assertEqual(adoption["skill_calls"]["router"], 1)
        self.assertEqual(adoption["skill_calls"]["total"], 1)
        self.assertEqual(adoption["raw_calls"]["sbatch"], 1)
        self.assertEqual(adoption["raw_calls"]["scheduler_poll"], 1)
        self.assertEqual(adoption["raw_calls"]["total"], 2)
        self.assertEqual(adoption["skill_call_share"], round(1 / 3, 6))

    def test_skill_script_execution_via_installed_path_counted(self):
        # 通过安装路径执行技能脚本（agent 的真实调用方式）必须计为技能调用，
        # 不得因路径含 .claude/skills 被误判为"读文档"（U1-S/U4-S 实跑缺陷）。
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command":
                          "python3 /Users/x/.claude/skills/entity-router/scripts/entityctl.py site list"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        adoption = report["skill_adoption"]
        self.assertEqual(adoption["skill_calls"]["router"], 1)
        self.assertEqual(adoption["skill_calls"]["total"], 1)

    def test_skill_doc_reads_not_counted_as_calls(self):
        records = [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Read", {
                          "file_path": "/home/x/.claude/skills/entity-nt2py/scripts/inspect_nt2_data.py",
                      })]),
            assistant("2026-07-21T08:01:00Z",
                      [("t2", "Bash", {"command": "ssh siyuan 'sbatch run.sbatch'"})]),
        ]
        write_transcript(self.transcript, records)
        report = analyze_transcript(self.transcript)
        adoption = report["skill_adoption"]

        self.assertEqual(report["skill_doc_reads"], 1)
        self.assertEqual(adoption["skill_calls"]["nt2py"], 0)
        self.assertEqual(adoption["skill_calls"]["total"], 0)
        # 技能文档读取不计入任何类别，也不进 unclassified 占比的分母
        self.assertEqual(report["unclassified_tool_share"], 0.0)
        for category in report["categories"]:
            self.assertEqual(
                category["tool_calls"],
                1 if category["name"] == "job-submit" else 0,
                category["name"],
            )


class ActivitiesCommandTest(unittest.TestCase):
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
            run_id="activities-cli",
        )
        self.run_dir = run_dir

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(CLI), *argv],
            capture_output=True, text=True,
        )

    def test_activities_command_writes_report_event_and_artifact(self):
        transcript = self.root / "session.jsonl"
        write_transcript(transcript, [
            assistant("2026-07-21T08:00:00Z",
                      [("t1", "Bash", {"command": "ssh siyuan ls"})],
                      {"input_tokens": 10, "output_tokens": 5}),
            assistant("2026-07-21T08:05:00Z",
                      [("t2", "Bash", {"command": "sbatch --job-name=ns-sim run.sbatch"})],
                      {"input_tokens": 10, "output_tokens": 5}),
            assistant("2026-07-21T08:10:00Z",
                      [("t3", "Bash", {"command": "totally-unmapped-command"})],
                      {"input_tokens": 10, "output_tokens": 5}),
        ])
        proc = self.run_cli(
            "activities", "--run-dir", str(self.run_dir),
            "--transcript", str(transcript),
        )
        # 即使存在 unclassified 调用也必须 exit 0
        self.assertEqual(proc.returncode, 0, proc.stderr)
        outcome = json.loads(proc.stdout)
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["submissions_total"], 1)

        report_path = self.run_dir / "activities.json"
        self.assertTrue(report_path.is_file())
        report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["category_order"], CATEGORIES)
        cats = {c["name"]: c for c in report["categories"]}
        self.assertEqual(cats["explore"]["tool_calls"], 1)
        self.assertEqual(cats["job-submit"]["tool_calls"], 1)
        self.assertEqual(cats["other"]["tool_calls"], 1)
        self.assertAlmostEqual(report["unclassified_tool_share"], round(1 / 3, 6))
        self.assertIn("ns-sim", report["job_lifecycle"]["jobs"])
        self.assertIn("skill_adoption", report)
        self.assertNotIn("comparable", report)

        events = [
            json.loads(line)
            for line in (self.run_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        finished = [e for e in events if e["type"] == "validation.finished"]
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0]["payload"]["kind"], "claude-activities")
        self.assertEqual(finished[0]["payload"]["status"], "pass")

        artifacts = [
            json.loads(line)
            for line in (self.run_dir / "artifacts.jsonl").read_text().splitlines()
            if line.strip()
        ]
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["role"], "activities-report")


if __name__ == "__main__":
    unittest.main()
