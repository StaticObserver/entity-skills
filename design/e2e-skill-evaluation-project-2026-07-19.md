# Entity Skills 端到端对照评测项目

日期：2026-07-19  
状态：第一阶段已实现，等待 gold run  
修订：2026-07-21 起任务契约与过程监控以 `e2e-skill-evaluation-revision-2026-07-21.md` 为准

## 1. 目的

这个项目不评测 Agent 是否“会说 Entity”，而是评测它能否把一个小型、真实、可验证的
模拟任务完整做完：

```text
环境确认与构建 → PGen/TOML → Entity 编译 → Slurm 作业 → 输出核验 → nt2py 分析
```

同一个冻结任务分别交给：

- `S`：安装指定版本 Entity skills 的 Agent；
- `N`：没有任何 Entity skill 的同模型 Agent。

两组使用相同模型、任务、工具权限、源码版本、计算站点、资源预算和验收器。差别只能是
Entity skills 是否暴露。最终同时看结果、过程、安全性和成本，不以主观观感代替证据。

## 2. 核心原则

评测保持四条简单规则：

1. **一个任务**：两组收到完全相同的 `task.md`。
2. **两种条件**：只改变 Entity skills 的暴露状态。
3. **一套裁判**：独立 oracle 直接检查源码、build、scheduler、raw data 和分析产物。
4. **先正确再高效**：安全与物理正确性是硬门，不能用速度或 token 抵消。

不抓取隐藏思维链。只记录可观测工具调用、简短决策、外部状态、产物指纹和验证结果。

## 3. 测试实例：Neutral Streaming Equilibrium

### 3.1 为什么选它

首个实例采用一维周期边界的中性正负电子等离子体匀速平衡态。它足够真实，覆盖场、粒子、
随机种子、输出和粒子分析；又足够简单，理论预期明确、计算便宜、错误容易归因。

不选重联、湍流或黑洞吸积作为第一项。那些问题更有科学趣味，但会把物理建模误差、随机涨落、
计算资源和工作流质量混在一起，难以判断 skill 本身是否改善了执行。

### 3.2 冻结的物理语义

PGen 暂定名为 `neutral_streaming`，基于 Entity v1.4.4 的 SRPIC/Minkowski/Cartesian
接口实现，但必须形成独立的 `docs/design.md + pgen.hpp + TOML` 一致单元。

| 项目 | 冻结值 |
|---|---|
| 维度与边界 | 1D，`x ∈ [0, 16]`，场和粒子均为周期边界 |
| 网格 | 128 个 active cells |
| 组分 | 等质量、相反电荷、等密度的正负电子 |
| 粒子数 | 每个 species 每格 32 个宏粒子 |
| 温度 | `T = 1e-3` |
| 漂移 | 两个 species 都为 `u = (0.2, 0, 0)` |
| 初始场 | `B = (1, 0, 0)`，`E = (0, 0, 0)` |
| 随机性 | 固定 seed，写入 TOML 和结果 manifest |
| 编译 | CUDA、single、zigzag、shape order 1、output ON、MPI OFF |
| 资源 | 1 node、1 GPU、1 task、最长 10 分钟 |

两个 species 具有相同的空间分布和漂移，电荷与电流在总体上相消；漂移平行于均匀磁场，
不存在横向洛伦兹力。因此预期解接近平稳：粒子数不变，平均漂移不变，均匀磁场保持不变，
电场只包含有限粒子数和离散化带来的小涨落。

正式运行步长、终止时间和输出间隔不在此处猜测。维护者先完成一次 gold run，根据实际
Entity 稳定性约束固定这些值；固定后不得根据 `S/N` 结果回调。

### 3.3 必须输出的结果

Agent 必须产出：

- PGen：`docs/design.md`、`pgen.hpp`、输入 TOML；
- 环境：`requirements.json`、`entity-deps.local.json`、`env.sh`、`entity-build.sh`；
- 构建：完整 build log、`entity.xc` 的 SHA-256 和 source identity；
- 运行：job ID、submission receipt、terminal scheduler state、run manifest 和 raw-data Locator；
- 分析：可重跑脚本、`analysis/report.json`、简短 `summary.md`、场与粒子图；
- 总结：公共 `submission.json`，只包含结构化 Locator、identity、状态和指纹。

`submission.json` 是两组共同的交付接口，不要求 no-skill Agent 模仿 Router 内部对象。

## 4. 完整环境构建如何测试

环境构建分两种模式，避免每轮都被依赖下载和集群波动淹没。

### 主实验：warm dependencies, cold Entity build

站点提供一套只读、版本已知但没有预先注入 shell 的 Kokkos/ADIOS2/HDF5/CUDA 依赖。
每个 Agent 仍必须独立完成：

```text
站点探测 → 依赖选择 → checkpoint → compatibility → env.sh → 全新 Entity build
```

源码 checkout、build root、run root 和 analysis root 每轮都是新的。这个模式适合重复对照，
也覆盖了完整的环境决策、兼容性收束和 Entity 编译链。

### 冷启动资格测试：cold dependencies, cold Entity build

在主实验稳定后，再做一组 `S/N` 配对：给定空的 dependency root，允许从已冻结的本地
source cache 构建依赖，禁止依赖公网可用性。它检验真正的 dependency source-build，但不
作为第一轮多次重复项。

两个模式都必须固定 Entity `v1.4.4` tag 解析出的 exact commit、依赖版本族、CUDA 架构和
nt2py `v1.5.3`。所有版本在试验 manifest 中记录内容指纹。

## 5. 公平对照

### 5.1 唯一实验变量

| 条件 | `S: skills-v5` | `N: no-entity-skills` |
|---|---|---|
| 模型与 reasoning 配置 | 相同 | 相同 |
| 用户任务文本 | 相同 | 相同 |
| 通用 shell/SSH/git 工具 | 相同 | 相同 |
| Entity 源码与官方文档 | 可访问 | 可访问 |
| 远端站点与资源预算 | 相同 | 相同 |
| Entity skills | 固定 bundle，全部可用 | 不安装、不挂载、不可检索 |
| 当前会话历史 | 新会话、空历史 | 新会话、空历史 |

`S` 使用仓库 v5 commit 的隔离安装，不能使用当前机器仍指向 v3 的 live bundle。`N` 的
workspace 不挂载本仓库和历史 Entity skill 目录，防止通过全文搜索意外读到答案。

### 5.2 每轮隔离

每轮使用独立的：

- local project/worktree；
- Router home（`S`）或普通 state root（`N`）；
- observability trace home；
- remote source/build/staging/run/analysis roots；
- Slurm job name 前缀与随机 run ID。

共享依赖只能只读复用。任何一组都不能看到另一组的源码修改、日志、分析报告或 oracle
判定。

### 5.3 重复与顺序

建议顺序：

1. oracle gold run：维护者执行一次，不计入比较；
2. pilot：`S/N` 各一次，修正评测基础设施，不修改冻结任务；
3. formal：至少 3 个配对重复，随机采用 `S→N` 或 `N→S`；
4. cold-dependency qualification：`S/N` 各一次；
5. recovery extension：基础实验稳定后再加入，不与首轮混算。

Slurm 排队时间单独报告，不计入 Agent 执行效率；编译、运行和分析时间分别记录。

## 6. 独立验收器

Agent 的“已完成”只是声明。oracle 从 owner artifact 和外部事实重新验证。

### Gate A：工作区与安全

- 所有写入都位于本轮允许根；
- 无凭据进入日志、TOML、脚本或 Git diff；
- 未修改只读依赖和输入 source cache；
- 没有重复提交同一 run，也没有运行中的遗留 job；
- analysis 不写 raw-data root。

任一失败即本轮无效，不再以效率指标补偿。

### Gate B：PGen 与构建

- `docs/design.md`、`pgen.hpp`、TOML 的物理参数与命名一致；
- source identity 包含 tracked、modified 和 untracked 内容；
- environment checkpoint 与本轮 site/backend/output/MPI 要求一致；
- compatibility 为可证明的 pass；
- clean build 成功，`entity.xc` 存在且指纹已记录；
- executable 指纹与实际运行 manifest 一致。

### Gate C：作业与数据

- scheduler 只存在一个匹配 job；
- job 正常终止且 exit code 为零；
- run manifest、input、executable、job ID 和 raw-data Locator 构成同一 identity chain；
- nt2py 能从正确 data root 读取至少两个时刻的 fields 和 particles；
- 输出中无 NaN/Inf，时间和 step 单调增加。

### Gate D：物理正确性

oracle 不采用 Agent 自报的数值，而是独立读取 raw data。第一版检查：

- 两个 species 初末粒子数相等且各自保持不变；
- 最终平均 `ux` 相对初始值的变化在冻结容差内；
- 体平均 `Bx` 和磁场能量保持在冻结容差内；
- 生成的 `E²`、净电荷和净电流不超过冻结噪声上限；
- 总能量漂移不超过冻结容差。

容差由 gold run 和一组数值分辨率复核产生，并在打开 `S/N` 结果前写入
`oracle/thresholds.json`。容差必须有物理量定义、归一化和计算公式，不能只保存一个神秘数字。

### Gate E：分析可重现性

- analysis script 在干净 Python 环境中可再次运行；
- 使用 nt2py 的实际 inventory，不凭 PGen 名称猜变量；
- 先选择 timestep/species/columns，再加载粒子数据；
- 报告值与 oracle 独立计算在舍入误差内一致；
- 图与报告写在 analysis root，不污染 raw data。

## 7. 怎样看 skill 的工作过程

现有 `tools/skill_observability` 作为统一 collector，记录：

```text
orient → pgen → env/build → plan/apply/status → data/analysis → verify
```

每个阶段只采集：

- 暴露的 skill 名称、bundle revision 和 content hash；
- 可观测到的 SKILL/reference 读取；
- 每阶段最多一个简短结构化决策；
- 工具调用、返回状态、耗时和脱敏后的输出指纹；
- source/build/job/data/analysis artifact Locator 与 SHA-256；
- oracle 和 owner validator 的 pass/fail/unknown。

三种证据严格分开：Agent 声明是 `declared`，collector 看到行为是 `observed`，独立验证器
确认才是 `verified`。不把“skill 被安装”写成“skill 被使用”，也不记录隐藏推理。

### 当前必须先补的缺口

Router 已经使用 v5 Goal/Plan/Operation/Step，但 observability 的 Router evidence validator
仍只认识 v3 Action request/result。正式开跑前必须增加 `router-operation-v5` validator，至少
验证：

- Goal、Plan 和 plan hash；
- Operation/Step journal 与 owner-site receipts；
- source/build/run identity chain；
- launch effect 只有一个 scheduler job；
- 重复 Apply 复用 receipt 而不重复 `sbatch`；
- terminal Operation 与 Router status 一致。

旧 validator 保留给历史 v3 trace，不用兼容分支伪装成 v5 证明。

## 8. 结果如何比较

不使用一个混合权重的总分。结果按固定优先级展示：

1. **硬门是否全部通过**：安全、身份链、作业、数据、物理、分析；
2. **自主完成度**：完成阶段数、需要用户决策次数、是否需要人工救援；
3. **恢复能力**：中断后是否继续同一身份、是否产生重复副作用；
4. **执行成本**：模型原生 token、工具调用、失败调用、SSH 往返、有效工作时间；
5. **资源成本**：编译 CPU/GPU 时间、作业 GPU 秒、最大存储和输出规模。

报告同时给出每轮原始值和配对差值，不只给平均值。工具调用少不是天然更好；只有在前面
的正确性门全部通过后，效率差异才有意义。

## 9. Recovery 扩展

基础项目通过后，增加一个标准故障：scheduler 已接受提交，但 Controller/Agent 在提交结果
落盘前中断。恢复任务继续使用原 workspace 与外部状态。

核心判据只有三个：

1. 是否发现已有 job；
2. 是否保持同一 run identity；
3. 是否避免第二次提交。

这个扩展专门检验 Router v5 的 receipt/replay 价值，不和正常端到端成功率混成一个分数。

## 10. 建议的仓库结构

确认设计后新增：

```text
evals/e2e-neutral-streaming/
├── README.md
├── task.md
├── experiment.json
├── fixtures/
│   ├── physics-spec.json
│   ├── tool-profile.json
│   └── site-profile.example.json
├── oracle/
│   ├── thresholds.json
│   ├── validate_submission.py
│   ├── validate_physics.py
│   └── summarize_pairs.py
├── variants/
│   ├── skills-v5.json
│   └── no-entity-skills.json
└── tests/
```

站点用户名、认证信息和实际可写根不提交仓库，只由本地 runtime fixture 注入。冻结任务、
oracle 公式、schema 和脱敏后的结果可以提交。

## 11. 实施顺序

第一阶段只做评测基础设施，不提交真实作业：

1. 建立冻结 task/spec/schema；
2. 实现公共 `submission.json` validator；
3. 给 observability 增加 v5 Operation evidence；
4. 用假数据和 fake scheduler 跑通两组 trace 与 oracle。

第二阶段执行 gold run，冻结 TOML 的数值参数和物理容差。

第三阶段先做一组真实 `S/N` pilot。只有隔离、trace、oracle 和清理都可靠后，才启动 3 组
formal 配对。最后再做 cold-dependency 和 recovery 扩展。

### 第一阶段实现记录

已在 `evals/e2e-neutral-streaming/` 建立共同任务、physics/tool/site fixtures、两组
variant、公共 submission schema、scheduler snapshot schema、submission oracle、fail-closed
physics oracle 和 file-backed fake Slurm。`tools/skill_observability` 已增加
`evidence router-operation`，核验 v5 Plan hash、Operation/Step、三份 receipt、controller
status 与独立 scheduler snapshot，并拒绝重复匹配 job。

本地测试使用真实 Router v5 planner/apply/status 驱动 fake Slurm，证明重复 Apply 只产生一个
job；同时验证公共 submission 的产物漂移检测和 gold run 前的正式执行门禁。尚未固定或执行
真实 Entity source/build/run，也未触碰 live controller。

## 12. 这项评测会回答什么

它最终能清楚回答：

- skills 是否提高端到端成功率和物理正确性；
- Router 是否真正减少状态混乱、重复提交和恢复成本；
- PGen/env-build/nt2py 的合同是否减少返工与错误调用；
- skills 的上下文成本是否换来了更少的工具往返和人工介入；
- 当前 v5 只自动化 run Goal，PGen/build/analysis owner handoff 是否仍是主要摩擦点。

最后一项尤其重要：这个项目不仅验证优化是否有效，也会直接指出下一轮应该简化哪个交界面。
