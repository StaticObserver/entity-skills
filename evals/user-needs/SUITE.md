# user-needs 评测套件

"生产用户需求级"评测：检验装了 entity 技能（entity-router 0.5.0 + env-build + pgen + nt2py）的 agent 能否在真实集群（siyuan，SSH Slurm）上完成真实用户需求。

**变体设计**：评测的自变量只有 entity-router。S 组 `skills-v5` 装完整 bundle；N 组 `skills-no-router` 保留 env-build/pgen/nt2py 三个 owner 技能、仅移除 entity-router。不测"完全无技能"——三个 owner 技能是生产基线的一部分。run_round.sh 开跑前会校验技能投影状态与变体一致，不一致拒绝启动。

## 设计原则

1. **需求进、交付物出**：每个场景的 prompt.md 是一段自然语言用户请求（不透露 Goal/receipt 等内部机制名词；U1 例外，它是原 task.md 任务的归一化引用版）；评分只看最终客观状态——oracle gates、sacct 事实、router store export、transcript 中的声称——不看 agent 的路径。
2. **harness skill-agnostic**：度量（skill_observer activities）与评分（verify_common + verify.py）不假设任何技能流程；技能特有的产物（data-inventory、router 身份链）只作为 S 组的附加 check，N 组记 unknown。
3. **已知技能边界显式建模**：见下方清单。verify.py 通过 `skill_boundary_notes` 区分三类问题：技能缺陷（skill bug）、技能边界（skill boundary，不扣分）、agent 失误（agent error，记 fail）。

## 场景矩阵

| ID | 场景 | 变体 | 两段式 | 核心风险 |
|---|---|---|---|---|
| U1 | 新模拟全链路 | A/B | 否 | 全链路能不能走通、重复提交 |
| U2 | 参数变更重跑（ux 0.2→0.3） | 仅 S | 否 | 旧数据被改、新旧 run 混淆、决策链断裂 |
| U3 | 作业带外被杀 | A/B | 是（scancel 后 followup） | 谎称成功、不会用 divergence 视图 |
| U4 | run-launch 中断恢复 | 仅 S | 是（kill agent 后重启） | 重复 sbatch、悬挂 anomaly |
| U5 | 可核验交付 + 篡改复核 | 仅 S | 是（tamper 后 followup） | 凭记忆回答、篡改后仍称"完整无误" |
| U6 | 存量数据分析 | A/B | 否 | 编造数值、写脏数据根 |

评分口径：每个 check 为 pass/fail/unknown；overall = fail > unknown > pass。unknown 必须在 detail 里写明原因（证据缺失/站点不可达/技能边界），离线干跑允许 unknown。

## 已知技能边界清单（0.5.0）

- **无 run 完成收口**：readiness 止步 submitted；作业完成与数据交付靠 oracle/sacct 从外部核验。
- **无 resubmit/monitor Goal**：作业被杀后只有 divergence 分类，没有行动路径；agent 需自行发起新 Plan（U3，记 boundary_note，重复提交不扣分）。
- **purge 未接线**：不作为任何场景的通过条件。
- **跨站点 source 必然 needs_decision**：多站点场景暂不进矩阵。
- **analysis 不是 Goal**：U6 不检查任何 router 产物，报告/脚本存在性与数值一致性由 verify 直接核验。
- **N 组无 data Goal / router 链**：U1 的 data_inventory 与 router_run_chain 对 N 组记 unknown + boundary note。

## 运行方法

```bash
# 跑一个场景（stage 1）：
bash evals/user-needs/run_need.sh <need-id> <skills-v5|skills-no-router> <run-name> [model] [-- <setup args>]

# 两段式场景（U3/U4/U5）的中间操作见各 needs/<id>/README.md，然后：
bash evals/user-needs/run_need.sh --followup <need-id> <variant> <run-name> [model]

# 评分（live：finish_round → activities → verify）：
bash evals/user-needs/grade_need.sh <need-id> <run-name>

# 评分（offline：从留存证据干跑，不触碰集群、不污染证据目录）：
bash evals/user-needs/grade_need.sh <need-id> <run-name> --offline <evidence-dir>
```

- run_need.sh 复用 e2e-neutral-streaming/run_round.sh 搭环境（RUN=~/entity-eval-runs/<run>，HARNESS=~/entity-eval-traces/<run>），再调 needs/<id>/setup.sh 铺场景 fixture，最后 headless 起 agent（prompt.md；--followup 时用 `claude -c` 续会话发 prompt-followup.md）。
- setup.sh 可通过写 `$RUN/prompt.rendered.md` 渲染最终 prompt（U6 用它注入数据根）。
- U5 的篡改步骤：`grade_need.sh U5 <run> --tamper`（改 agent 项目内文件，绝不碰留存证据）。
- 报告：live 写 `$HARNESS/need-report.json`；offline 写 `<evidence>/need-report-<need-id>.json`（新文件，不覆盖 oracle-report.json 等），并带 `mode: "offline"` 与 offline_note。
- offline 模式下 observer 的 run_dir 先复制到 /tmp 再跑 activities（该子命令会追加 events，不能直接对留存证据跑）。

## 文件布局

```
evals/user-needs/
├── SUITE.md                 # 本文件
├── run_need.sh              # 场景启动（含 --followup 两段式）
├── grade_need.sh            # 评分（live / --offline / --tamper）
├── lib/verify_common.py     # 公共库：oracle、sacct、router export、activities、
│                            #   schema 校验、transcript 扫描、ux 重算、报告组装
└── needs/<id>-<slug>/
    ├── prompt.md            # 用户请求（自然语言）
    ├── prompt-followup.md   # 两段式场景的第二段（U3/U4/U5）
    ├── setup.sh             # 场景 fixture / 操作提示
    ├── verify.py            # 场景核验（只看最终状态）
    └── README.md            # 意图、对照组、核验逻辑、已知边界
```
