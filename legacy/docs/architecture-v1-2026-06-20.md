# Entity Skills 总体架构

日期：2026-06-20

归档状态：已由 `design/architecture.md` 取代，不参与当前设计或运行时上下文。

## 1. 项目定位

`entity-skills` 暂时设计为一个完整的 skills package。

它不是 Entity 知识库，也不是教程，而是一套面向 agent 的 harness：顶层 `SKILL.md` 负责判断用户请求属于哪类任务，并指导 agent 加载对应的具体 skill。

设计原则见 `design/harness-principles.md`。该原则用于指导项目设计，但不是 package 运行时依赖。

## 2. 仓库分区

```text
entity-skills/
├── SKILL.md        # 顶层 router
├── README.md       # package 使用说明
├── core/           # 所有 skill 共享的基本规则
├── skills/         # 具体 task skills
├── playbooks/      # 跨 skill 的组合工作流
├── templates/      # 交接和状态模板
├── references/     # 非权威参考材料
├── design/         # 项目设计工作文件
└── legacy/         # 旧项目归档
```

边界：

- `SKILL.md`、`core/`、`skills/`、`playbooks/`、`templates/`、`references/`、`README.md` 属于 skills package。
- `design/` 只保存设计文档，不应被运行时自动加载。
- `legacy/` 只保存旧项目归档，不应被运行时自动加载。

## 3. 顶层 Router

顶层 `SKILL.md` 应该很薄。

它只做三件事：

- 说明这个 package 的目标和非目标；
- 根据用户请求选择需要加载的 skill；
- 要求 agent 只加载完成当前任务所需的最小上下文。

它不应该包含详细 Entity API、TOML 参数表、PGen 细节或分析代码示例。

## 4. 核心模块

`core/` 保存所有 skill 都需要遵守的基础规则。

暂定包含：

- `context.md`：项目角色、非目标、成功标准；
- `source-of-truth.md`：当前 checkout、上游、wiki、references、local overlay、legacy 的优先级；
- `checkout-probe.md`：什么时候必须检查目标 Entity checkout；
- `code-map.md`：Entity 源码中应优先查看的位置；
- `state-model.md`：当前任务状态、会话发现、长期约定的区分。

这些文件只放稳定规则和索引，不复制大段知识。

## 5. Task Skills

`skills/` 是项目主体。每个 skill 负责一种任务边界和一种验证方式。

暂定六个 skill：

- `entity-env-build.md`：依赖、编译环境、CMake、MPI、Kokkos、ADIOS2。
- `entity-case.md`：simulation case，包括 TOML、PGen、run script 和 run manifest。
- `entity-analysis.md`：输出读取、诊断、作图、证据分级和分析报告。
- `entity-core-dev.md`：Entity 源码修改、call path、owner boundary 和测试。
- `entity-debug.md`：build/runtime/output/checkpoint/performance/numerical failure 诊断。
- `entity-docs.md`：长期交接产物，如 simulation plan、run manifest、analysis report、debug report、dev note。

重要边界：

- 跑模拟和源码开发必须分开。
- TOML 和 PGen 必须作为同一个 case contract 处理。
- 不单独设置泛化的 run-ops skill。
- output/checkpoint 相关内容进入 analysis 或 debug。

## 6. Playbooks

`playbooks/` 用来组合多个 skill，处理跨模块任务。

暂定 playbooks：

- `new-simulation.md`
- `reproduce-run.md`
- `analyze-output.md`
- `debug-failure.md`
- `source-change.md`

playbook 只写编排逻辑，不写大量领域知识。

## 7. Templates

`templates/` 是状态和交接机制。

暂定模板：

- `simulation-plan.md`
- `run-manifest.yaml`
- `analysis-report.md`
- `debug-report.md`
- `dev-design-note.md`

模板的细节之后单独设计。

## 8. References

`references/` 只放非权威 orientation。

暂定 reference：

- `build-orientation.md`
- `case-orientation.md`
- `nt2py-orientation.md`
- `version-buckets.md`

reference 不能覆盖当前 Entity checkout。它们只能帮助 agent 知道该查什么、怎么查。

## 9. 设计顺序

先设计整体框架，再逐个细化：

1. 顶层 `SKILL.md` router。
2. `core/` 基础规则。
3. 六个 `skills/` 的边界和骨架。
4. `templates/` 的最小字段。
5. `playbooks/` 的组合逻辑。
6. `references/` 的取舍和压缩。

每一步都先定义边界、输入、输出和验收标准，再决定需要多少知识内容。
