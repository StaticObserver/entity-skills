---
name: entity-ledger
description: 为 Entity 等离子体模拟项目维护一份确定性记录：环境、源码版本、构建、run 台账和数据状态都有据可查，任何一轮会话（换机器、换 agent、中途崩溃）都能接着上次继续。用于跨会话或跨机器的模拟工作、run 提交与跟踪、结果盘点。有界的只读问题和独立的 PGen/构建/分析编辑可以直接进入对应的 owner skill。
---

# Entity Ledger

这个技能帮你用 Entity 做等离子体模拟研究时**不丢状态**：编译环境怎么
配的、代码用哪个版本、跑过哪些 run、参数是什么、结果在哪——这些确定
性的事实都记录在案。你自由探索（改 PGen、换参数、分析数据），Ledger
负责把既成事实登记进 Case 台账，让任何一轮会话都能知道项目在哪、
下一步是什么。

公开模型：

```text
Workspace → Project → Case → Identity → Evidence
```

- **Workspace** 是唯一工作目录：`projects/` 下的项目树、`sites/` 下的
  site 档案、`.ledger/` 控制器状态（ledger.db + 源码快照）。目录自包含，
  可以整体迁到任何机器后 `workspace adopt` 继续工作。
- **Project** 是研究主题容器，持有 source authority；**Case** 是项目内
  一个意图明确的研究线索（一份意图 + 一个 PGen 配置族 + 它的
  build/run/data 链）。参数扫描 = 一个 case 多条 run；意图换了才开新
  case。
- **Computation Site** 是一台机器（或 HPC 访问边界）上的约定文件树
  （`<site_root>/{deps,checkouts,projects}`）+ 登记在 workspace 里的
  档案（`sites/<site>.yaml` 为权威）：持有共享 deps、物化源码、执行
  build/run。

Case/identity ID、哈希、Locator 和路径由控制器推导，不要让用户提供
或管理这些字段。

## 架构红线

- **控制器只在开发机运行**:`entityctl`、workspace(`.ledger/`、
  `sites/`、`projects/`）只存在于你（agent）运行的这台机器。
  Computation Site 只是 ssh 执行端——Ledger 经 transport 驱动它。
- **永远不要把 entityctl、workspace 或任何 skill 工具 scp 到 site 上
  执行**;site 上只允许两类动作：Slurm 作业（sbatch/squeue/sacct)
  和平常的文件操作（由 Ledger 的 transport 发起，或你手工的轻量
  ssh)。在 site 上跑控制器是架构倒置。
- **workspace 的位置先与用户确认再 init**（建议默认：开发机上的项目
  目录下）。不要在 site 上建 workspace；含有 `entity-site.yaml` 的目
  录是 Site 树根，不是 workspace。

## 先读项目状态

先确认控制器指向哪个 workspace：

```bash
python3 scripts/entityctl.py workspace where
```

控制器 home 的解析顺序：`--ledger-home`（以及 `ENTITY_LEDGER_HOME`/
`ENTITY_ROUTER_HOME` 环境变量，同属显式档）> `ENTITY_WORKSPACE` 环境
变量 > `~/.entity-ledger/active-workspace` 指针 > 旧 `~/.entity-ledger`
（兼容回退）。没有激活的 workspace 时用 `workspace init <path>` 创建、
`workspace adopt <path>` 激活；旧布局（散落的项目目录、旧
`~/.entity-ledger`、site-notes）用 `workspace import` 一次性收编，见
`references/migration-guide.md`。

进入一个项目，先跑：

```bash
python3 scripts/entityctl.py status --project-root <project> [--case <slug>]
```

输出人可读的项目仪表盘（按 project → case 分组）：

- **就绪板**：source / pgen / build / run / data / analysis 六格状态与
  证据（哪格缺、哪格过期、run 的退出码）；
- **Run 台账**：跑过哪些 run、在什么机器、什么状态——run 序列就是
  研究轨迹；
- **待决**：未确认的参数、带外变更等需要决定的事；
- **建议下一步**：由当前事实推导（不存储、永不过期）。

`--live` 额外探测 scheduler/进程的当前状态；`--json` 返回机器可读
合同；`show --project-root <project>` 输出 Case 事实明细。status 和
show 只读，绝不写状态。项目只有一个 case 时 `--case` 可省略；有多个
case 时所有 record/render/status/show 命令都必须用 `--case <slug>`
选择（省略会报错并列出可选 case）。

## 确定性原语

CLI 是辅助工具，每个命令只做一件确定性的事；流程顺序由你按用户
目标编排。写入类原语自带证据探测——先验证、后落账，失败时零写入，
修复原因后重跑同一条命令即可：

```bash
# workspace 与项目骨架
python3 scripts/entityctl.py workspace init|adopt|where|import ...
python3 scripts/entityctl.py project init <name>
python3 scripts/entityctl.py case init <project> <name>

# 生成（不写状态）
python3 scripts/entityctl.py render-run \
  --project-root <project> --toml <input.toml> --site <site> \
  [--gpus N] [--walltime HH:MM:SS] [--gres gpu[:type]:count] \
  [--precision single|double] [--executable <path>]
  # --walltime 留空（默认）则不设置时限，由分区/QoS 默认值决定
  # --gres 留空（默认）则用 site policy 的 default_gres，再没有则回退 gpu:<N>;
  # 无调度器（direct）Site 忽略 gres
python3 scripts/entityctl.py snapshot-source --project-root <project>

# 记录（先探测证据，后落账）
python3 scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  record run-prepare --project-root <project> --toml <input.toml> --site <site> [...]
python3 scripts/entityctl.py record run-launch --project-root <project> [--run-id <id>] [--resubmit]
python3 scripts/entityctl.py record run-exit  --project-root <project> [--run-id <id>] [--reclassify]
python3 scripts/entityctl.py record run-abort --project-root <project> [--run-id <id>] --reason "<原因>"
python3 scripts/entityctl.py record run-correct --project-root <project> [--run-id <id>] \
  --status <completed|failed> --reason "<原因>"
python3 scripts/entityctl.py record build --project-root <project> --site <site> \
  --checkpoint <deps-checkpoint.json> --executable <path>
python3 scripts/entityctl.py record data --project-root <project> [--run-id <id>]
python3 scripts/entityctl.py record intent --project-root <project> --text "<当前研究目标>"
python3 scripts/entityctl.py record analysis --project-root <project> \
  --script <scripts/ 相对路径> --data <run_id|data_id> --params '<json>' \
  --output-root <site 产物目录> [--env-stack <stack_id>] [--hardcoded-paths]

# site 档案、文件树与 deps 注册表
python3 scripts/entityctl.py site sync [site]        # 档案 → db
python3 scripts/entityctl.py site init <site>        # 目标机建 <site_root> 骨架 + 标记
python3 scripts/entityctl.py site deps <site>        # 注册表(人读 / --json)
python3 scripts/entityctl.py site deps-add <site> --from-checkpoint <entity-deps.local.json>

# 迁移(移动由 agent 执行,原语只盘点与落账)
python3 scripts/entityctl.py site plan-migration <site>
python3 scripts/entityctl.py record relocate --project-root <project> \
  --dimension <build|run|data> --identity-id <id> --to <新绝对路径>
```

错误契约：失败输出 `{"ok": false, "status": ..., "error": ...,
"retryable": ...}`（exit 2)。**只有 `status: "anomaly"`（瞬时/外部
故障，如 SSH 断连、远端崩溃）才值得原样重试**，此时 `retryable` 为
`true`;`invalid_request`、`needs_decision` 等其余 status 都是确定性
错误（`retryable: false`)，原样重试永远无效——必须改变输入，或把
`decisions` 里的问题升级给用户。不要把每条调用都包进固定次数的重试
循环。

关键语义：

- `record run-prepare` 要求参数已确认（pgen skill 的
  `pgen_preflight.py confirm <input> --by <actor>` 写入
  `<input>.decisions.json`）；TOML 改动后需重新确认。
- `record run-launch` 的 receipt 保证 exactly-once：重复执行不会
  重复提交，进程中断后重跑会认领已提交的作业；绕过 Ledger 自己提交
  的作业用 `--adopt-job` / `--adopt-pid` 认领进台账。Ledger 提交的
  job 已终态且失败（秒挂、CANCELLED 等）时用 `--resubmit` 重提：
  会先探测旧 job 确已死亡（在跑或探测不到终态都拒绝），新提交拿
  自己的 exactly-once 收据（exactly-once 按"每次提交"计，不是
  "每个 run 一次")，旧 scheduler 记录移入 identity 的
  `prior_submissions`，事件标注 `resubmit: true`。
- run 上了调度器后就是在途事实，不占用项目状态；等待期间你可以去
  分析上一个 run 或开发下一个 PGen，`status --live` 随时探测进度。
- `record run-exit` 先信调度器终态词再信退出码：sacct 报
  CANCELLED/TIMEOUT/OUT_OF_MEMORY 等非 COMPLETED 词时一律记
  failed（即使退出码是 0:0——被 scancel/OOM 杀掉的 job 也能报干净
  退出码）,scheduler_state 一并写进事件；COMPLETED 或无调度器词
  （direct）时按退出码分类。终态非零退出时会用 run_root 日志证据识别已知的
  退出阶段 teardown abort：stdout（去 ANSI）最后一步满足
  `Step: N [of M]` 且 `N >= M - 1`，stderr 尾部命中已知 glibc
  `malloc_consolidate()` abort 签名——两组证据齐备时记 completed 并附
  `exit_anomaly`（真实 exit_code 保留），缺一维持 failed。已落账为
  failed 的 run 事后拿到日志证据时用 `--reclassify` 重判（跳过调度器
  探测，仅 failed 可用，其余状态报错零写入）。
- `record run-correct` 是人工更正原语：已落账的终态记错了（例如
  CANCELLED 0:0 被旧版本误记 completed）时，用 `--status
  completed|failed --reason <原因>` 在 completed/failed 之间更正；
  在途 run 拒绝（先 run-exit 到终态），更正为相同状态是 no-op。
  与 `--reclassify` 并存：reclassify 按日志证据重判，run-correct
  是人工声明，reason 必填并落进 identity 与审计事件。
- `record run-abort` 是卡死 run 的显式逃逸口：site 永久不可达（机器
  退役、SSH 失效）或确认死亡的在途 run，由人工声明放弃。`--reason`
  必填并落进 identity 与审计事件；仅对在途 run 可用（已终态报错零
  写入）。aborted 是终态：可 relocate、可迁移，status --live 不再探
  测。`--reclassify` 不适用于 aborted;site 恢复后输出仍可用
  `record data` 盘点。
- `record analysis` 是 identity 链第六维：**执行自由、登记严格**——
  在哪跑怎么跑 Ledger 不管，登记做事后证据探测：脚本必须来自项目通
  用脚本库 `projects/<p>/analysis/scripts/`（内容哈希；case 级一次性
  脚本 agent 自管不入台账），产物目录的 `analysis-manifest.json` 必须
  存在且 data_id 与声称一致；manifest 一旦写了 `script`/
  `script_sha256`/`params` 字段，登记时会被逐一交叉核对。
  `--params` 可选、默认 `{}`；注意 JSON 数字类型影响
  analysis_id(`1` 与 `1.0` 是不同参数)。
  `analysis_id = hash(data_id, 脚本哈希, 参数)`，幂等；父 data 不再是
  current 时 analysis 自动显示 stale（历史 identity 保留不删；父 data
  已非 current 的新登记作为历史条目入账，不拨回 current）。硬编码存
  量脚本不拒绝登记，用 `--hardcoded-paths` 标记，dashboard 提醒。
  Python 分析环境用 `site deps-add --kind analysis` 登记进 deps 注册
  表（只要求解释器在 site 上存在），`record analysis --env-stack` 引用。
- `record build` 要求 env-build checkpoint 为 `compatibility: pass`
  且参数已确认；登记后 run 原语可省略 `--executable`。
- `record intent` 记录当前研究目标（仪表盘"目标"行）。意图是唯一
  存下来的"指针"——产物全绿不代表该收工，目标只能显式记录；它引导
  你探索后不漂移，新目标会替换旧目标（历史留在审计事件里）。db 为
  主：写入时同步重写 case 目录的 `intent.md`，手工改动与 db 不一致
  时会在待决中标注漂移。
- site 档案（`sites/<site>.yaml`）是 site 信息的权威，`site sync`
  刷新 db。profile 带 `site_root` 时新 build/run 落在新树
  `<site_root>/projects/<project>/{builds,runs,staging}/<case>/<id>`；
  旧 profile 保持独立 roots 推导并标注 legacy，旧 Locator 保持可引用。
- deps 注册表解决"这台机器上以前用过什么环境"：已验证的栈用
  `site deps-add` 落账（证据不符零写入），env-build 解析依赖时用
  `site deps <site> --json` 导出的注册表直接复用
  `deps/<stack_id>/env.sh`。
- 迁移三件套：`workspace import`（本地收编，dry-run 默认）、
  `site plan-migration`（只读盘点旧树 → 新树计划）、`record relocate`
  （agent 移动后重新探测证据并更新 Locator，在途 run 拒绝，证据不符
  零写入）。流程与禁忌见 `references/migration-guide.md`。
- 管理命令：`doctor`、`install`、`site add/list/show/discover`、
  `store migrate`、`submission create/verify`、`export`。写 site 策略
  前先用 `site discover` 探测（结果落进档案 machine 节）；崩溃后用
  `doctor` 检查安装与存储。

内部机制（receipt、executor、scheduler 后端、live 探测细节）只在
调试时需要，见 `references/ledger-runtime.md`；Workspace 与 Site 布局
见 `references/workspace-layout.md`；迁移流程见
`references/migration-guide.md`。

## Owner skills

`entity-pgen` 负责 PGen/TOML/design，`entity-env-build` 负责依赖与
构建，`entity-nt2py` 负责数据访问与分析。对它们使用**自由探索、
严格收束**：给出语义目标、输入 identity、边界和验收标准，让它们
自行选择内部方法；Ledger 只登记经过重新探测的既成事实，不做它们
的领域推理。

## 破坏性操作

删除原始数据总是需要明确的用户授权、精确的 manifest、
受保护的源/构建/依赖 root，以及目标之外的 receipt。
绝不要从一个宽泛的请求推断删除授权。

## 汇报

汇报原语执行结果、精确的源/构建/运行 identity、执行 Site、已验证
的输出/效果、未解决的决策，以及 status 是缓存的还是实时的。内部
receipt 和存储字段属于诊断细节，不是面向用户的正常工作内容。
