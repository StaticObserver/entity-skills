# Entity Skills Package 整体设计

日期：2026-07-13  
状态：当前设计基准；初版 Router runtime 已实现，真实 Entity 端到端 smoke 尚待完成

## 1. 目标与边界

`entity-skills` 帮助用户使用 Entity 完成可运行、可验证、可恢复和可复现的天体物理模拟。

第一版覆盖：

- PGen、匹配 TOML 和设计记录；
- 依赖环境和 Entity 编译；
- simulation 准备、运行、监控和续跑；
- nt2py 数据访问及分析代码组织；
- 长流程的状态恢复、上下文隔离和失败回路。

它不是大型知识库，也不把整个模拟流程塞进一个大 skill。`entity-case` 不是 skill，运行流程也不建立 `entity-simulator`。

## 2. 核心模型

```text
Case                         持久模拟对象
└── Workflow                 一次完整用户目标
    └── Action               最小状态转移和上下文隔离单元
        └── Worker           执行该 Action 的隔离 Agent
```

- **Case**：集中保存一个 PGen、build、多个 run、分析文件和关键记忆。
- **Workflow**：例如“建立并运行新模拟”或“分析已有 run”；每个 Case 同时只有一个 active workflow。
- **Action**：例如 `pgen.design`、`build.compile`、`run.launch`；每个 Action 只有一个 owner。
- **Worker**：加载一个专业 skill 或 playbook 片段，在限定路径内完成 Action。

Case 保存事实索引，Workflow 保存目标，Action 约束行为，Worker 隔离专业上下文。

## 3. 系统结构

```text
用户
  -> Router（控制面）
       -> Playbook（流程图）
       -> Case State Tool（状态、门禁、事件）
       -> Action Contract（最小上下文）
       -> Case-bound Worker（执行面）
            -> entity-pgen
            -> entity-env-build
            -> entity-nt2py
            -> playbook-run / playbook-analysis
       -> 产物验证
       -> 状态转移
```

### Router

Router 长期驻留，只掌握全局控制信息：

- 当前 Case、Workflow、phase 和 active Action；
- 目标、完成条件、关键决定和 blocker；
- readiness、allowed actions 和 next action；
- 产物路径、fingerprint 和 owner；
- Worker 的创建、复用、回收和失败路由。

Router 不执行专业 skill 的内部工作，不读取不必要的完整源码、长日志或全部 references。

### Playbook

Playbook 只定义阶段顺序、进入条件、交接物、失败出口和完成条件，不复制 skill 知识。

当前 runtime 只保留：

| Playbook | 用途 |
|---|---|
| `new-simulation` | 新建或补全模拟 |
| `run-simulation` | 使用已验证的 PGen/TOML 和 executable 启动 run |
| `resume-simulation` | 从 checkpoint 创建新的 continuation run |
| `analyze-run` | 检查输出并组织数据访问和分析 |

失败诊断是所有 playbook 的公共分支，不单独常驻加载 debug skill。

### Task Skills

| Skill | Owner 范围 | 主要产物 |
|---|---|---|
| `entity-pgen` | PGen、匹配 TOML、物理与接口设计 | `pgen.hpp`、工作 TOML、`docs/design.md` |
| `entity-env-build` | 依赖、toolchain、配置和编译 | `_build/` 状态、build logs、executable、build result |
| `entity-nt2py` | nt2py 读取、选择、绘图和导出能力 | inventory、分析代码、图像和导出 |

运行、监控、续跑和科学分析由 Router 按 playbook 组织。`entity-nt2py` 不拥有物理结论。

Router-owned 的 `run.prepare`、`run.launch`、`run.monitor` 和 `run.resume` 由 Playbook Worker 执行。它只加载当前 playbook 片段，不形成新的 `entity-simulator` skill。

## 4. 上下文隔离

目标机制是 **常驻 Router + 按 `(case_id, execution_domain)` 绑定的 Worker**。

1. Router 首次进入某专业阶段时创建 Worker；
2. Worker 使用全新上下文，只加载一个 child skill 或 playbook 片段，以及当前 Action Contract；
3. 同一 Case 再次回到该专业阶段时复用原 Worker；
4. Worker 不接收完整聊天历史，也不直接与其他 Worker 交接；
5. Router 只接收结构化结果，重新读取磁盘产物后决定状态转移。

Worker 在 Case 切换时保持隔离；运行环境支持且容量允许时可以继续保留，切回原 Case 后复用。出现以下情况时回收并按需重建：

- 专业范围或 Entity checkout 发生根本变化；
- 上下文过长、明显漂移或积累大量无效 debug 路径；
- Workflow 完成、长期不用或 Worker pool 容量不足。

Agent/thread ID 是易失 runtime 信息，不写入持久 Case 状态。多-Agent 不可用时可降级为单 Agent 顺序执行，但只能减少上下文增长，不能实现真正隔离。

## 5. Action Contract

Router 在执行前生成最小任务包：

- Case、Workflow、Action ID 和 owner；
- 本 Action 的目标；
- 输入路径、角色和 fingerprints；
- `read_roots`、`write_roots` 和 protected paths；
- 相关约束和必要决定；
- 预期输出和验收检查；
- 与当前失败直接相关的 evidence。

Worker 只返回状态、实际改动路径、验证结果、blocker 和建议 owner。完整日志留在 owner 目录，不复制进 Router 上下文。

Action 使用两阶段记录：

```text
started -> completed
        -> failed
        -> blocked
        -> cancelled
```

Action Contract 启动后不可原地改变。输入发生实质变化时关闭旧 Action，创建带新 fingerprints 的 Action。

## 6. Agent 行为控制

所有修改型 Action 必须同时满足：

1. Case 已精确选择且 orientation ready；
2. Action 位于 `allowed_actions`；
3. Worker 与 `owner`、`case_id` 匹配；
4. 输入 evidence 未过期；
5. 写入目标位于 `write_roots`，且不在 protected paths；
6. 前置 readiness 和验收条件明确；
7. 不存在 blocking blocker。

强制规则：

- 只有 Router 状态工具可以修改 `_case/`；
- Worker 只修改 owner 产物，不能修改 `case.json`；
- Worker 之间不直接传递自由文本，由 Router 通过 Action Contract 交接；
- 每个 Case 默认只允许一个 active 修改型 Action；
- 长时间 build/run 可以异步监控，但不得并发修改会使其失效的输入；
- Worker 的文字总结不能推进状态，Router 必须验证实际文件；
- 不自动选择“最新” checkout、Case 或 run；
- 参数变化或 checkpoint 续跑必须创建新的 run identity；
- 原始 simulation 数据和历史 run 默认只读。

## 7. 状态与事实

```text
problems/<case_id>/_case/
├── case.json                 当前 Case 和 Workflow 控制快照
├── events.jsonl              append-only 状态事件
├── actions/<action_id>/
│   ├── request.json          不可变 Action Contract
│   └── result.json           Router 验证后的结果
└── history/                  已完成或挂起 Workflow 快照
```

`case.json` 只保存继续工作所需的摘要和指针：identity、goal、done-when、scope、workflow、readiness、blockers、next action 和 active action。

事实仍由 owner 文件提供：

| 范围 | Source of truth |
|---|---|
| PGen | `pgen.hpp`、匹配 TOML、`docs/design.md` |
| Build | `_build/requirements.json`、`entity-deps.local.json`、`.entity-session.json`、日志和 executable |
| Run | `run-manifest.yaml`、进程或 scheduler、日志和输出 |
| Data/Analysis | 原始数据、nt2py inventory、脚本、图像和报告 |

状态工具使用原子写入、单调 `revision` 和 optimistic concurrency。动态 run 状态必须重新查询，不能只相信 manifest。

## 8. Readiness 与失效传播

Case 至少跟踪：

```text
orientation  pgen  build  run  data  analysis
```

每项 readiness 必须带 evidence path、observed time，文件证据尽量带 SHA-256。

主要失效规则：

- checkout/commit 变化 -> build stale；
- PGen 或编译选项变化 -> build 和未启动 run stale；
- TOML 变化 -> contract verification 和未启动 run stale；
- executable 变化 -> prepared run stale；
- run input 变化 -> 创建新 run，不复用原 identity；
- data 变化 -> inventory 和相关 analysis stale。

已完成历史 run 和 analysis 不改写，只保留其原始 provenance。

## 9. Failure 与 Debug

- owner 内部错误由原 Worker 诊断和最小修复；
- 确认错误属于另一 owner 时，关闭当前 Action，由 Router 创建新的 Action；
- 原因不明时创建短生命周期 `failure.triage` Action，只携带相关 evidence；
- retry 必须记录输入变化或明确的重试理由；
- 未闭合 Action 恢复时先检查实际产物，不假设成功；
- 当前三个 skill 无法处理的 Entity core 问题保留证据并明确报告，不虚构可用能力。

## 10. Workspace 约定

```text
$ENTITY_WORKDIR/
├── entity-<version-or-label>/
├── deps/
└── problems/<case_id>/
    ├── pgen.hpp
    ├── <pgen>.toml
    ├── docs/design.md
    ├── build/
    ├── _build/
    ├── _case/
    ├── scripts/
    └── run-<label>/
        ├── input.toml
        ├── run-manifest.yaml
        ├── data/
        ├── logs/
        └── analysis/
```

第一版 `case_id` 等于 PGen 名。完整路径和状态约定见 `workspace-and-state.md`。

## 11. Source of Truth 顺序

1. 用户明确指定的 checkout、Case 和 run；
2. 当前磁盘上的 owner 产物、日志、进程和输出；
3. 与当前 checkout 匹配的 Entity 源码和官方资料；
4. 对应 skill 的版本化 references；
5. site notes 和历史案例；
6. `legacy/`。

聊天摘要、Worker 总结和旧 Case 记忆不能覆盖更高优先级证据。

## 12. 第一版完成标准

- Router 可创建、恢复、挂起和切换 Case；
- Action 门禁、原子状态更新和 stale 传播有确定性工具和测试；
- Router 可以按需创建、复用和回收 Case-bound Worker；
- 三个 live skill 的输入、输出、write roots 和验证边界明确；
- PGen、build、TOML、executable 和 run identity 可互相核对；
- simulation 可以运行、续跑和复现；
- failure 能回到正确 owner，未知问题不会盲目重试；
- CPU smoke case 覆盖设计、构建、运行和最小数据检查。

## 13. 实施顺序

1. 固化 Case/Workflow/Action schema、Action Contract 和 transition rules；
2. 实现并测试确定性 case-state 工具；
3. 将 `skills/entity-router` 实现为控制面和 Case-bound Worker supervisor；
4. 更新 playbook 的门禁、handoff 和失败出口；
5. 增加 contract tests 和 CPU 端到端 smoke case。

设计、runtime 和历史材料必须分离：`design/` 是当前设计，`skills/entity-router/` 是 Router runtime，`legacy/` 只做归档。
