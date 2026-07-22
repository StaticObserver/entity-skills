# E2E 评测配置问题与修复方案（S1 + Snr1 复盘）

范围：2026-07-21 S1（skills-v5）与 2026-07-22 Snr1（skills-no-router）两轮中，
**评测装置本身**（task 契约、fixtures、监控切分、oracle、归档流程）暴露的问题。
技能侧问题见姊妹篇 `skill-review-2026-07-22.md`。诊断原始记录见
`findings-2026-07-22.md`。

## A. 任务契约缺口（影响公平性，优先级最高）

### A1. submission schema 只随 router 技能存在

- 现象：task.md 要求 submission.json "conforms to the supplied schema"，但
  fixtures 里没有 schema 文件。S1（装 router）拿到了 router 契约里的 schema 并
  符合；Snr1（无 router）只能自创布局（`output.data_root` vs `run.data_root`）。
- 后果：schema 符合度这一指标实际度量的是"装没装 router"，而不是 agent 能力；
  对 no-router / N 组不公平，且会让 oracle 解析失败。
- 修复（二选一，需用户定夺）：
  1. 把 `submission.schema.json` 作为 fixture 放进 project 目录，task.md 改为
     指向该文件——schema 符合度成为对所有组公平的指标；
  2. 维持现状，但在评分口径里明确"schema 符合度"是 router 的技能效果，oracle
     解析层保持容错回退（已加 `output.data_root` 回退）。

### A2. "requested analysis" 没有定义，E 门要求从未告知 agent

- 现象：task.md 说"perform the requested field and particle analysis"、"write
  all required artifacts"，但 task.md 和 physics-spec.json 都没有说明要分析
  什么、交付什么。Gate E 却按"有分析报告文件 + 有可重跑脚本"评分。S1 交了
  report 没交脚本，Snr1 两样都没有——它们考的其实是 agent 没收到过的要求。
  （router 契约里有这些要求，所以这又是一条隐性技能依赖。）
- 修复：在 task.md 中明确分析交付物清单，例如：
  `analysis/report.md`（结论 + 证据）与 `analysis/analyze.py`（可对数据根目录
  重跑的脚本）。 oracle 的 Gate E 与该清单逐条对应。

### A3. 粒子输出 stride 无上限

- 现象：S1 agent 把 stride 设为 100（gold run 为 10），每 species 仅 ~20 个宏
  粒子进入分析，ux 漂移结论证据力弱；Snr1 stride=10（每 species 204 个）。
  physics-spec 未约束。
- 修复：physics-spec 增加 `output.particle_stride_max`（如 20），或 thresholds
  增加"最少分析粒子数"指标（建议 ≥ 每 species 100）。

### A4. "分析用 CPU" 边界含糊

- 现象：task.md 只说"Use CPU resources for data analysis"，未明确登录节点跑
  nt2py 是否违规、交互式 srun 是否算合规。Snr1 用交互式 srun 跑分析（3 次
  尝试），S1 方式不同，Gate A/C 难以一致裁量。
- 修复：task.md 明确"分析也不得在登录节点进行，须通过批处理或交互式 CPU
  作业"，并把它纳入 Gate A 检查词表。

## B. 证据链与归档缺陷

### B1. S1 的 project 产物在复核前被清理（已造成不可逆损失）

- 现象：S1 轮按流程清理了 agent 产物，input.toml / pgen.hpp / submission.json
  未归档。Snr1 物理失败（ux -40%、E² 超 20 倍）后想做 S1-vs-Snr1 根因对比
  （两轮同 spec、同 seed、同精度，结果迥异），S1 的 pgen 已不可考，对比只能
  止步于"注入实现路径不同"。
- 修复：`finish_round.sh` 增加归档步骤——收尾时把 project 下的
  `input.toml`、`pgen.hpp`、`submission.json`、`docs/`、`analysis/`（如有）
  复制进 `~/entity-eval-traces/<run>/project-snapshot/`，清理动作必须在快照
  之后。

### B2. 远端日志拉取与清理是手工步骤

- 现象：Snr1 的关键证据（12 次构建作业、7 次模拟提交、3 次分析作业的 slurm
  脚本与日志）靠手工 scp 归档，`~/entity-run` 手工删除。漏拉即丢证据。
- 修复：新增 `clean_remote.sh <run-name>`（或 finish_round 加 `--clean-remote`
  选项）：先按 submission.json 的 artifacts 段 + 远端 run 目录通配拉取日志到
  traces，再删除远端产物目录，最后 `squeue` 确认无残留作业。

### B3. 轮次间环境污染面没有开跑前校验

- 现象：S2 污染事件（agent 经 trace 文件摸到含 gold run 答案的开发仓库）已从
  架构上修复（harness 状态移出 agent 可及目录），但仍有三处残留面：
  1. `~/entity-eval-runs/` 里上一轮未清理的 run 目录（agent 可 `ls ..` 看到）；
  2. 本地 `~/.claude/projects/` 里上一轮 session transcript（不同 slug，但
     agent 理论上可读）；
  3. siyuan `~/.bash_history` 可能含上一轮的资源探索命令（未核实，有意未读）。
- 修复：`run_round.sh` 增加开跑前自检——`~/entity-eval-runs/` 必须为空、
  打印上一轮 session 残留警告；在 RUNBOOK 里写明每轮结束后清理本地
  `~/.claude/projects/<slug>` 与（如决定处理）远端 history。transcript 污染
  扫描词表补充 `entity-eval-runs`（跨轮引用）。

## C. 监控与切分

### C1. sbatch 提交的编译作业计入 run 阶段

- 现象：S1 的 run 阶段 40 min、Snr1 的 105 min 里都含构建/探测作业（Snr1 有
  12 次构建类 sbatch）。run 阶段时长因此高估，env-build 低估。
- 修复：切分规则按 sbatch 作业名/脚本内容区分 build 类与 sim 类（如作业名含
  build/rebuild/kk/deps 或脚本调 cmake/make 的归入 env-build）。

### C2. pgen 阶段切不出来（阶段只前进）

- 现象：Snr1 的 agent 在 env-build 信号出现后才写本地 pgen.hpp，pgen 阶段
  0 条记录，工作量并入 env-build。
- 修复：允许"本地写 pgen.hpp/docs 设计文档"在任何时刻重标为 pgen（写本地
  文件不产生外部效应，回退安全）；或不改规则、在 phases.json 里加注记。倾向
  前者，改动小。

### C3. finish_round 幂等性瑕疵与过期警告

- 现象：Snr1 收尾时打印一次 "cannot append an event after the terminal event"
  （重复 finish），随后又成功；同时打印了 comparable=false 警告，但最终
  phases.json 里 comparable=true（警告取自第一遍结果）。
- 修复：finish 前检测 terminal event 已存在则跳过；警告改为读取最终落盘的
  phases.json。

### C4. 缺少作业生命周期计数指标

- 现象：router 的核心价值主张是作业管理，但 phases.json 只有阶段时长/token，
  看不出"提交 7 次才成功 1 次"这类关键对比点（本轮靠人工数远端日志）。
- 修复：切分器增加计数器——sbatch 提交次数、squeue/sacct 轮询次数、按作业名
  分组的提交序列，写进 phases.json 的 run 阶段小节。

## D. Oracle（复核器）

### D1. Gate B 的 TOML 布局脆弱（待修，已记录）

- Snr1 的合法替代布局导致 4 项假 fail：小写 `engine = "srpic"`、无显式
  `particles.nspec`（Entity 从 `[[particles.species]]` 数组推导）、drift 与
  temperature 收在 `[setup]` 自定义段。修复：engine 大小写归一；nspec 缺省时
  取数组长度；drift/temperature 支持 per-species 与 `[setup]` 两种来源。
  （只改解析不改阈值，符合"不因单轮结果回调阈值"原则。）

### D2. Gate D 只看末快照、无样本量下限

- ux 漂移仅用最后一个快照的 stride 抽样均值；Snr1 数据显示漂移是全程渐变
  （0.199 → 0.12），末快照单点既丢信息也对抽样噪声敏感。
- 修复：改为"全程每快照 |mean_ux - 0.2|/0.2 的最大值"，并结合 A3 的最少粒子
  数指标。

### D3. 已修复项（记录）

- `run.data_root` 缺失时回退 `output.data_root`（Snr1 触发，已修，65 项测试
  全过）；
- `2>&1`/`2>/dev/null` 误判为文件写入（S1 前修复）；
- sacct NTasks 空值按 unknown 处理（S1 前修复）。

## E. 已修复的架构级问题（记录，防回归）

- **S2 污染事件**：trace manifest 的 `--skill` 仓库路径经 `run_dir.txt` 泄漏给
  agent。修复：脚本不传 `--skill`、harness 状态全部移出 agent 可及目录；任何
  写入 agent 可及目录的文件不得含仓库路径/评测内部信息。
- **切分误匹配三连**：工具输入正文误匹配（改为只匹配命令与路径目标）、读
  `.claude/skills/` 文档误触发阶段迁移（改为只计数）、`squeue`/`sinfo` 误触发
  run 阶段（run 只认 sbatch / entityctl）。

## 修复优先级建议

1. A1、A2（契约公平性，直接影响下一轮的指标有效性）
2. B1、B2（证据链，防止 S1 式不可逆损失重演）
3. C4、C1（router 价值的关键度量）
4. D1、D2（oracle 假阳性/判据加固）
5. A3、A4、B3、C2、C3（打磨项）
