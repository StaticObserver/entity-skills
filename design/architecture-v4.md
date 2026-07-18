# Entity Skills 架构 v4：共享控制状态与模型高效入口

日期：2026-07-18
状态：已实施并通过本地验收

验收快照（2026-07-18）：

| 项目 | 结果 |
|---|---|
| 公共状态 | `bh-reconnection` 由公共 project binding 解析到 controller-local Case；查询前后 Case revision 65、sha256、size、mtime 全部不变 |
| 三端安装 | Codex、Claude Code、Kimi Code 的 12 个 skill 投影均解析到 bundle `sha256:ea3d59bcac8cb9cfcae46e52d2e809d0ac24cd447cb094e27660142330d301b6` |
| 单写合同 | 并行 writer 被拒绝；显式 handoff 后新 Agent 可继续；lease 过期不阻塞恢复 |
| 查询效率 | 真实 project inspect 为 1 次工具往返、0 次远端调用、0 次审批、2,281 B 输出，正确性硬门通过 |
| 回归 | Router/observability 84 项、PGen 3 项、env-build 18 项全部通过；Python 3.6 grammar、JSON、skill quick validation 和 `git diff --check` 通过 |

Claude/Kimi 原生 session 已导入共享 trace，用于定位上下文成本；但两者不是同一任务的
matched-scenario 对照，因此跨 provider token reduction 仍标记为 `not_assessed`。真实 SSH
build/run/nt2 staging 与 m87 live canary 属于长期 flow 计划的后续门，不作为本轮公共状态
架构完成度的替代证据，也未在本轮触发远端计算。

## 1. 问题与目标

近期 `bh-reconnection` 实践暴露出四个相互耦合的问题：

1. Codex、Claude Code 和 Kimi Code 各自安装了完整 skill 副本，版本可以漂移；
2. 项目源码、客户端私有目录、Router Case、远端 `_tools` 和会话日志之间的
   权威边界不够直观；
3. Case 虽然共享，但事件和 Action 缺少 Agent/session/bundle provenance；
4. Agent 直接驾驶 `show -> start-action -> SSH -> finish-action` 原语，简单查询也会
   触发大量模型轮次和上下文回灌。

v4 的目标不是删除 Router 的安全约束，而是把这些约束下沉到确定性程序中：

- 所有同机 Agent 从一个公共控制区发现和读取项目状态；
- 控制事实默认保存在 Agent 所在机器，远端不可用时仍可恢复；
- 远端只拥有执行产物和原始数据，控制端只保存 Locator、身份和最后验证证据；
- 每次状态写入都可追溯到 Agent run 和 skill bundle；
- 普通查询只调用一个紧凑只读入口，不创建 Action、不修改 Case；
- 项目源码、控制状态、执行证据和运行 trace 各有且只有一个权威位置。

## 2. 文件存放与唯一权威

### 2.1 控制机公共区域

默认控制根为 `$ENTITY_ROUTER_HOME` 或 `~/.entity-router`。它位于 Agent 所在机器，
不属于任何客户端：

```text
~/.entity-router/
├── registry.json                 # Case UID -> control root，可重建索引
├── project-bindings.json         # project root -> Case UID，唯一项目绑定事实
├── sites/<site_id>.json          # site/transport/root 描述
└── cases/<case_uid>-<label>/
    ├── case.json                 # 当前控制快照
    ├── events.jsonl              # append-only 状态事件和 actor provenance
    ├── actions/<action_id>/
    │   ├── request.json          # 不可变 Action 请求和发起 actor
    │   └── result.json           # 验证结果和收口 actor
    ├── history/
    └── evidence/
```

同一 OS 用户下的 Codex、Claude Code、Kimi Code 和普通 shell 都读取这一位置。
客户端私有目录不得保存第二套 Case、project binding 或 readiness 状态。

`project-bindings.json` 只保存规范化绝对项目根和 `case_uid`。它不复制 `case.json`，
解析时始终通过 `registry.json` 找到当前 control root。Agent 从项目任意子目录启动时，
按最长祖先匹配发现 Case。

### 2.2 项目 Git 仓库

项目仓库保存可审查、可合并的科学事实：

```text
<project>/
└── problems/<pgen>/
    ├── pgen.hpp
    ├── <pgen>.toml
    └── docs/design.md
```

仓库内不保存 mutable Router state、Agent 私有 memory、客户端 skill 副本或 session
导出。一个 PGen 只有一个 canonical `docs/design.md`；旧方案进入明确的 archive，
不能与当前设计并列成两个候选权威。

项目绑定默认也不写入仓库，因为 Case 是控制机本地资源；若未来需要跨控制机迁移，
应导出经过签名/校验的 handoff manifest，而不是提交 mutable `case.json`。

### 2.3 远端执行 site

远端拥有：

- 内容寻址的 source snapshot/materialization；
- immutable build/run identity；
- build log、scheduler receipt、raw data 和 analysis artifact；
- 内容寻址的 runner cache。

远端 Worker 不写控制状态。控制机不可连接远端时：

- `case.json`、Action request/result 和历史 evidence 仍可读；
- 旧 evidence 明确标为最后一次 observation，不升级为当前事实；
- `entityctl inspect` 返回本地控制快照；
- 只有显式 live probe 才尝试远端连接，失败只影响动态字段。

### 2.4 Skill 与 trace

共享产品目录和运行 trace 使用 `~/.entity-skills`：

```text
~/.entity-skills/
├── bundles/<bundle-hash>/         # 只读、版本化的完整 skill bundle
├── current                         # 当前 bundle 选择器
└── observability/runs/...          # 跨客户端统一 trace
```

Codex/Claude/Kimi 的 discovery 目录最终只应包含薄 adapter 或指向同一 bundle 的安装
投影；不得在这些目录直接开发。trace 只引用 Case/Action/evidence，不成为第二套状态。

## 3. 公共运行接口

`entity_router_state.py`、`entity_router_site.py` 和 flow runner 继续作为内部安全原语。
普通 Agent 使用 `scripts/entityctl.py`：

```text
entityctl doctor
entityctl bundle install --source-root <entity-skills-repo>/skills
entityctl project bind --project-root <path> --case <uid>
entityctl project resolve --project-root <path>
entityctl inspect [--case <uid> | --project-root <path>]
entityctl run-status [--case <uid> | --project-root <path>] --job-id/--pid ...
```

合同：

- `inspect` 只读本地公共状态，`state_mutated=false`，正常输出不超过 4 KiB；
- `run-status` 从 Case 推导 exact site/run root，再执行最多一次远端调用；
- 查询不 resume/suspend Case，不创建或完成 Action；
- 写操作仍由 state tool 单写并受 revision/envelope/identity 约束；
- 后续 `change/build/run` 高层事务复用 deterministic flow，不向模型暴露长原语链。

## 4. Actor provenance

每个 mutation 和 Action 记录：

```json
{
  "run_id": "provider-session-or-run-id",
  "provider": "codex|claude|kimi|...",
  "client": "desktop|cli|...",
  "session_id": "native-session-id-or-empty",
  "model": "model-id-or-empty",
  "bundle_hash": "sha256:...-or-empty"
}
```

字段来自显式 CLI 参数或以下环境变量：

```text
ENTITY_AGENT_RUN_ID
ENTITY_AGENT_PROVIDER
ENTITY_AGENT_CLIENT
ENTITY_AGENT_SESSION_ID
ENTITY_AGENT_MODEL
ENTITY_SKILLS_BUNDLE_HASH
```

旧客户端未提供身份时记录 `run_id=unattributed`，保持兼容但不得伪造归属。后续可用
`ENTITY_ROUTER_REQUIRE_ACTOR=1` 在正式多 Agent 环境中拒绝无身份 mutation。

provenance 是审计信息，不保存隐藏 reasoning，也不改变科学证据等级。

### 4.1 Workflow writer lease

受管写事务可在 `control.writer_lease` 持有 60–3600 秒的短期 lease。lease 记录
`lease_id`、完整 actor、acquired/expires 时间；它与 Case 一起位于控制机公共区。

- `entityctl writer acquire/status/handoff/release` 是公共入口；
- active lease 存在时，所有 Case mutation 必须同时匹配 actor run ID 和 lease ID；
- handoff 在同一个 Case lock/revision 下原子更换 holder，并写 append-only event；
- `entityctl flow execute/watch` 必须持有 lease；inspect/check/status 永不占 lease；
- 写事务必须先 acquire lease，再基于 acquire 后的新 revision 冻结 flow request；否则
  lease acquisition 自身产生的 revision 会使旧 request 按预期被并发门拒绝；
- lease 过期后不继续阻塞恢复，旧记录仍可审计。

## 5. 模型与程序分工

### 模型处理

- 把用户目标变成结构化 target 和验收标准；
- 决定物理参数、计算资源、数据保留和异常处置；
- 执行确实需要科学判断的 PGen/analysis 工作；
- 在 `needs_decision`、新 anomaly 和 terminal 时形成报告。

### 程序处理

- project -> Case 发现、Case compact summary；
- revision、allowed action、site/path、identity chain 和 bundle 检查；
- Action start/stage/dispatch/reprobe/finish；
- scheduler/PID 轮询、重复状态抑制；
- actor/trace 关联和结果限长。

`Case -> Workflow -> Action -> Worker` 是内部状态模型，不再要求每个 Agent 在上下文中
逐步复述和手工驾驶。

## 6. 本轮优化计划与完成门

### WP1：公共状态和项目发现

实现 `entity_router_project.py`：

- 默认写 `~/.entity-router/project-bindings.json`；
- 支持 bind/resolve/list/unbind；
- bind 时验证 Case UID 和项目目录；
- resolve 支持项目子目录的最长祖先匹配；
- 使用文件锁和原子写，客户端并发不损坏注册表。

完成门：两个不同进程可通过同一 project root 得到同一 Case UID；项目仓库无状态写入。

### WP2：Actor provenance

- state CLI 增加全局 actor 参数和环境变量解析；
- 所有新事件保存 actor；
- Action request 保存发起 actor，result 保存收口 actor；
- 模板和合同测试同步。

完成门：测试能从 `events.jsonl` 和 request/result 精确恢复两个不同 Agent run 的归属。

### WP3：高层只读入口

- `entityctl doctor` 输出公共路径、bundle identity 和 provenance 配置健康度；
- `entityctl inspect` 输出紧凑 Case summary；
- `entityctl run-status` 从 Case 推导 run site/root，并复用一次性 status probe；
- 所有只读命令显式返回 `state_mutated=false`。

完成门：inspect 不写任何文件；run-status 最多一次远端调用；正常摘要小于 4 KiB。

### WP4：内容寻址发布、文档、合同与验证

- `entityctl bundle install` 从唯一源码发布内容寻址 bundle；
- `~/.entity-skills/current` 原子选择当前 bundle，三端 skill 目录只保存符号链接投影；
- 被替换的三端目录进入带时间戳的本机 backup，不静默删除；
- 更新 SKILL、workspace/runtime reference、README 和 runtime file contract；
- 新增 project/entityctl/provenance 测试；
- 运行 Router、PGen、env-build、observability、Python compile 和 quick validation；
- 验证后同步 Codex、Claude Code、Kimi Code，并核对源码/安装 hash。

完成门：三端 discovery 解析到同一物理 bundle；现有 v3 Case 仍可 show/verify，旧 Action
仍可读取，新增字段向后兼容。

### WP5：多 Agent 归属、单写协调与效率硬门

- 增加 Claude transcript 与 Kimi multi-agent wire adapter；
- 统一事件保存 `agent_run_id/native_session_id/native_agent_id`，与 Action actor 对齐；
- deterministic flow 成为 `entityctl flow` 默认事务入口；
- 增加 60–3600 秒 writer lease、显式 handoff 和公共 CLI；
- efficiency collector 同时检查正确性 invariant、绝对门、相对 reduction 和原生 token；
- 增加真实 controller-local query canary 和 provider session baseline。

完成门：并行 writer 被拒绝、handoff 后新 writer 可继续；简单状态查询一轮完成、无远端
调用、不改 Case、输出小于 4 KiB；没有平台原始 usage 时 token 保持 `not_assessed`。

## 7. 后续迁移计划

本轮之后按以下顺序继续，不在本轮偷偷扩张状态模型：

1. 用真实任务持续校准效率门：status 1 次工具/1 次远端调用，普通参数查询 1 次工具，
   完整 build/run 默认不超过 4 次模型唤醒。

这些后续能力只能引用本轮确定的公共状态与 provenance，不得再创建新的项目状态文件。
