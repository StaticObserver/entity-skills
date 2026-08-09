# E2E 对照测试 Runbook（官方 streaming pgen 版，轻量 A/B)

一个任务、两种条件、每轮三条命令。本文件是唯一设置文档。

## 任务规定（随任务文本发给被测 agent)

按 `task.md` 和 `physics-spec.json`（本目录）完成 Entity 模拟全流程。
**agent 拿到的是脱敏 spec**:`run_round.sh` 用 `redact_spec.py` 从完整
physics-spec.json 生成——去掉 `resources` 里的分区/gres/QoS/分析分区
（自发现考察点），保留物理、编译契约与资源预算；oracle 判分始终用仓
库里的完整 spec(`oracle.py --spec` 默认值）。
与 e2e-neutral-streaming 的核心差异：**PGen 创作环节消失**——指定
`compile.pgen=streaming`（官方 PGen，不得修改其源码），交付物变为
`docs/design.md`（参数选择依据）+ 输入 TOML + 分析 +
submission.json。任务显式要求走 0.7.0 全流程：

1. `workspace init/adopt` + `project/case init`;
2. 已登记的 `astro-streaming` site 档案（0.7.0 site_root 新树）+
   `site sync`;`site deps astro-streaming` 查询复用既有 verified 栈，
   新栈才 `deps-add`;
3. TOML + `docs/design.md`;clean build（CUDA、单卡、无 MPI）+
   `record build`——**编译也必须走 Slurm CPU-only 作业**(mgmt 登录节点
   禁止重活）;
4. `render-run` → `record run-prepare` → `record run-launch`(Slurm
   sbatch 提交）→ `record run-exit`（恰好一次 run，等到终态）;
5. `record data` 盘点；nt2py 分析；`record analysis`（脚本进项目
   `analysis/scripts/` 库，产物目录带 `analysis-manifest.json`);
6. 符合 `fixtures/submission.schema.json` 的 submission.json。

站点与约束：

- 服务器：`ssh astro`(Slurm 集群，登录节点只做轻量文件操作，编译/
  模拟/分析全部走调度器；分区、GPU、QoS、工具链由 agent 自行探索）;
- 资源上限：1 GPU / walltime ≤ 10 分钟；数据分析只用 CPU;
- 源码与依赖：agent 自行发现（路径不进任务文本；astro-streaming 既有
  verified 依赖栈这件事由 agent 通过 `site deps` 自查）;
- 不使用公网；不修改只读依赖、冻结源码与**官方 PGen 源码**;analysis
  不写入 raw-data root；凭据不进入任何文件；
- 完成标准：run 正常终态、≥2 个时刻的 fields/particles 可读、分析结
  论与双流不稳定的物理预期一致。

## 两个变体

| | S：`skills-v5`（完整 bundle） | N：`skills-no-router`（仅无 entity-ledger） |
|---|---|---|
| Entity skills | `entityctl install` 发布当前 bundle(0.7.0rc) | `~/.claude/skills/` 下 entity-* 投影临时移走 |
| 模型 / 任务文本 / shell·ssh 工具 | 相同 | 相同 |
| 会话 | 新会话、空历史 | 新会话、空历史 |
| 工作区 | 独立项目目录（agent 自建 workspace） | 独立项目目录（不用 Ledger） |

## 每轮命令

```bash
# 开跑（建目录、注册 trace、启动 agent;启动前校验技能投影状态:
# S 组要求 entity-ledger 在场,N 组要求仅 entity-ledger 已移走——
# 不满足则拒绝启动。0.7.0 起不再预置 controller home,workspace 由
# agent 按 task.md 自建)
evals/e2e-streaming-official/run_round.sh skills-v5 2026-08-XX-S1 [model]
evals/e2e-streaming-official/run_round.sh skills-no-router 2026-08-XX-N1 [model]

# 收尾（先快照 project 产物到 traces/<run>/project-snapshot/,再导入
# transcript、阶段切分、关闭 trace;重复执行检测到 terminal event 直接跳过)
evals/e2e-streaming-official/finish_round.sh 2026-08-XX-S1 completed

# 远端清理（先拉 *.sbatch/slurm-*.out/*.log/manifest 到
# traces/<run>/remote-logs/,默认 dry-run,-f 才删除远端 run 目录,
# 最后 squeue/sacct 确认无残留作业)
evals/e2e-streaming-official/clean_remote.sh 2026-08-XX-S1 -f
```

监控是带外的：切分与统计全部在运行结束后离线进行，agent 的工具调用路
径上没有任何探针，skills 不知道监控存在。

## Oracle 独立复核

`finish_round.sh` 之后运行（不信任 agent 自报，从外部事实重验）:

```bash
python3 evals/e2e-streaming-official/oracle_streaming/oracle.py \
  --project ~/entity-eval-runs/<run>/project \
  --transcript ~/.claude/projects/<project-slug>/<session>.jsonl \
  --fetch ~/entity-eval-traces/<run>/oracle-data
```

产出 `<project>/oracle-report.json`，总体 fail > unknown > pass。五道
门：A 安全（transcript 扫描）、B 官方 PGen 指纹 + TOML/spec 一致性 +
submission schema、C Slurm 作业事实（sacct:job id 存在且恰好一条记
录、终态/exit code、资源与 Elapsed 对账、gres 上限；direct 分支保留
供 m87)+ 数据可读、D 物理（阈值见下）、E 分析可复现。`--site` 默认
astro。

## ⚠️ Gate D 阈值未冻结（pending gold run)

`oracle_streaming/thresholds.json` 目前是从 neutral-streaming 复制的**结构性占位**
（标 `"calibration": "pending-gold-run"`)：双流不稳定会热化漂移、增长
电场，与中性对照的物理方向相反，现有数值（漂移守恒上限、E² 噪声上限）
**不是**物理预期。在 gold run 产出前，oracle 的 D 门结果只作参考，不
得用于判轮。待 gold run 后：冻结 TOML runtime 参数、重写 D 门阈值为
gold 观测带（含增长带方向）。

## 每轮归档

轮次结束后把 `summary.json` 放进该轮目录：变体、模型、开始/结束时间、
wall-clock、input/output token、run_id、完成与否、一句话结果；agent 最
终自报摘要（原文，可放 `agent-summary.md`)。
