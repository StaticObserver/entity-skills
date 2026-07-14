# `entity-case` Skill 设计

日期：2026-07-11

归档状态：该方案已放弃。当前架构改用 `entity-pgen`、`entity-env-build`、`entity-simulator`、`entity-debug` 和 `entity-analysis` 协同完成具体 case，不参与后续设计上下文。

## 定位

`entity-case` 帮助用户继续开发和使用一个 Entity simulation case。

它处理 PGen、TOML 以及二者直接关联的运行信息。用户可能从一句想法开始，也可能带着已有 PGen、上次未完成的设计、可以直接运行的 case，或者一个失败的 run 进入。skill 不假设固定起点，也不要求把任务补成完整科研项目。

典型请求包括：

- “在这个 PGen 里增加一种粒子注入方式”；
- “按照上次的设计继续写边界条件”；
- “帮我检查 PGen 和 TOML 是否一致”；
- “修改网格和输出频率”；
- “这个 case 能不能在当前 Entity checkout 里编译？”；
- “用现有 executable 跑一下”；
- “从这个 checkpoint 继续跑”。

`entity-case` 不负责构建依赖、修改 Entity engine 或分析 simulation 的物理结果。这些任务分别交给 `entity-env-build`、`entity-core-dev` 和 `entity-analysis`。

## 核心原则：先识别状态，再继续工作

`entity-case` 没有统一的线性流程。Agent 接手后先读取用户指定的 workspace、当前 Entity checkout 和与请求相关的文件，形成一个当前状态快照，然后只处理用户目标涉及的部分。

状态由六个彼此独立的维度组成：

| 状态维度 | 可取值 | 含义 |
|---|---|---|
| `source` | `located` / `uncertain` | 当前 Entity checkout、版本和 case 位置是否明确 |
| `case` | `absent` / `partial` / `present` | PGen、TOML 或设计材料是否存在 |
| `contract` | `unchecked` / `conflicted` / `consistent` | PGen 与 TOML 的相关部分是否已经核对 |
| `build` | `unknown` / `missing` / `stale` / `ready` | 是否存在与当前 case 匹配的 executable |
| `run` | `none` / `prepared` / `running` / `completed` / `failed` / `stopped` | 当前 run 的状态 |
| `decisions` | `clear` / `open` / `blocked` | 当前任务所需的关键决定是否足够 |

这些状态不是一条必须走完的流水线。例如：

- 只解释一段 PGen 时，可以是 `contract: unchecked`、`build: unknown`、`run: none`；
- 修改已有 TOML 时，可以是 `case: present`、`build: stale`，但不需要创建 run；
- 继续上次设计时，可以是 `case: partial`、`decisions: open`；
- 直接续跑时，可以是 `case: present`、`build: ready`、`run: stopped`。

状态默认由 Agent 从文件和日志中临时重建，不要求用户维护额外的状态文件。只有真正运行 simulation 时，才用 `run-manifest.yaml` 持久化运行身份和状态。

## 如何识别状态

Agent 只检查与当前请求有关的证据，不做无目的的全仓扫描。

### `source`

检查：

- 用户指定的是哪个 Entity checkout；
- checkout 的 commit、版本和工作树状态；
- case 在哪里，是否存在多个同名副本。

找不到唯一 checkout 或 case 时设为 `uncertain`。在写代码前必须解决会导致修改错目录的歧义。

### `case`

检查已有的：

- `pgen.hpp`；
- TOML；
- 设计说明、上次会话留下的 TODO 或未提交修改；
- 用户指出的参考 PGen。

只有部分材料时设为 `partial`。这不是错误，Agent 可以从已有部分继续。

### `contract`

只核对本次任务影响的契约面：

- PGen traits 与 TOML 中的 engine、metric、维度；
- `params.get` 与 `[setup]`；
- species 数量、顺序、质量、电荷和索引；
- grid、scales 和 boundaries；
- source、force、custom output 与相应配置；
- 特殊算法需要的编译选项。

没有检查过就是 `unchecked`，不能因为文件能解析就记为 `consistent`。修改 PGen 或 TOML 后，受影响的契约面重新变成 `unchecked`；无关部分不需要全部重验。

### `build`

只有用户要编译、运行或判断可运行性时才检查：

- executable 对应的 Entity commit；
- 是否包含当前 PGen；
- backend、precision、MPI 和特殊编译选项是否匹配；
- PGen 或相关源码是否晚于构建产物。

无法证明匹配时为 `unknown`，已知不匹配时为 `stale`。需要重新构建就把明确的 build requirements 交给 `entity-env-build`。

### `run`

只有存在运行意图或运行证据时才识别。优先读取 scheduler 状态、进程状态、退出码、stdout、stderr、checkpoint 和输出，不根据聊天描述猜测。

### `decisions`

仅判断完成当前请求所必需的信息：

- 信息足够，或可使用无风险默认值：`clear`；
- 有未决定事项，但 Agent 仍能做草案、调查或其他局部工作：`open`；
- 缺少的决定会改变实现方向、物理含义或重大计算成本：`blocked`。

不要为了追求完整设计而询问与当前修改无关的科学问题。

## 根据用户需求行动

Agent 将“用户当前目标”与“状态快照”结合起来，选择最小动作。

| 用户目标 | 需要关注的状态 | 动作 |
|---|---|---|
| 解释现有 PGen/TOML | `source`、`case` | 读取相关实现并解释，不要求补 plan 或验证运行 |
| 继续上次设计 | `source`、`case`、`decisions` | 找到已有设计和改动，从未完成点继续 |
| 局部修改 case | `source`、`case`、`decisions` | 修改最小范围，并重验受影响的 contract |
| 从零创建 PGen | `source`、`case`、`decisions` | 只收集当前实现必需的信息，再生成 PGen/TOML |
| 检查配置 | `source`、`case`、`contract` | 报告具体冲突和证据，不自动扩展成完整 case 开发 |
| 编译当前 case | `source`、`case`、`contract`、`build` | 整理 build requirements，交给 `entity-env-build` |
| 运行 case | `source`、`case`、`contract`、`build`、`run` | 确认输入身份，创建 manifest，再启动或生成命令 |
| checkpoint 续跑 | `source`、`case`、`build`、`run` | 验证 checkpoint 和输入身份，创建新的 run 记录 |
| 修复失败 | `run` 加故障证据 | 只处理已归属于 PGen、TOML 或 launch 配置的问题；否则交给 `entity-debug` |

Agent 可以在一次任务中执行多个动作，但不自动把局部请求扩展成完整生命周期。例如用户只要求增加 `CustomStat`，完成代码、TOML 对应项和局部一致性检查即可，不应自动设计资源、编译和运行。

## 关键决定

Agent 应自行处理机械性和低风险选择，只把真正影响方向的问题交给用户。

需要确认的典型情况：

- 两种实现会表达不同的物理模型；
- normalization、坐标基或单位域无法从当前 case 确定；
- 修改会破坏已有 run 的可比性；
- 需要覆盖现有文件、输出或 checkpoint；
- 要提交昂贵的 GPU、多节点或长时间作业；
- 当前 Entity checkout 不支持需求，需要修改 engine。

不应阻塞的典型情况：

- 可以从现有 PGen/TOML 明确推断的命名和代码风格；
- 不影响物理意义的局部组织；
- 只读检查、草案和静态验证；
- 用户明确要求的局部改动中无关的未完成设计。

## PGen/TOML 是同一个 case contract

这是 `entity-case` 最重要的硬边界。修改一侧时，Agent 必须寻找另一侧是否存在对应关系，但只检查受影响部分。

最低检查规则：

| 修改内容 | 必须检查 |
|---|---|
| traits | engine、metric、dimension |
| `params.get` | `[setup]` 的 key、类型和默认行为 |
| particle injection | species 顺序、质量、电荷、温度、ppc 和 1-based index |
| fields 或 source | scales、单位域、坐标基和 engine 限制 |
| boundary hook | 每个方向的 TOML boundary |
| custom output/stat | TOML 中是否请求、名称是否一致 |
| higher-order feature | TOML 算法参数和 build option |

`consistent` 只表示检查范围内没有发现冲突，不表示物理模型已经被证明正确。

## 可选产物

产物按任务需要创建，不要求每个 case 都具备完整文件集。

### `simulation-plan.md`

仅在以下情况创建或更新：

- 从较模糊的想法设计新 case；
- 任务包含多个相互影响的物理或数值决定；
- 用户希望保存设计以便下次继续；
- 现有实现缺少足够的设计依据。

内容只记录当前有用的信息：已确认决定、当前假设、待办项和成功判断。未知部分可以缺省，不使用大而全的固定问卷。

### PGen 和 TOML

这是最常见的直接产物。保持用户现有目录结构；除非用户要求，不迁移到统一模板目录。

### 局部验证结果

简单任务直接在回复中报告检查结果。只有检查较多、需要复用或用户要求留档时，才写 `case-validation.md`。第一版不引入专用 validation schema。

### `run-manifest.yaml`

只有准备或执行实际 run 时才创建。至少记录：

- Entity checkout、commit 和 executable；
- PGen、TOML 及 hash；
- launch command、workdir 和资源；
- parent run 或 checkpoint；
- output、stdout、stderr；
- run 状态、时间、退出码和 scheduler job ID。

每次续跑创建新的 run 记录并引用 parent，不覆盖原 run。

## References 与工具

现有 `entity-pgen` references 继续作为 `entity-case` 的主要知识基础，并按功能加载：

- normalization；
- PGen skeleton；
- fields；
- particle injection；
- current 和 force；
- boundaries；
- custom output；
- timestep hooks；
- TOML；
- higher-order methods；
- 官方 PGen 索引。

Agent 应先读取当前 checkout 中的相关实现，再用 reference 补充稳定规则。reference 与 checkout 冲突时，以 checkout 为准。

第一版只考虑两个确定性工具：

- `check_case_contract.py`：对指定 PGen/TOML 执行可可靠自动化的局部一致性检查；
- `run_manifest.py`：创建 manifest、计算输入 hash、更新 run 状态。

不应一开始建立完整 schema 系统、通用 workflow engine 或多 scheduler 管理层。

## 与其他 Skill 的边界

### `entity-env-build`

`entity-case` 提供当前 checkout、PGen 和所需 engine/backend/build features；`entity-env-build` 返回 executable 和 build record。`entity-case` 不安装依赖或编写通用构建逻辑。

### `entity-analysis`

`entity-case` 交付 TOML、PGen、run manifest、输出位置和已有设计目标。`entity-analysis` 负责正式诊断与物理结论，不直接反向修改 case。

### `entity-debug`

owner 不明确时由 `entity-debug` 首诊。确认问题属于 PGen、TOML、checkpoint 参数或 launch 配置后，再交回 `entity-case`。

### `entity-core-dev`

只有确认当前 PGen API 无法实现需求时才进入。`entity-case` 应给出缺少的能力和已检查的 extension point，而不是笼统要求修改 Entity。

## 从 `entity-pgen` 迁移

迁移的重点不是增加流程，而是给现有 PGen 能力加上状态识别和运行上下文。

保留：

- 当前按 feature 组织的 references；
- normalization、coordinate basis、unit domain 等硬规则；
- scenario router 和 PGen/TOML self-check；
- 官方 PGen 检索入口。

调整：

- `SKILL.md` 开头先识别状态和用户目标；
- requirements checklist 改为按当前修改缺什么才问什么；
- `simulation-plan.md` 从强制前置产物改为可选的连续设计记录；
- deliverables 根据任务选择，不再默认输出完整 case workspace；
- 增加 build identity、run 和 checkpoint 的最小支持。

暂不做：

- 强制目录结构；
- 线性阶段状态机；
- 固定的七步或五步流程；
- 完整 validation JSON schema；
- 通用远程运行平台；
- 参数扫描和 ensemble orchestration；
- 站点专属 scheduler 规则。

## 第一版完成标准

第一版只需要证明以下行为可靠：

- Agent 能识别“没有 case、部分 case、已有 case、已有 run”等不同起点；
- Agent 能从上次留下的设计或代码继续，而不是重新问一整套问题；
- 局部请求只触发局部修改和相关 contract 检查；
- PGen/TOML 的关键冲突能够被发现；
- 需要编译时能向 `entity-env-build` 给出明确要求；
- 准备运行时能确认 executable 与输入身份并写 manifest；
- 续跑不会覆盖原 run；
- 不属于 case 层的问题会转给正确的 skill。

验证时应覆盖四种真实入口：从一句想法开始、修改已有 PGen、继续未完成设计、运行或续跑现有 case。重点观察 Agent 是否正确识别状态和控制工作范围，而不是它是否走完某套预定流程。
