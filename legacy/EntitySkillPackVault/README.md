# Entity Skill Pack 知识库

这是一个用于设计和开发 Entity 通用 skill pack 的 Obsidian 知识库。

目标是帮助 agent 以三种主要方式使用
[Entity](https://github.com/entity-toolkit/entity)：

- 可复现地运行等离子体模拟；
- 使用 nt2py 和数值诊断分析模拟结果；
- 基于当前源码 checkout 开发 Entity 功能。

从这里开始：

- [[Home|首页]]
- [[10-Architecture/Entity Skill Pack Architecture|Entity Skill Pack 架构]]
- [[40-Development/Development Plan|开发计划]]

## 当前状态

这个 vault 是设计和指导层，还不是可直接安装的 skill pack。第一阶段实现目标是最小可用版本：

- router skill；
- 共享的 source-of-truth 知识；
- simulation 和 development 两个核心 skill；
- run/development 模板。

## 写作约定

以后这个 Obsidian vault 内的笔记默认使用中文书写。代码标识符、命令、路径、YAML 字段名和上游英文术语可以保留英文。

