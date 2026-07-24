# Entity Router 重构迁移计划：plan/apply → 确定性原语

日期：2026-07-23
状态：P1–P4 已完成（2f333ef、b7330e6 及后续提交）；P5 实测验证待做
依据：`design/router-case-centric-restructure-2026-07-23.md`（目标架构）
前置：P1（status 仪表盘化）已完成

本文把设计稿 §6 的 P2–P5 展开为可执行的迁移计划，基于对现有实现的全量
盘点（executor 823 行、operation 871 行、planner 840 行、entityctl 859 行、
测试与文档）。

## 1. 盘点结论

### 1.1 可以整体复用的零件（不碰或只包薄壳）

| 零件 | 位置 | 服务哪个原语 |
|---|---|---|
| `render_sbatch` / `render_direct` / `_validate_run_spec` / `_walltime_seconds` | executor.py:178-277，纯函数 | 生成 run 脚本 |
| `source_manifest` | common.py:237 | 生成 source 快照清单 |
| `make_manifest` / `snapshot_archive` / `snapshot_install` / `verify`（已写好但**从未接线**） | remote.py 全文件 | 生成 source 快照 |
| 数据盘点 walk+hash+manifest 核心 | executor.py:709-725 | 记录 data |
| `file_evidence` / `sha256_file` | executor.py:116-126 / common.py:112 | 探测哈希 |
| `_slurm_live_status` / `_direct_live_status` / `_direct_foreign_scan` | operation.py:717-868，输入仅 (profile, scheduler, result)，无 store 依赖 | 探测 live run |
| `validate_site_profile` / `run_on_site` / `parse_locator` 等 | common.py | 全部原语 |
| site policy 默认值（`_slurm_site_policy` / `_direct_site_policy`） | planner.py:269-340 | 生成 run 脚本 |
| decisions 确认门禁（`_simulation_confirmation`）、checkpoint 门禁（`require_verified_checkpoint`） | planner.py:407-434, 608-627 | 记录原语的前置检查 |
| `ExecutorClient`（内容寻址部署 + 本地/SSH 分发） | operation.py:71-192 | 在远端执行的原语 |
| receipt 三态机制（intent→effect→verified + 恢复匹配） | executor.py:152-175, 461-519, 592-615 | 提交/删除类副作用内部 |

### 1.2 被 plan 绑死、需要拆的（只有 4 处）

1. `_direct_launch` 的 Popen 段（executor.py:649-660）：comment 由
   `operation_id+plan_hash` 派生。拆法：提取
   `launch_detached(run_root, script, log, comment)`，comment 改为由
   case_uid+run_id 派生。
2. `receipt_base` / `matching_receipt`（executor.py:152-175）：身份字段绑定
   operation/plan_hash/step。拆法：身份键换成 `(case_uid, run_id, action)`。
3. `_prepare` 组装段（executor.py:418-438）：payload 来自 plan。拆法：参数化
   为 `(run_root, input_path, manifest, script)`。
4. `_identity_projection` 与 apply 回写段（operation.py:449-606）：投影规则
   本身很简单，照抄 per-kind 映射重写成各 record 原语自己的落账逻辑。

### 1.3 随协议整体删除的

- planner.py 的 GoalSpec 校验（:25-146）、plan 派生/hash/schema
  （:459-472, 774-839）——planner.py 最终只剩被 1.1 保留的辅助函数，
  建议搬到新模块 `entity_router_facts.py` 后删除整个文件；
- operation.py 的 `apply_plan` 引擎与 claim 心跳；
- templates/goal.schema.json、templates/operation-plan.schema.json；
- entityctl 的 `plan` / `apply` / `operation cancel` 子命令。

## 2. 原语命令面（P2 的目标形态）

```text
读取   entityctl status [--live] [--json]          # 已完成（P1）
       entityctl show --project-root X             # Case 事实明细（JSON）
生成   entityctl render-run --project-root X --toml input.toml --site m87 \
         [--gpus 4 --walltime 04:00:00]            # 渲染 run 脚本 + 派生 run_root
       entityctl snapshot-source --project-root X  # 接线 remote.py
记录   entityctl record build --project-root X --site m87 \
         --checkpoint deps.local.json --executable /abs/entity.xc
       entityctl record run-prepare --project-root X --toml input.toml --site m87
       entityctl record run-launch --run-id R [--adopt-job 42 | --adopt-pid N]
       entityctl record run-exit  --run-id R       # 探测 exit 文件/sacct 落终态
       entityctl record data --run-id R            # 盘点 → manifest + identity
探测   status --live（已有）/ record run-exit 内含探测
```

要点：

- **写门禁全部内嵌在 record 原语里**：`record build` 先验证 checkpoint 的
  `compatibility: pass` 与 decisions 记录，再探测 executable 存在与哈希；
  `record run-prepare` 先跑 `_simulation_confirmation`（参数卡片确认）；
  `record run-launch` 走 receipt 防重复提交；`--adopt-*` 认领 agent 自己
  提交的作业（探测 squeue/`kill -0` 验证后才落账）。agent 没有任何"绕过
  验证直接写状态"的入口。
- run_id 派生（内容寻址）、run_root 路径、site policy 默认值从 planner
  搬进 `entity_router_facts.py`，render/record 共用。
- 构建脚本的生成不在 router：那是 entity-env-build 的 `entity-build.sh`
  职责；router 只 `record build`。设计稿 §3.3 的"生成构建脚本"一项据此
  修正。

## 3. 阶段计划

### P2a：抽取事实派生层（纯重构，低风险）

- 新建 `scripts/entity_router_facts.py`：从 planner.py 搬入 `_resolve_case`、
  `_simulation_confirmation`、`require_verified_checkpoint`、site policy
  默认值、run_root/run_id 派生、`_source_identity`、`_git_revision`、
  `_resolve_input`、`_current_build_executable`。
- planner/operation/dashboard 改为从 facts 导入；行为不变。
- 完成门：全量测试绿，无行为变化。

### P2b：原语命令上线（与 plan/apply 并存，纯增量）

- `show`、`render-run`、`snapshot-source`、`record build/run-prepare/
  run-launch/run-exit/data` 逐个实现；复用 1.1 零件，拆 1.2 的 4 处。
- record 落账直接写 identities/current（参照 `_identity_projection` 的
  映射），不经 operations/steps 表。
- 每个原语配新测试（沿用 fake slurm/direct 夹具）；plan/apply 旧测试
  此阶段不动。
- 仪表盘推导器文案切换到原语名（"apply 同一 plan" → "重新执行失败的
  record"；"用 data Goal 盘点" → "record data"）。
- 完成门：同一场景用原语链路和用 plan/apply 链路走通的结果一致；
  全量测试绿。

### P2c：退役 plan/apply（删除性改动，集中一次做）

- 删：entityctl 的 plan/apply/operation cancel 命令、planner.py 协议部分
  （随 P2a 已搬走辅助函数，整文件删除）、operation.py 的 apply 引擎、
  goal/plan 两个 schema。
- 同步必须一起改的（探查发现的硬依赖）：
  - `tools/skill_observability/adapters/claude_phases.py:56`（run 阶段正则
    含 `entityctl\b.*\b(plan|apply)\b`）和 `claude_activities.py:66`
    （job-submit 正则同）——改写为匹配 record/run-launch；
  - `tools/skill_observability/evidence.py:254-310`
    `validate_router_operation` 绑定 plan envelope——改为校验 record
    落账后的 Case 事实（或退役该校验，决策点见 §5）；
  - `tests/test_skill_observability.py:279,968-1004`、
    `test_skill_observability_phases.py:88,279` 的 plan 夹具；
  - `evals/user-needs/needs/U4-interrupted-apply/`（整个用例围绕打断
    apply）——改写为打断 record run-launch，或随 receipt 语义保留
    verify 逻辑；
  - `skills/entity-pgen/SKILL.md:82` 等处 "plan 门禁" 措辞、
    `pgen_preflight.py` docstring 的 "Router plan gate" 表述。
- 测试矩阵（test_router_v5.py 68 个方法）：约 35 个随协议删除（plan
  hash、reapply 恢复、claim、cancel 等），约 15 个改用原语搭夹具重写
  （live status 系列、site policy、confirmation 门禁、direct 后端端到端），
  约 18 个不动（site add/discover、doctor、submission、executor 白名单）。
  test_router_contracts.py 更新入口清单与 goal/plan schema 断言；
  purge、dashboard 测试不动。
- 完成门：全量测试绿；`entityctl plan/apply` 返回未知命令；grep 全仓无
  GoalSpec 残留引用（除 design/legacy 归档）。

### P3：store 瘦身与门禁删除

- operations/steps 表随 P2c 失去写入者；`STORE_SCHEMA_VERSION` 升 2，
  `store migrate` 提供迁移：保留 sites/cases/projects/identities/events，
  operations/steps 归档导出后删除（开放问题 2 的落点：旧数据可读性由
  导出文件保证）。
- 删 claim/lease 机制（claim_operation/renew/release/心跳）：并发退化
  为 `BEGIN IMMEDIATE` 文件锁（已在 transaction 里）。
- actor 保留为 events 的被动审计字段。
- 完成门：旧 router.db 迁移后 dashboard/status 正常；测试绿。

### P4：SKILL.md 重写与 playbooks

- 按设计稿 §3.6：薄 SKILL + 六份 playbooks；references/router-runtime.md
  的 Step/Apply 段落改写为原语内部机制；workspace-layout.md 保留。
- 同步 entity-pgen（:3, :23-24, :40, :65, :69, :82）、entity-env-build
  （:9, :154）的 router 相关表述；entity-nt2py 无需改。
- 完成门：contracts 测试更新后绿；四个 skill quick validation 通过。

### P5：实测验证

- m87 重跑 S1/S2 同场景；对照指标：record 原语进入率、status 首读率、
  总 token 消耗；adoption 度量规则已在 P2c 同步，不会产生误报。

## 4. 风险与顺序说明

- **顺序硬依赖**：P2a → P2b → P2c → P3；P4 可与 P3 并行，P5 最后。
  P2b 保持并存是为了让删除集中在 P2c 一次完成，中间任何时点仓库都可用。
- **最大改动面在 P2c**：约 35 个测试删除 + observability/evidence 两个
  工具 + evals U4。建议 P2c 单独一个 commit，便于回滚。
- **SSH 路径**：record 类原语在远端执行时复用 ExecutorClient 的内容寻址
  部署；m87（ssh + direct）是当前唯一真实验证环境，P2b 的 run-launch
  必须在 m87 冒烟一次再进 P2c。
- **remote.py 首次接线**：snapshot 工具写好但从未被生产调用，P2b 接
  `snapshot-source` 时按新代码对待（补测试）。

## 5. 迁移前需要拍板的决策点

1. `evidence.py validate_router_operation`：改为校验 record 落账事实，
   还是随 plan 协议退役（observability 不再做 operation 级校验）？
   倾向后者——校验职责已在 record 原语内部。
2. `--adopt-*` 认领外部作业：P2b 就做，还是等到真实场景需要再补？
   倾向 P2b 做——S1/S2 里 agent 都是绕过 router 自己跑的，认领是
   把这类既成事实纳入台账的唯一途径。
3. U4-interrupted-apply 用例：改写为打断 `record run-launch`（receipt
   恢复语义不变），还是直接退役？
4. store schema v2 迁移时 operations/steps 是导出归档还是直接丢弃？
