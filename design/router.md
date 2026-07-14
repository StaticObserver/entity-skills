# Entity Router 控制协议

日期：2026-07-13  
状态：整体设计的专项细化；初版控制协议已实现

整体架构以 `architecture.md` 为准。本文只保留 Router 实现必须遵守的控制协议。

## 1. 职责

Router 是唯一控制面，负责：

- 选择和恢复 Case；
- 建立 Workflow 和 Action；
- 计算 readiness、stale、allowed actions 和 next action；
- 生成 Action Contract；
- 管理 Case-bound Worker；
- 验证 Worker 产物后提交状态转移；
- 处理失败路由、Case 切换和中断恢复。

Router 不实现专业 skill，不把完整日志或全部 child references 放进自身上下文。

## 2. 控制对象

```text
Case -> Workflow -> Action -> Worker
```

- 每个 Case 同时最多一个 active Workflow；
- 每个 Workflow 同时最多一个 active 修改型 Action；
- 每个 Action 只有一个 owner；
- Worker 绑定 `(case_id, execution_domain)`，不能跨 Case 复用或改作其他领域；
- Agent/thread ID 只属于当前 runtime，不进入持久 Case 状态。

## 3. 标准循环

1. **Orient**：精确选择 Case、checkout 和 run，禁止猜“最新”；
2. **Recover**：读取 `case.json` 和 owner 产物，校验 fingerprints 与动态状态；
3. **Decide**：根据 playbook、readiness 和 blocker 计算下一 Action；
4. **Start**：原子记录 `action.started`，生成不可变 `request.json`；
5. **Dispatch**：复用匹配 Worker，或使用全新上下文创建 Worker；
6. **Verify**：重新读取实际输出，执行 Action 的 acceptance checks；
7. **Commit**：写 `result.json`、append event、更新 `case.json` revision；
8. **Route**：进入下一 Action，或将 Workflow 标记为 blocked、suspended、complete。

Worker 总结只能作为验证线索，不能直接触发第 7 步。

## 4. Action Contract

`request.json` 至少包含：

- schema version、Case revision、Case/Workflow/Action ID；
- owner、goal 和 relevant decisions；
- inputs 及 fingerprints；
- read roots、write roots 和 protected paths；
- expected outputs、acceptance checks；
- 与本 Action 直接相关的 failure evidence。

`result.json` 由 Router 验证后写入，至少包含：

- terminal status；
- changed paths 和 output fingerprints；
- verification evidence；
- blocker、diagnosis 和建议 next owner；
- started/finished time。

Action 启动后 Contract 不可修改。需要改变目标、owner、输入或写入范围时，先关闭或取消旧 Action，再建立新 Action。

## 5. Worker 管理

### 创建

Worker 首次创建时只接收：

- 对应 child skill 或 Router-owned playbook 片段；
- Action Contract 路径；
- 读取 Contract 所需的最小说明。

不要继承 Router 的完整对话，也不要预加载其他 child skill。

### 复用

Case 和 owner 不变时复用 Worker。PGen -> build -> PGen 的回路应回到原 PGen Worker，而不是重新加载全部 PGen 上下文。

运行、监控和续跑由 `playbook-run` Worker 执行。它属于 Router 执行域，但不是独立 skill。

### 回收

出现以下情况时回收：

- checkout 或专业范围根本变化；
- 上下文过长、过期或明显漂移；
- 无变化的失败循环；
- Workflow 完成、Worker 长期不用或 Worker pool 容量不足。

Case 切换时 Worker 必须保持原 Case 绑定；容量允许时可隔离保留，容量不足时按 LRU 回收。Worker registry 是易失内存。Router 恢复后若旧 Worker 不可用，按 Action Contract 和磁盘事实惰性重建。

## 6. 写入与并发门禁

Action 开始前必须确认：

- Case/Workflow/Action 与当前 revision 一致；
- owner 和 Worker binding 匹配；
- Action 位于 allowed actions；
- 输入 evidence 当前有效；
- 所有目标位于 write roots；
- protected paths 不被覆盖；
- 前置 readiness 通过；
- 无 blocking blocker。

默认只允许一个 active 修改型 Action。只读工作或写入范围完全分离的工作可以并发，但 Router 必须显式证明无失效关系。

只有 Router 状态工具可以写 `_case/`。Worker 不得修改 Case 状态，也不得直接向另一个 Worker 发指令。

## 7. Case 切换

### 离开

1. 检查未闭合 Action；
2. 根据实际产物更新 readiness；
3. 保存 blocker、next action 和 last summary；
4. 挂起未完成 Workflow；
5. 保存 history snapshot 并 append event；
6. 隔离该 Case 的 Worker；容量不足时再回收。

### 进入

1. 按明确 Case ID/path 选择；
2. 校验 schema、revision 和 scope；
3. 重新读取 PGen、build、run 和 data evidence；
4. 比较 fingerprints 并传播 stale；
5. 查询真实 process/scheduler 状态；
6. 重算 allowed actions 和 next action；
7. 绑定目标 Case 的 write roots 后再创建 Worker。

不得沿用上一个 Case 的 decisions、active run、handoff、Worker 或 write roots。

## 8. Failure、Retry 与恢复

- owner 内错误留在原 Worker 中最小修复；
- owner 改变时关闭当前 Action，由 Router 建立新 Action；
- 原因不明时运行短生命周期 `failure.triage` Action；
- retry 必须记录变化的 input fingerprint 或明确理由；
- 未闭合 `action.started` 恢复时，以磁盘产物判断结果；
- revision 冲突时拒绝覆盖，重新读取 Case；
- 不支持的 Entity core 问题保留 evidence 并停止扩张能力边界。

## 9. 状态工具边界

确定性 case-state 工具负责：

- create/list/open/suspend/resume Case；
- schema validation、atomic write 和 revision compare-and-swap；
- start/finish/cancel Action；
- 生成 request、提交验证后的 result；
- append event 和保存 Workflow snapshot；
- fingerprint、stale propagation 和 allowed-actions 计算。

Agent 不手写复杂 Case JSON。状态 schema、transition rules 和 tests 完成后，再修改 `skills/entity-router/SKILL.md` 与其 playbooks。
