# Docs Skill 规范

## 使命

为 Entity 模拟和开发工作创建可长期复用的文档。

这个 skill 让工作可以跨 session、跨 agent 延续。

## Artifact 类型

- simulation plan；
- run manifest；
- analysis report；
- development design note；
- PR summary；
- validation report；
- troubleshooting note。

## 规则

- 必要时使用绝对路径记录本地 artifact。
- 记录 Entity checkout commit。
- 记录实际运行过的命令。
- 分离已验证事实和假设。
- 分离官方上游行为和 local overlay。
- 保留未解决问题。

## 模板

- [[90-Templates/Run Manifest Template|Run Manifest 模板]]
- [[90-Templates/Simulation Plan Template|Simulation Plan 模板]]
- [[90-Templates/Analysis Report Template|Analysis Report 模板]]
- [[90-Templates/Development Design Note Template|Development Design Note 模板]]

