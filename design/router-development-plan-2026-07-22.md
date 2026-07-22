# Entity Router 开发计划(2026-07-22)

来源:S1/Snr1 两轮 e2e 评测复盘(`evals/e2e-neutral-streaming/skill-review-2026-07-22.md`)、
R1–R4 修复过程、以及三处生产反馈(确认缺失、版本命名)。本文是后续开发的基准计划。

## 已定决策

1. **版本从 0.x 起步**。当前技能不作为生产基线;第一个基本满意的版本发布为 1.0.0。
2. **确认门为硬 fail**,不设 warn 观察期。
3. 编译参数与模拟参数的确认必须是**记录的事实**,不是对话历史。

## 设计原则

从评测与生产证据归纳,漂移全部发生在"规则已知但靠 agent 自觉"的环节;agent 的
价值全部体现在"规则未知需要推理"的环节。据此把工作分三类:

| 类别 | 判据 | 处理方式 | 证据 |
|---|---|---|---|
| 确定性收束 | 规则已知,错了烧 job 或坏状态 | 代码 hard gate,agent 无自由度 | `-input`、指纹、QoS 合法性、ID/hash 派生 |
| 受约束的选择 | 选项可数,选择需判断 | 代码枚举选项,agent/用户选,代码记录 | QoS/分区选型、编译/模拟参数确认、删除授权 |
| 自由发挥 | 规则未知,需要推理 | agent 在 owner skill 内自由,router 只在边界验 receipt | PGen 物理设计、新故障诊断、分析结论判断 |

三条贯穿纪律:

1. **agent 不算代码能算的,不读代码能总结的**——hash、ID、参数卡、scheduler 查询
   收归代码;agent 的思考只花在物理和新故障诊断上。
2. **确认和结论必须是记录的事实**——`decisions` 里带 digest 和署名的记录才算数,
   gate 不认散文。
3. **每个 release 用 S1/Snr1 transcript 重放验收**,不靠感觉。

元规则:**每烧一个 job、每发现一次漂移,转化为一个 hard gate 或一个
`needs_decision` 字段,不允许只转化为文档。**

## 版本控制设计

两层版本,各司其职:

- **Schema 版本 = 兼容性契约**(纯整数,已存在,不动):`STORE_SCHEMA_VERSION`、
  plan/GoalSpec/receipt `schema_version`、env-build `checker_version`。契约变才 +1。
  用户可见字符串中的 "v5" 全部清理,降级为纯技术字段。
- **产品版本 = 发布管理**(semver):单一来源 `skills/entity-router/VERSION`
  (被 `bundle_hash` 覆盖,版本变更自动产生新 bundle 身份)。
  - PATCH:bug 修复、文档纠错;
  - MINOR:向后兼容的新能力(新 Goal kind、新命令、新 gate、site profile 新字段);
  - MAJOR:schema 契约破坏式变更、使既有 checkpoint 失效的 gate 语义变化。
    0.x 期间 MINOR 承担所有功能演进,MAJOR 语义暂缓,1.0.0 起严格执行。
- 配套:`CHANGELOG.md`(Keep a Changelog)、每 release 打 git tag、
  `entityctl store migrate` 为真实命令(现在先建命令壳与 schema 检测,第一个真实
  迁移等 store schema 6 出现时再写)、doctor 区分"tag 发布"与"开发脏版本"。

## Release 路线

> 进度(2026-07-22):0.1.0–0.5.0 已交付(132 项测试全绿)。0.5.0 落地了
> status --live divergence 分类(job_gone/state_mismatch/untracked_job)、
> doctor 硬失败(bundle 漂移、Site profile 失效)+ 泄漏 Operation 警告、
> `apply --refresh` data inventory 刷新、以及 phases 报告的 skill_adoption
> 采用率指标。与本文的偏差:`analysis` Goal 暂缓(留在 entity-nt2py,
> router 只记录),已记入 CHANGELOG Known limitations。

### 0.1.0(基线 + Phase 0,版本基础设施)

已完成部分(R1–R4 + OpenMPI gate,见 CHANGELOG):
- executor sbatch `-input`;apply 失败 finish anomaly + `operation cancel`;
  store 缺失报错修正;`status --live` 失败降级;OpenMPI >= 5.0.0 gate。

Phase 0 待做:
- `skills/entity-router/VERSION` = 0.1.0;`CHANGELOG.md` 建立;
- doctor/status/install receipt 报告 `bundle_version` + `bundle_hash`;
- 清理 "Router v5" 用户可见字符串;`entityctl store migrate` 命令壳 + schema 检测。

### 0.2.0(Phase 1,run 边界收束)

1. `entityctl site discover <site>`:代码跑 `sinfo`/`sacctmgr`/`scontrol`,枚举合法
   QoS/分区/GRES 并建议 `policy.default_*`;选择留给 agent/用户。(R8,两轮各烧一次)
2. `templates/site-profile.schema.json`,消除"读 `validate_site_profile` 源码
   才会写"的成本。(R6)
3. Submission 契约 v1:`entityctl submission create/verify`,指纹由工具对最终产物
   重算,agent 从管道里碰不到 hash 字符串。(R10,S1 Gate B 指纹过期)
4. Executor preflight 异常结构化映射(无效 QoS → 提示 `site discover`),
   错误信息自带修复路径。

### 0.3.0(Phase 1.5,确认门,硬 fail)

生产问题:agent 不主动确认编译参数和 TOML 模拟参数。根因:pgen 无此规则、
env-build 是 14 字段散文清单、全链路无 gate。

1. env-build 参数卡:`entity_checkpoint.py validate` 从 requirements.json 派生编译
   参数卡 + digest;`decisions.parameters = {digest, confirmed_by, confirmed_at}`;
   validate/env.sh 生成时 digest 缺失或不匹配 → **fail**。
2. pgen 参数卡:preflight 从 TOML/PGen 派生模拟参数卡(drift/注入、ppc、分辨率、
   steps/dt、边界、输出节奏)+ digest。
3. router plan(run Goal)重算 TOML 参数 digest,无匹配确认记录 → `needs_decision`
   附参数卡——烧 job 边界的最后一道闸。
4. 字段分两层:Tier 1(物理与钱,阻塞):pgen、backend+gpu_arch、mpi、precision、
   drift/注入、ppc、分辨率、steps/dt、边界;Tier 2(列出可默认):deposit、
   shape_order、debug/tests、dependency_policy。`--confirm-defaults` 旁路带署名,
   审计链不断。

### 0.4.0(Phase 2,e2e 覆盖,R9)

- `build` Goal:router 只验 checkpoint 存在且 compatibility=pass、派生 build
  identity、记录产物 hash;编译过程自由度不收回。
- `data`/`analysis`:先只做 inventory identity + readiness 推进。
- SKILL.md 承诺与实现对齐。

### 0.5.0(Phase 3,观测与对账)

1. `status --live` 对账:divergence 分类(`job_gone`/`state_mismatch`/
   `untracked_job`),带外操作在 status 里现形。
2. doctor 升级:bundle 漂移 fail(R5)、泄漏 active operation 检测并提示 cancel、
   site policy 完整性。
3. 采用率指标:trace 记技能脚本调用计数(评测干净对照的前提)。

### 1.0.0 候选标准(满足才可发布)

- 0.2.0–0.5.0 全部落地;
- S1/Snr1 失败点 transcript 重放全部被 gate 拦截或有明确归属;
- 真实 SSH 站点(siyuan)端到端跑通 build→run→data 链,身份链完整;
- 至少一轮新 e2e 评测,技能脚本命中率 > 0 且无 sqlite 级控制面手术。

### 持续(Phase 4,知识沉淀闭环)

- apply 以 anomaly 收尾且诊断结论已知时,`entityctl site note` 写回 site
  profile/env-build site-notes(OpenMPI gate 是首个实例);
- 每轮 release 在 CHANGELOG 记 "Gates added" 小节。

## 明确不做

- 不建通用 workflow 引擎;Project→Goal→Operation→Evidence 四层够用,Phase 2 只
  横向加 Goal kind。
- 物理正确性判据不进 router:落 nt2py/pgen 交付要求(首末守恒 checklist 工具,
  agent 负责解读),router 只要求该 checklist 的 receipt 存在。**待用户最终拍板**。
- 不动 legacy 兼容路径,直到新 Goal 在真实 SSH 验收过。
