# Entity Skill Pack

## 目的

构建一个面向 Entity 的通用 skill pack：

- 帮助用户安全、可复现地运行模拟；
- 帮助用户分析结果，并明确结论的证据强度；
- 帮助用户从当前 checkout 出发开发 Entity 功能，而不是依赖过时记忆。

这个设计刻意区分“使用 Entity”和“开发 Entity”。这两类工作需要不同的知识深度、风险控制和验证标准。

## 导航

### 架构

- [[10-Architecture/Entity Skill Pack Architecture|Entity Skill Pack 架构]]
- [[10-Architecture/Knowledge Model and Version Strategy|知识模型与版本策略]]
- [[10-Architecture/Agent Collaboration Model|Agent 协作模型]]

### Skill 规范

- [[20-Skills/Router Skill Spec|Router Skill 规范]]
- [[20-Skills/Env Build Skill Spec|Env Build Skill 规范]]
- [[20-Skills/Entity Case Skill Spec|Entity Case Skill 规范]]
- [[20-Skills/Simulation Skill Spec|Simulation Skill 规范]]
- [[20-Skills/Analysis Skill Spec|Analysis Skill 规范]]
- [[20-Skills/Development Skill Spec|Development Skill 规范]]
- [[20-Skills/Debug Skill Spec|Debug Skill 规范]]
- [[20-Skills/Docs Skill Spec|Docs Skill 规范]]

### Playbook

- [[30-Playbooks/New Simulation Workflow|新模拟工作流]]
- [[30-Playbooks/Analysis Workflow|分析工作流]]
- [[30-Playbooks/Entity Development Workflow|Entity 开发工作流]]
- [[30-Playbooks/Debugging Workflow|排错工作流]]

### 开发

- [[40-Development/Development Plan|开发计划]]
- [[40-Development/Backlog|Backlog]]
- [[40-Development/Acceptance Criteria|验收标准]]

### 参考

- [[50-References/Entity Source of Truth|Entity 权威信息源]]
- [[50-References/Local Context and Overlays|本地上下文与 Overlay]]

### 模板

- [[90-Templates/Run Manifest Template|Run Manifest 模板]]
- [[90-Templates/Simulation Plan Template|Simulation Plan 模板]]
- [[90-Templates/Development Design Note Template|Development Design Note 模板]]
- [[90-Templates/Analysis Report Template|Analysis Report 模板]]

## 写作约定

本 vault 的笔记默认使用中文。必要的英文术语、代码标识符、命令、路径和 YAML 字段名保留英文。

## 设计原则

Skill pack 不应该试图记住 Entity 的全部细节。它应该教 agent 如何在当前 checkout 中找到权威细节，并把这些细节组织成可靠的工作流。
