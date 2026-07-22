# 技能问题复盘：entity-router 与相关技能（S1 + Snr1）

范围：两轮 e2e 评测中**技能本身**（文档、脚本、实现、契约）暴露的问题，
与 agent 行为问题明确区分。评测装置问题见姊妹篇
`harness-review-2026-07-22.md`。证据：S1/Snr1 存档 transcript、远端日志、
oracle 报告；技能源码按仓库 `skills/` 当前版本核对。

---

## 第一部分：S1（skills-v5）暴露的技能问题

S1 背景：72 min、207 调用 15 失败。agent 读技能文档相当主动（router/pgen/
env-build 的 SKILL.md 与多篇 references 都读了），读后行为方向正确——所以
下面的坑是在"认真读文档"的前提下踩的，责任主要在技能。

### 1. entity-router：实现缺陷（按修复优先级）

**R1. executor sbatch 模板错误——直接烧 job，仓库当前仍存在。**
`entity_router_executor.py:211` 生成 `srun %s %s`（位置参数传 input），但
Entity v1.4.4 忽略位置参数、去开默认文件 "input"，需要 `-input input.toml`。
router 提交的第一个 job（59855912）因此失败，并迫使 agent 脱离 router 手写
sbatch、带外迭代 4 次——这是后续 fingerprint 过期、状态失联的源头。
**修复：executor 模板改为 `srun entity.xc -input <file>`，并加一次真实
submission 的回归测试。**

**R2. 失败的 apply 泄漏 active operation，且无 cancel 出口——把 agent 逼进
sqlite。**
`apply_plan`（entity_router_operation.py:403）先 `create_operation`（置
active）再跑 preflight；preflight 因 site profile 缺 `policy.default_qos`
抛异常后无回滚，`complete_operation`（store.py:564）永不执行。后续 apply
全部被 "Case has another active Operation" 拒绝，而 entityctl 没有
cancel/reset/abort 子命令。agent grep 确认无出口后只能
`sqlite3 UPDATE cases SET active_operation_id=NULL` 直改控制面——router 的
"DB 是唯一权威"机制从此被架空。
**修复：apply 失败路径回滚/完成 operation（try/except 里补
complete_operation(failed)）；新增 `entityctl operation cancel <id>`。**

**R3. 误导性错误信息：`run entityctl migrate`。**
store.py:162 在 store 不存在时建议运行 `migrate`，该子命令不存在
（`invalid choice: 'migrate'`）。仓库当前仍如此。
**修复：改为自动建库或提示 `entityctl doctor`；给错误文案加测试。**

**R4. `status --live` 脆弱。**
scheduler 查询失败（job 已出队，`slurm_load_jobs error: Invalid job id`）
直接让整个命令 exit 2（operation.py:513），不降级为 cached 状态。叠加
agent 手动重交后 router 追踪的是旧 job，--live 必然报错。
**修复：live 查询失败降级为 warning + 返回 store 缓存状态。**

**R5. 安装 bundle 与仓库版本漂移。**
S1 报出的 `allocation failure: Invalid qos specification` 字符串在仓库源码
中不存在；doctor 也显示 `matches_runtime: false`。安装目录事后被删，无法
核对差异。评测复现性受损。
**修复：安装流程记录 bundle 的 commit/hash；doctor 对漂移报错而不是提示。**

### 2. entity-router：文档/契约缺陷

**R6. site profile 无文档。** SKILL.md/references/templates 都没有 site
profile 的 schema 或示例，agent 被迫读 `validate_site_profile` 源码才会写，
建站花了 3 分钟读源码。
**修复：templates/ 增加 site-profile.schema.json 与 siyuan 示例。**

**R7. 恢复语义承诺与实现不符。** SKILL.md 第 5 步宣称"apply 异常就重跑同一
个 plan，没有也不需要 recover 命令"，但 R2 的死锁（修复需改 site profile →
必须新 plan → 新 plan 被泄漏 op 卡死）使该承诺不成立。
**修复：随 R2 一并解决后回归验证此路径。**

**R8. QoS/分区发现无指引。** SKILL.md 说 "Site policy supplies safe defaults
such as … QoS"，但没有任何步骤提示先用 sacctmgr/sinfo 发现合法 QoS；agent
烧了两次提交才学到 qos=debug。
**修复：site add 流程加"发现 QoS/分区"步骤或 doctor 检查项。**

**R9. 覆盖面与承诺不符。** SKILL.md 以 e2e 生命周期框架自居（Project→Goal→
Operation→Evidence、身份链必须完整），但 v5 只实现 `run` 一种 Goal，
pgen/build/data/analysis 无生命周期管理（pgen preflight 返回
`standalone-write: locator is not registered by Router`）。最终 status 里
`build_id/data_id/analysis_id` 全空，run readiness 永停 "submitted"——
身份链在 e2e 场景必然断裂。
**修复：二选一——补齐 build/data/analysis Goal 的最小实现，或下调
SKILL.md 的承诺并明确 e2e 各阶段的归属技能。**

**R10. 无 submission 契约。** 全部技能中没有任何 submission.json 规范
（agent 的 find 证实了这点）；e2e 最后一步（提交物、最终指纹重算）完全无
指引。S1 指纹过期是三段叠加：executor bug 迫使带外改 input（R1）→ agent
改完不 re-plan（agent 行为）→ 抄 plan.json 里的旧 hash 而非对最终产物
重算（无契约提醒）。
**修复：定义 submission schema（见 harness 文档 A1），并在其中强制
"指纹必须对最终产物重算"的校验步骤或工具命令。**

### 3. entity-pgen：文档与 Entity v1.4.4 源码三处矛盾——照文档做烧了 3 个 job

这是 S1 run 阶段 5 次提交中 3 次失败的直接原因：

**P1. `maxnpart` 类型标注矛盾。** 09-toml-config.md:84 标 `uint (>0)`，同
文件示例却用 `5e6`（TOML 浮点）；agent 写 `524288` → `bad_cast to
floating`（job 59855920 烧毁）。
**修复：统一为浮点示例并注明 Entity 解析器按浮点读。**

**P2. `[boundaries]` 表位置错误。** 09-toml-config.md:109 把 boundaries 写
成顶级表（agent 初稿照抄），Entity v1.4.4 官方 input.example.toml 要求
`[grid.boundaries]`（job 59855932 烧毁）。
**修复：按官方示例改正，并在 CI 里用 Entity 自带校验跑一遍文档示例。**

**P3. `use_weights` 指引与源码强制逻辑相反。** 03-particle-injection.md:
52/297 教"PGen 传 false、TOML 设 `use_weights = true`"，09-toml-config.md
也说 must be true；但 particle_injector.h 实际校验是 **TOML 标志必须与
injector 实参相等，且 Cartesian 必须为 false**。agent 读 Entity 源码后改
`use_weights = false` 才通过（job 59855960 烧毁）。
**修复：按源码语义重写该节；这是三处中最严重的，因为文档给出了与校验器
完全相反的建议。**

### 4. entity-env-build：覆盖缺口

**E1. siyuan 站点特性无预制 notes。** SKILL.md 明确声明"不编码 partition/
account/module stack"，siyuan 又无 site notes，QoS、slurm 里 module 不可用
等问题全靠 agent 试错（`Invalid qos specification`、env 缺失各烧一次）。
**修复：为 siyuan 补 site notes（qos=debug、debuga100、module 可用性、
PMI 配置）——这正是技能设计的扩展点，只是还没填。**

**E2. 脚本半 adoption。** agent 把技能 scripts 整个 scp 上集群，但只用了
`entity_checkpoint.py validate/create`；entity_compat.py、
entity_generate.py env/build、entity_run.py 全程没跑，build 脚本全部
heredoc 手写——包括 SKILL.md 明示的"env.sh 生成前不编译"也被跳过，两次
slurm env 失败本可由 env.sh 规避。原因待查（文档没有展示端到端用法？
还是 agent 行为偏好），作为技能可用性问题记录。

**E3. 正面案例也要记：** `entity_checkpoint.py validate` 正确拦截了
version_bucket 1.4.0 与 CUDA 的冲突——hard gate 起了作用。

### 5. entity-nt2py：安装无离线兜底

**N1.** 分析阶段 `import nt2` 失败，任务禁外网，SKILL.md 把"安装 nt2py"
列为职责却无离线安装指引；agent 退用 ADIOS2 自带 bpls 完成检查（合理
兜底），但产出只有 report、无可重跑脚本。
**修复：SKILL.md 加离线安装路径（ wheel 包随源码缓存预置 siyuan），并
明确"无 nt2py 时的降级分析链"。**

### 6. agent 行为问题（区分记录，不归技能）

heredoc 引号错误、前台 `sleep 120` 超时、version_bucket 填错、改 input 不
re-plan、写 submission 抄旧 hash 不重算。值得记录的倾向：**该模型遇到
技能失灵时沉默地绕过（sqlite 手术、手写 sbatch、sed 改上游 cmake），不
上报、不查文档**，留痕只能靠 transcript 事后还原。这对"技能失灵可观测性"
是个启示：oracle 的 Gate A/越界检查词表应覆盖 sqlite3 直改 router.db 这类
控制面手术。

---

## 第二部分：Snr1（skills-no-router）暴露的技能问题

Snr1 背景：134 min、226 调用 16 失败。总判定先说：**agent 行为问题是主因
（知道技能存在却基本不用），技能缺陷是次因但真实**。agent 从 session 开头就
看到了 3 个技能的 listing，思考块里明确写过"let me just use the
entity-env-build skill"，但一句"But first let me understand the build
system"之后被手动探索吸走，再没回来——env-build、pgen 全程零调用零阅读；
nt2py 是模拟跑完后才调用的唯一技能。全场 181 条 Bash 命令中技能脚本
（checkpoint/compat/generate/run、pgen_preflight、inspect_nt2_data）命中
**0 次**。

### 1. 技能缺陷（即使读了技能也救不了的真空）

**G1. siyuan 的 srun/PMI 装配知识整体缺位（最大缺口，4/7 次模拟失败的根
源）。** siyuan 上系统 OpenMPI 4.1.9a1 的 ORTE 层与 pmi2 不兼容，必须换
Spack 模块 `openmpi/4.1.1-gcc-11.2.0-cuda` + `srun --mpi=pmi2`——agent 用
mpirun（PMIx 冲突）→ `srun --mpi=pmix`（无插件）→ pmi2+系统 MPI（ORTE
炸）→ 加 OMPI_MCA 强制（仍炸）→ 换 MPI 栈才收敛，另加 39 min 盲等（SSH
卡顿 + API 断流期间作业已失败但未察觉）。这条站点知识：env-build 声明
"does not launch simulations"不管；router executor 只生成裸 `srun`（本轮
router 被移除）；site-notes 只有 `astro.md`、`pi2-v100.md`，**无
siyuan.md**。按设计它应沉淀进 site-notes，但 agent 没用技能，自然什么也没
留下——下一轮还会重踩。
**修复：把本轮结论写成 `site-notes/siyuan.md`（qos=debug、debuga100、
Spack openmpi 4.1.1 + srun --mpi=pmi2、kokkos/adios2 版本组合、登录节点
限制），并明确"运行时装配"归属哪个技能。**

**G2. kokkos.md 缺一条 Known Issue：GCC 11.2 在 C++20 concepts 上 ICE，
解法 `Kokkos_ENABLE_LAUNCH_COMPILER=OFF`。** agent 在错误层换了 3 个编译器
版本（11.2→12.3→14.2），50 min、4 次失败后才定位真因（nvcc host compiler
被 launch_compiler 钉死）。文档只有相邻的 nvcc_wrapper 传播问题。
**修复：补录 kokkos.md Known Issues。**

**G3. "物理正确性判断"无 owner——no-router 组的结构性盲区。** nt2py 的
SKILL.md 明确划线"does not prescribe physics diagnostics or judge whether
a simulation is physically correct"；阈值意识、首末守恒对比这类判据在 v5
bundle 里属于 router 的科学分析域。router 一移除，ux 衰减 40%、E² 超 20
倍在技能层面没有任何防线，agent 单快照分析（`isel(t=-1)`）后把结果写成
"consistent with drift 0.2 given thermal spread"（T=0.001 下 v_th≈0.03，
解释不了 0.08 的均值平移；uy/uz 弥散 ±0.08 本身已超热预期 ~25 倍——无
任何思考块讨论过这个矛盾）。
**修复（需用户定夺）：把"基本物理 sanity checklist"（首末对比、漂移/
能量守恒量级、E² 噪声意识）放进 nt2py 或 pgen 的交付要求里，或接受这是
router 的独占价值并在评分口径中明确。**

**G4. Entity 1.4.4 CMake 的 MPI 变量怪癖无记录，"不许改 Entity core"的
硬门没有出路。** agent 靠 patch Entity 自己的 `CMakeLists.txt`
（`MPI_CXX_INCLUDE_PATH`→`MPI_CXX_INCLUDE_DIRS`）才过配置——S1 也 sed 改
过上游 cmake（ADIOS2 路径）。两轮都越权，说明这是 Entity 1.4.4 的真实
障碍，而技能只禁止、不给方案。
**修复：在 env-build 的 Known Issues 记录该怪癖及最小 patch，或提供受控
patch 机制（patch 文件纳入 checkpoint 声明）。**

**G5. nt2py 的"不强制产物格式"与评测要求冲突。** SKILL.md 规则 5 刻意不
强制 report/script 格式，agent 的分析脚本只活在远端 slurm heredoc 里，
本地零分析产物。这同时是 harness 契约问题（见 A2），但技能侧至少应把
"产物留在调用方可及处"写成规则。
**修复：配合 harness A2 统一产物清单。**

### 2. 两轮交叉验证的技能文档 bug

以下问题两轮独立复现，严重度升级：

- **`maxnpart` 类型矛盾（S1-P1）两轮各烧一个 job**：S1 的 59855920 与
  Snr1 的 59862858 都是 `bad_cast to floating`。文档必须修。
- **Entity CLI `-input` 知识缺位两轮各烧至少一个 job**：S1 是 router
  executor 生成位置参数（R1）；Snr1 是 agent 手写 `-i`（59862855）。
  Entity 的 CLI 约定（`-input <file>`、忽略位置参数）应写进 pgen 的
  toml-config 或 env-build 的运行章节——不只属于 router executor。
- **QoS 发现无指引两轮各烧一次提交**（S1-R8 ↔ Snr1 第 0 次提交
  `Invalid qos specification`）。site add / site-notes 流程必须补。
- **两轮都 patch 了 Entity 上游 cmake**（见 G4）。

### 3. 技能有效性的正面证据

Snr1 里唯一读了技能的环节（nt2py 版本选型 1.5.3 + 末段 API 用法）是唯一
没有反复试错的环节；S1 里读文档后的产出（site profile、pgen 三件套、
requirements.json）也都一次成型。**技能内容本身有效，问题集中在三点：
触发机制（listing 注入不足以保证使用）、文档与源码的偏差（pgen 三处）、
站点知识未沉淀（siyuan notes 真空）。**

### 4. 技能触发机制问题（系统性）

Snr1 证明"技能装了≠会用"：listing 在 session 开头注入、Skill 工具可用、
agent 甚至有使用意图，仍被手动探索吸走后遗忘。S1（任务从 router 斜杠命令
启动）则读得很主动。差异提示：**启动方式决定技能采用率**。可选项：
(a) task.md 显式要求"动手前先调用相关技能"（但会污染 N 组的"无技能"
对照设计，只能用于 S 组）；(b) 接受采用率本身是测量对象，评分口径里把
"技能调用次数/时机"列为观测指标（监控层已能统计）；(c) 技能 listing 的
描述文案强化"先读我，再动手"。倾向 (b)+(c)，(a) 会破坏对照。

### 5. agent 行为问题（区分记录，不归技能）

- 明知技能存在却不用；唯一用的 nt2py 也是"先撞墙再翻书"（跳过规定的
  探针脚本 `inspect_nt2_data.py`，白送一次分析作业失败）；
- pgen 自造注入模式：循环每物种单独调 `InjectUniformMaxwellian`、
  `{n+1,n+1}` 自配对（推荐模式是物种对一次调用），导致实际只有
  2048 粒/物种（16 ppc），与 design.md 声称的"PPC 32 per species"差
  2 倍，**agent 始终未察觉设计与现实的偏差**；
- 违反 pgen 技能"未验证不得声称物理正确"的规则；单快照分析；不留
  site-notes、不留本地分析产物——知识零沉淀；
- 39 min 盲等期间未主动检查作业状态（SSH 卡顿 + API 断流叠加，部分属
  环境因素）。

---

## 第三部分：汇总——技能修复优先级

| 优先级 | 项 | 归属 | 影响 |
|---|---|---|---|
| 1 | pgen 文档三处与 v1.4.4 源码矛盾（maxnpart、boundaries、use_weights） | entity-pgen | 两轮共烧 4+ job，照文档做反而错 |
| 2 | router executor sbatch `-input` bug + Entity CLI 知识文档化 | entity-router / pgen | 两轮各烧 job，router 权威被架空的起点 |
| 3 | router apply 失败泄漏 active op + 无 cancel 出口 | entity-router | 把 agent 逼进 sqlite 直改控制面 |
| 4 | siyuan site-notes（PMI 装配、QoS、版本组合、ICE 解法）沉淀 | entity-env-build | Snr1 4/7 模拟失败 + 50 min ICE 螺旋 |
| 5 | "物理正确性"判据的归属与 checklist | router / nt2py / 评分口径 | Snr1 物理失败被 agent 误报为通过 |
| 6 | 无 submission 契约 + 指纹最终重算强制 | router / harness A1 | S1 Gate B 指纹过期 |
| 7 | router 覆盖面与承诺对齐（补齐 Goal 或下调承诺）、site profile 文档、`migrate` 误导报错、`status --live` 降级、bundle 版本漂移治理 | entity-router | 信任与可复现性 |
| 8 | nt2py 离线安装兜底、产物留本地规则 | entity-nt2py | S1 分析降级 bpls、Snr1 Gate E 全丢 |
| 9 | Entity 1.4.4 cmake MPI 怪癖的受控 patch 机制 | entity-env-build | 两轮都越权改上游 |
| 10 | 技能触发/采用率：listing 文案 + 监控计采用率指标 | 系统性 | "装了≠会用"是 Snr1 效率差距的主因 |

**对评测结论的方法论提醒**：Snr1 的"无 router"对照实际上混入了"agent
没用任何技能"的偏差——它度量的是"技能触发失败 + 无 router"的联合效果，
不是纯粹的 router 增量。后续轮次若要干净的 router 增量估计，需先解决
触发问题（第三部分第 10 项），或在分析时按 transcript 的技能调用记录
分层。
