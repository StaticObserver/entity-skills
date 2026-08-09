# e2e-streaming-official:官方 streaming PGen 版端到端对照评测

检验 0.7.0 skill 全流程（workspace → project/case → site 档案 → deps 注
册表 → build/run/data/analysis 的 record 原语链）在真实任务上是否可
用、可核验。与 `e2e-neutral-streaming`（历史记录，不改）的关系：

- **任务**:pgen 创作环节消失——用官方 `streaming` PGen(`compile.pgen`
  指定，禁止改源码）；交付物为 `docs/design.md`（参数依据）+ TOML +
  分析 + submission.json。任务显式要求走 0.7.0 全流程。
- **站点**：新登记 `astro-streaming`(`ssh astro`,Slurm 集群，gpu1 的
  V100S-32GB;0.7.0 site_root 新树 `~/entity-compute`,VOLTA70 deps 栈
  由 pilot 登记进注册表）。旧 m87 变体（direct 后端、legacy roots）保
  留在 gate C 的 direct 分支中。
- **oracle**：五道门同构适配。B 门改为官方 PGen 指纹（钉住
  source-cache 里 `streaming/pgen.hpp` 的 sha256，防 agent 改写官方
  pgen)+ TOML/spec 一致性 + submission schema;C 门走 Slurm sacct
  (job id 存在且恰好一条记录、终态/exit code、资源与 Elapsed 对账、
  gres 上限，teardown abort 从 slurm 日志独立确认后豁免；direct
  exit-file 分支保留供 m87);D 门为 two-stream 增长判据，**阈值已于
  2026-08-09 gold run 冻结**（增长率带、增长倍数、饱和、能量漂移、
  粒子数守恒）。
- **gold run(2026-08-09,pilot 自跑）**:`run-879cd51744bad483`(job
  357003,V100,Slurm elapsed 2s),oracle 五门 overall pass;ledger
  status 六格全绿。
- **harness**：沿用 Claude Code headless + skill_observability 的 A/B 框
  架（skills-v5 vs skills-no-router，自变量是 entity-ledger 在场与否）。

## 目录

```text
task.md                        # 发给被测 agent 的任务文本
physics-spec.json              # 冻结的物理语义(two-stream,官方 streaming;含 astro Slurm 细节,仅供 oracle)
redact_spec.py                 # 生成 agent 侧脱敏 spec(去掉分区/gres/QoS 等自发现答案)
fixtures/submission.schema.json
oracle_streaming/            # 独立复核(五道门 + thresholds.json)
run_round.sh                   # 开一轮(建目录、注册 trace、启动 agent)
finish_round.sh                # 收尾(快照、导入 transcript、关 trace)
clean_remote.sh                # 远端清理(dry-run 默认,-f 执行)
RUNBOOK.md                     # 运行手册(唯一设置文档)
```

## 运行步骤（gold run / 实校时）

1. 确认 `ssh astro` 可用、gpu1 空闲（`ssh gpu1 nvidia-smi`）与技能投影
   状态（S/N 组按 RUNBOOK 表）。
2. `run_round.sh skills-v5 <run-name> [model]` 开跑 → agent 完成后
   `finish_round.sh <run-name> completed`。
3. oracle 复核：`oracle_streaming/oracle.py --project <run>/project --fetch <data>`
   (`--site` 默认 astro)。
4. `clean_remote.sh <run-name> -f` 清理远端（squeue/sacct 确认无残留），
   归档 summary.json。

## 校准状态（阶段 0–2 已完成，2026-08-09)

- **TOML 参数**:cells=128/ppc0=32/drift=±0.2/final_time=50/CFL=0.5 经
  gold run 验证——双流增长从噪声底 4.8e-7 到峰值 3.4e-3,t≈13.8 饱和，
  单场 V100 计算 ~1s(Slurm elapsed 2s),walltime 预算极其宽裕。
- **Gate D 阈值已冻结**:two-stream 增长判据（增长率带 [0.08,0.20]、
  增长倍数 ≥1e3、t_final 前饱和、能量漂移 ≤1%、粒子数严格守恒），依
  据见 thresholds.json 的逐条 calibration 注记。
- **seed 语义**：官方 streaming pgen 无 seed knob，有效默认即内核全
  局序列；spec 已注明（random_seed.calibration=resolved-gold-run)。
- **oracle 五门已实测**:pilot gold run 自判 overall pass;A 门在
  pilot 用空 transcript（虚过），正式轮由 agent transcript 实质扫描。
