# Agent 协作模型

## 单 Agent 模式

一个 agent 可以使用整个 skill pack：

```text
用户请求
-> router
-> core knowledge
-> task skill
-> 可选 debug/analysis/docs 支持
-> 最终产物
```

这是默认设计目标，可以让第一版保持简单。

## 多 Agent 模式

同一套 skill pack 也可以支持多个专门 agent：

- Coordinator Agent：路由任务、维护状态、处理交接。
- Simulation Agent：配置、编译、运行并记录模拟。
- Analysis Agent：读取数据、生成诊断、校准结论强度。
- Development Agent：修改 Entity 源码并验证变更。
- Debug Agent：调查编译、运行、集群和数值问题。

所有 agent 必须共享同一个 core knowledge，不应该各自维护一份 Entity 事实。

## 交接契约

每次交接都应包含：

- Entity checkout 路径；
- branch/tag/commit；
- 任务目标；
- 已检查文件；
- 已产出 artifact；
- 已运行命令；
- 已完成测试或检查；
- 未解决风险。

模拟任务使用 [[90-Templates/Run Manifest Template|Run Manifest 模板]]。

开发任务使用 [[90-Templates/Development Design Note Template|Development Design Note 模板]]。

## 避免的模式

不要创建一个声称凭记忆掌握所有 Entity API 的巨大 agent。Entity 会变化，这种模式必然漂移。

