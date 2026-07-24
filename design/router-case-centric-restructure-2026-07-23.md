# Entity Router 重构设计：以 Case 为中心的事实记录与确定性执行

日期：2026-07-23
状态：讨论稿

本文定义 entity-router 的重构目标架构。重构不改变底层已实现的安全能力
（identity 链、白名单执行器、receipt、证据重新探测），改变的是：
**agent 看到什么、需要组装什么、每轮花多少 token。**

## 1. 问题诊断

### 1.1 实测证据

2026-07-23 两轮手动测试（S1/S2，m87 无 Slurm 无 MPI，证据在
`~/entity-eval-traces/2026-07-23-S{1,2}/`，分析见
`evals/e2e-neutral-streaming/findings-2026-07-23.md`）显示：两轮 agent 都把
router 只当 site 注册器使用，plan/apply 零执行——当时 direct 后端已经就位。
入口边界是动机问题，不是能力问题。

### 1.2 三个错位

1. **叙事主体错位**：SKILL.md 通篇叙述如何遵守控制面规范（identity 链、
   receipt、租约、白名单），没有说清楚这套规范用来做什么。技能的目的是帮助
   用户用 Entity 做等离子体模拟研究：建环境、写 PGen、跑模拟、改代码、
   分析结果。这个工作流在文档中从头到尾没有出现。
2. **确定性三层被压平**：确定性的东西（编译环境、构建配置）、半确定的东西
   （模拟参数，频繁修改）、完全不确定的东西（选什么参数、跑多久、PGen 怎么
   设计）被塞进同一套"受管写事务"机制。中间层太重（改参数像走审批），顶层
   没有抓手（探索完没有沉淀锚点）。
3. **状态定位错位**：`router.db` 是"合规账本"，回答"这次写入是否合法"；
   设计目标是"项目地图"，回答"项目现在到哪了、哪些完成、哪些待完成"。

### 1.3 效率问题

agent 每次 Action 要组装和校验过多控制面字段（revision、lease、target
hash、Action 历史、owner/domain、路径 envelope），token 消耗大、效率低。
根因：协议字段交给 agent 组装、校验层层嵌套，而不是由代码提供简单的
确定性工具。

## 2. 设计原则

1. **三层确定性，三种处理。**
   - 确定层（环境、构建配置、site 拓扑、source 版本）：一次确立，文件权威，
     极少改。
   - 半确定层（模拟参数、资源量）：agent 自由改，改完轻量确认；参数卡片是
     "这份 run 的含义锚点"，不是合规门禁。
   - 不确定层（科学判断、参数探索、PGen 设计）：router 不干预过程，只在收敛
     后记录结论和证据。
2. **agent 规划流程，代码做确定性的事。** agent 负责与用户对话、科学判断和
   模拟流程的编排（先做什么、后做什么、出错怎么办）；CLI 是 agent 的辅助
   工具，负责读取和生成确定性记录、生成确定性脚本、探测与校验。确定性工作
   由代码执行，但大流程不包装进代码。
3. **只存不可推导的事实。** "当前该干什么"几乎总能从产物就绪情况推出；
   存一个可推导的指针等于制造第二个事实源，必然漂移。可推导的一律算出来。
4. **状态只凭证据推进。** 任何状态变化背后必须有重新探测过的证据（文件、
   哈希、退出码），agent 或 worker 的叙述不算数。
5. **最小动作，按需持久化。**（继承自 `legacy/docs/entity-case-design-
   2026-07-11.md`）用户目标 + 状态快照 → 选最小动作，不把局部请求扩展成
   完整生命周期；只有真正发生的事实才落盘。

## 3. 目标架构

### 3.1 Case：事实中心

每个模拟项目一个 Case，记录所有需要的事实。继承 Case v3
（`design/workspace-and-state.md`）的 Locator 与 identity 模型，底层不动：

- **意图**：当前研究目标（唯一存下来的"指针"，因为它不可推导——产物全绿
  不代表该收工）。
- **source identity**：Entity checkout、commit/版本、可编辑 authority 位置、
  PGen 身份。
- **build 记录**：在哪台机器、用什么环境 checkpoint、产出哪个可执行文件；
  引用 source revision。
- **参数卡片**：人可读的模拟参数 + 哈希；run 前确认，改动后重新确认。
- **run 台账**：追加式列表，每条 = 参数卡片哈希、site、资源、状态、退出
  证据、数据 Locator、盘点状态；续跑引用 parent，不覆盖。**run 序列就是
  研究轨迹。**
- **决策状态**：`clear / open / blocked` 两集合——已确认的决策与未决问题；
  只判断完成当前请求必需的信息。
- **证据引用**：receipt、manifest、盘点哈希的 Locator。

### 3.2 状态呈现：就绪板 + 推导器

不建状态机（已明确放弃）。状态呈现分两层：

- **就绪板（存）**：依赖链 source → pgen → build → run → data → analysis
  每格的状态词表（如 `missing / established / stale / running / failed`）+
  证据 + 最后验证时间。是向量不是标量，天然允许"run 在 m87 跑着、同时数据
  在分析"。stale 沿链传播：source 变 → build/run stale；参数卡片变 → 未启动
  run stale；数据变 → analysis stale。
- **推导器（算，不存）**：router 内一段确定性代码，
  `f(就绪板, 意图) → 建议的下一步`。原状态机的迁移知识（"编译失败去修编译"
  "run 终态后盘点数据"）变成推导规则，可测试。仪表盘显示"当前阶段"是算出
  来的视图，永远与现实一致。

debug 不是状态：它就是"某环节附着了失败证据"，推导器自然把下一步路由到
拥有修复的环节。

### 3.3 接口：确定性原语，不是大流程包装

CLI 的定位是 agent 的辅助工具。每个命令只做一件确定性的事，不包装大流程。
流程的编排——先做什么、后做什么、出错怎么办——由 agent 负责；这正是
debug 和意外情况需要 agent 在场的地方。

四类原语：

- **读取**：`status`（就绪板 + 意图 + 台账 + 推导的下一步建议）、
  `show`（Case 事实明细）；
- **生成**：source 快照、构建脚本、run 脚本、参数卡片——确定性的文本和
  记录由代码生成，不由 agent 手写；
- **记录**：登记 build（代码探测 executable 与 env checkpoint 后写入
  identity）、登记 run 启动/终态（探测 receipt 与退出码）、数据盘点
  （生成带哈希的 manifest）；
- **探测**：live run 状态、文件哈希、路径与 site 校验。

写入类原语自带证据探测：记录不是"登记 agent 的说法"，而是"代码验证后
落账"——agent 无法仅凭叙述推进任何状态（原则 4 由此实现）。

一次编译在 agent 眼中是：读 `status` → 决定编译 → CLI 生成构建脚本 →
执行脚本（长任务可拉起 sub-agent 隔离上下文）→ CLI 记录 build（代码验证
后落账）。每一步都是简单的工具调用，没有协议字段要组装；脚本执行失败时
agent 就在现场，直接看日志、改配置、重跑——不需要任何恢复协议。

所有正常输出保持紧凑（status、命令结果分别不超过约 4 KiB）。

### 3.4 校验系统：只保留两个机制

1. **内容哈希**——身份与 stale 检测的唯一手段。覆盖"哪些完成、哪些待
   完成"的全部推导需求。
2. **执行后重新探测**——效果验证的唯一手段。文件、退出码、哈希由代码
   自查，不信任何叙述。

两个特例保留但藏在代码内部，agent 永远看不到：

- 提交作业、删除数据等不可重放副作用：仍走 intent → effect → verified
  的 receipt 逻辑防重复提交；
- 删除原始数据：仍需显式用户授权 + manifest（现有 purge 机制保留）。

并发控制退化为单写文件锁。actor provenance 降级为被动记录的环境变量，
只供审计，不做门禁。

### 3.5 子 agent 使用边界

- 确定性工作由"CLI 原语 + agent 驱动"完成，不包装大流程。长任务（如完整
  编译）可拉起 sub-agent 执行生成的脚本，只为隔离上下文——脚本由代码
  生成、结果由代码验证，sub-agent 不做任何记录。
- 需要判断的工作（改 PGen、做分析）沿用 model Worker envelope 机制
  （`design/model-efficient-router-flow.md`）：只给目标、精确 read/write
  边界、验收标准，不带历史对话；结果不被信任，代码重新探测后才记账。

### 3.6 SKILL.md 与 playbook 结构

SKILL.md 保持薄。第一屏回答目的：本技能为你的 Entity 模拟项目维护一份
确定性记录，让任何一轮会话（换机器、换 agent、中途崩溃）都能知道项目在
哪、下一步是什么。然后只讲两件事：怎么读 Case 状态（status / 就绪板）、
有哪几类确定性原语可用。

不规定线性流程。每种活动写成一份独立 playbook 供 agent 参考，流程顺序和
组合由 agent 按用户目标自行定制：

- `playbooks/setup-env.md`：依赖与编译环境确立，产物是 env checkpoint
  （转引 entity-env-build）；
- `playbooks/develop-pgen.md`：PGen/TOML/design 一致开发（转引 entity-pgen）；
- `playbooks/build.md`：从生成构建脚本到记录 build identity；
- `playbooks/run-simulation.md`：参数卡片确认、生成 run 脚本、提交、监控、
  登记终态；
- `playbooks/analyze-data.md`：数据盘点与 nt2py 分析（转引 entity-nt2py）；
- `playbooks/debug.md`：按失败证据定位环节、修复后回到对应活动。

每份 playbook 只写编排逻辑：这个活动的产物是什么文件、用哪些原语、状态
记在哪、做完记什么账——不写大段领域知识（那是 owner skill references 的
职责），也**先写收益再写走法**（checkpoint 让你不重摸编译选项；run 记录让
崩溃后能认领原作业而不是重复提交）。playbook 是参考不是轨道：agent 可以
跳过、合并、乱序，唯一硬约束是原则 4——状态只能凭证据通过记录原语推进。
控制面概念全部退场到内部参考文档。

## 4. 从历史版本继承与丢弃

| 概念 | 来源 | 处置 |
|---|---|---|
| Case 事实中心、Locator、identity 链、stale 传播 | `design/workspace-and-state.md` (v3) | 继承，底层不动 |
| model Worker envelope、上下文隔离、结果重探测 | `design/model-efficient-router-flow.md` | 继承，仅用于需判断的子任务 |
| 独立状态维度、最小动作、decisions 三态、按需持久化 | `legacy/docs/entity-case-design-2026-07-11.md` | 复活其精神，写入 SKILL.md 行为原则 |
| 多 agent 交接契约 | `legacy/EntitySkillPackVault/10-Architecture/Agent Collaboration Model.md` | 归档，不进入新架构 |
| run-manifest（每次续跑新记录、引用 parent） | `legacy/.../Run Manifest Template.md` | 并入 run 台账 |
| playbooks（只写编排逻辑、组合跨 skill 工作流） | `legacy/docs/architecture-v1-2026-06-20.md` §6 | 复活，按活动拆分，见 §3.6 |

## 5. 删除清单

以下 agent 可见的概念和门禁整体删除（token 消耗主体）：

- GoalSpec JSON 协议、三种 Goal 类型（run/build/data）与 `needs_decision`
  计划门（参数确认改为轻量卡片确认，build/run/data 由记录原语取代）；
- plan 审查循环（agent 读 plan 再 apply）；
- writer lease、handoff、revision 并发门禁；
- flow request 组装（step、Action ID、owner/domain、binding、验收条件）；
- 确定性步骤的 Worker staging；
- owner/domain 匹配、Action 历史连续性等多步门禁；
- 包装大流程的动词命令（一口吃完的 build/run/data 事务）。

保留为内部实现或降级：identity 链、白名单执行器、receipt（仅不可重放
副作用内部）、purge 授权、actor 被动审计。plan/apply 引擎拆解为原语后
退役。

## 6. 迁移步骤

详细迁移计划（零件盘点、原语命令面、测试矩阵、风险）见
`design/router-restructure-migration-2026-07-23.md`。阶段概要：

1. **P1 status 仪表盘化**：`entityctl status` 输出重构为就绪板 + 意图 +
   台账 + 推导的下一步；人可读，紧凑。
2. **P2 原语工具集**：将 plan/apply 引擎拆解为读取、生成、记录、探测四类
   原语命令；内部复用现有执行器与 receipt 逻辑。
3. **P3 删除门禁**：移除 lease/revision/owner-domain 等校验路径，并发
   退化为文件锁；确认现有测试改造。
4. **P4 SKILL.md 重写**：按 3.6 叙事；references 按内部机制重新归位；
   同步其余三个 owner skill 的边界描述。
5. **P5 实测验证**：重跑 S1/S2 同场景 eval（m87），观察 agent 是否主动
   使用原语、是否先读 status，用 adoption 度量和 token 消耗对比。

## 7. 验证标准

- agent 进入项目后第一轮能回答：项目目标、基座状态、跑过什么、待决项；
- agent 用少量原语调用驱动完整流程，协议字段零组装，每步输出紧凑；
- 会话中断后，新会话凭 Case 事实恢复，不重复提交作业、不重复编译；
- S1/S2 场景重跑：router 进入率显著提升，总 token 消耗显著下降；
- 现有测试套件改造后全绿。

## 8. 开放问题

1. 就绪板的人可读形态：只改进 `entityctl status` 输出（单一权威在控制区），
   还是项目目录里同时落一份 `ENTITY-STATE.md`（直觉更锚，但有双写漂移风险）？
   当前倾向前者。
2. 旧 v5 Case 数据（router.db）如何迁移到新呈现层：一次性迁移脚本，还是
   只保证旧数据可读、新项目用新路径？
3. 多 agent 并发防护放弃到什么程度：单写文件锁是否足够覆盖真实使用
   （同一项目两个 agent 会话同时工作）？
