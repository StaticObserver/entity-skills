---
name: entity-router
description: 通过一个由 GoalSpec 驱动的控制平面来 Plan、Apply、恢复和检查受管理的 Entity 模拟 Operation。用于持久化或跨 Site 的模拟工作、run 提交、Case 迁移/恢复、下游 identity 变更，或任何受管理的生命周期效果。有界的只读问题和独立的 owner-skill 编辑可以直接进入对应的 owner skill。
---

# Entity Router

Entity Router 把一个用户目标转化为一个经过验证的 Operation。公开模型
保持精简：

```text
Project → Goal → Operation → Evidence
```

由控制器推导 Case/Operation ID、哈希、Locator、路径、绑定、
认领关系、Step 顺序和恢复状态。不要让用户提供或管理
这些字段。

## 入口边界

当工作是持久化的、跨越 PGen/build/run/data/analysis、需要选择
执行 Site、会改变不可变 identity、或会写入受管理的 Case
资源时，使用 Router。仅对于有界的只读任务，或明确独立、
没有受管理生命周期效果的编辑，才直接进入 owner skill。

仅当 Site/root 归属不清楚时才阅读 `references/workspace-layout.md`。
仅用于内部调试时才阅读 `references/router-runtime.md`。

## 公开接口

正常工作只使用：

```bash
python3 scripts/entityctl.py plan \
  --project-root <project> --goal <goal.json> --output <plan.json>

python3 scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  apply --plan <plan.json>

python3 scripts/entityctl.py status --project-root <project> [--live]
```

管理类命令有 `doctor`、`install`、`site add/list/discover`、
`operation cancel <id>`、`store migrate`、`submission create/verify` 和
`export`。在编写 site 策略之前使用 `site discover`：在 Slurm Site 上它会
枚举合法的 partition/QoS；在无 scheduler 的 Site 上它会探测
执行环境、GPU 和 root 可写性。`operation cancel` 仅用于放弃一个活跃的
Operation 并释放 Case；失败的 Apply 本身就会释放 Case，
对同一个 Plan 重新 Apply 即可恢复。`submission create` 从最终产物
重新计算全部 fingerprint；`submission verify` 在之后出现任何
漂移时失败。当客户端安装与运行时 bundle 漂移，或存储的 Site
profile 校验失败时，`doctor` 会失败（exit 2）；并对泄漏的活跃
Operation 给出警告和确切的 `operation cancel` 补救办法——
在崩溃之后、信任某台工作站之前运行它。

## GoalSpec

GoalSpec 只包含用户语义。可执行的 Goal 种类是 `run`、
`build` 和 `data`：

```json
{
  "schema_version": 1,
  "kind": "run",
  "input": "input.toml",
  "site": "gpu-site",
  "compute": {
    "gpus": 4,
    "walltime": "04:00:00",
    "precision": "double"
  }
}
```

`run` Goal 只有在模拟参数确认之后才会规划：pgen skill 的
`pgen_preflight.py confirm <input> --by <actor>` 会写入
`<input>.decisions.json`；当记录缺失或 TOML 在之后被改动时，
规划会以 `needs_decision` 失败。确认之前先把参数卡片展示给
用户。

```json
{"schema_version": 1, "kind": "build", "site": "gpu-site",
 "checkpoint": "/abs/entity-deps.local.json", "executable": "entity.xc"}
```

`build` Goal 把一个经过验证的 env-build checkpoint 注册进 identity
链；该 checkpoint 必须具有 `compatibility: pass` 和已确认的
`decisions.parameters` 记录。注册之后，后续的 `run` Goal 可以省略
`executable`。

```json
{"schema_version": 1, "kind": "data", "run": "current"}
```

`data` Goal 把一个 run 的输出盘点为一份带哈希的 manifest，并推进
data identity。`analysis` 尚不是一种 Goal；它仍归 entity-nt2py 负责。

当 Case 拥有经过验证的当前 build identity 时，`executable` 是可选的。
Site 策略提供安全默认值，例如节点数、任务数、每个 GPU 的 CPU 数，以及——
在 Slurm Site 上——partition 和 QoS。仅当物理设置、资源
承诺、删除操作或真正的歧义仍然存在时才询问用户。绝不要把 ID、哈希、
Locator、绑定、owner/domain、租约、shell、命令或生成的脚本
字段放进 GoalSpec。

## Scheduler 后端

Site 的 `scheduler.kind` 选择 run 后端；无论哪种后端，Goal 和 Step
的种类都相同。`slurm` 通过 `sbatch` 提交并跟踪
作业 id。`none` 为无 scheduler 的 Site 选择 direct 后端：prepare
阶段渲染 `run.sh`，launch 阶段以 `pid == pgid` 的分离方式启动它
作为 effect identity，walltime 由 `timeout`（或内嵌的 bash
等价物）强制执行，每一次退出——正常、失败或被杀死——都记录在
`<run_root>/.entity-exit-code` 中。receipt、重放恢复和实时 status
语义是相同的；只有 effect identity 不同。

## 运行循环

1. 运行 `plan`。除了写出请求的 plan 产物之外，它是只读的。
2. 如果返回 `needs_decision`，只询问列出的语义问题，然后
   重新生成 Plan。
3. 当涉及资源承诺时，展示精简的 Plan 摘要。
4. 运行一次 `apply`。它内部会认领 Operation、暂存精确的 payload、
   执行白名单内的 Step、验证 owner-site receipt，并以事务方式
   提交事实。
5. 如果 Apply 被中断或报告可重试的异常，对同一个 Plan 再次运行
   `apply`。没有单独的 recover 命令。
6. 用 `status` 读取缓存的控制器事实。仅当需要当前 scheduler
   观测时才加 `--live`。
   实时 status 最多做三次有界的后端查询。在 Slurm Site 上：
   作业状态、作业离开队列后的 `sacct` 兜底查询，以及对 Case
   run root 的未跟踪作业扫描。在无 scheduler 的 Site 上：退出
   文件、`kill -0` 存活探测，以及外来进程扫描——当 Site
   拒绝该扫描时降级为 `unknown`（绝不视为失败）。`--live` 还会
   报告 `divergences`，对带外变更分类：`job_gone`（后端对
   已记录的作业或进程没有记录）、`state_mismatch`
   （作业到达了 router 从未观测到的终态），以及
   `untracked_job`（一个外来的 scheduler 作业或进程正在 Case
   run root 中运行——这是绕过控制平面的证据）。
7. 当某个 run 的输出在盘点之后发生变化，对同一个 `data` Goal
   plan 重新运行 `apply --refresh`；它会重新执行盘点并重写
   manifest。其他 Goal 种类会被拒绝使用 `--refresh`。

不要仅仅因为 Apply 被中断就创建第二个 Plan。只有当 Goal、源
内容、Site profile、输入、可执行文件或资源决策发生变化时才创建
新的 Plan。

## 权威与验证

- `router.db` 是唯一的结构化控制器权威。
- 源、构建、运行、原始数据和分析产物在其各自 owner Site 保持权威；
  控制器只存储 identity 和证据引用。
- 一个 Case 只有一个可编辑的源权威。
- identity 链 `source → build → run → data → analysis` 必须保持完整。
- Site 和绝对路径共同标识一个资源。
- 本地和 SSH 执行使用相同的不可变 StepSpec 和相同的
  内容寻址执行器。
- 执行器只接受结构化的白名单请求，绝不接受调用方的 shell 文本。
- 外部效果之前先有 intent receipt，且绝不盲目重放。控制器状态
  仅在独立的 receipt/输出验证通过之后才推进。
- worker 的文字叙述不能推进状态。
- 默认 status 是控制器本地的，且绝不写状态。

## Owner skills

对于 PGen 和科学分析，使用**自由探索，严格收束**的方式：向 owner skill
给出语义目标、精确的输入 identity、工作区/root 边界、受保护
路径和验收标准。让它自行选择内部方法。只接受
结构化的变更/输出 Locator，然后由 Router 重新探测并提交
证据。

`entity-pgen` 负责 PGen/TOML/design 工作，`entity-env-build` 负责依赖与
构建工作，`entity-nt2py` 负责数据访问/检查。Router 负责生命周期
排序和权威转移，而不是它们的领域推理。

## 破坏性操作

删除原始数据总是需要明确的用户授权、精确的 manifest、
受保护的源/构建/依赖 root，以及目标之外的 receipt。
绝不要从一个宽泛的请求推断删除授权，也绝不要用一个 run 或
analysis Operation 作为删除的边界范围。

## 汇报

汇报 Goal 结果、Operation 状态、精确的源/构建/运行 identity、
执行 Site、已验证的输出/效果、未解决的决策或异常，以及
status 是缓存的还是实时的。内部认领、Step 机制和旧版
Case 字段属于诊断细节，不是面向用户的正常工作内容。
