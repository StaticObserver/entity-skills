---
name: entity-router
description: 通过一个由确定性 record 原语驱动的控制平面来登记、恢复和检查受管理的 Entity 模拟 Case 事实。用于持久化或跨 Site 的模拟工作、run 提交、Case 迁移/恢复、下游 identity 变更，或任何受管理的生命周期效果。有界的只读问题和独立的 owner-skill 编辑可以直接进入对应的 owner skill。
---

# Entity Router

Entity Router 通过确定性的 record 原语把 owner skill 的既成事实登记进
受管理的 Case 台账。公开模型保持精简：

```text
Project → Case → Identity → Evidence
```

由控制器推导 Case/identity ID、哈希、Locator 和路径。不要让用户提供
或管理这些字段。

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
python3 scripts/entityctl.py status --project-root <project> [--live] [--json]
python3 scripts/entityctl.py show --project-root <project>
python3 scripts/entityctl.py snapshot-source --project-root <project>

python3 scripts/entityctl.py render-run \
  --project-root <project> --toml <input.toml> --site <site> \
  [--gpus N] [--walltime HH:MM:SS] [--precision single|double] [--executable <path>]

python3 scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  record run-prepare --project-root <project> --toml <input.toml> --site <site> [...]

python3 scripts/entityctl.py record run-launch --project-root <project> [--run-id <id>]
python3 scripts/entityctl.py record run-exit  --project-root <project> [--run-id <id>]
python3 scripts/entityctl.py record build --project-root <project> --site <site> \
  --checkpoint <deps-checkpoint.json> --executable <name>
python3 scripts/entityctl.py record data --project-root <project> [--run-id <id>]
```

`status` 默认输出人可读的项目仪表盘：就绪板（source/pgen/build/run/data/
analysis 各环节状态与证据）、Run 台账、待决项和由当前事实推导的建议下一步。
`--json` 返回机器可读的控制器事实合同。

管理类命令有 `doctor`、`install`、`site add/list/discover`、
`store migrate`、`submission create/verify` 和 `export`。在编写
site 策略之前使用 `site discover`：在 Slurm Site 上它会
枚举合法的 partition/QoS；在无 scheduler 的 Site 上它会探测
执行环境、GPU 和 root 可写性。`submission create` 从最终产物
重新计算全部 fingerprint；`submission verify` 在之后出现任何
漂移时失败。当客户端安装与运行时 bundle 漂移，或存储的 Site
profile 校验失败时，`doctor` 会失败（exit 2）；并对旧 plan/apply
协议残留的活跃 Operation 给出警告——在崩溃之后、信任某台工作站之前
运行它。

## 原语使用循环

record 原语直接把既成事实落账；每步的门禁嵌在原语内部，失败时修复
原因后重跑同一条原语即可，receipt 语义保证不会重复提交。

1. `render-run`：只读预检。渲染 run 目录布局与提交脚本，校验 Site
   策略与输入，不写任何状态。
2. `record run-prepare`：登记 prepared run identity 并暂存输入。
   门禁：pgen skill 的 `pgen_preflight.py confirm <input> --by <actor>`
   写入的 `<input>.decisions.json` 必须存在，且其 `input_sha256` 与
   当前 TOML 匹配，否则拒绝登记。确认之前先把参数卡片展示给用户。
3. `record run-launch`：按 executor receipt 语义提交 run（Slurm
   `sbatch` 或 direct `run.sh`），保证 exactly-once；带外提交的作业
   用 `--adopt-job` / `--adopt-pid` 认领进台账。
4. `record run-exit`：探测终态（`sacct` 或退出文件）后落账。
5. `record data`：重新盘点 run 输出为带哈希的 manifest 并推进
   data identity；输出变化后再跑一次即可刷新。analysis 仍归
   entity-nt2py 负责。
6. `record build`：把经过验证的 env-build checkpoint 注册进 identity
   链；该 checkpoint 必须具有 `compatibility: pass` 和已确认的
   `decisions.parameters` 记录。注册之后，run 原语可以省略
   `--executable`。

用 `status` 读取项目仪表盘（就绪板 + Run 台账 + 待决 + 建议下一步，
均为控制器本地事实）。仅当需要当前 scheduler 观测时才加 `--live`；
需要机器可读合同时加 `--json`。
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

## Scheduler 后端

Site 的 `scheduler.kind` 选择 run 后端；无论哪种后端，record 原语面
都相同。`slurm` 通过 `sbatch` 提交并跟踪
作业 id。`none` 为无 scheduler 的 Site 选择 direct 后端：prepare
阶段渲染 `run.sh`，launch 阶段以 `pid == pgid` 的分离方式启动它
作为 effect identity，walltime 由 `timeout`（或内嵌的 bash
等价物）强制执行，每一次退出——正常、失败或被杀死——都记录在
`<run_root>/.entity-exit-code` 中。receipt 和实时 status
语义是相同的；只有 effect identity 不同。

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

汇报原语执行结果、精确的源/构建/运行 identity、
执行 Site、已验证的输出/效果、未解决的决策或异常，以及
status 是缓存的还是实时的。内部 receipt、Step 机制和旧版
Case 字段属于诊断细节，不是面向用户的正常工作内容。
