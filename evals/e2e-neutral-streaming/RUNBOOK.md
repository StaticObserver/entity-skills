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

- 服务器：`ssh m87`（个人主机，单 GPU，**无 Slurm、无 MPI**，环境由 agent 自行探索）；
- 资源上限：1 GPU / walltime ≤ 10 分钟；
- 数据分析只用 CPU 资源，不占用 GPU；
- 源码与依赖：agent 自行发现（source-cache 已预置在可发现位置，路径不进任务文本）；
- 不使用公网；不修改只读依赖和冻结源码；analysis 不写入 raw-data root；
- 凭据不进入任何源码、脚本、日志或结果文件；
- 完成标准：作业正常终止、≥2 个时刻的 fields/particles 可读、分析结论与
  "中性双流近似平稳"的物理预期一致。

## 两个变体

| | S：`skills-v5`（完整 bundle） | N：`skills-no-router`（仅无 entity-ledger） |
|---|---|---|
| Entity skills | `entityctl install` 发布当前 bundle（commit `6c6e205`） | `~/.claude/skills/` 下 entity-* 投影临时移走 |
| 模型 / 任务文本 / shell·ssh 工具 | 相同 | 相同 |
| 会话 | 新会话、空历史 | 新会话、空历史 |
| 工作区 | 独立项目目录 + 独立 Router home | 独立项目目录（不用 Router） |

## 每轮命令

推荐直接用封装脚本（内部等价于下面的手动步骤）：

```bash
# 开跑（建目录、注册 trace、启动 agent；启动前校验技能投影状态：
# S 组要求 entity-ledger 在场，N 组要求仅 entity-ledger 已移走、
# env-build/pgen/nt2py 三者保留——不满足则拒绝启动）
evals/e2e-neutral-streaming/run_round.sh skills-v5 2026-07-21-S1 [model]
evals/e2e-neutral-streaming/run_round.sh skills-no-router 2026-07-22-Snr1 [model]

# 收尾（先快照 project 产物到 traces/<run>/project-snapshot/，再导入
# transcript、阶段切分、关闭 trace；finish 必须是最后一步；重复执行会
# 检测到 terminal event 并直接跳过）
evals/e2e-neutral-streaming/finish_round.sh 2026-07-21-S1 completed

# 远端清理（先拉 slurm 脚本/日志到 traces/<run>/remote-logs/，默认 dry-run，
# -f 才真正删除远端 data_root 及其 run 目录，最后 squeue 确认无残留作业）
evals/e2e-neutral-streaming/clean_remote.sh 2026-07-21-S1 -f
```

`run_round.sh` 会一并把 `fixtures/submission.schema.json` 拷进 project
（submission.json 必须符合它，schema 符合度对所有组公平），开跑前自检
`~/entity-eval-runs/` 必须为空（非空直接退出），并对 `~/.claude/projects/`
下早于今天的 entity-eval-runs session 目录打印残留警告。S 组开跑前还会把
`entityctl doctor` 的 bundle_version/bundle_hash 写入
`~/entity-eval-traces/<run>/bundle.json`（只读取版本事实，不安装）。

每轮结束后：清理 `~/.claude/projects/` 下本轮 session 目录（slug 形如
`-Users-…-entity-eval-runs-<run>-project`），再按上面 `clean_remote.sh`
清理远端。

手动步骤：

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
  --skill skills/entity-ledger --skill skills/entity-pgen \
  --skill skills/entity-env-build --skill skills/entity-nt2py \
  --trace-home ~/entity-eval-runs/<run>/traces
# → 输出 <run-dir>（N 组去掉 --skill 行，--variant skills-no-router）
# 注：--agent-configuration / --tool-configuration 要求小写 SHA-256 hex，
#     例如 shasum -a 256 <claude-settings.json> | cut -d' ' -f1

# 2. 用 Claude Code 新会话发出任务文本（含上面"任务规定"全文）。
#    监控开关：OBSERVE=off 时直接用普通命令跑，不重定向输出、不注入任何
#    hook/settings——与裸跑完全一致。OBSERVE=on（默认）时用 headless
#    stream-json 跑，输出落到本轮目录：
OBSERVE=on claude -p "$(cat evals/e2e-neutral-streaming/task.md)" \
  --output-format stream-json --verbose \
  > ~/entity-eval-runs/<run>/transcript.jsonl

# 3. 结束后（仅 OBSERVE=on）：导入 transcript 拿 token 总量，做阶段切分，收尾
python3 $OBS import-claude --run-dir <run-dir> --transcript <transcript.jsonl>
python3 $OBS phases --run-dir <run-dir> --transcript <transcript.jsonl>
# → 写 <run-dir>/phases.json：每阶段 wall time、四类 token（cache 分列）、
#   工具调用/失败/SSH 数；unclassified token 占比 >10% 时 comparable=false
python3 $OBS finish --run-dir <run-dir> --status completed \
  --input-tokens <n> --output-tokens <n> --wall-time-ms <ms>
```

监控是带外的：切分与统计全部在运行结束后离线进行，agent 的工具调用路径上
没有任何探针，skills 不知道监控存在。`OBSERVE=off` 时第 3 步整段跳过，
agent 的运行命令、settings、环境与裸跑逐字节一致。

## 每轮目录约定（仓库外）

每轮一个独立目录，例如 `~/entity-eval-runs/2026-07-22-S1/`：

```text
├── project/       # Agent 工作区（PGen、TOML、docs、分析脚本）
└── controller/    # S 组 Router home（export ENTITY_LEDGER_HOME 指到这里；N 组不创建）
```

Harness 状态在 agent 不可及的 `~/entity-eval-traces/<run>/`（trace home、
transcript、`project-snapshot/`、`remote-logs/`、`bundle.json`）。

远端 `m87` 上的 source/build/run/analysis 根由 site profile 的 `roots`
决定（S 组用 `entityctl site add` 注册时指定，建议每轮换路径，如
`~/entity-eval/<run-name>/`）；m87 无 Slurm，run 日志由 agent 自行落盘。

## Oracle 独立复核

`finish_round.sh` 之后运行（不信任 agent 自报，从外部事实重验）：

```bash
# 拉取 raw data 并跑全部五道门（A 安全 / B PGen / C 作业数据 / D 物理 / E 分析）
python3 evals/e2e-neutral-streaming/oracle/oracle.py \
  --project ~/entity-eval-runs/<run>/project \
  --transcript ~/.claude/projects/<project-slug>/<session>.jsonl \
  --fetch ~/entity-eval-traces/<run>/oracle-data
```

产出 `<project>/oracle-report.json`，总体 fail > unknown > pass。物理阈值冻结在
`oracle/thresholds.json`（每条含物理定义、公式和 gold run 观测值），不得根据
S/N 结果回调。

## 每轮归档

轮次结束后把 `summary.json` 放进该轮目录：
- `summary.json`：变体、模型、开始/结束时间、wall-clock、input/output token、
  Slurm job ID、完成与否、一句话结果；
- agent 最终自报摘要（原文，可放 `agent-summary.md`）。

Slurm 排队时间单独注明，不计入 agent 执行时间。
