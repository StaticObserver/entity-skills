# Entity Router 模型高效执行流程

日期：2026-07-17
状态：本地核心路径、默认公共入口和多 provider 观测完成；显式授权的 m87 live canary 待执行

实现快照（2026-07-17）：WP0–WP5 的本地 runtime、合同与 replay 测试已落地；
本地 Slurm fake transport 已验证 launch recovery/watch；Linux `/proc` PID launcher
已实现“先原子 PID record、再 exec”的恢复协议，但当前 macOS CI 只能验证其安全
拒绝门。真实 SSH runner staging 和 m87 canary 尚未完成。
`entityctl flow` 已成为默认受管事务入口，旧低层命令仅用于恢复。Claude/Kimi 原生
usage 已可读取；matched-scenario token reduction 在 live canary 前仍保持
`not_assessed`，不能由字符数或不同任务的 session 直接替代。

| 工作包 | 当前状态 | 剩余门 |
|---|---|---|
| WP0 合同/identity | completed | 无 |
| WP1 inspect/check | completed | 无 |
| WP2 deterministic execute | local completed | SSH build runner staging |
| WP3 launch/watch | local Slurm + Linux PID implemented | SSH live recovery |
| WP4 data/model Worker | local completed | SSH nt2/Worker staging |
| WP5 eval/default entry | query canary + native baselines completed | m87 matched-scenario canary |

## 1. 目标与边界

本方案保留 Router v3 的 `Case -> Workflow -> Action -> Worker`、controller
single-writer、不可变 source/build/run identity、site/path envelope 和证据门禁，
只增加一个确定性 façade，把状态压缩、固定 Action 执行、恢复和轮询移出模型
循环。

目标：

- 模型/工具往返相对基线减少至少 60%；
- 正常 build/run/data 路径不因中间 Action 成功而唤醒模型；
- 运行中的无变化轮询不进入模型上下文；
- Case summary 和正常 terminal result 分别不超过 4 KiB；
- 失败摘要不超过 8 KiB；
- 不向模型默认注入完整 Case、完整日志、全量 evidence 或 raw data inventory；
- 任何效率改进不得弱化 revision、identity、site/path、证据和恢复语义。

不在本方案范围内：

- 不修改 Entity、nt2py 或 scheduler 的科学/执行语义；
- 不让 façade 直接编辑 `case.json`、Action request/result 或 Case events；
- 不让 Router 缓存或伪造宿主平台的权限审批；
- 不把自由文本 `goal/done_when` 解析成物理事实；
- 不自动修复未分类异常，不自动接受兼容性 warning；
- 不建立第二套可变 workflow 状态机。

`bh-reconnection` 旧链路记录了 73 次命令调用、8 次等待和 39 次审批审查。
该数据只作为历史基线；进入评测前必须把原始观测、统计口径和工具版本固化为
`evals/router-flow/baseline.json`，不能只引用本文数字。

## 2. 不可破坏的控制原则

1. 所有 Case mutation 仍由 `entity_router_state.py` 在 Case lock 下完成；façade
   只能调用其公开子命令。
2. `entity_router_site.py` 继续负责 site profile、probe 和 source
   materialization；owner runner 不自行解释 site 配置。
3. 一个 Case 同时最多一个 active mutating Action。flow bundle 中的步骤严格串行，
   前一步完成并验证后才能启动下一步。
4. 每个 Action 仍有独立 request/result、owner、execution domain、site/path
   envelope 和 controller revision；bundle 不能合并或跳过 Action 边界。
5. flow request 是不可变执行计划，不记录运行进度。恢复时只从 Case revision、
   Action request/result 和远端 receipt 推导进度。
6. Worker 只能写 Action envelope；controller Case root 永远是 protected path。
7. `run.status` 保持现有一次性只读 fast path。持久轮询必须使用
   `run.monitor` Action。
8. `data.purge` 不进入普通 flow bundle，继续要求独立 Action 和显式业务授权。

## 3. 模型与程序的明确分工

### 3.1 必须由模型处理

- 把用户目标转成结构化 `workflow.target` 和成功标准；
- 决定 PGen/物理参数、build 配置、计算资源、数据保留和 authority transfer；
- 执行 `pgen.*` 和需要科学判断的 `analysis.*`；
- 处理首次出现的 `needs_decision`、`anomaly` 或未知 owner 失败；
- 形成科学解释和最终报告。

### 3.2 必须由确定性程序处理

- Case 候选发现、歧义报告和 compact summary；
- schema、revision、allowed action、owner/domain、site/path 和 identity chain 检查；
- 已经完整确认的 source/build/run/data Action；
- Action start、staging、runner dispatch、reprobe 和 finish；
- scheduler/PID 轮询、重复状态抑制和 terminal Action 收口；
- request/result/log 的 hash、字节数、调用数和 wall time 统计。

### 3.3 模型唤醒定义

一次 `model_wakeup` 指 façade 返回了必须由 controller 或 owner 模型处理的事件，
原因枚举固定为：

- `user_goal`：新目标或范围改变；
- `owner_model_required`：进入 `pgen.*` 或科学 `analysis.*`；
- `needs_decision`：缺少会改变物理、资源或数据策略的选择；
- `anomaly`：首次出现或 evidence fingerprint 已变化的异常；
- `workflow_terminal`：整个 Workflow 达到 complete/blocked；
- `user_requested_report`：用户显式要求说明。

确定性 Action 的 `completed` 不是模型唤醒事件。重复的同一异常只在第一次返回；
后续相同 `issue_code + evidence_fingerprint` 被抑制，直到 evidence 改变。这样端到端
链路可以保留每个 Action 的独立性，同时满足不超过 6 次模型唤醒的目标。

## 4. 新增运行时文件

所有 runnable 文件仍位于 `skills/entity-router/`：

```text
skills/entity-router/
├── scripts/
│   ├── entity_router_flow.py
│   ├── entity_router_flow_common.py
│   └── entity_router_flow_runners.py
└── templates/
    ├── flow-request.schema.json
    ├── flow-result.schema.json
    ├── flow-check.schema.json
    ├── worker-envelope.schema.json
    └── dispatch-receipt.schema.json
```

约束：

- Python 3.6.8 可运行，不引入第三方 runtime 依赖；
- runner 使用显式映射表，不用动态 import、`eval` 或调用方提供的 shell 字符串；
- JSON canonicalization 固定为 UTF-8、sorted keys、紧凑 separators、禁止 NaN；
- 所有 compact 输出在脱敏后按 UTF-8 实际字节数计量；
- 超限时保存完整 artifact，stdout 只返回 Locator、sha256、size 和尾部摘要。

## 5. Case v3 的增量状态合同

本方案不升级 `case.json.schema_version=3`，只增加可选字段。旧 Case 可以继续
`show/verify/status`；只有进入 flow façade 时才要求完成 backfill。所有 backfill
通过新的 state CLI mutation 完成，façade 不直接写文件。

### 5.1 结构化 Workflow target

在 `workflow` 下增加：

```json
{
  "target": {
    "schema_version": 1,
    "target_id": "target-512-v1",
    "source_revision_hash": "sha256:...",
    "build_id": "build-m87-cuda-v1",
    "build_spec_hash": "sha256:...",
    "run_id": "run-512-v1",
    "run_spec_hash": "sha256:...",
    "data_id": "",
    "analysis_id": "",
    "criteria": [
      {
        "id": "run-terminal-success",
        "subject": "run",
        "subject_id": "run-512-v1",
        "check": "terminal_status",
        "expected": "completed"
      },
      {
        "id": "fields-readable",
        "subject": "data",
        "subject_id": "",
        "check": "nt2_inventory_status",
        "expected": "ok"
      }
    ]
  },
  "target_hash": "sha256:..."
}
```

`check` 只接受固定枚举，不执行表达式：

- `identity_exists`
- `source_revision_matches`
- `spec_hash_matches`
- `terminal_status`
- `artifact_exists`
- `artifact_sha256`
- `nt2_inventory_status`
- `analysis_result_status`

`memory.goal` 和 `memory.done_when` 保留为人类可读描述，但不得用于自动推进
readiness 或 completion。若旧 Case 只有自由文本目标，`check` 返回
`needs_decision/WF_TARGET_MISSING`，由模型或用户确认一次结构化 target。

`build_id/run_id/data_id/analysis_id` 可以为空，但语义不是“任意当前值”：

- deterministic build/run bundle 启动前，source revision、build ID、run ID 和相应
  spec hash 必须已绑定；PGen 修改后的新 source revision 应在进入该 bundle 前由模型
  确认一次 target；
- 新 run 尚未产生 data/analysis identity 时，空 `data_id/analysis_id` 表示 late
  binding，只允许绑定到 parent chain 精确匹配 target run 的第一个 verified identity；
- late-bound 实际 ID 记录在 resource current identity 和 completion evidence 中，
  不回写 target，因此不会改变 `target_hash`；
- 若工作流要求复用某个已有 data/analysis，必须在 target 中写 exact ID。

新增 state CLI：

```bash
python3 entity_router_state.py set-workflow-target \
  --case <uid> --expected-revision <n> --target <target.json>
```

门禁：无 active Action；target schema 合法；引用已有 identity 时其 hash/parent
必须匹配；`target_hash` 由 state 工具计算而不是信任输入。修改 target 不自动修改
外部资源，只重新计算 allowed actions，并把与新 target 冲突的下游 readiness 标为
`stale/unknown/none`。

对带结构化 target 的 Workflow，`complete-workflow` 必须逐条执行 criteria 的固定
evaluator，并记录 criterion ID、subject identity 和 evidence；原有“verification 数量
不少于 done_when 数量”的逻辑只保留给尚未进入 façade 的 legacy Workflow。

### 5.2 统一 identity record

`resources.<dimension>.identities[]` 使用共同字段：

```json
{
  "id": "data-run-512-<12hex>",
  "kind": "data",
  "site_id": "m87",
  "root": {"site_id": "m87", "path": "/.../run-512/data"},
  "spec_hash": "sha256:...",
  "parents": {"run_id": "run-512-v1"},
  "evidence": [
    {"locator": {"site_id": "m87", "path": "/.../nt2-inventory.json"},
     "sha256": "...", "observed_at": "..."}
  ],
  "created_by_action": "data-inspect-001",
  "verified_at": "..."
}
```

维度约束：

| Identity | 必需 parent/spec/evidence |
|---|---|
| source | authority/snapshot fingerprint；canonical revision hash |
| build | `source_revision_hash`、`build_spec_hash`、executable hash |
| run | `build_id`、`run_spec_hash`、run manifest hash、run root |
| data | `run_id`、data root、nt2 inventory hash；即使 raw data 增长也创建新 identity |
| analysis | `data_id`、analysis spec/code hash、结果 artifact hash |

`data_id` 由 canonical JSON
`{run_id, data_root, inventory_sha256, nt2py_version}` 的 sha256 生成；
`analysis_id` 由 `{data_id, analysis_spec_hash, code_hash}` 生成。程序不得按目录 mtime
或“最新文件”生成 identity。

### 5.3 原子激活新 run

`run.prepare` 完成时，Action request 必须包含：

```json
{
  "identity_id": "run-512-v1",
  "spec_hash": "sha256:...",
  "parents": {"build_id": "build-m87-cuda-v1"},
  "resource_bindings": {
    "run": {"site_id": "m87", "path": "/.../run-512-v1"},
    "data": {"site_id": "m87", "path": "/.../run-512-v1/data"},
    "analysis": {"site_id": "m87", "path": "/.../analysis/run-512-v1"}
  }
}
```

`finish-action` 针对成功的 `run.prepare` 在同一个 Case lock 和 revision 中：

1. 验证 run/data/analysis binding 的 site 和注册 root；
2. 追加不可变 run identity 并设置 `resources.run.current_id/active`；
3. 更新 data/analysis root；
4. 清空 data/analysis current ID；历史 identities 保留；
5. 设置 `data=unknown`、`analysis=none`；
6. 若 workflow target 的 run ID/spec hash 不匹配，拒绝完成而不是自动改 target。

禁止用独立的 `reconcile` 调用分步完成以上切换。

### 5.4 Action request/result 的增量字段

Action request v2 增加可选字段：

```json
{
  "orchestration": {
    "flow_id": "flow-20260717-001",
    "flow_request_hash": "sha256:...",
    "step_index": 2,
    "runner": "run.prepare.v1"
  },
  "spec_hash": "sha256:...",
  "parents": {"build_id": "...", "run_id": "...", "data_id": "..."},
  "resource_bindings": {}
}
```

Action result v2 增加同一 `orchestration` 和可选 `identity` record。旧 request/result
仍可读取；缺少 orchestration 的 active Action 只能按原 Router 流程恢复，façade
不得隐式接管。若确需接管，必须由用户显式执行未来单独设计的 adopt 操作，本期
不实现 `--adopt`。

`start-action` 增加：

```text
--flow-id
--flow-request-hash
--flow-step-index
--runner
--spec-hash
--parent NAME=ID
--resource-binding DIMENSION=LOCATOR
```

这些字段在 Action 启动后不可修改。

## 6. Flow request：不可变 bundle，不是第二套状态机

`flow-request.json` schema v1：

```json
{
  "schema_version": 1,
  "flow_id": "flow-20260717-001",
  "case_uid": "case-uid",
  "base_revision": 24,
  "workflow_id": "wf-512",
  "target_hash": "sha256:...",
  "goal": "materialize, build and launch the approved 512 run",
  "steps": [
    {
      "index": 0,
      "action_id": "source-materialize-001",
      "action_type": "source.materialize",
      "owner": "router",
      "execution_domain": "playbook-sync",
      "execution_site_id": "m87",
      "runner": "source.materialize.v1",
      "identity_id": "",
      "spec_hash": "sha256:...",
      "parents": {},
      "input_from": [],
      "inputs": [],
      "read_roots": [],
      "write_roots": [],
      "protected_paths": [],
      "resource_bindings": {},
      "constraints": [],
      "expected_outputs": [],
      "acceptance_checks": [],
      "runner_args": {}
    }
  ],
  "stop_policy": {
    "on_completed": "continue",
    "on_needs_decision": "return",
    "on_blocked": "return",
    "on_anomaly": "return"
  }
}
```

规则：

- bundle 最多 8 个步骤；每个步骤仍创建一个独立 Action；
- `action_id`、Action type、owner/domain/site、identity、roots、acceptance 和 runner
  均在执行前固定；
- `flow_request_hash` 是去掉该 hash 字段后的完整 canonical JSON sha256；
- `base_revision` 只约束 bundle 起点。后续每一步重读 current revision，但必须证明
  从起点以来的新增 mutation 都属于同一 flow 的已完成前序步骤；否则返回
  `revision_conflict`；
- façade 不维护 `current_step`。它扫描 Action request/result 的 flow hash 和 index
  推导已完成、active 或尚未开始的步骤；
- 下一步只有同时满足“前序 completed、在当前 allowed actions、target hash 未变、
  无未决选择、runner preflight pass”时才启动；
- bundle 不能包含 `data.purge`、`source.transfer-authority` 或 dependency source
  build；这些操作要求独立决策和授权；
- model-required step 只能使用 `execute --prepare/--resume`，不能在普通 bundle 中
  被 façade 假装完成。

后续步骤只能通过声明式 `input_from` 读取前序输出：

```json
{
  "step_index": 4,
  "role": "launch_receipt",
  "expected_locator": {"site_id": "m87", "path": "/.../launch-receipt.json"}
}
```

不支持字符串插值或表达式。façade 在前序 Action 完成后，从其已验证 result 中按
`step_index + role + exact Locator` 解析输入、重新 probe，并把实际 scheduler/PID
identity 写入即将启动的 Action request。这样 flow plan 在 launch 前不需要猜 job
ID，而 `run.monitor` Action request 启动后仍然完全不可变。

## 7. Façade CLI 精确合同

入口：

```text
skills/entity-router/scripts/entity_router_flow.py
```

公共输出字段：

```json
{
  "schema_version": 1,
  "status": "pass",
  "case_uid": "...",
  "revision": 24,
  "flow_id": "",
  "result": {},
  "issues": [],
  "artifact_refs": [],
  "metrics": {"tool_calls": 0, "remote_calls": 0, "output_bytes": 0}
}
```

退出码：

| Exit | 语义 |
|---:|---|
| 0 | `pass/completed/observe_only` |
| 10 | `needs_decision` |
| 20 | `blocked` |
| 30 | `anomaly` |
| 40 | request/schema/envelope 非法 |
| 50 | revision/active Action/flow hash 冲突 |

所有非零退出仍必须输出符合 schema 的 JSON；traceback 只写脱敏后的本地 debug
artifact，不进入 stdout。

### 7.1 `inspect`

```bash
python3 entity_router_flow.py inspect --case <uid>
python3 entity_router_flow.py inspect --cwd <absolute-path>
python3 entity_router_flow.py inspect --case <uid> --live --phase run
```

Case 选择规则：

1. `--case` 接受 exact UID 或 control path，优先使用；
2. `--cwd` 只按 registry 中的 authority/artifact/resource envelope 匹配，不读取
   source checkout 内的控制标记；
3. 0 个候选返回 `needs_decision/CASE_NOT_FOUND`；
4. 多个候选返回 `needs_decision/CASE_AMBIGUOUS` 和 compact candidates；
5. 永不按 last-opened、mtime、标签或“最新”自动选择。

`--live` 只 probe `--phase` 所需资源。新增
`entity_router_site.py probe-batch`，每个相关 site 最多一次 transport call，在该调用
内检查多个精确 Locator。多站点 Case 可以每 site 一次，不能承诺全局只有一次远端
调用。

compact 输出至少包含：

```json
{
  "case_uid": "...",
  "revision": 24,
  "workflow": {"id": "...", "phase": "run", "status": "active",
               "target_hash": "sha256:..."},
  "active_action": {"id": "...", "type": "run.monitor", "flow_id": "..."},
  "readiness": {"pgen": "verified", "build": "pass", "run": "running",
                "data": "unknown", "analysis": "none"},
  "identities": {"source": "...", "build": "...", "run": "...",
                 "data": "", "analysis": ""},
  "allowed_actions": [],
  "issues": [],
  "decision_required": false
}
```

### 7.2 `check`

```bash
python3 entity_router_flow.py check --case <uid>
python3 entity_router_flow.py check --case <uid> --live --phase run
```

静态 `check` 不访问远端；live check 复用 batch probe。结果优先级为
`anomaly > blocked > needs_decision > pass`。

Issue schema：

```json
{
  "code": "ID_RUN_BUILD_MISMATCH",
  "class": "anomaly",
  "message": "current run references a non-current build",
  "subject": {"kind": "run", "id": "run-512-v1"},
  "evidence_fingerprint": "sha256:...",
  "artifact_ref": null
}
```

首批 invariant：

| Code | 检查 | 失败分类 |
|---|---|---|
| `WF_TARGET_MISSING` | active flow 有结构化 target | needs_decision |
| `WF_TARGET_HASH_DRIFT` | request 与 current target hash 一致 | anomaly |
| `ACTION_REQUEST_MISSING` | active Action request 存在且 schema 合法 | anomaly |
| `ACTION_RESULT_ON_ACTIVE` | active Action 不得已有 terminal result | anomaly |
| `ACTION_OWNER_ENVELOPE` | owner/domain/site/read/write/protected 完整 | anomaly |
| `ID_BUILD_SOURCE_MISMATCH` | build parent 等于目标 source revision | anomaly |
| `ID_RUN_BUILD_MISMATCH` | run parent 等于目标/current build ID | anomaly |
| `ID_ACTIVE_RUN_SCOPE` | active run 位于 run root | anomaly |
| `ID_DATA_RUN_MISMATCH` | data parent 等于 current run ID | anomaly |
| `ID_DATA_SCOPE` | positive data evidence 位于 current data root | anomaly |
| `ID_ANALYSIS_DATA_MISMATCH` | analysis parent 等于 current data ID | anomaly |
| `MONITOR_TERMINAL_ACTIVE` | live terminal process 不保留 active monitor | anomaly |
| `RETRY_UNCHANGED_EVIDENCE` | 相同 request 的重试必须有 changed evidence | blocked |
| `SITE_UNREACHABLE` | live check 无 current evidence | blocked |

### 7.3 `execute`

```bash
python3 entity_router_flow.py execute --request <flow-request.json>
python3 entity_router_flow.py execute --request <flow-request.json> --prepare --step <index>
python3 entity_router_flow.py execute --request <flow-request.json> --resume \
  --step <index> --worker-result <site:/path>
```

普通 bundle：

```text
validate flow schema/hash/base revision/target
  -> derive step state from Case Actions
  -> for each unfinished deterministic step
       validate allowed action and runner preflight
       call state.py start-action
       dispatch fixed runner
       read/verify dispatch receipt
       reprobe expected outputs
       call state.py finish-action
  -> emit one compact bundle result
```

`--prepare`：

1. 校验并启动 model-required Action；
2. stage immutable Action request；
3. 返回不超过 4 KiB 的 worker envelope，只包含 Action request Locator/hash、owner
   skill/playbook、精确 input/read/write roots、成功标准和 worker-result 目标；
4. 不加载其他 phase 的 skill 或历史对话。

owner Worker 将结构化结果写到 Action 授权的 staging Locator。`--resume`：

1. 校验 worker-result 的 `case_uid/action_id/request_hash/owner`；
2. 不信任 Worker 的 success 文本，重新 probe changed/output Locator；
3. 逐项执行 acceptance check；
4. 通过 state.py finish；失败则关闭为 `failed/blocked` 并保留 evidence。

### 7.4 runner allowlist

`entity_router_flow_runners.py` 使用固定映射：

| Runner ID | Action | 固定入口/结果 |
|---|---|---|
| `source.materialize.v1` | `source.materialize` | `entity_router_site.py materialize`；revision evidence |
| `build.plan.v1` | `build.plan` | validate/create checkpoint、compat、generate env/build；requirements/checkpoint/scripts |
| `build.compile.v1` | `build.compile` | `entity_run.py build ... --quiet --json`；build_result/log/executable |
| `run.prepare.v1` | `run.prepare` | 创建 immutable run root/input/manifest；manifest hash |
| `run.launch.v1` | `run.launch` | scheduler/PID launcher；submission receipt/process identity |
| `run.monitor.v1` | `run.monitor` | `entity_router_status.py` 循环；terminal evidence |
| `data.inspect.v1` | `data.inspect` | `inspect_nt2_data.py DATA --output INVENTORY`；inventory/data identity |

`build.plan.v1` 仅在 schema-v2 `requirements.json` 已包含全部用户选择时运行；
checkpoint 已存在时才使用 `--merge`：

```text
entity_checkpoint.py validate requirements.json
entity_checkpoint.py create requirements.json [--merge checkpoint] --output checkpoint
entity_compat.py requirements.json --checkpoint checkpoint --json
entity_generate.py env checkpoint --output env.sh
entity_generate.py build requirements.json --env env.sh --checkpoint checkpoint --output entity-build.sh
```

若 validation 为 partial、compat 不是 pass、需要 dependency source build 或存在未接受
warning，runner 返回 `needs_decision`，不得自动降级或安装依赖。

runner_args 是每个 Runner ID 的独立 schema。任何 `command`、`shell`、`script_text`、
`pre_command` 字段一律拒绝；site-specific module/pre-command 只能来自已验证的
entity-env-build checkpoint，不能来自 flow request 自由文本。

## 8. 幂等执行与崩溃恢复

### 8.1 恢复判定

对每个 step，execute 按以下顺序判定：

1. 已存在同 action ID 的 result，且 flow hash/index 相同：返回缓存 terminal，
   不重跑；
2. 同 action ID active，且 flow hash/index 相同：进入恢复，不重新 start；
3. 同 action ID 存在但 hash/index 不同：`revision_conflict`；
4. Case 有其他 active Action：`revision_conflict`；
5. 前序 flow Action 与 Case events 不构成连续链：`revision_conflict`；
6. 否则启动新 Action。

### 8.2 dispatch receipt

每个 runner 在 Action staging/write root 写：

```json
{
  "schema_version": 1,
  "case_uid": "...",
  "action_id": "...",
  "flow_request_hash": "sha256:...",
  "runner": "run.launch.v1",
  "state": "effect_observed",
  "attempt": 1,
  "intent_written_at": "...",
  "effect_identity": {
    "scheduler": "slurm",
    "job_id": "12345",
    "job_name": "entity-<action-hash>"
  },
  "outputs": [],
  "stdout": {"sha256": "...", "bytes": 0, "tail": ""},
  "stderr": {"sha256": "...", "bytes": 0, "tail": ""}
}
```

`state` 枚举：`intent_written`、`effect_observed`、`outputs_verified`。receipt 是 owner
artifact，不是 controller workflow state；controller 只在 finish 时把其 hash/Locator
记为 evidence。每次 state 更新都必须以临时文件 + rename 原子替换；最终
`outputs_verified` receipt 的 hash 才进入 Action result。

### 8.3 `run.launch` 特殊规则

作业提交是不可盲重放的外部副作用：

1. 提交前写 `intent_written`，job name/comment 包含 deterministic action hash；
2. 提交成功后立即写 job ID 和 scheduler identity；
3. 若进程在 1 与 2 之间崩溃，恢复时先按 exact job name、user、submission time
   window 和 run root 查询 scheduler；
4. 恰好一个匹配则补写 receipt；0 个匹配才允许再次提交；多个匹配返回 anomaly；
5. 非 scheduler 启动必须由 wrapper 原子写 PID、`/proc` start ticks 和 run root；
6. 没有足够 identity evidence 时返回 blocked，绝不猜测进程。

普通自动重试最多一次，而且必须满足以下之一：

- external evidence fingerprint 已变化；
- runner 明确声明尚未产生外部副作用；
- runner 的恢复协议证明前一次副作用不存在。

## 9. `watch` 与 `run.monitor` 的唯一语义

`watch` 不是 `run.status` 的别名。它只执行已经 active 的 `run.monitor` Action：

```bash
python3 entity_router_flow.py watch --case <uid> --action <monitor-action-id> \
  --flow-request-hash <sha256> --interval-seconds 60 --timeout-seconds 86400
```

前置条件：

- Action type 必须是 `run.monitor`；
- request 中的 run ID/root、scheduler job ID 或 PID identity 完整；
- Action flow hash 与 CLI 相同；
- 当前 revision 和 active Action 匹配。

循环：

1. 调用 `entity_router_status.py`，每轮每个 site 最多一次远端调用；
2. 将 compact observation 写到 Action staging trace；
3. 若 process identity 与上一轮相同且状态/进度/evidence hash 未变，只增加
   `unchanged_polls_suppressed`，不产生模型事件；
4. 运行中继续等待；
5. terminal/anomaly/offline/timeout 时立即通过 state CLI 收口 Action，然后返回。

终态映射：

| 观察 | Action status | readiness | façade status |
|---|---|---|---|
| exit 0 + terminal evidence + acceptance pass | completed | `run=completed`；quick inventory 只可设 data `absent/partial/unknown` | completed |
| nonzero/fatal/identity mismatch | failed | `run=failed` | anomaly |
| site offline/evidence 不足 | blocked | 不推进 positive readiness | blocked |
| 用户授权 timeout | blocked | 保持最后已证实状态 | blocked |

`watch` 在返回前必须完成 `finish-action`。唯一例外是 façade 自身被 kill/crash；此时
active Action 保留，下一次相同 hash 的 `watch` 按第 8 节恢复。`check --live` 发现
process 已 terminal 但 Action 仍 active 时返回 `MONITOR_TERMINAL_ACTIVE`，恢复入口
必须优先收口它，不能新建第二个 Action。

`data=ready` 只能由后续 `data.inspect` 的 nt2py inventory 建立；field/checkpoint 的
浅层文件计数不足以宣称数据可读。

## 10. Data 与 analysis identity 流程

### 10.1 `data.inspect`

固定步骤：

1. 校验 current run ID/root 和 Action read envelope；
2. 在 data site 执行 `inspect_nt2_data.py`；raw data 只读；
3. inventory 必须写到 analysis/staging root，禁止写入 data root；
4. Router reprobe inventory，并计算 sha256；
5. 根据 `{run_id,data_root,inventory_sha256,nt2py_version}` 生成 data ID；
6. `finish-action` 原子追加 data identity、设置 current ID/readiness，并把旧 current
   analysis 标为 stale；
7. nt2 probe error 只证明 data `corrupt/unknown`，不得被解释为物理失败。

### 10.2 `analysis.run`

这是 model-required Action，使用 `--prepare/--resume`：

- request 必须包含 exact data ID、scientific question、analysis spec hash、code/output
  roots 和 acceptance checks；
- owner 模型只能在 analysis root 写代码、图和报告，不得写 raw data root；
- resume 重新执行或检查必要代码并 probe outputs；
- 成功后创建引用 exact data ID 的 analysis identity；
- data current ID 改变时，analysis readiness 自动 stale，历史产物不删除。

## 11. 审批与远端执行边界

审批分两类，不能混为一谈：

1. **业务授权**：Router request 内的 authorization，例如 `data.purge`、dependency
   source build、authority transfer；由 Case/Action contract 验证。
2. **宿主执行审批**：Codex/sandbox 对实际命令或权限边界的审批；由宿主决定，
   Router 不保存、不重放、不按 hash 自行放行。

runner 的价值是把多条零散 SSH/SCP 命令收敛到一个固定、可审查的入口，并减少
宿主可能需要的审批次数，但“一 Action 一审批”只是观测指标，不是 Router 保证。
若未来宿主提供 scoped approval API，必须单独评审 adapter；本期不实现 approval
cache。

远端 runner 必须：

- 使用 site profile 中的 transport/alias；
- 发送固定 helper 和不可变 JSON request，不拼接调用方 shell；
- 在远端再次验证 request hash、site ID、roots 和 protected paths；
- 首个失败停止，保留 receipt/log，不猜测修复；
- 返回结构化错误 `permission_denied/site_unreachable/envelope_violation/
  runner_failed`。

## 12. Context 与 observability

| 内容 | 正常上限 | 超限行为 |
|---|---:|---|
| Case summary | 4 KiB | 只保留 current identity/readiness/issues |
| Flow request summary | 4 KiB | 完整 request 留在 Locator |
| Terminal result | 4 KiB | evidence 列表改为 artifact ref |
| Failure result | 8 KiB | stdout/stderr 各保留脱敏尾部最多 2 KiB |
| Worker envelope | 4 KiB | 输入文件仅给 Locator/hash |
| 单个 owner reference | 一个 phase 一个 | 进入 phase 时延迟加载 |

新增观测字段：

```json
{
  "model_wakeups": {
    "total": 4,
    "by_reason": {"user_goal": 1, "owner_model_required": 2,
                  "workflow_terminal": 1}
  },
  "tool_roundtrips": 18,
  "remote_calls": 7,
  "approval_reviews": 7,
  "tool_output_bytes_injected": 12000,
  "unchanged_polls_suppressed": 42,
  "retries": {"total": 1, "without_changed_evidence": 0},
  "usage": {"input_tokens": null, "cached_input_tokens": null,
            "output_tokens": null, "wall_time_ms": 120000}
}
```

collector 只观察 façade、state/site/owner runner 和 artifact，不写 Case state。token
字段只用平台原始值；没有 usage 时保持 `null`，不按字符数估算。

## 13. 实施工作包

### WP0：合同和兼容层

修改：

- `templates/case-state.json`
- `templates/action-request.json`
- `templates/action-result.json`
- 新增五个 flow schema
- `scripts/entity_router_state.py`
- `tests/test_router_state.py`
- `tests/test_router_contracts.py`

实现：结构化 target、criteria evaluator、增量 Action 字段、统一 identity record、
`run.prepare` 原子激活、data/analysis identity transition。

完成门：旧 Case 仍可 show/verify；缺 target 的旧 Case flow-check 明确返回
needs_decision；所有 mutation 有 revision conflict 和 active Action 测试。

### WP1：inspect/check 与 batch probe

新增：

- `entity_router_flow.py inspect/check`
- `entity_router_flow_common.py`
- `entity_router_site.py probe-batch`
- `tests/test_router_flow_inspect.py`
- `tests/test_router_flow_check.py`

完成门：Case 0/1/N 候选、每 site 单调用、所有 invariant code、4 KiB 截断和离线
site 行为均有测试。

### WP2：确定性 execute 与 owner adapters

新增：

- `entity_router_flow.py execute`
- `entity_router_flow_runners.py`
- `tests/test_router_flow_execute.py`
- `tests/test_router_flow_build_adapter.py`

先支持 `source.materialize`、`build.plan`、`build.compile`、`run.prepare`。完成门：
bundle 内每步独立 Action；错误 stop-first；无任意 shell 字段；build partial/compat
fail 返回 needs_decision；崩溃恢复不重复副作用。

### WP3：launch/watch/monitor

新增：

- `run.launch.v1` 和 `run.monitor.v1`
- dispatch receipt 与 scheduler/PID recovery
- `tests/test_router_flow_watch.py`
- `tests/test_router_flow_launch_recovery.py`

完成门：模拟“提交后写 receipt 前崩溃”、重复 job、PID 重用、offline、timeout、
terminal active Action 和无限 unchanged poll；任何路径都不盲重提作业。

### WP4：data/analysis 与 model Worker 两段式

新增：

- `data.inspect.v1`
- `execute --prepare/--resume`
- `tests/test_router_flow_data_identity.py`
- `tests/test_router_flow_worker_resume.py`

完成门：data ID 对 run/inventory 稳定；inventory 变化生成新 ID；analysis exact
引用 data ID；Worker narrative 单独不能推进状态；错误输出 root 被拒绝。

### WP5：观测、评测与启用

新增：

```text
evals/router-flow/
├── baseline.json
├── scenario.json
├── expected-invariants.json
└── replay-fixtures/
```

本地 replay 和 controller-local query canary 先执行；受管事务默认通过
`entityctl flow`。旧 `list/show/verify/status/start-action/finish-action` 不删除，只用于
精确恢复和诊断。m87 live canary 仍要求用户对该远端计算副作用单独明确授权。

## 14. 测试矩阵

| 类别 | 必测场景 |
|---|---|
| Case 选择 | exact UID、cwd 单候选、共享 checkout 多候选、registry stale |
| Revision | base drift、step 间外部 mutation、同 Action 不同 hash |
| Target | 缺失、hash drift、512 target 对 256 run、target 更新后 stale |
| Envelope | wrong site、path escape、symlink escape、controller overlap |
| Identity | source-build、build-run、run-data、data-analysis parent mismatch |
| Bundle | 正常串行、第二步失败、model step stop、禁止 purge/authority transfer |
| Build | partial requirements、compat fail、warning、dependency source build gate |
| Launch | 提交前失败、提交后 crash、0/1/N scheduler match、PID reuse |
| Watch | unchanged、progress、exit 0、nonzero、fatal、offline、timeout、resume |
| Data | absent、partial、ready、corrupt、inventory 改变、output 写入 data root |
| Context | 4/8 KiB 边界、脱敏、artifact ref、无完整 Case/log 泄漏 |
| Compatibility | Python 3.6.8、旧 Case、旧 Action、现有 fast status |

单元测试不能访问真实 scheduler；通过 fake site transport 和固定 status fixture 验证。
live m87 只用于 canary，不作为 CI 必要条件。

## 15. 端到端验收

场景：

```text
修改 PGen
  -> m87 source materialize
  -> build plan/compile
  -> new run prepare/launch
  -> model 外 monitor
  -> data inspect
  -> scientific analysis
```

正确性硬门：

- Case、Workflow、每个 Action、owner/domain/site/envelope 均符合 Router v3；
- source -> build -> run -> data -> analysis identity chain 闭合；
- 新 run 原子切换 roots，绝不继承旧 run 的 data/analysis current identity/readiness；
- scheduler/PID 恢复不重复提交；
- terminal monitor 在 façade 返回前收口；
- Worker 结果必须经 controller reprobe 才能推进状态；
- 任一硬门失败，效率指标即使达标也不接受。

效率门：

- `model_wakeups.total <= 6`；
- `tool_roundtrips <= 30`；
- `approval_reviews <= 10`，仅作为观测目标；
- 注入模型的工具输出总量 `<= 64 KiB`；
- 任意数量 unchanged polls 不增加模型上下文；
- 相对固定 baseline 的工具往返和注入字节均降低至少 60%。

token 门是条件式的：当 baseline 和 canary 都有平台原始 token usage 时，要求模型
处理 token 降低至少 60%；任一侧 usage 为 `null` 时记录 `not_assessed`，不以字符数
替代，最终结论由调用数、注入字节、wall time 和正确性硬门决定。

## 16. 开工顺序与停止条件

严格顺序：`WP0 -> WP1 -> WP2 -> WP3 -> WP4 -> WP5`。WP0 未完成前不实现
watch；WP2 的幂等基础未通过前不接 scheduler；WP3 未证明不重复提交前不做 live
canary。

每个工作包结束时必须：

1. 运行该包定向测试；
2. 运行完整 `python3 -m unittest discover -s tests -v`；
3. 运行 `git diff --check` 和 Router Python 3.6 兼容检查；
4. 更新本文对应的已实现/未实现状态；
5. 若发现需要第二写入者、降低证据强度或盲重放外部副作用，立即停止并重新评审。

当 WP0 的 schema/transition tests 全部通过后，本计划即具备进入代码实现阶段的
条件；在此之前不得先写 façade 外壳来绕过缺失的状态语义。
