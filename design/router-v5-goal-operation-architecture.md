# Entity Router v5：Goal → Operation → Evidence

日期：2026-07-19
状态：已实现（run Goal v1）
前置基线：[当前架构说明](current-entity-router-architecture-2026-07-19.md)

## 目标

普通用户和主 Agent 只描述目标、确认科学/资源/删除决策并读取结果。Case UID、Action、
Locator、binding、revision、lease、owner/domain 和恢复步骤全部由程序派生。

公共模型为：

```text
Project → Goal → Operation → Evidence
```

公共命令为：

```text
entityctl plan   --project-root <path> --goal <goal.json> --output <plan.json>
entityctl apply  --plan <plan.json>
entityctl status --project-root <path> [--live]
```

`doctor`、`install` 和一次性 `migrate` 属于管理面，不进入普通模拟流程。

## 核心对象

### Project / Case

Case 只保存跨 Operation 的持久事实：项目绑定、source authority、Site、当前
source/build/run/data/analysis identity 和 evidence reference。readiness 是这些事实的派生视图。

### GoalSpec

GoalSpec 只包含用户语义。第一版支持 `run`，随后扩展 `build`、`data`、`analysis` 和
`purge`，但使用同一个外层合同。所有 ID、路径、hash、owner 和校验条件由 Planner 生成。

### Plan / Operation

Plan 是 GoalSpec 在一个精确 Case/Site/source revision 上解析出的不可变执行计划。Apply
第一次接收 Plan 时创建 Operation；重复 Apply 同一 Plan 必须恢复或返回缓存结果，不得重复
不可盲重放的副作用。

### Step

Step 是 Operation 的内部 journal 单位，不是公共 Action。每个 Step 使用固定状态：

```text
pending → intent_written → effect_observed → verified → committed
```

失败状态为 `needs_decision`、`blocked` 或 `anomaly`。再次 Apply 根据 controller journal 与
execution-site receipt 恢复。

### Evidence

Controller 只保存精确 Locator、fingerprint、effect identity 和验证时间。长日志、build、run、
raw data 和 analysis artifact 保持在 owner site。

## Controller store

`~/.entity-router/router.db` 是 v5 controller 的唯一结构化状态。SQLite 事务同时提交 Operation
step、identity/current pointer、event 和最终结果，替代跨多个 JSON 文件的自制事务。

旧 `registry.json`、`project-bindings.json`、site JSON 和 Case v3 通过一次性迁移导入。
迁移保留原文件为只读证据，不在两套状态之间双写。

数据库只保存小型 JSON payload 和 evidence reference，不保存 raw data 或完整日志。提供 JSON
导出用于审计和调试。

## Planner 合同

Planner 必须：

1. 从 cwd/project root 发现或创建 Case；
2. 验证 GoalSpec，缺少真正的科学/资源决策时返回 `needs_decision`；
3. 固定 source revision、Site 和 input/build identity；
4. 在创建 run identity 和远端 run root 前完成 site/resource preflight；
5. 派生所有 ID、Locator、binding、acceptance checks 和 StepSpec；
6. 输出 canonical plan hash；同一事实生成同一 plan。

## Apply 合同

Apply 必须：

1. 校验 plan hash 与当前 Project/Case/source/Site；
2. 在 controller 内部获得带过期时间的 Operation claim，不向用户暴露 lease；
3. 按顺序执行 allowlisted Step；
4. 在外部副作用前记录 intent；
5. 从 execution-site receipt 恢复已发生的副作用；
6. Controller 重新 probe 输出；
7. 在一个 SQLite 事务内提交 Step、identity、event 和 Operation 状态；
8. 只在 `needs_decision`、新 anomaly 或 terminal 时返回主 Agent。

没有独立 `recover` 命令；恢复等于再次 Apply 同一 Plan。

## Executor 合同

Local 与 SSH 使用同一个不可变 StepSpec 和同一个内容寻址 executor bundle。SSH transport 只做：

1. 安装/复用 exact bundle；
2. staging request 和必要 payload；
3. 调用 allowlisted adapter；
4. 返回 result/receipt。

Executor 不接受 `command`、`shell`、`script_text` 或 `pre_command`。集群 module、partition 和
policy 进入 site-local 配置/adapter，不进入通用 GoalSpec 或核心 skill。

## Owner skill 合同

`entity-pgen` 和科学 analysis 使用“自由探索、严格收束”：Router 提供目标、输入 identity、
workspace envelope、保护路径和验收条件；owner skill 自由选择具体方法；Controller 最后重新
probe changed/output Locator 并提交 evidence。

## 不变量

- 项目 Git、controller、execution site 和 skill bundle 各有唯一权威；
- 每个 Case 只有一个 source authority；
- source → build → run → data → analysis identity chain 不可断裂；
- Site 与 path 同时属于资源身份；
- 外部副作用不可盲重放；
- Worker 叙述不能推进状态；
- raw data 删除必须有精确 manifest 和显式授权；
- 正常查询不写状态，默认不访问远端。

## 迁移策略

1. 在现有代码旁实现 v5 store、Planner、Apply 和 Status；
2. 导入 v3 registry/site/project/Case，停止对导入对象双写；
3. 用统一 executor 完成本地和 SSH run prepare/launch/status；
4. 将旧 state/flow CLI 移到 `legacy`/developer surface；
5. 重写 `SKILL.md`，正常上下文只保留 v5 入口和不变量。

## 完成门

- 正常 run 只需一次 Plan 和一次 Apply；
- GoalSpec 不包含 ID、hash、Locator、binding、owner/domain 或 lease；
- 同一 Plan 重放不会重复 `sbatch`；
- controller 在每个 Step 边界崩溃后都能通过 Apply 恢复；
- local 与 SSH 使用同一 StepSpec；
- 用户只在科学、资源承诺、删除或真正歧义时被询问；
- `status` 默认只读 controller，`--live` 最多一次远端调用；
- v3 Case 可一次性导入，导入后不双写；
- Router 全量测试、Python 3.6 grammar、真实 SSH canary 和 `git diff --check` 通过。

实现与验收结果见
[`router-v5-implementation-2026-07-19.md`](router-v5-implementation-2026-07-19.md)。
