# Entity Skills 0.7.0 生产使用评估（第一周）

日期：2026-08-17
状态：评估完成，修复方案待评审
数据来源：`~/.entity-skills/observability/invocations/2026-08.jsonl`（生产调用日志，
2026-08-09 上线）、kimi 会话 wire 日志（`~/.kimi-code/sessions/`）、codex rollout
日志（`~/.codex/sessions/`）、源码逐条核实。

## 0. 总结

0.7.0 的 Workspace/Site 抽象在生产中**立住了**：迁移周的真实工作（多项目目录迁移、
run 对账、远程编译提交）都走了新模型，`record relocate` 51 次调用 50 次成功。
观测埋点第一周就证明了自己的价值——本报告的全部问题证据都来自它。

同时暴露出 **3 个真 bug（P0）** 和一批契约/可用性问题（P1/P2）。最严重的一个
（远端 executor 崩溃被报成 "invalid JSON"）让 kimi agent 在 8-10 夜里白白排查了
28 分钟；另一个是台账失真：Slurm CANCELLED 的 run 被记成 `completed` 且无法更正。

## 1. 数据概览

- 调用总量 2258 条，其中 **2030 条（90%）是仓库 pytest 噪声**（见 P1-I1），
  真实生产调用 228 条。
- 生产时间分布：08-09（142，迁移日）→ 08-10（69，polar_cap 事故夜）→
  08-11（11）→ 之后零星。使用项目：polar_cap、bh-reconnection、axion-pic、
  axion-grpic。
- 客户端：全部为 kimi（codex 本周无 entity 会话，见 §5；claude 无使用）。
  kimi 主动携带了 `--actor-provider kimi --actor-run-id kimi-ledger`，归因可用。
- 关键命令成功率（生产，不含测试）：

| 命令 | 成功 | 失败 | 备注 |
|---|---|---|---|
| `record relocate` | 50 | 1 | 迁移主力，健康 |
| `record run-prepare` | 2 | 9 | 事故中心，见 P0-B1 |
| `record run-launch` | 6 | 5 | 连锁失败，见 P0-B2 |
| `record run-exit` | 2 | 5 | 见 P0-B2/B3 |
| `status` / `show` / `doctor` | 5 | 2 | 见 P1-I5 |
| `pgen_preflight` | 3 | 1 | 失败的那次是**好的失败**（见 §3） |

## 2. 什么运作良好（不要动）

1. **观测层本身**：被动 JSONL 日志 + never-fail 设计无故障运行一周，抓到了全部
   关键事件，且没有对宿主工具造成任何可见影响。
2. **迁移流程**：`workspace import` + `record relocate`（51 次调用）完成了四个
   项目的目录迁移，成功率 98%。
3. **好的错误消息即时生效**：`pgen_preflight` 拒绝相对路径时给出
   `"locator must use SITE_ID:/absolute/path [target: ...]"`,agent 10 秒内
   换绝对路径成功。对比 P0-B1 的 28 分钟——错误消息质量直接决定恢复成本。
4. **legacy schema 守卫**:8-09 修复后，无指针 + 旧 v2 db 的场景下 doctor 正常
   给出迁移指引，无崩溃复发。
5. **agent 的台账纪律**:8-09 批量 run-exit 失败时，agent 没有擅自批量 abort
   需要人工声明的 run，而是列为待用户拍板事项；事故后主动向用户报备台账失真。
   Ledger 的"人工声明"门禁起到了设计意图的作用。

## 3. P0：真 bug（建议立即修）

### B1. 远端 executor 崩溃被吞成 "Site executor returned invalid JSON"

- **现象**:8-10 13:10–13:20,`record run-prepare` 连续 8 次 exit 2，错误只有
  `"Site executor returned invalid JSON"`,status=anomaly。agent 被迫读三个技能
  源码文件、ssh 到 astro 手动重放 executor，才看到真实根因：astro 登录节点默认
  python3 是 3.6.8，executor 用了 `contextlib.nullcontext`(3.7+）直接
  AttributeError,traceback 在 stderr,stdout 为空。
- **根因**（已核实）:`skills/entity-ledger/scripts/entity_ledger_operation.py`
  `ExecutorClient.invoke()`（约 201 行）在检查 `code != 0` **之前**调用
  `_json_from_stdout(stdout, "Site executor")`。远端非零退出、stdout 无 JSON 时，
  `_json_from_stdout` 先抛，携带 traceback 的 stderr 永远到不了错误消息。
  讽刺的是错误分支里本来写了 `stderr.strip()` 兜底，但不可达。
- **修复方案**:invoke 里先判 `code != 0`：非零时用 stderr 尾部（最后 ~500 字符）
  构造 OperationError("Site executor exited <code>: <stderr tail>");code 为 0
  才解析 JSON，解析失败时报 "invalid JSON" 并附 stdout 头部。附带收益：executor
  的 python 版本下限（3.7+）应写进 site profile 的探测/文档。
- **工作量**：小（~15 行 + 2 个测试：远端非零退出带 stderr、零退出坏 JSON)。
- **会话证据**:`wd_polar_cap_f4cd27212882/session_21329893`,turn 112–114。

### B2. Slurm CANCELLED/TIMEOUT 的 run 被记成 `completed`，且无法更正

- **现象**:8-10 凌晨 polar_cap 的 run-23dbefcc8d2d9b64 实际 OOM 死亡，agent 先
  手动 `scancel` 了空转进程，sacct 报 `CANCELLED 0:0`;`record run-exit` 按
  exit_code=0 记成 **completed**。台账失真，且后续 `record run-launch` 被拒
  ("only a prepared run can be launched"),`--reclassify` 只对 failed 开口，
  completed 是死路。agent 只能向用户报备"这条记录有水分"而无法修正。
- **根因**（已核实）:`entity_ledger_record.py` `record_run_exit()`（约 1475 行）
  `final = "completed" if exit_code == 0 else "failed"` —— **scheduler_state
  完全不参与分类**。CANCELLED/TIMEOUT/PREEMPTED/NODE_FAIL/OUT_OF_MEMORY 只要
  退出码是 0:0 就记 completed。`_slurm_exit_probe` 明明已经把 scheduler_state
  取回来了。
- **修复方案**:
  1. 分类时先看 scheduler_state:`COMPLETED` 才允许按 exit_code 记 completed;
     `CANCELLED`/`TIMEOUT`/`PREEMPTED`/`NODE_FAIL`/`OUT_OF_MEMORY` 等记 failed
     （或新增终态 `cancelled`,`TERMINAL_RUN_STATES` 已有 "exited"/"aborted"
     先例，加一个是兼容的），并把 scheduler_state 写进事件 payload（现在只写进
     identity.scheduler.state)。
  2. `--reclassify` 的适用范围从 failed 扩到 completed（反向更正场景），或新增
     `record run-correct --status cancelled` 人工更正原语。倾向后者：reclassify
     语义是"按日志证据重判"，人工更正不该伪装成证据判定。
  3. 存量失真记录（run-23dbefcc8d2d9b64）在新原语落地后由用户人工更正。
- **工作量**：中（分类逻辑 + 新原语 + ~5 个测试）。
- **注意**：这改了终态语义，动之前确认没有测试钉住 "CANCELLED 0:0 → completed"。

### B3. `_require_case` 错误消息误导：把"项目未登记"说成"Case 缺失"，并指向错误命令

- **现象**:8-10 12:57–13:00,agent 用迁移前的旧路径
  `--project-root ~/Documents/polar_cap` 调 `record run-exit`，得到
  `"no Case covers the project; create it first"`,decision 建议
  "run entityctl record run-prepare to create the Case" —— **run-prepare 并不
  创建 Case**。Case 存在，只是绑在迁移后的新路径。agent 没盲从（值得表扬），
  靠自己对迁移背景的记忆花了 5 分钟才换对新路径。
- **根因**（已核实）:`entity_ledger_record.py:108` `_require_case()` 里
  `CaseResolutionError(no_project)` 和 `StoreError` 共用同一条消息；消息既没
  区分"这个项目路径没登记"和"项目里没有 Case"，也没给出正确的建 Case 命令。
- **修复方案**:
  1. 拆分两类错误的文案：项目未登记 → "no project is registered at
     <path>; if it moved, use the new path or `entityctl workspace import`";
     项目无 Case → 给出真实建 Case 的命令（核对代码里的正确拼写）。
  2. 加分项：项目未登记时，在 workspace registry 里模糊匹配同名目录（如
     `projects/polar_cap`）并在消息里列出候选——agent 是在报错里学习的，
     这比文档有效（8-10 的 site deps-add astro → astro-axion 也是同类问题，
     site 名不匹配时应列出已登记的 site 候选）。
- **工作量**：小（消息层 + 2–3 个测试）。

## 4. P1：契约与可用性（建议 0.7.1)

### I1. 测试流量污染生产日志（90% 噪声）

- 2258 条记录里 2030 条来自仓库 pytest(cwd/argv 含 `/var/folders/` 临时目录）。
  不处理的话，长期统计（成功率、命令分布）都要先写过滤器。
- **方案**:`_invocation_log.py` 加 kill switch:`ENTITY_SKILL_INVOCATION_LOG=off`
  时完全静默；仓库 `tests/conftest.py` 里 autouse fixture 把它设为 off（或指向
  tmp)。四份拷贝同步，一致性测试已有。工作量：小。

### I2. `status` 字段的重试语义没有告诉 agent

- kimi 因 astro SSH 间歇断连养成习惯，把**所有** ledger 调用包进
  `for i in 1..5; sleep` 重试循环。对 `invalid_request`/`needs_decision` 这类
  确定性错误重试永远无效——8-10 夜的 ×5/×5/×8 全是白烧（每次最多浪费 150 秒
  sleep)。
- **方案**:① 在 SKILL.md 的合约节写明：`anomaly` 才可重试，其余 status 必须
  改变输入或升级给人；② 错误 payload 里加一个 `"retryable": false` 字段
  （机器可读，agent 不用猜）。工作量：小。

### I3. run-launch 没有重提交原语

- job 357460 因 executable 缺失秒挂后，再 `record run-launch` 返回
  `ok:true, state_mutated:false, "run already has a recorded scheduler
  identity"`(exactly-once 收据，设计如此）。agent 只能绕过 ledger 手动 sbatch
  再 `--adopt-job`。"ledger 提交的 job 失败后重提"是常见场景，值得一个原语。
- **方案**:`record run-relaunch`（或 `run-launch --resubmit`)：仅当 run 的已记
  job 处于终态且失败时，生成新 submission 收据并重新提交。设计需要过一稿
  （收据语义、事件链），工作量：中。

### I4. run-exit 对在跑的 run 返回含糊

- 对在跑的 run 调 run-exit 返回 `ok:true, state_mutated:false, state:"running"`
  （代码核实：确实有 state 字段），但无任何一句人话说明"什么都没写"。agent 要靠
  推理确认。方案：返回里加 `detail: "run is still running; no state written"`。
  工作量：一行 + 测试。

### I5. `doctor` 不支持 `--project-root`

- agent 凭对称性直觉猜了 `doctor --project-root`（status/show/record 都收），
  撞 argparse 错误。方案：要么 doctor 接受该旗标做项目级过滤，要么 argparse
  错误文案里写明 "doctor is workspace-scoped; use status --project-root"。
  工作量：小。

### I6. 调用归因依赖 agent 自觉

- 迁移批次（无 actor 旗标）无法归因到客户端。方案：`_invocation_log.py`
  best-effort 嗅探环境变量（`KIMI_*`/`CLAUDE*`/`CODEX_*` 等）补 `agent_hint`
  字段，嗅探不到就省略。工作量：小。

## 5. 环境状态更正与遗留事项

- **codex 已在 0.7.0**:8-09 21:42（本地）有一次不带 `--provider` 的
  `entityctl install`，把 codex 链接也重建为走 `current` → bundle `7215fc5a`。
  此前"codex 钉在 0.6.1"的状态已不存在。本周 codex 无 entity 会话（黄金/文献
  项目），无冲突实例。这再次暴露共享 `current` 选择子的固有行为：任何一次
  裸 install 都会联动三家——0.7.x 设计议题（每 provider 独立选择子）仍在桌上。
- **deps 注册表为空**:8-17 axion-grpic 会话里 `site deps pi2-v100` 返回
  `"stacks": []`,agent 只能靠手写交接文档拿依赖信息。astro/pi2 的依赖栈补登
  是运维待办（`site deps-add`)，不是代码问题；但 `site deps` 输出为空时可以
  加一句提示（"no stacks registered; see site deps-add")。
- **0.7.x 设计议题**（不在本次修复范围）:source authority 重登记原语、批量历史
  run import、跨会话知识（如 "astro 需 companion sbatch""python3.6 已修"）目前
  靠项目目录里的手写交接文档承载，Ledger 不存这类 site 运维事实。
- **astro python3.6 根因已临时修复**(agent 在 astro ~/.bashrc 前置了 py39 路径）,
  但这是 site 级环境修补，应补登进 site 档案（sites/<site>.yaml）而不是只留在
  交接文档里。

## 6. 建议的修复路线

1. **立即（一个 commit 批）**:B1、B3、I1、I2、I4、I5、I6——都是小改动，
   互不冲突，合计一天内。B1 优先级最高（诊断成本最大）。
2. **0.7.1（需要一稿小设计）**:B2（终态语义变更 + 人工更正原语）、I3（重提交
   原语）。B2 涉及存量记录更正，落地后处理 run-23dbefcc8d2d9b64。
3. **0.7.x 设计讨论**：共享 current 选择子、source authority 重登记、批量
   import、site 运维事实的承载位置。
4. **运维待办（非代码）**:astro/pi2 deps 栈补登、astro python 修复写入 site
   档案。

## 附：证据索引

- 调用日志：`~/.entity-skills/observability/invocations/2026-08.jsonl`
- kimi 关键会话：`wd_polar_cap_f4cd27212882/session_21329893`（事故夜）、
  `wd_documents_3746f1f7c2c5/session_5f71f7c7`（迁移收尾批量对账）、
  `wd_axion-grpic_9df4b4432942/session_a8d28d5b`（健康样本）
- 代码核实点：`entity_ledger_operation.py:201`、`entity_ledger_record.py:108`
  (`_require_case`)、`entity_ledger_record.py:1475`（终态分类）、
  `entity_ledger_record.py:1296`（`_slurm_exit_probe`)
