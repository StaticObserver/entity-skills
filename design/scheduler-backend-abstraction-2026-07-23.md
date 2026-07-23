# Scheduler 后端抽象设计方案（2026-07-23）

状态：方案待评审。动机证据：`evals/e2e-neutral-streaming/findings-2026-07-23.md`
（m87 轮：scheduler=none 站点上 router 主链路零进入，agent 绕过控制面裸跑）。

## 1. 问题定义

Router 的抽象骨架（GoalSpec 语义层、Site profile 的 `scheduler.kind` 枚举、
Locator、Step 白名单、意图收据/恢复）是系统无关的；但 **run 生命周期只落地了
Slurm 一个实现，且没有收口成后端接口**，Slurm 调用散在四个文件：

| 位置 | 耦合点 |
|---|---|
| `entity_router_planner.py:434` | `run Goal currently requires a Slurm Site`，plan 硬拒绝 |
| `entity_router_planner.py:284-295` | policy 强制 `default_partition`/`default_submit_user` |
| `entity_router_executor.py:178-216` | `render_sbatch`：`run.prepare.v2` 的提交脚本就是 sbatch 脚本 |
| `entity_router_executor.py:219-253` | preflight = `sbatch --test-only` |
| `entity_router_executor.py:337-439` | launch = `sbatch --parsable`；恢复用 `squeue`/`sacct` 匹配 comment |
| `entity_router_operation.py:615-731` | `--live` 与三类 divergence 全部基于 `squeue`/`sacct` |
| `entityctl.py:394-427` | `site discover` = `sacctmgr list qos` |

本质：**"一次运行的身份"被等同于 Slurm job_id**，缺少
`validate_policy / render / preflight / submit / probe / history /
scan_foreign / recover_match` 这一组后端操作的统一接口。

## 2. 设计原则

1. **GoalSpec 不动**。`compute`（gpus/walltime/precision）是用户语义，
   partition/qos 本来就不是 Goal 字段——抽象缺口不在这一层。
2. **收据与恢复语义不动**。`pending → intent_written → effect_observed →
   verified → committed`、同一 Plan 重放恢复、意图先行，全部保留。
3. **后端选择烘进 Plan，executor 不读 Site profile**。envelope 目前不含
   profile（executor 可能被推到远端独立执行），planner 按
   `profile.scheduler.kind` 生成后端专属 request，executor 按 request 里的
   `scheduler` 字段分发——保持 executor 的单向依赖。
4. **Slurm 行为逐字节不变**是第一阶段的验收标准；现有收据/plan 不需要迁移。
5. 不为 `pbs`/`custom` 写实现（枚举保留，报 `PlanError` 指引），本期只加
   `direct`。

## 3. 后端接口面

逻辑接口（按 `scheduler.kind` 分发，不是公开 API，先做成各文件内的一张
分发表 + 每后端一组函数，避免过度工程）：

```text
validate_policy(profile)          → policy 缺失时的 needs_decision 问题列表
render_launch(run_spec, context)  → 提交载体文本（sbatch 脚本 | run.sh）
preflight(request)                → 提交前验收（sbatch --test-only | 可执行性检查）
submit(request)                   → effect_identity（见下）
probe(identity)                   → RUNNING | PENDING | <terminal> | NOT_FOUND
history(identity, comment)        → 终端态回退查询（sacct | exit-code 文件）
scan_foreign(run_root, identity)  → 带外作业扫描（squeue %Z | /proc cwd 扫描）
recover_match(request, comment)   → 中断后认领既有效果（唯一匹配才采纳）
```

**effect_identity 已是开放结构**（现有收据里就是
`{"scheduler": "slurm", "job_id": ..., "comment": ...}`），direct 后端扩展为：

```json
{"scheduler": "direct", "pid": 418795, "pgid": 418795,
 "run_root": "...", "log": "<run_root>/run.log",
 "exit_file": "<run_root>/.entity-exit-code", "comment": "entity-router:..."}
```

旧收据不含这些键，读取路径已按键名取，无需迁移。

## 4. direct 后端语义（scheduler.kind == "none"）

- **prepare**：渲染 `run.sh`（`set -eu`；`timeout <walltime> exec <executable>
  -input input.toml`；退出码写入 `.entity-exit-code`）。run-manifest 与
  Slurm 路径完全一致。
- **preflight**：可执行文件存在且可执行、run_root 可写、（有 GPU 需求时）
  `nvidia-smi` 可用。不承诺资源可用性——无调度器站点没有这个概念。
- **launch**：`setsid nohup bash run.sh >> run.log 2>&1 &`，记录 pid/pgid。
  恢复时按 comment 扫描 `/proc/*/cmdline`+cwd 认领唯一匹配；多个匹配同样
  报 terminal anomaly（语义与 Slurm 一致）。
- **probe**：`kill -0 <pgid>` + exit_file 存在性 → RUNNING / 终端态 / NOT_FOUND。
- **divergence 降级语义**：`job_gone`/`state_mismatch` 可完整支持；
  `untracked_job` 靠 /proc 扫描 entity 进程 cwd，**允许 unknown**（权限/
  容器边界下扫描不可靠），unknown 不算 fail——与评测套件对 known boundary
  的处理一致。
- **walltime 由 `timeout` 执行**，超时即 SIGTERM，退出码 124 写入 exit_file。

## 5. 涉及文件与改动量（估算）

| 文件 | 改动 | 量级 |
|---|---|---|
| `entity_router_common.py` | profile 校验按 kind 分发（slurm 保留现有要求） | 小 |
| `entity_router_planner.py` | 删 :434 硬拒绝；`_site_policy` 按后端要字段；direct 时 steps 的 request 换后端字段 | 中 |
| `entity_router_executor.py` | `render_sbatch`/`_preflight`/`_launch` 按 request.scheduler 分发；新增 direct 渲染/提交/认领 | 中大 |
| `entity_router_operation.py` | `status --live`/`_reconcile_job` 按后端分发；direct 的 probe/exit_file 判定 | 中 |
| `entityctl.py` | `site discover`：none 站点探测 GPU/可执行环境（nvidia-smi、可写根）替代 sacctmgr | 小中 |
| `tests/test_router_v5.py` 等 | 新增 local + scheduler=none 的端到端：plan→apply→status 全链路本机可测（direct 后端的最大测试红利） | 中 |
| SKILL.md / router-runtime.md | run Goal 不再写 "requires a Slurm Site"；后端语义各一段 | 小 |

未读细 `entity_router_remote.py` 与 store 层，量级为估算；remote 只负责
搬运 envelope，预期不受影响。

## 6. 一个显式设计决策：Step kind 不升版

`run.prepare.v2`/`run.launch.v2` 的 kind 名保持不变，request 内部字段按后端
不同（planner 侧已按 plan_hash 绑定不可变内容）。理由：kind 表达的是"生命
周期阶段"而非"提交机制"，升版会污染白名单且旧 plan 无法对读。代价是
executor 校验逻辑按 `request.scheduler` 分支——可接受，因为分发表本来就
要在 executor 落地。

## 7. 分期

- **Phase A（纯重构）**：把四处 Slurm 调用收口到分发表后面，Slurm 行为
  逐字节不变，现有测试全绿。可独立发布。
- **Phase B（direct 后端）**：planner/executor/operation 接 direct；
  本机 scheduler=none 端到端测试；m87 场景重跑验证 router 主链路可进入。
- **Phase C（发现与观测）**：`site discover` 的 none 分支、direct divergence
  的 unknown 语义、SKILL.md 更新。

每期独立可发布（0.6.0 / 0.7.0 / 0.7.x），不捆绑。

## 8. 明确不做

- 不实现 pbs/custom；不在 GoalSpec 加 execution 机制字段；不改收据/身份链
  schema 主版本；不为 direct 后端加资源互斥（单机 GPU 争抢超出控制面职责，
  divergence 报告即边界）。
