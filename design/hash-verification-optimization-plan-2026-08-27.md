# Entity Skills 0.7.2 Hash 与校验机制优化方案

日期：2026-08-27  
状态：WP0/WP1 已实施（0.7.3）；WP2–WP5 仍为 0.8.0 计划  
适用范围：`entity-ledger`、`entity-pgen`、`entity-env-build`、bundle 安装与观测工具

## 1. 结论

0.7.2 的问题不是单纯“SHA-256 太多”，而是语义身份、字节证据、资源位置、
调度尝试和观测去重共用了相似的 hash 机制。结果同时出现两类失真：

1. 路径、QoS、walltime、缓存文件等偶然变化造成身份漂移；
2. 原始数据即使付出了全量逐文件 hash 的成本，`data_id` 却没有绑定该 inventory，
   数据变化后仍可能保留同一身份。

本方案不以减少 hash 数量为目标，而以“每个 hash 只承担一种职责”为目标。默认路径
使用与风险相称的验证强度；只有封存、迁移、发布或明确要求字节级真实性时，才读取大型
产物的全部内容。

## 2. 目标与非目标

### 2.1 目标

- 取消大型、仍在增长的数据目录的默认全量内容扫描；
- 让每个稳定 ID 只由对象的语义字段决定；
- 将 Site/绝对路径建模为可变 placement/Locator，而不是混入内容身份；
- 将科学运行定义、一次具体执行和调度提交尝试拆开；
- 让数据变化必然产生新的数据 revision，并使下游 analysis 正确 stale；
- 保留远程执行、搬运、封存和发布边界上的强完整性校验；
- 兼容已有 0.7.2 Case、identity、receipt 和分析记录，不重写历史事实。

### 2.2 非目标

- 不更换 SHA-256 算法；当前问题主要是 payload 和调用时机，而不是算法强度；
- 不把 mtime 或“最新文件”提升为强内容身份；
- 不要求普通运行完成后立刻生成可发表级别的数据封存证明；
- 不删除 append-only 事件、receipt、actor provenance 或安全路径边界；
- 不在本轮重写整个 Ledger schema 或 Router 工作流。

## 3. 统一术语与规则

所有新 digest 必须声明以下属性，禁止继续添加无名的 `canonical_hash({...})`：

| 属性 | 含义 |
|---|---|
| `purpose` | `identity`、`evidence`、`transfer` 或 `observation` |
| `schema` | 被 hash 的规范 payload 名称及版本 |
| `scope` | 文件、目录、语义对象或一次调用 |
| `cost_class` | `small`、`bounded`、`large` |
| `gate` | 是否允许阻断状态推进 |
| `remediation` | 不匹配后的明确恢复动作 |

四类 hash 的边界如下：

| 类别 | 用途 | 是否生成对象身份 | 是否可包含路径/时间 |
|---|---|---:|---:|
| 语义身份 `identity` | 判断是不是同一个科学或软件对象 | 是 | 否 |
| 字节证据 `evidence` | 证明某次观察到的文件字节 | 否 | Locator 可作为证据属性，但不进入对象 ID |
| 传输校验 `transfer` | 校验上传、下载、复制或远程部署 | 否 | 可以绑定源和目标 Locator |
| 观测指纹 `observation` | 日志去重、异常折叠、调用统计 | 否 | 可以，但只能影响展示和去重 |

语义身份 payload 必须包含 `kind` 和 `schema_version`，形成 domain separation。例如：

```json
{
  "kind": "entity.run-spec",
  "schema_version": 2,
  "build_id": "build-...",
  "semantic_input_digest": "sha256:...",
  "numerics": {"mpi_ranks": 8, "gpus": 8},
  "replicate_key": "default"
}
```

## 4. 目标身份模型

现有 `source -> build -> run -> data -> analysis` 保留为用户可见主链，但内部改为带类型的
provenance DAG：

```text
source_spec ──> build_spec ──> build_artifact
                                  │
semantic_input ───────────────────┼──> run_spec
                                  │        │
                                  │        └──> run_execution ──> data_revision ──> analysis
                                  │                    │
                                  │                    └──> submission_attempt[*]
                                  │
                                  └──> placement[*] = {site_id, path, verified_at}
```

### 4.1 Build

- `build_spec_id = H(source_id, requirements/checkpoint semantic digest,
  toolchain target, stack_id, build options)`；
- `build_id = H(build_spec_id, executable_sha256)`；
- 可执行文件绝对路径不进入任一 ID；
- Site 和路径记录为 `placements[]`。如果 ABI 或 GPU 架构影响构建，它必须以明确的
  toolchain/target/stack 字段进入 `build_spec_id`，不能用 `site_id` 代替。

### 4.2 Run 与 submission

- `run_spec_id = H(build_id, semantic_input_digest, numerics, replicate_key)`；
- `run_id = H(run_spec_id, execution_site, execution_generation)`；
- `submission_attempt_id = H(run_id, scheduler_request_digest, attempt_index)`；
- run root、staging root 是从 ID 派生或记录的 Locator，不进入 `run_spec_id`；
- partition、QoS、account、submit user、walltime 和 scheduler job ID 只属于
  `submission_attempt`；
- MPI ranks、线程数、GPU 数和会影响数值顺序的并行拓扑属于 `numerics`；launcher
  名称、队列和纯资源上限不属于 `numerics`。

`replicate_key` 使用户能够显式创建同参数重复实验；`execution_generation` 区分“在原目录
续跑/重投”和“从头生成一份新数据”。系统不能再用修改 walltime 的方式偶然制造新 run。

### 4.3 Data

数据分为两个层次：

1. `data_revision`：对当前可见数据的一次有类型 inventory，允许快速生成；
2. `data_release`：用户明确 seal 后得到的强完整性版本，用于迁移、归档、发布或高保证分析。

```text
data_revision_id = H(run_id, inventory_schema, inventory_digest, integrity_level)
data_release_id  = H(data_revision_id, strong_manifest_digest)
```

`observed_at`、inventory 文件自身路径和目录 mtime 不进入 ID。每次 inventory 内容变化都创建
新的 `data_revision_id`；不得覆盖旧 identity 后仍声称是同一数据身份。

支持三种完整性级别：

| 级别 | 默认场景 | 内容 |
|---|---|---|
| `metadata` | 活跃运行、日常盘点 | 相对路径、类型、大小、BP step/变量元数据、格式可读性 |
| `trusted-storage` | 存储系统提供 checksum | 记录 checksum 算法、来源和可信边界，不重复读取文件 |
| `strong` | seal、迁移、归档、发布 | 对纳入 manifest 的全部文件计算或验证强内容摘要 |

默认 `entityctl record data` 使用 `metadata`。新增显式入口：

```text
entityctl record data --run-id <id> --integrity metadata
entityctl data seal --data-id <revision> [--checksum-source storage|sha256]
entityctl data verify --data-id <release>
```

分析记录必须保存父 `data_revision_id`、完整性级别和 inventory evidence。普通探索允许绑定
`metadata` revision；需要发表级复现保证的工作流可把 `strong` 设为 acceptance gate。

### 4.4 TOML 与参数确认

参数卡同时保存两个摘要：

- `document_sha256`：原始 TOML 字节，仅用于证据、staging 和审计；
- `semantic_input_digest`：完整 TOML 解析树的规范摘要，用于 run/确认身份。

规范化必须保持 TOML 类型差异，例如 `1` 与 `1.0` 不得自动合并；table key 排序、数组顺序
保持，注释和空白不参与摘要。任何语义值变化都重新确认；只改格式或注释不重新确认。
当前参数卡的精选物理字段继续用于人类审阅，但不能代替完整语义摘要。

### 4.5 Bundle

以发布时生成的 `BUNDLE-MANIFEST.json` 代替运行时无边界目录遍历：

- manifest 只列出发布所包含的、Git 跟踪的运行文件；
- `.pytest_cache`、`__pycache__`、日志、临时文件和测试产物不进入 bundle identity；
- install 只复制 manifest 中的文件并逐项验证；
- doctor 验证 manifest 摘要和列出的文件，不把环境噪声报告为版本 drift；
- 已发布的 content-addressed bundle 目录应只读；hot patch 必须形成新的 bundle digest，
  版本字符串相同也不能覆盖原目录。

## 5. 保留的强校验

以下校验风险收益比合理，不在优化中删除：

- source snapshot 的规范 manifest 和内容摘要；
- build executable 的内容摘要；
- run prepare 时实际 staged TOML 的字节校验；
- 本地到远程 executor 的上传前后校验；
- receipt、plan envelope 和幂等 effect identity；
- relocate、复制、下载和归档边界的源/目标校验；
- analysis 脚本与产出 artifact 的摘要；
- 非阻断式 observability fingerprint。

可以缓存 source manifest 以避免同一操作内重复扫描，但缓存命中必须绑定目录快照条件，并在
写入或状态不明时失效。这里的优化优先级低于数据 inventory。

## 6. 实施工作包

### WP0：建立 hash registry 和性能基线

1. 枚举生产代码中的所有 hash 调用，登记 purpose、payload、gate 和 cost class；
2. 增加统一的 domain-separated digest helper；
3. 对小目录、典型 BP5 和多 TB 估算场景记录读取字节数、文件数和耗时；
4. 禁止新的未登记大型递归内容 hash。

交付物：`hash-registry.json`、单元测试、基线报告。该阶段不改变现有身份。

### WP1：先修复数据路径

1. 将 `data.inventory.v1` 拆为 metadata inventory 与显式 strong seal；
2. inventory manifest 加入 schema、probe version、integrity level 和规范摘要；
3. `data_id` 改由 inventory revision 生成，内容增长时创建新 identity；
4. current data 改变时，既有 analysis 通过 parent mismatch 自动 stale；
5. 保留旧 manifest 读取器和 v1 data identity。

这是最高优先级：它同时消除最大的 I/O 成本和当前最危险的“假内容身份”。

### WP2：拆分 run、submission 和 Locator

1. 将现有 `compute` 分成 `numerics` 与 `scheduler_request`；
2. 引入 `run_spec_id`、`submission_attempt_id` 和显式 replicate/generation；
3. 从稳定身份中删除 executable path、run root、QoS、partition、submit user 和 walltime；
4. 调整 exactly-once/recovery，使其按 run + submission attempt 查询，不削弱防重复提交；
5. dashboard 同时显示“科学运行”和“第几次调度尝试”。

### WP3：重构 build identity 与 placement

1. 引入 `build_spec_id`；
2. build artifact 由 spec + executable bytes 定义；
3. relocate 只新增或更新 placement，不改变 build identity；
4. 兼容旧 build identity，首次重新登记时生成 v2 identity，不回写历史记录。

### WP4：TOML 语义摘要

1. 使用完整 TOML 解析树生成稳定、保类型的 canonical representation；
2. 参数确认改由 `semantic_input_digest` 控制失效；
3. staging 仍比较 `document_sha256`，保证实际运行字节与 manifest 一致；
4. 更新 U2 parameter-rerun oracle，使其分别检查语义绑定和字节证据。

### WP5：发布 manifest 和剩余去重

1. 构建 `BUNDLE-MANIFEST.json` 生成、安装、doctor 验证链；
2. 排除缓存和运行时垃圾；
3. 合并同一事务内重复的 source tree manifest 计算；
4. 依据 registry 删除无消费方、无 gate、无审计价值的重复摘要。

## 7. 兼容与迁移策略

- 所有新 identity payload 增加 `identity_schema: 2`，旧记录隐式视为 v1；
- 不重算、不删除、不“升级”历史 ID；历史 evidence 保持原样；
- 新记录走 v2，current pointer 可以自然前移到 v2 identity；
- CLI 查询同时接受 v1/v2 ID；导出中明确标出 schema 和 integrity level；
- v1 `data_id` 显示 `integrity: legacy-unknown`，不能冒充 sealed；
- 旧 analysis 仍可读取；只有当 current data 前移时才按既有 parent 规则显示 stale；
- 迁移期间提供 feature flag，但数据库写入只能使用一个 identity 版本，避免双写分叉；
- rollback 只关闭 v2 生成，不删除已经生成的 v2 identity。

## 8. 验收标准

### 8.1 正确性

- TOML 只改注释/空白：`semantic_input_digest` 和 `run_spec_id` 不变，
  `document_sha256` 改变；
- TOML 任一值或类型变化：语义摘要变化并触发重新确认；
- executable 仅搬家：build ID 不变，placement 改变；
- partition/QoS/walltime 变化：run ID 不变，submission attempt ID 改变；
- MPI/GPU 数等 numerics 变化：run spec ID 改变；
- 数据新增、删除、大小或 BP metadata 变化：产生新 data revision，旧 analysis stale；
- cache 文件新增：bundle identity 不变；manifest 内运行文件变化：bundle 验证失败；
- seal 后任一字节变化：strong verify 失败，且不覆盖原 release identity。

### 8.2 性能

- 默认 metadata inventory 读取的文件内容字节数接近零，只读取目录项和必要格式元数据；
- 默认 inventory 的复杂度以文件数/metadata 量为主，不以数据总字节数为主；
- `strong` 模式明确报告计划读取字节数，并在执行前显示模式和范围；
- 普通 `record data` 不因 TB 级数据量隐式触发 TB 级读取；
- bundle doctor 的工作量只与 manifest 中发布文件有关。

### 8.3 安全与恢复

- 中断发生在 `sbatch` 后、receipt 前时，仍能发现并收养同一 submission attempt；
- 更换 walltime 后不会误收养不匹配的新 attempt；
- 远程 executor、staged input、复制和 relocate 的强校验保持通过；
- v1 Case 可以不迁移数据库直接查询、继续和导出；
- 全量测试、fake Slurm、SSH canary 和至少一个真实 BP5 metadata inventory 通过。

## 9. 发布顺序与停止条件

建议以一个小版本完成 WP0-WP1，另一个小版本完成 WP2-WP5，避免一次性改变全部身份语义：

1. `0.7.x`：registry、性能观测、metadata inventory、v2 data revision；
2. `0.8.0`：run/submission/build identity v2、TOML 语义摘要、bundle manifest；
3. 一个完整版本周期后，才考虑停止新建 v1 identity；读取兼容长期保留。

出现以下任一情况必须停止发布：

- v2 无法区分 data growth 与同一 revision 的重复盘点；
- exactly-once 提交恢复能力下降；
- identity migration 会覆盖历史记录；
- metadata inventory 被文档或 UI 错称为强内容校验；
- 大型数据默认路径仍读取全部 payload 字节。

## 10. 需要在实施前确认的设计决策

1. 哪些工作流必须把 `strong data release` 设为硬门槛：发表、跨站迁移、长期归档，
   还是由 Case policy 自定义；
2. `execution_generation` 是用户显式命名，还是 Ledger 分配的单调序号；
3. Site 提供的 checksum 哪些可被列入 `trusted-storage` 信任清单；
4. bundle manifest 是否包含测试和设计文档，还是只发布运行时 skill 内容；
5. `numerics` 的最小稳定字段集，需要用 Entity 实际启动方式和并行分解行为确认。

这五项不影响 WP0；其中第 1、2、5 项必须在 WP1/WP2 合入前形成固定契约。
