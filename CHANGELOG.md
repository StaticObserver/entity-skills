# Changelog

All notable changes to the Entity skills bundle are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The bundle is versioned with semantic versioning, starting at 0.x: the first
version considered production-satisfactory will be released as 1.0.0. Schema
versions (store, checkpoint, compat checker) are independent integer
compatibility contracts and are not the product version.

## [Unreleased]

## [0.7.1] - 2026-08-18

### Added

- `project init` 现在同时创建 `analysis/scripts/` 通用脚本库骨架（幂等，
  存量 project 再次 init 也会补建）。
- `record analysis` 增加 ssh 通道 manifest 证据探测的测试覆盖
  （`run_on_site` 假通道：happy path 落账 + 探测失败零写入）。

### Fixed

- env-build 生成的 `build-hdf5.sh` 克隆 HDF5 时把版本号的点替换成下划线，
  拼成不存在的 tag `hdf5-1_14_6`；HDF5 自 1.12 起 tag 使用点号格式，
  现直接使用 `hdf5-$VERSION`（如 `hdf5-1.14.6`）。

## [0.7.0] - 2026-08-03

Workspace 与 Computation Site 顶层模型落地（设计：
`design/workspace-and-computation-site-2026-08-03.md`，开发计划：
`design/workspace-development-plan-2026-08-03.md`）。公开模型变为
`Workspace → Project → Case → Identity → Evidence`：Workspace 是唯一
工作目录（projects/ 项目树、sites/ site 档案、.ledger/ 控制器状态，
自包含、可整体迁移后 `workspace adopt` 继续）；Project 是持有 source
authority 的容器；Case 拆为项目内一个意图明确的研究线索（Project
1:N Case）；Computation Site 是计算机器上的约定文件树
（`<site_root>/{deps,checkouts,projects}`）加 workspace 里的权威档案。
store schema 升级为 v3（projects 变为 project 实体，cases 带
project_uid 外键；`store migrate` 链式 v1→v2→v3，旧 root→case 1:1
绑定升级为每 project 一个默认 case）。

### Added

- Workspace 容器：`workspace init/adopt/where`；控制器 home 解析顺序
  `--ledger-home` > `ENTITY_WORKSPACE` > `~/.entity-ledger/active-workspace`
  指针 > 旧 `~/.entity-ledger`（兼容回退，打一次 deprecation 警告），
  snapshots 随 db 解析。workspace.yaml/project.yaml/sites/*.yaml 统一
  使用标准库实现的 flat+flow YAML 子集（无 PyYAML 依赖）。
- Project/Case 拆分：`project init`、`case init`（intent.md 与
  decisions.json 骨架）；`--case <slug>` 寻址贯穿
  status/show/render-run/snapshot-source/record/submission，单 case
  项目自动解析，多 case 省略时报错并列出可选 case。
- `record intent` 以 db 为准同步 case 目录的 intent.md，手工改动在
  dashboard 待决中标注漂移。
- Site 档案与文件树：`sites/<site>.yaml` 成为 site 信息权威（transport/
  scheduler/machine/site_root/projects/deps/notes）；`site sync`
  （档案 → db，db-only 只报告不删）、`site list/show` 合并视图、
  `site init`（目标机建 `<site_root>` 骨架 + `entity-site.yaml` 标记，
  幂等）、`site discover` 扩展（machine 节落档案、认领既有标记）。
- 新树路径推导：profile 带 `site_root` 时新 build/run/staging 落在
  `<site_root>/projects/<project>/{builds,runs,staging}/<case>/<id>`
  （layout `site-tree`）；无 `site_root` 的旧 profile 保持独立 roots
  推导并标注 `legacy-roots`，旧 Locator 保持可引用。
- deps 注册表：`site deps <site>`（人读 + `--json`）与
  `site deps-add --from-checkpoint`（confirm + compatibility pass +
  env.sh 证据齐备才落账，零写入否则）；env-build
  `entity_checkpoint.py create --from-registry` 按签名匹配 verified
  栈预填 selected（临场探测补缺，兼容性门禁不变）；`record build`
  的 payload 与 identity 带 `stack_id` 并在栈未登记时提示 deps-add。
- 迁移原语（agent 驱动迁移）：`workspace import`（本地收编 projects/
  ledger.db+snapshots/site-notes/旧绑定，dry-run 默认、冲突只报告不
  覆盖）、`site plan-migration`（只读盘点旧树 → 新树计划，在途 run
  标记 skip）、`record relocate`（移动后重新探测证据并更新 Locator，
  在途 run 拒绝，证据不符零写入，写 record.relocate 审计事件）。
- `record run-abort`:site 永久不可达或确认死亡的在途 run 的显式逃逸
  口——`--reason` 必填并落进 identity 与审计事件（actor 归因沿用
  现有机制）；仅对在途 run 可用，已终态报错零写入。`aborted` 加入
  终态词表：可 relocate、plan-migration 不再 skip、status --live 不
  再探测；`--reclassify` 不适用于 aborted(site 恢复后输出仍可用
  `record data` 盘点）。
- analysis 管理（identity 链第六维，`design/analysis-management-2026-08-05.md`）：
  `record analysis --script/--data/--params/--output-root
  [--env-stack] [--hardcoded-paths]`——执行自由、登记严格：脚本须来自
  项目通用脚本库 `projects/<p>/analysis/scripts/`（内容哈希），产物目
  录的 `analysis-manifest.json` 须存在且 data_id 与声称一致；
  `analysis_id = hash(data_id, script_hash, params)` 确定性推导、幂
  等；父 data 非 current 时 dashboard analysis 格显示 stale（读取时
  推导，历史 identity 保留）。dashboard analysis 格升级
  none/established/stale + hardcoded_paths 提醒；`show` 增加 analyses
  列表。deps 注册表加 `kind` 字段（build 默认 / analysis），
  `site deps-add --kind analysis` 以解释器存在性为门禁登记 Python 分
  析环境。
- `references/migration-guide.md` 迁移指南。
- typed gres 支持：site policy 新增 `default_gres`（格式
  `gpu[:type]:count`，如 `gpu:V100:1`，profile 校验拒绝坏值）；
  `render-run` / `record run-prepare` 新增 `--gres` 显式覆盖；解析
  顺序为显式 `--gres` > policy `default_gres` > 通用 `gpu:<N>`，解析
  结果记入 run identity 的 compute 并原样渲染进 sbatch；`site
  discover` 在建议分区只有一种 GPU 类型时建议 `default_gres`（多类型
  时警告需显式选择）。direct 后端忽略 gres（归一化为 ""）。

### Fixed

- astro gold run(pilot）实测暴露并修复：
  - `record run-launch` 对 site-tree profile（只有 site_root、无显式
    roots）报 "execution Site has no staging_root"——launch 路径改用
    `merged_execution_profile` 推导 roots(prepare/data 本来就走）;
  - slurm 终态探测的 sacct 调用缺 `-P`,real sacct 默认表格输出导致
    exit_code 永远解析为 None（测试假 sacct 始终管道分隔，掩盖了该
    bug；假件已改为诚实模拟）;
  - teardown abort 日志探测只认固定文件名（simulation.err/out):Entity
    以 simulation.name 命名日志且放在输出子目录，slurm 默认把 stderr
    并进 out——探测现覆盖 slurm-<job>.out（双向证据）与
    `<run_root>[/*]/*.err|*.out`;
  - dashboard pgen 格只扫项目根，0.7.0 source/ 权威布局下误报
    "没有 TOML 输入"——现同时扫描 project.yaml 登记的 source 目录。

### Added(rc 增量)

- `entityctl install --provider {codex,claude,kimi}`（可重复）：只把
  bundle 投影到指定 client；缺省保持三家全投。返回负载新增
  `providers` 记录实际投影的 client。
- env-build 构建脚本生成的 build_dir 防护：`compile.build_dir` 指向
  已存在且非空的目录时拒绝生成（中文报错说明重链/证据失真风险），
  显式 `--reuse-build-dir` 或 `--clean-build` 才放行——防止从上一轮
  复制 requirements 继承旧 build_dir 后静默重链已登记构建。
- `record run-prepare --run-id`：要求新推导的 run 等于 render-run 预
  览的 id——run_id 按（源、TOML、compute、build）内容寻址，不一致即
  证明 render 之后输入漂移，报错零写入，不再静默准备出第二个 run。
- 报错改进（中止轮 S1 复盘）:`case init` 的 "no local Site
  source_root covers the project" 现在给出可操作建议（登记本地 site
  档案、source_root 建议取 workspace 根而非整个 home、site sync);
  `workspace init` 发现目标是含 `entity-site.yaml` 的 Site 树根时报
  针对性错误（Site 是 ssh 执行端，workspace 应在开发机）。
- 文档：SKILL.md 新增"架构红线"节（控制器只在开发机、禁止把工具
  scp 到 site、workspace 位置先与用户确认）;
  `references/workspace-layout.md` 新增 site 档案格式节（flat-YAML +
  JSON flow 规则 + 带注释的完整 astro-streaming 示例）。
- 生产调用日志（passive invocation logging，与评测 trace 不同层）:
  四个 skill 的 CLI 入口（entityctl、ledger executor/remote 独立
  CLI、env-build 四个 CLI、pgen_preflight、inspect_nt2_data）每次实
  际调用追加一条 JSONL（时间/时长/exit_code/argv 脱敏/cwd/host 等）,
  默认 `~/.entity-skills/observability/invocations/<yyyy-mm>.jsonl`
  按月轮转，`ENTITY_SKILL_INVOCATION_LOG` 可覆盖；日志路径所有异常
  吞掉，宿主语义不变；四个 scripts/ 下字节相同的
  `_invocation_log.py`，字节一致性有测试防漂移；对 agent 不可见（不
  改 SKILL.md)。
- 调用日志修复批（同上评估报告）:`ENTITY_SKILL_INVOCATION_LOG=off`
  （大小写不敏感精确匹配）完全静默，仓库 tests/conftest.py autouse
  默认关闭——测试流量（曾占调用量 90%）不再污染生产统计；记录时
  best-effort 嗅探 agent 客户端环境变量（KIMI_/CLAUDE/CODEX 常见名）
  补 `agent_hint` 字段——只记变量名、不记值（防泄密），未命中省略该
  字段。四份拷贝同步。
- 错误 payload 新增机器可读 `"retryable"` 布尔（`status=="anomaly"`
  → true，其余 false）;SKILL.md 错误契约节写明只有 anomaly（瞬时/
  外部故障）值得原样重试，invalid_request/needs_decision 必须改变
  输入或升级给人。
- `record run-correct`（人工更正原语，B2 配套）:completed↔failed
  两个已落账终态之间的人工更正，`--reason` 必填并落进 identity
  (`correction` 节）与审计事件（from/to/reason)；在途 run 拒绝
  （先 run-exit 到终态），同态更正是 no-op。与 `--reclassify`（按
  日志证据重判）并存，互不替代。
- `record run-launch --resubmit`(I3):Ledger 提交的 job 已终态且
  失败时重新提交同一 run——先探测旧 job 确已死亡（在跑、gone 或
  探测不到终态都拒绝，提示先 run-exit)，再正常走 preflight+提交；
  新提交使用自己的 exactly-once 收据（`run-relaunch-<n>.json`,
  exactly-once 按"每次提交"计），旧 scheduler 记录移入 identity
  的 `prior_submissions`，事件与返回标注 `resubmit: true` 和
  `previous_scheduler`。不带旗标行为不变。

### Fixed(rc 增量)

- v3 bundle 读取 pre-workspace(v2/v1)store 不再以
  `IndexError: project_uid` Traceback 崩溃:`OperationStore` 打开既有
  db 时先校验 meta schema_version,不符即抛带迁移指引的
  StoreError(`entityctl store migrate`);doctor 把未迁移 store 作为
  诊断 warning 报告并跳过 export(原来 export 在 warning 逻辑之前就
  崩了)。单一检查覆盖 export/dashboard/facts/site 等全部
  OperationStore 读取路径。
- `entity_checkpoint.py create --merge` 丢失旧 checkpoint 的
  `paths.pre_commands`/`modules`/`extra_env`——regenerate 的 env.sh
  缺 module 加载；merge 现保留这些键（modules 与 derive_paths 从
  selected 各 entry 收集的 modules 取并集），且 `derive_paths` 会把
  依赖 entry 自带的 `modules` 收进 paths。
- 生产评估修复批（`design/skill-production-evaluation-2026-08-17.md`）：
  - 远端 executor 非零退出不再被吞成 "Site executor returned invalid
    JSON"：先判退出码，错误消息带 stderr 尾部（最后 ~500 字符）;
    零退出但 stdout 无 JSON 时才报 invalid JSON 并附 stdout 头部
    (~200 字符）。
  - `_require_case` 拆分误导性消息：项目路径未登记（no_project）明说
    "no project is registered at <path>"并提示改用新路径或
    `workspace import`，按 basename 匹配已登记项目并在消息里列候选
    （迁移后旧路径场景）；"项目已登记但无 Case"分支的建 Case 指引改
    为真实命令 `entityctl case init <project> <name>`(run-prepare 并
    不建 Case);store `get_site` 对未知 site_id 列出已登记 site 候选。
  - `record run-exit` 对在跑 run 的返回增加
    `detail: "run is still running; no state written"`。
  - `doctor --project-root` 不再撞 argparse 裸错误：doctor 是
    workspace 级诊断，接受该旗标并立即给出指引错误
    (invalid_request，指向 `status --project-root <path>`)。
- Slurm 终态分类修正（B2,sacct 终态词优先于退出码）:
  CANCELLED/TIMEOUT/OUT_OF_MEMORY 等非 COMPLETED 终态词一律记
  failed，即使退出码是 0:0（被 scancel/OOM 杀掉的 job 也能报干净
  退出码——polar_cap OOM run 因此被旧逻辑误记 completed);
  COMPLETED 或无调度器词（direct）维持退出码分类与 teardown-abort
  救援不变；终态词一并写进 run-exit 事件 payload
  (`scheduler_state`)。不新增终态。

### Changed

- **export JSON 的 projects 形状变化**（破坏性）：v2 的
  `{project_root, case_uid, updated_at}` 绑定行变为 v3 project 实体
  `{project_uid, slug, project_root, created_at, updated_at}`；cases 增
  加 `project_uid` 字段。消费 `entityctl export` 的脚本需同步。
- `references/workspace-layout.md` 重写为 Workspace + Computation Site
  布局契约；四个 SKILL.md 与 README 同步新模型；env-build 文档同步
  deps 注册表查找顺序与回写流程。
- `pgen_preflight.py` 的控制器定位改走统一的 `resolve_ledger_home`
  （workspace 感知，`--ledger-home` 显式入口不变）。
- `site-notes` 散文由 `site import-notes` 迁入档案 notes 节；
  `references/site-notes-template.md` 标注 deprecated。

## [0.6.1] - 2026-07-29

### Fixed

- `entity-pgen` write gate no longer routes managed writes into a dead end:
  the preflight refused every write inside a Ledger-registered Case source
  ("managed writes require a v5 pgen Goal") and bounced the request to a
  Ledger record primitive that does not exist — that Goal kind was retired
  with the plan/apply protocol. Writes inside the Case source authority are
  now allowed (`managed-write`) — the Ledger does not intervene in the PGen
  process; once the change settles, `entityctl snapshot-source` re-probes the
  tree and books the new source identity (re-`confirm` the input TOML before
  `record run-prepare`). Recorded artifact roots (build/run/data identities,
  the active run) stay fail-closed (`router-required`).
- Observability `validate_pgen_preflight` no longer fails real
  `managed-write` outcomes: it required an Action id, controller root, and
  Action-request envelope from the retired plan/apply protocol; it now
  requires only a Case identity.

## [0.6.0] - 2026-07-28

Skill rename: `entity-router` is now `entity-ledger` — the plan/apply
control plane is gone and the skill is a deterministic ledger of project
assets and facts, so the Router name no longer fit. The rename covers the
skill directory, all `entity_router_*.py` modules, the JSON contract kinds
(`entity-ledger.*`, receipt comment prefix `entity-ledger:`), and storage:
the home is now `~/.entity-ledger` with `ledger.db` (`ENTITY_LEDGER_HOME`).
Pre-rename storage is adopted automatically: `ENTITY_ROUTER_HOME` is still
honoured when `ENTITY_LEDGER_HOME` is unset, a legacy `~/.entity-router`
directory is renamed on first access, and a legacy `router.db` is renamed
to `ledger.db` when the store opens. The per-activity playbooks are
removed; their unique semantics (exactly-once launch receipts, external
job adoption, in-flight runs not occupying project state) live in
`SKILL.md`.

Case-centric restructure: the plan/apply control plane is replaced by
deterministic primitives. Agents plan the simulation flow; the CLI reads and
writes deterministic records, renders deterministic scripts, and probes
evidence — big flows are no longer wrapped in code.

### Added

- `entityctl status` human-readable dashboard: readiness board
  (source/pgen/build/run/data/analysis with evidence), run ledger, pending
  items, and derived next steps; `--json` preserves the machine contract.
- Primitive commands: `show`, `render-run`, `snapshot-source`, and
  `record build|run-prepare|run-launch|run-exit|data|intent`. Write
  primitives probe their own evidence before booking facts and fail with
  zero writes; `record run-launch` keeps exactly-once via receipts, runs a
  Slurm preflight before submitting, and can adopt externally submitted
  jobs (`--adopt-job` / `--adopt-pid`).
- `record intent`: the research intent is the only stored pointer, shown on
  the dashboard.
- `store migrate` v1→v2: archives legacy operations to
  `<ledger_home>/archive/`, then installs the slimmed store.
- `record run-exit` recognizes Entity's known harmless teardown abort: when
  the terminal exit code is non-zero but the run_root logs show both the
  final step reached (`Step: N ... [of M]` with `N >= M - 1`, ANSI escapes
  stripped) and a known glibc `malloc_consolidate()` abort signature, the
  run is booked `completed` with an `exit_anomaly` note (the real exit code
  is preserved). Missing or mismatched evidence keeps the run `failed`,
  exactly as before. The new `--reclassify` flag re-judges a run already
  booked `failed` from its log evidence alone (no scheduler probe), and the
  dashboard run cell annotates the anomaly.

### Changed

- Job submission no longer sets a walltime by default: `--walltime` now
  defaults to empty, the rendered sbatch carries no `#SBATCH --time=` line
  (the partition/QoS default limit applies), and the direct backend skips
  its timeout wrapper. An explicit `--walltime HH:MM:SS` behaves exactly as
  before, including format validation.
- `entity-ledger/SKILL.md` rewritten around the research workflow;
  control-plane internals moved to `references/ledger-runtime.md`.
- Store schema v2: drops the operations/steps tables and the whole
  Operation API; concurrency degrades to the `BEGIN IMMEDIATE` file lock,
  events remain as passive audit.
- Local Sites run the executor in-process: `ExecutorClient` calls the same
  validate/execute/verify logic with the same on-disk receipts, skipping
  the content-addressed script copy, the request envelope file, and two
  `python3` spawns per record step. SSH Sites are unchanged.
- The snapshot manifest walk now lives in one place
  (`entity_ledger_common.source_manifest`). The removed duplicate in
  `entity_ledger_remote.py` did not exclude `run-*` directories, so a
  source containing them could get two different snapshot ids depending on
  the path taken; snapshot ids of such sources change (content addressing
  simply writes a new archive).
- Site fingerprinting, identity lookup, and the pgen confirmation
  comparison are unified into shared helpers
  (`site_file_sha256`, `find_identity`, `load_simulation_confirmation`)
  instead of three near-identical copies.

### Removed

- The plan/apply protocol: `entityctl plan/apply/operation cancel`,
  GoalSpec and plan JSON schemas, the planner, the apply engine, and
  claim/lease machinery. Legacy operations are export-archived on migrate.
- Plan/apply-era dead code: `entity_ledger_purge.py` (the `data.purge`
  Action protocol had no producer), the executor kinds
  `build.register.v1` and the direct-backend preflight (no caller),
  `entity_ledger_remote.py`'s snapshot-install half, the duplicate
  `entityctl bundle install` command, and the `--router-home` CLI alias
  (the `ENTITY_ROUTER_HOME` environment variable is still honoured).

## [0.5.0] - 2026-07-22

Observability and reconciliation (Phase 3): out-of-band changes now surface,
drift fails, and skill adoption is measurable.

### Added

- `status --live` reconciliation: the report always carries a `divergences`
  list classifying out-of-band changes between the store and the scheduler:
  - `job_gone`: the recorded job is absent from `squeue`; `confirmed` is true
    when `sacct` also has no record, false when `sacct` is unavailable.
  - `state_mismatch`: the job reached a terminal scheduler state
    (`recorded: submitted`, `observed: <STATE>`) the router never saw.
  - `untracked_job`: a foreign scheduler job runs in the Case run root —
    evidence of control-plane bypass.
  Live status makes at most three bounded scheduler queries.
- `entityctl apply --refresh`: re-executes a completed `data` Goal plan so a
  stale `data-inventory.json` is rebuilt after run artifacts changed.
  Rejected for other Goal kinds. This closes the 0.4.0 known limitation.
- `doctor` hard failures (exit 2, `ok: false`, new `failures` list): client
  bundle installs that drifted from the runtime bundle, and stored Site
  profiles that fail validation.
- `doctor` warnings for leaked active Operations (crash leftovers holding a
  Case), each with the exact `entityctl operation cancel <id>` remedy.
- Skill adoption metrics: the phase-segmentation report
  (`tools/skill_observability/adapters/claude_phases.py`) now carries a
  `skill_adoption` section counting skill-script invocations
  (router/env_build/pgen/nt2py) versus raw equivalents (sbatch/srun/scancel/
  scheduler polls/build tools), direct `sqlite` control-plane surgery, and a
  `skill_call_share` ratio — the clean-comparison metric required by the
  1.0.0 candidate criteria.

### Changed

- The `data.inventory.v1` executor Step always re-walks the run root instead
  of short-circuiting on a previous verified receipt; inventory is a pure
  function of the current run root, which is what makes `--refresh` work.

## [0.4.0] - 2026-07-22

### Added

- New Goal kinds `build` and `data` (Phase 2 e2e coverage):
  - `build` registers an env-build-produced build into the identity chain.
    Hard gates at plan and apply: the checkpoint must have
    `compatibility.status == "pass"` and a `decisions.parameters` confirmation
    digest. The registered build identity feeds subsequent run Goals without
    an explicit `executable`.
  - `data` inventories a run's outputs into a content-hashed
    `data-inventory.json` and advances `current.data_id` / readiness.
- Executor Step kinds `build.register.v1` and `data.inventory.v1`.
- Gates added: run Goal planning now requires a simulation-parameter
  confirmation record (`<input>.decisions.json` written by
  `pgen_preflight.py confirm`) whose `input_sha256` matches the current TOML;
  missing or stale records fail planning with `needs_decision` (Phase 1.5).

### Changed

- Plans now carry `goal_kind`; `validate_plan` checks per-kind key sets and
  Step schemas. Plans written by 0.1.0 remain valid (missing `goal_kind`
  reads as `run`) but should be re-planned.

### Known limitations

- Re-inventorying a run whose outputs changed produces the same Plan, which
  resolves to the completed Operation; a refresh path lands with the
  reconciliation work in 0.5.0.
- `analysis` Goal is not implemented yet; analysis stays with entity-nt2py
  and router records only.

## [0.3.0] - 2026-07-22

### Added

- entity-env-build: build parameter confirmation gate (Phase 1.5, hard fail).
  `entity_checkpoint.py confirm <requirements> --checkpoint <checkpoint>
  --by <actor> [--confirm-defaults]` records `decisions.parameters`
  `{digest, confirmed_by, confirmed_at, defaults, card}`; the compatibility
  check `parameters.confirmation` fails when the record is missing or the
  digest no longer matches the current requirements.
- entity-pgen: `pgen_preflight.py card <input.toml>` prints the simulation
  parameter card; `pgen_preflight.py confirm <input.toml> --by <actor>
  [--confirm-defaults]` writes `<input>.decisions.json`.

## [0.2.0] - 2026-07-22

### Added

- `entityctl site discover <site>`: enumerates Slurm partitions and QoS via
  `sinfo`/`sacctmgr` and suggests `policy.default_*` values (read-only).
- `templates/site-profile.schema.json` documenting the Site profile contract.
- `entityctl submission create/verify`: submission fingerprints are always
  recomputed by the tool from the final artifacts; `verify` reports stale and
  missing artifacts and exits non-zero on drift.
- Executor anomaly remediation: scheduler rejections (invalid QoS/partition)
  now carry the exact repair path (`entityctl site discover` + policy fix).

## [0.1.0] - 2026-07-22

First disciplined release. Baseline: the Entity Router v5 architecture lineage
(store schema 1) with the fixes below. Development plan:
`design/router-development-plan-2026-07-22.md`.

### Added

- `entityctl operation cancel <id>`: terminal escape hatch for pending/running
  Operations; releases the Case so a different Plan can proceed.
- `entityctl store migrate`: store schema migration entry point (shell; no
  schema migrations exist yet). Doctor reports the store schema version and
  points here on mismatch.
- `bundle_version` reported alongside `bundle_hash` in `entityctl doctor` and
  install receipts; single source at `skills/entity-router/VERSION`.
- entity-env-build: `mpi.openmpi_min_version` compatibility check — OpenMPI
  must be >= 5.0.0 when selected (fail below; warn when unrecorded).
- Gates added: re-applying a Plan after a failed Apply reopens the Operation
  and resumes committed Steps instead of deadlocking the Case.

### Fixed

- entity-router executor sbatch now invokes `srun <exe> -input <file>`;
  Entity ignores positional arguments and previously opened the default
  `input` file, burning the first submitted job.
- A failed Apply no longer leaks an active Operation; it finishes as
  `anomaly` and releases the Case (previously forced direct sqlite surgery).
- Missing-store error no longer points at the nonexistent `entityctl migrate`.
- `status --live` degrades to cached controller state with a warning when the
  scheduler query fails, instead of exiting 2.

### Changed

- User-facing "Router v5" strings renamed to plain "Entity Router"; v5 remains
  only as the internal architecture lineage and store schema integer.
- Doctor output keys `v5_store`/`v5_store_available` renamed to
  `store`/`store_available`.
