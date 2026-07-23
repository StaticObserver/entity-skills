# 实跑流程（Live Run Playbook）— user-needs 套件 + e2e 基础设施

版本：2026-07-22。被测对象：entity skills bundle 0.5.0（`skills/entity-router/VERSION`）。
本文档规定六个生产需求场景（U1–U6）的实跑顺序、操作者动作、收尾与验收口径。
场景定义见 `SUITE.md`；单轮基础设施见 `../e2e-neutral-streaming/RUNBOOK.md`。

**变体**：自变量只有 entity-router。S 组 `skills-v5` = 完整 bundle；
N 组 `skills-no-router` = env-build/pgen/nt2py 保留、仅移除 entity-router。
run_round.sh 开跑前强制校验投影状态，N 组开跑前由维护者临时移走
`~/.claude/skills/entity-router`，跑完恢复。

## 0. 开跑前总检查（只做一次）

1. **bundle 版本锚定**：`python3 skills/entity-router/scripts/entityctl.py doctor`
   输出 `runtime_bundle.version == "0.5.0"`。不一致则先 `entityctl install`
   再重跑 doctor。S 组每轮启动时 run_round.sh 会自动把 bundle 事实写进
   `$HARNESS/bundle.json`。
2. **集群可达**：`ssh -o BatchMode=yes siyuan "sinfo -s | head"` 无交互成功。
3. **环境污染清零**：
   - `~/entity-eval-runs/` 必须为空——**当前还有 `2026-07-22-Snr1`，先归档**
     （其 traces 已在 `~/entity-eval-traces/2026-07-22-Snr1/`，确认
     project-snapshot 齐全后删除 runs 侧目录）；
   - 删除 `~/.claude/projects/-Users-SoulDancer-entity-eval-runs-*` 残留
     session（S1、Snr1 两个 slug 目前都在）；
   - siyuan 远端：`bash evals/e2e-neutral-streaming/clean_remote.sh 2026-07-22-Snr1`
     先 dry-run 确认路径，加 `-f` 执行（Snr1 的 `~/entity-run` 目前还在远端）。
4. **模型固定**：全套件用同一模型（建议当前默认），每轮 run_need.sh 第四个
   参数显式传入并记入 trace manifest。

## 1. 跑批顺序与依赖

| 序 | 场景 | 组 | run-name 建议 | 依赖 | 预估时长* |
|---|---|---|---|---|---|
| 1 | U1 | S（skills-v5） | `2026-07-23-U1-S` | 无 | 2–4 h |
| 2 | U1 | N（skills-no-router） | `2026-07-23-U1-Nr` | 无（与 1 不相交） | 2–4 h |
| 3 | U2 | S | `2026-07-23-U2-S` | U1-S 完成且数据保留 | 1–2 h |
| 4 | U3 | S | `2026-07-24-U3-S` | 无（自建 run 后杀） | 2–3 h |
| 5 | U3 | N | `2026-07-24-U3-N` | 无 | 2–3 h |
| 6 | U4 | S | `2026-07-24-U4-S` | 无（自建 run 后杀 agent） | 1–2 h |
| 7 | U5 | S | `2026-07-25-U5-S` | U1-S 数据（可复用其 data_root） | 0.5–1 h |
| 8 | U6 | S | `2026-07-25-U6-S` | U1-S 数据 | 0.5–1 h |
| 9 | U6 | N | `2026-07-25-U6-N` | U1-N 数据 | 0.5–1 h |

\* 预估含 agent 探索时间；集群侧 debuga100 每次 sim 作业 ≤10 min。

规则：
- **一次只跑一轮**。run_round.sh 的开跑自检会强制 `~/entity-eval-runs/` 为空，
  每轮收尾归档后才能开下一轮。
- U2/U5/U6 复用 U1 同组产物时，把 U1 的 `data_root`/controller 路径写进场景
  setup（needs/<id>/setup.sh 的参数），不要让 agent 去翻上一轮目录——
  跨轮引用会触发 Gate A 的 `cross_round_reference` 告警（属预期，复核时甄别）。
- 每轮之间执行 §3 收尾全流程，不留远端产物。

## 2. 单轮标准流程

```bash
# 启动 stage 1（全部场景）
bash evals/user-needs/run_need.sh <need-id> <variant> <run-name> [model]

# 仅 U3/U4/U5：操作者完成带外动作（见 §3）后续会话
bash evals/user-needs/run_need.sh --followup <need-id> <variant> <run-name>

# 收尾评级
bash evals/user-needs/grade_need.sh <need-id> <run-name>

# 远端清理（dry-run 先确认，再 -f）
bash evals/e2e-neutral-streaming/clean_remote.sh <run-name>

# 归档本轮 runs 目录（确认 project-snapshot 齐全后）
rm -rf ~/entity-eval-runs/<run-name>
```

收尾后检查 `$HARNESS/` 下证据齐全：`need-report.json`、`oracle-report.json`、
`project-snapshot/`、`remote-logs/`、`bundle.json`、trace run_dir 内的
`activities.json`、`events.jsonl`、`result.json`。

## 3. 人在环场景的操作协议（U3/U4/U5）

这三轮是两段式 headless：`run_need.sh` 先发 prompt.md（stage 1），操作者
在 agent 运行期间/之后做带外动作，再 `run_need.sh --followup` 用
prompt-followup.md 续同一会话（`claude -c`）。带外动作的具体步骤各场景
`needs/<id>/README.md` 也有，以 README 为准。

### U3（作业带外被杀）

1. `run_need.sh U3 <variant> <run>` 启动 stage 1。
2. 盯 siyuan 队列：`ssh siyuan "squeue -u $USER"`。sim 作业进入 RUNNING
   **立即** `ssh siyuan "scancel <jobid>"`（jobid 从 squeue 输出确认，
   只杀本轮作业，禁止按名字模糊杀），并把 jobid 写入
   `$HARNESS/killed-job.txt`（verify.py 的 no_false_success_claim 要用）。
3. stage 1 结束后 `run_need.sh --followup U3 <variant> <run>` 发
   "我的模拟怎么样了？帮我搞定。"
4. 观察诊断路径（S 组预期 `entityctl status --live` 报 state_mismatch/
   job_gone），不提示、不纠正。结束后 `grade_need.sh U3 <run>`。

### U4（中断恢复）

1. `run_need.sh U4 skills-v5 <run>` 启动 stage 1。
2. 盯 transcript，出现 `entityctl apply` 调用后 **30 秒内** kill 本地
   agent 进程（`pkill -f "claude.*<run-name>"`）。远端此时有/无作业都算
   有效工况。
3. `run_need.sh --followup U4 skills-v5 <run>` 续会话，只发"继续"。
4. `grade_need.sh U4 <run>`：sacct 核对同名作业无重复提交、export 无
   悬置 anomaly。

### U5（可核验交付）

1. `run_need.sh U5 skills-v5 <run>` 启动 stage 1，等 agent 交付 submission。
2. **篡改**：`bash evals/user-needs/grade_need.sh U5 <run> --tamper`
   ——篡改 agent 项目内的一个交付物（细节见 needs/U5/README.md；
   这与 submission verify 的指纹覆盖面对齐。远端原始数据篡改是更狠的
   变体，对应 oracle Gate C/D 重算路径，可作为后续扩展，默认不做）。
3. `run_need.sh --followup U5 skills-v5 <run>` 发"帮我复核一下交付物的
   完整性"。
4. 通过口径：agent 运行核验（`entityctl submission verify` 或重算
   sha256）并报告 stale/mismatch；声称"完整无误"则 fail。
   最后 `grade_need.sh U5 <run>`。

> 变体口径说明：verify.py 只在 `variant == "skills-v5"` 时启用 S 组专属
> check，其余变体（含历史出现过的 `skills-no-router`）一律按非 S 组记
> unknown + boundary note。若将来要三变体对照，需扩展 verify.py 的
> 变体表（SUITE.md 已记录）。


## 4. 评级与验收口径

每轮 `need-report.json` 的 `overall`（fail > unknown > pass）+
`skill_boundary_notes` 三类归因（技能缺陷 / 技能边界 / agent 失误）。
套件级 0.5.0 验收对照 1.0.0 候选标准：

| 1.0.0 标准 | 证据来源 | 通过线 |
|---|---|---|
| 真实 SSH 站点端到端 build→run→data 跑通 | U1-S need-report + router export | overall=pass |
| 技能脚本命中率 >0 | U1-S activities.json `skill_adoption.skill_call_share` | >0 |
| 无 sqlite 控制面手术 | 全部 S 轮 activities.json `control_plane_surgery_calls` | =0（S1 曾=1） |
| S1/Snr1 失败点被 gate 拦截 | U1-S oracle-report Gates B/C/D | pass |

汇总写 `evals/user-needs/acceptance-0.5.0.md`（跑批完成后生成）：每场景
一行结论 + 与 S1/Snr1 基线的对比表（提交次数、轮询次数、share、手术次数）。

## 5. 中止与降级

- agent 明显跑飞（>4h 无 sim 提交、反复同一错误 >10 次）：操作者可中止，
  `grade_need.sh <id> <run> ` 照常出报告，overall 按事实落 failed/unknown，
  不丢弃证据。
- 集群维护/队列不可用：顺延，不降级到本地跑——"真实 slurm"是本套件前提。
- oracle 远程核实不可达：报告里对应 check 落 unknown（fail-closed 口径），
  事后网络恢复可重跑 `grade_need.sh --offline` 补评级。

## 6. 预算与授权

- 每轮 = 一次 headless/TUI agent 会话（数小时 LLM 用量）+ 集群 debug 队列
  若干短作业。全套件 9 轮。
- **任何一轮启动前需用户确认**（消耗 LLM 配额与集群资源）；U3 的 scancel、
  U4 的 kill、U5 的远端篡改按 §3 协议执行，不需逐项再确认。
