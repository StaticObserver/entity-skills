# Entity Skills 运行日志系统

日期：2026-07-15  
状态：v1 已实现

## 1. 目标

这套系统用于回答三个问题：

1. 一次任务中哪些 skill 和 reference 暴露给了 Agent；
2. Agent 做了哪些关键决策，实际调用了哪些工具，产生了哪些产物；
3. 哪些结果只是 Agent 声称成功，哪些已被外部证据验证。

日志为后续的对照实验、组件消融和错误归因提供可机读证据，但日志本身
不证明 skill 造成了结果改善。

## 2. 边界

### 记录

- 任务、模型、工具集和 skill 版本身份；
- 路由、门禁、停止、恢复等关键决策事件；
- 工具调用链、状态转移、产物引用和验证结果；
- 失败位置、终止状态和执行成本。

### 不记录

- 模型隐藏思维链或长篇自述推理；
- 密码、token、SSH 私钥、完整环境变量或其他凭据；
- 默认复制大型原始数据、完整编译日志或完整工具输出；
- 第二套 Case、build 或 run 权威状态。

模型可以提交简短的结构化决策记录，但它只是“声明”，不是对真实内部
推理的读取，也不是独立证据。

## 3. 三层日志

```text
领域事实层        Router events / Action / build logs / probe output
       ^             各 owner 继续对自己的状态和产物负责
       |
执行观测层        本设计：每次 Agent run 的统一 trace
       ^             只记录调用链和指向领域证据的引用
       |
评测汇总层        未来的 baseline/full/ablation 对照和指标聚合
```

这三层不可互相代替。Router 的 `events.jsonl` 仍是 Case 控制事实；
env-build 的 `run.log` 和 build logs 仍是构建事实；观测日志只保存它们的
Locator、hash 和相关 ID，不回写这些权威状态。

## 4. 证据等级

每个事件都必须声明 `evidence_level`：

| 等级 | 含义 | 示例 |
|---|---|---|
| `declared` | Agent 或 Worker 的声明 | “这是 managed write，应进入 Router” |
| `observed` | collector 直接观测到的行为 | 调用了 `pgen_preflight.py`，返回码为 0 |
| `verified` | 验证器或权威事实源确认 | Action 存在且 site/path/revision envelope 匹配 |

`declared` 不得自动升格为 `observed` 或 `verified`。例如，Agent 声称“已编译
成功”只是 `declared`；实际命令返回零是 `observed`；预期 executable 存在且
引用正确 build ID 才是 `verified`。

## 5. 运行目录

默认日志根目录为 `~/.entity-skills/observability`，可由
`ENTITY_SKILL_TRACE_HOME` 覆盖。评测器应为每次实验传入独立临时目录。

```text
<trace-home>/runs/<yyyy-mm-dd>/<run_id>/
├── manifest.json
├── events.jsonl
├── artifacts.jsonl
└── result.json
```

- `manifest.json`：不可变的运行身份和捕获策略；
- `events.jsonl`：单写者、append-only 的调用链；
- `artifacts.jsonl`：产物和外部证据的 Locator/hash 索引；
- `result.json`：可重建的终态摘要，不是新的领域事实源。

运行日志不写入 Entity source checkout、Router Case root 或 raw data root。

## 6. Run manifest

`manifest.json` 至少包含：

```json
{
  "schema_version": 1,
  "run_id": "run-uuid",
  "task": {
    "case_id": "eval-routing-001",
    "input_ref": "evals/cases/routing/managed-pgen-write.json",
    "input_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "variant": "full",
  "agent": {
    "provider": "...",
    "model": "...",
    "configuration": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "tools": {
    "profile": "tool-profile-name",
    "configuration": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "skills": [
    {
      "name": "entity-router",
      "source": "/absolute/path/to/skill",
      "package_revision": "git-commit-or-null",
      "content_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "dirty": false,
      "exposure": "injected"
    }
  ],
  "capture": {
    "raw_input": false,
    "raw_tool_output": false,
    "decision_records": true,
    "protected_roots": [
      "/absolute/entity-source",
      "/absolute/router-case",
      "/absolute/raw-data"
    ]
  },
  "started_at": "2026-07-15T00:00:00Z"
}
```

`exposure: injected` 只证明 skill 被放入了 Agent 可用上下文，不证明模型在
因果意义上使用了它。如果平台不暴露精确的 context-load 事件，日志不得
猜测“已阅读”。

## 7. 事件协议

### 公共 envelope

```json
{
  "schema_version": 1,
  "event_id": "event-uuid",
  "run_id": "run-uuid",
  "seq": 12,
  "time": "2026-07-15T00:00:03.420Z",
  "type": "tool.finished",
  "source": {
    "kind": "collector",
    "id": "local-runner"
  },
  "evidence_level": "observed",
  "phase": "execute",
  "span_id": "span-uuid",
  "parent_span_id": "parent-span-uuid",
  "payload": {}
}
```

`span_id/parent_span_id` 连接 Router、Worker、owner skill 和工具调用。`seq` 由
collector 在单个 run 内单调分配；时钟只用于展示，不用于代替顺序。
`phase` 使用 `orient/decide/execute/verify/finish`；owner 内部更细的阶段放入
payload，不扩张公共枚举。

### 事件类型

| 类别 | 类型 | 用途 |
|---|---|---|
| lifecycle | `run.started`, `run.finished`, `run.failed` | 运行边界 |
| skill | `skill.exposed`, `skill.resource_observed` | 可用 skill 和可观测的 reference 读取 |
| decision | `decision.recorded` | 路由、门禁、恢复或停止决策 |
| tool | `tool.started`, `tool.finished` | 命令或 API 调用 |
| state | `state.transition_observed` | 外部状态变化的观测 |
| artifact | `artifact.observed` | 产物、日志和证据引用 |
| validation | `validation.finished` | 确定性检查或 rubric 结果 |
| error | `error.observed` | 工具、collector 或协议失败 |

v1 不记录每个 token、普通对话句子或每次无关文件读取。只记录能改变
执行路径、产物或验证结论的事件。

## 8. 决策记录

Agent 每个阶段最多记录一个关键决策，避免因持续自述改变本来的执行
行为。

```json
{
  "type": "decision.recorded",
  "evidence_level": "declared",
  "payload": {
    "kind": "route",
    "choice": "entity-router",
    "observed_facts": [
      "request spans pgen and build",
      "target belongs to a registered Case"
    ],
    "contract_ref": "entity-router.entry.cross-domain"
  }
}
```

要求：

- `observed_facts` 只写当时可获得的任务事实；
- `choice` 是可以与后续工具调用核对的决策；
- `contract_ref` 指向稳定行为合同，不使用 SKILL.md 行号；
- 不强制记录候选方案、详细推理或事后解释。

`contract_ref` 的评测定义应未来保存在仓库根部的 `evals/contracts/`，不在
SKILL.md 中增加评测专用文字。

## 9. 工具和产物

`tool.started/tool.finished` 记录：

- 稳定工具名、参数 hash 和安全摘要；
- exit/status、开始和结束时间；
- stdout/stderr 的 hash、字节数和经脱敏的尾部摘要；
- 与 Action、Worker、Case、build 或 run 的关联 ID；
- 产物 event ID。

`artifacts.jsonl` 每行记录：

```json
{
  "artifact_id": "artifact-uuid",
  "run_id": "run-uuid",
  "role": "verification-evidence",
  "locator": {"site_id": "controller", "path": "/absolute/path"},
  "media_type": "application/json",
  "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "size_bytes": 1234,
  "produced_by": "event-uuid",
  "authority": "entity-router-action-result"
}
```

大型产物留在 owner site；日志只保存 Locator 和指纹。如果产物会被覆盖，
必须在 run 结束前记录当时指纹，否则不能作为可重现证据。

`result.json` 由 collector 从事件重建，至少包含：

```json
{
  "schema_version": 1,
  "run_id": "run-uuid",
  "terminal_status": "completed",
  "last_seq": 42,
  "decisions": 3,
  "tool_calls": {"total": 8, "failed": 1},
  "artifacts": 4,
  "validations": {"pass": 5, "fail": 0, "unknown": 1},
  "usage": {
    "input_tokens": null,
    "output_tokens": null,
    "wall_time_ms": 120000
  },
  "terminal_event_id": "event-uuid"
}
```

平台没有暴露的 usage 值保持 `null`，不通过字符数猜测 token。

## 10. 与当前四个 skill 的集成

### entity-router

- 不改变 Case `events.jsonl`、Action request/result 和 evidence 的权威性；
- 观测日志记录 `case_uid/action_id/revision/execution_domain` 和权威文件 hash；
- Router 保持 controller single writer，collector 不得写 Case state。

### entity-pgen

- 捕获 preflight 命令、结果和目标 envelope；
- 索引 `docs/design.md` / `pgen.hpp` / TOML 的变更前后 hash；
- 由验证器判断 managed write 是否存在匹配 Action，不信任 Agent 自述。

### entity-env-build

- 引用现有 `~/.entity-env-build/run.log`、build result 和 build logs；
- 记录 requirements/checkpoint/env/build script 的 hash 关系；
- 以 expected executable、build ID 和 source revision 核验成功。

### entity-nt2py

- 捕获只读 probe 命令和 inventory JSON 指纹；
- 记录选择后的输出产物，不复制 raw data；
- 验证输出 Locator 不位于 Entity data root 内。

## 11. Collector

v1 只允许一个 collector 写一个 run 的 `events.jsonl`。Router、Worker、tool
adapter 和 validator 向 collector 提交事件，不同时 append 同一文件。

collector 负责：

1. 生成 `run_id/event_id/seq/time`；
2. 验证 schema 和 `evidence_level`；
3. 执行参数、输出和路径脱敏；
4. 逐行 append 并立即 flush；
5. 索引 artifact，在正常终止时原子写 `result.json`。

如果进程崩溃，已完成的 JSONL 行仍然可读；缺少 `run.finished/run.failed`
的 run 统一视为 `incomplete`，不根据最后一行猜测成功。

## 12. 脱敏和保留

默认策略：

- 原始用户输入、原始工具输出和文件内容不进入日志，仅记录 hash/ref；
- 匹配 `token/password/secret/credential/private_key/cookie/authorization` 的字段整体替换为 `[REDACTED]`；
- 不记录完整 `env`，只记录允许列表中与执行身份有关的值或 hash；
- 评测 run 默认保留 manifest/events/result 和小型验证产物；
- 真实任务的保留期由运行器配置，collector 不自动删除 owner 产物。

v1 固定关闭 raw capture。后续如果增加该能力，必须是显式的 run-level
选项，并在 manifest 中留痕。

## 13. v1 实现范围

v1 只实现最小闭环：

1. JSON Schema：`manifest` / `event` / `artifact` / `result`；
2. 一个本地 collector CLI：`start` / `emit` / `import-events` / `import-codex` / `tool` /
   `artifact` / `evidence` / `finish` / `validate`；
3. 安全脱敏和内容 hash；
4. 工具调用、决策、artifact 和 validator 的事件录入；
5. 历史 Router Action、Router v5 Operation、PGen preflight、env-build result、
   nt2py inventory 五种现有证据的引用；
6. schema、顺序、崩溃恢复、脱敏和单写者测试。

v1 不实现 dashboard、隐藏思维抓取、自动评分、A/B 调度、跨机日志服务或
全量 transcript 存档。这些只在基础 trace 证明稳定后再进入后续设计。

## 14. 验收标准

v1 完成时必须满足：

1. 仅凭 manifest 和 JSONL 即可重建一次 run 的路由、工具、产物和验证链；
2. 能区分 skill 被暴露、Agent 声明使用、实际行为被观测和结果被验证；
3. 每次 run 能精确识别 skill content hash、package revision、model 和 tool profile；
4. collector 不写 Router Case state、Entity source checkout 或 raw data root；
5. 中途崩溃后 JSONL 仍可校验，run 被正确标记为 `incomplete`；
6. 测试能证明常见 secret 字段不进入日志；
7. 移除决策自述不影响工具和验证事件的完整性；
8. 日志关闭时，四个 skill 的现有执行路径和产物不变。

## 15. v1 默认决定

- 核心 collector 保持平台无关，接受标准事件；Codex、Claude 和 Kimi transcript 导入作为独立 adapter，不进入核心 schema；
- 本地命令 wrapper 先覆盖确定性工具调用，transcript adapter 补全路由和 Agent/Worker 调用链；
- 真实任务默认只保存用户输入 hash 和外部引用；冻结评测题的原文保存在独立测试集；
- Agent 可选提交 `contract_ref`，但 validator 根据行为和领域事实给出的判定才是权威结果；
- 平台不提供 skill/context load event 时，只记录 `injected`，并明确不声称“已阅读”或“已使用”。

## 16. 实现位置

```text
tools/skill_observability/
├── skill_observer.py
├── cli.py
├── core.py
├── contracts.py
├── evidence.py
├── adapters/
│   ├── codex_rollout.py
│   ├── claude_transcript.py
│   ├── kimi_wire.py
│   └── tool_trace.py
└── schemas/
    ├── manifest.schema.json
    ├── event.schema.json
    ├── artifact.schema.json
    └── result.schema.json
```

`tests/test_skill_observability.py` 与 `tests/test_e2e_evaluation.py` 覆盖完整 owner
证据链、Router v5 Plan/Operation/receipt/scheduler 证据、secret 脱敏、多进程
写入序列化、崩溃后 incomplete 判定、产物指纹漂移、三种 provider 的增量导入与
零侵入运行时边界。所有 adapter 只导入可观测的 tool call/output 指纹；Kimi adapter
遍历 main 和子 agent wire，并读取平台原生 usage，但不保留 `think` 内容。

## 17. 生产调用日志(passive invocation logging)

状态:已实现(2026-08-09)。

与本文档前述的评测 trace(skill_observability,面向受控评测轮的完整证
据链)不同层:生产调用日志是**被动的**——四个 entity skill 的 CLI
每次实际被调用,就追加一条 JSONL 记录,目的是在日常使用中积累真实
使用数据。

- **记录什么**:schema_version、时间戳(UTC Z)、duration_ms、skill、
  script、argv(脱敏后)、cwd、exit_code、error_type(可选)、
  skill_version(有 VERSION 文件时)、pid、ppid_comm(best-effort)、
  host。每个 CLI 入口(`entityctl`、ledger 的 executor/remote 独立
  CLI、env-build 四个 CLI、pgen_preflight、inspect_nt2_data)在其
  `__main__` 块用一个薄上下文管理器包装,不侵图书馆代码。
- **写在哪**:默认 `~/.entity-skills/observability/invocations/
  <yyyy-mm>.jsonl`(UTC 月份轮转,append-only,O_APPEND,必要时
  mkdir -p);环境变量 `ENTITY_SKILL_INVOCATION_LOG` 可指定完整文件
  路径覆盖(测试与一次性收集用)。
- **隐私边界**:argv 中匹配 token/secret/password/passwd/api[-_]?key/
  credential(大小写不敏感)的 flag 值一律记为 `<redacted>`
  (`--flag value` 与 `--flag=value` 两种形式都处理),flag 名本身
  保留;不记录 secrets;日志是观察数据,**不成为第二权威状态**——
  Ledger 的 ledger.db 仍是唯一权威,调用日志永远不参与任何状态推导。
- **never-fail 原则**:写日志路径上的所有异常(目录不可写、磁盘满、
  ps 失败等)一律吞掉;被包装主流程的返回值、exit code、异常语义完
  全不变。四个 skill 的 scripts/ 下各放一份字节相同的
  `_invocation_log.py`(installed skill 目录自包含,不能跨 skill
  import;entity-ledger 在 skills-no-router 变体中可能缺席),由
  `tests/test_invocation_log.py` 的字节一致性测试防漂移。
