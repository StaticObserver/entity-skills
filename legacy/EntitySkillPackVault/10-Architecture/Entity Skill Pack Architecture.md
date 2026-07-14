# Entity Skill Pack 架构

## 问题

Entity 相关工作天然分成几类：

- 模拟运行：配置、编译、运行、监控、重启；
- 结果分析：读取输出、作图、验证数值和物理行为；
- 功能开发：修改 C++/Kokkos/MPI/ADIOS2 代码并验证变更；
- 排错：诊断编译、运行、数值、输出和集群环境问题。

如果把这些内容塞进一个很大的 skill，浅层运行指导和深层源码开发知识会混在一起。结果会难以维护，也更容易臆造版本相关 API。

## 系统方案

采用 Entity Skill Pack：

```text
entity-skillpack/
├── SKILL.md                  # router / dispatcher
├── core/                     # 共享的源码事实与基础知识
├── skills/                   # 面向任务的 skill
├── playbooks/                # 可复用工作流
└── templates/                # 结构化交接与产物模板
```

在这个 Obsidian vault 中，上述目录以设计笔记的形式存在：

- [[20-Skills/Router Skill Spec|Router Skill 规范]]
- [[Knowledge Model and Version Strategy|知识模型与版本策略]]
- [[40-Development/Development Plan|开发计划]]

## 组件

### Router

Router 应该很薄，只负责分类用户请求，并加载最小必要的任务 skill：

- 模拟请求 -> simulation skill；
- 分析请求 -> analysis skill；
- 源码功能请求 -> development skill；
- 失败诊断 -> debug skill；
- artifact/report 写作 -> docs skill。

### Core Knowledge

Core knowledge 由所有 skill 和所有 agent 共享。它存放稳定的方向感和 source-of-truth 规则，而不是完整复制 Entity 文档。

它应该包含：

- 版本与 checkout 检测；
- 官方权威信息源；
- 代码地图；
- 概念和术语；
- 常见陷阱；
- 不能和上游行为混淆的本地 overlay。

### Task Skills

每个 task skill 只负责一种工作流和一种验证标准。

- Simulation skill：可复现实验运行。
- Analysis skill：基于证据解释输出。
- Development skill：基于源码事实实现和测试。
- Debug skill：跨工作流的失败诊断。
- Docs skill：长期笔记、run manifest、设计说明和 PR 摘要。

## 边界

### Simulation 与 Development

Simulation 工作可以编辑 pgen、TOML、脚本和分析 artifact。默认不修改 Entity 核心源码。

Development 工作可以修改 Entity 核心，但必须先检查当前 checkout，并明确相关源码路径、trait、kernel、engine 或 writer 边界。

### Official 与 Local

只有从当前 checkout 或官方 wiki 确认过的上游行为，才能写入共享 core。

用户 fork、实验分支和项目专用行为应写入 local overlay，并明确标注。

## 第一阶段实现目标

先做最小可用 skill pack：

```text
SKILL.md
core/source-of-truth.md
core/code-map.md
skills/entity-sim.md
skills/entity-dev.md
templates/run-manifest.yaml
templates/dev-design-note.md
```

之后再补 analysis、debug、docs 和 playbooks。

