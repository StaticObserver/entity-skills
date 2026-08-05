# e2e-streaming-official:官方 streaming PGen 版端到端对照评测

检验 0.7.0 skill 全流程（workspace → project/case → site 档案 → deps 注
册表 → build/run/data/analysis 的 record 原语链）在真实任务上是否可
用、可核验。与 `e2e-neutral-streaming`（历史记录，不改）的关系：

- **任务**:pgen 创作环节消失——用官方 `streaming` PGen(`compile.pgen`
  指定，禁止改源码）；交付物为 `docs/design.md`（参数依据）+ TOML +
  分析 + submission.json。任务显式要求走 0.7.0 全流程。
- **站点**:m87(RTX 4070 Ti,scheduler=none,direct 后端，deps 全套已
  验证）。m87 的 site 档案用 legacy roots（无 site_root)。
- **oracle**：五道门同构适配。B 门改为官方 PGen 指纹（钉住
  source-cache 里 `streaming/pgen.hpp` 的 sha256，防 agent 改写官方
  pgen)+ TOML/spec 一致性 + submission schema;C 门走 direct 后端
  (exit file 证据，m87 无 Slurm);D 门物理判据结构继承，**阈值全部
  pending-gold-run**。
- **harness**：沿用 Claude Code headless + skill_observability 的 A/B 框
  架（skills-v5 vs skills-no-router，自变量是 entity-ledger 在场与否）。

## 目录

```text
task.md                        # 发给被测 agent 的任务文本
physics-spec.json              # 冻结的物理语义(two-stream,官方 streaming)
fixtures/submission.schema.json
oracle_streaming/            # 独立复核(五道门 + thresholds.json)
run_round.sh                   # 开一轮(建目录、注册 trace、启动 agent)
finish_round.sh                # 收尾(快照、导入 transcript、关 trace)
clean_remote.sh                # 远端清理(dry-run 默认,-f 执行)
RUNBOOK.md                     # 运行手册(唯一设置文档)
```

## 运行步骤（gold run / 实校时）

1. m87 开机，确认 `ssh m87` 与技能投影状态（S/N 组按 RUNBOOK 表）。
2. `run_round.sh skills-v5 <run-name> [model]` 开跑 → agent 完成后
   `finish_round.sh <run-name> completed`。
3. oracle 复核：`oracle_streaming/oracle.py --project <run>/project --fetch <data>`。
4. `clean_remote.sh <run-name> -f` 清理远端，归档 summary.json。

## 待 gold run 清单（本轮未做，m87 关机）

- **TOML 参数校准**:physics-spec 的 cells=128/ppc=32/drift=±0.2 沿
  neutral 组量级（4070 Ti 验证过）,`final_time=50.0` 与 CFL=0.5 是暂
  定值——用 gold run 确认不稳定增长在 walltime 预算内可观测量。
- **Gate D 阈值冻结**:thresholds.json 现为 neutral 结构占位；gold run
  后重写漂移/电场/E² 的期望带（two-stream 是增长物理，不是守恒）。
- **seed 语义确认**：官方 streaming pgen 是否暴露 seed 入口，若无则在
  gold run 记录有效默认值并改 spec 注释。
- **实测 oracle 五门**:B/C/D/E 门目前只有单测覆盖（纯函数），首次实
  跑需人工核对 oracle-report.json 各 check 的合理性。
