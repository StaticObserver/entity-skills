# 知识模型与版本策略

## 原则

当前 Entity checkout 比 skill pack 更权威。

Skill pack 应该保存：

- 去哪里查；
- 查什么；
- 如何解释查到的内容；
- 应该遵循什么工作流。

除非明确标注版本范围，否则不要在 skill pack 中保存大段复制的参数表或 API 签名。

## 信息源优先级

每个 Entity 任务都按以下顺序优先：

1. 当前本地 checkout。
2. 需要或用户要求时，检查当前上游仓库。
3. 官方 wiki，用于概念解释。
4. Skill pack 笔记，用于工作流和方向。
5. Local overlays，用于用户 fork 或实验分支行为。

## 必做 Checkout 探测

在模拟或开发前，收集：

```bash
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse --short HEAD
git describe --tags --always
```

如果不是 Git checkout，就记录绝对路径和可用版本信息。

## 官方权威文件

先查这些文件，再相信 skill-pack 摘要：

- `input.example.toml`：运行参数和 TOML 层级。
- `pgens/*/pgen.hpp` 与 `examples/*/pgen.hpp`：当前 PGen 写法。
- `src/global/traits/pgen.h`：PGen hook 检测和签名。
- `src/engines/*`：engine 调度顺序以及 time/step 状态归属。
- `src/kernels/*`：device kernels 与数值操作。
- `src/framework/domain/*`：`Metadomain`、`Domain`、`Mesh` 和 local domain 行为。
- `src/output/*` 以及 ADIOS2 相关代码：输出语义。

## 版本桶

至少跟踪这些版本桶：

- `official-v1.4.x`：当前上游 release 系列。
- `official-master`：最新上游开发状态。
- `legacy-v1.3.3`：仍和现有本地工作有关的旧分支系列。
- `local-staticobserver`：用户 fork 行为。
- `local-experimental`：任务分支和未发布修改。

任何描述行为的笔记都应该说明适用哪个版本桶。

## 依赖版本矩阵

Entity 编译环境必须按 Entity 主版本选择依赖族，不能随意混用：

| Entity 版本桶 | Kokkos | ADIOS2 | 关键注意事项 |
| --- | --- | --- | --- |
| `official-v1.4.x` | Kokkos 5.x | ADIOS2 2.11.x | 编译 ADIOS2 时需要带上 Kokkos 依赖。 |
| `legacy-v1.3.x` | Kokkos 4.x | ADIOS2 2.10.x | 不要套用 1.4.x 的 ADIOS2/Kokkos 组合。 |

如果当前 checkout 不能明确归入这些版本桶，agent 必须先读取仓库的 `README.md`、`dependencies.py`、`cmake/` 和官方 wiki，再给出依赖建议。

## 高漂移风险

容易变化的内容：

- TOML 层级和默认值；
- PGen hook 签名；
- 输出 quantity 名称；
- custom particle update hook；
- Kokkos 和 ADIOS2 版本要求；
- ADIOS2 是否需要 Kokkos 依赖；
- 分支特定功能。

相对稳定的内容：

- simulation 与 development 的工作流边界；
- run manifest 的必要性；
- `Metadomain -> Domain -> Mesh -> Fields/Particles` 概念层级；
- code units、physical coordinates、tetrad basis、coordinate basis 的区别。

## Local Overlay 规则

本地扩展不能写成上游事实。

例子：

- 官方上游可能说明 `ext_current` 只限 Minkowski。
- 本地 fork 可能扩展了 `ext_current`，加入 time-aware context 或其他行为。

Skill pack 必须把后者标注为 local overlay，并要求使用前检查当前 checkout。
