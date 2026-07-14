# 验收标准

## 系统级标准

- Skill pack 支持单 agent 和多 agent 两种用法。
- 所有 task skills 共享 core knowledge。
- 版本敏感细节从当前 checkout 验证。
- 官方上游行为和本地 fork 行为清晰分离。
- 生成的 artifact 可复现，并包含路径、commit 和命令。

## Simulation Skill 标准

- 产出 run manifest。
- 在生成 TOML 指导前读取当前 `input.example.toml`。
- 捕获 build flags 和 backend。
- 记录 checkpoint policy。
- 区分 config check、smoke run、numerical sanity 和 physics validation。

## Analysis Skill 标准

- 尽可能 lazy load 数据。
- 记录 data path、species、time selection 和 output quantities。
- 标注证据强度。
- 非平凡分析保存 script/notebook/report。

## Development Skill 标准

- 编辑前探测 Git checkout。
- 提出修改前读取当前源码。
- 分离已验证事实和拟议设计。
- 列出 tests run 和 tests not run。
- 记录 compatibility risks。

## Debug Skill 标准

- 从离错误最近的 artifact 开始。
- 分类 failure category。
- 一次只提出一个改动。
- 报告 verification result 和 remaining uncertainty。

