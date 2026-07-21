# E2E 对照测试 Runbook（轻量 A/B）

一个任务、两种条件、每轮三条命令。本文件是唯一设置文档。

## 任务规定（随任务文本发给被测 agent）

按 `task.md` 和 `physics-spec.json`（本目录）完成 Entity 模拟全流程：

1. 确认评测站点环境，生成编译环境脚本；
2. 产出一致的 `docs/design.md` + `pgen.hpp` + 输入 TOML；
3. clean build 出 `entity.xc`；
4. 提交**恰好一个** Slurm 作业并等到终止；
5. 用 nt2py 读取输出，做场/粒子分析，出图和简短结论。

站点与约束：

- 服务器：`ssh siyuan`；GPU partition：`debuga100`（短任务，walltime ≤ 10 分钟）；
- 不使用公网；不修改只读依赖和冻结源码；analysis 不写入 raw-data root；
- 凭据不进入任何源码、脚本、日志或结果文件；
- 完成标准：作业正常终止、≥2 个时刻的 fields/particles 可读、分析结论与
  "中性双流近似平稳"的物理预期一致。

## 两个变体

| | S：`skills-v5` | N：`no-entity-skills` |
|---|---|---|
| Entity skills | `entityctl install` 发布当前 bundle（commit `6c6e205`） | `~/.claude/skills/` 下 entity-* 投影临时移走 |
| 模型 / 任务文本 / shell·ssh 工具 | 相同 | 相同 |
| 会话 | 新会话、空历史 | 新会话、空历史 |
| 工作区 | 独立项目目录 + 独立 Router home | 独立项目目录（不用 Router） |

## 每轮三条命令

```bash
OBS=tools/skill_observability/skill_observer.py

# 1. 开跑前：建 trace（记下此时刻为开始时间）
python3 $OBS start \
  --task-id e2e-neutral-streaming-v1 \
  --input-ref evals/e2e-neutral-streaming/task.md \
  --input-file evals/e2e-neutral-streaming/task.md \
  --variant skills-v5 \
  --agent-provider claude --agent-model <model> \
  --agent-configuration <config-sha256> \
  --tool-profile claude-code-default --tool-configuration <tools-sha256> \
  --skill skills/entity-router --skill skills/entity-pgen \
  --skill skills/entity-env-build --skill skills/entity-nt2py \
  --trace-home ~/entity-eval-runs/<run>/traces
# → 输出 <run-dir>（N 组去掉 --skill 行，--variant no-entity-skills）
# 注：--agent-configuration / --tool-configuration 要求小写 SHA-256 hex，
#     例如 shasum -a 256 <claude-settings.json> | cut -d' ' -f1

# 2. 用 Claude Code 新会话发出任务文本（含上面"任务规定"全文）

# 3. 结束后：导入 transcript 拿 token 总量，记录 wall-clock，收尾
python3 $OBS import-claude --run-dir <run-dir> --transcript <session.jsonl>
python3 $OBS finish --run-dir <run-dir> --status completed \
  --input-tokens <n> --output-tokens <n> --wall-time-ms <ms>
```

## 每轮目录约定（仓库外）

每轮一个独立目录，例如 `~/entity-eval-runs/2026-07-22-S1/`：

```text
├── project/       # Agent 工作区（PGen、TOML、docs、分析脚本）
├── controller/    # S 组 Router home（export ENTITY_ROUTER_HOME 指到这里；N 组不用）
└── traces/        # skill_observer --trace-home 指到这里
```

远端 `siyuan` 上的 source/build/run/analysis 根由 site profile 的 `roots`
决定（S 组用 `entityctl site add` 注册时指定，建议每轮换路径，如
`~/entity-eval/<run-name>/`）；Slurm 日志在远端 run root 的 `logs/`。

## 每轮归档

轮次结束后把 `summary.json` 放进该轮目录：

- `summary.json`：变体、模型、开始/结束时间、wall-clock、input/output token、
  Slurm job ID、完成与否、一句话结果；
- agent 最终自报摘要（原文，可放 `agent-summary.md`）。

Slurm 排队时间单独注明，不计入 agent 执行时间。
