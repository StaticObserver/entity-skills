---
name: entity-pgen
description: 设计、实现、解释、评审和修改 Entity problem generator（PGen），以及配套的 TOML 配置与 docs/design.md。适用于目标明确、边界清晰的 PGen 领域工作，可直接使用，包括独立的新建或既有 PGen、初始场或粒子、边界、自定义行为、输出、归一化以及 PGen-TOML 一致性。当前拒绝在 Router 管理的 Case 内写入（v5 pgen Goal 尚未实现）；Case 生命周期、跨领域工作、构建、运行、未归类的故障、Entity 核心改动以及科学分析，请路由给对应的负责技能。
---

# Entity PGen

## 目的

将 `pgen.hpp` 与其 TOML 配置作为一个设计单元来开发。以 `docs/design.md` 作为权威设计文档与当前完成情况记录。在不强制每个任务走固定流水线的前提下，保持设计、PGen 实现与 TOML 三者一致。

将随附的 references 作为按需查阅的知识库使用。只加载当前任务所需的内容，并对照当前活动的 Entity 源码检出核实与版本相关的细节。

## 执行模式与写入门禁

在加载领域 references 或修改文件之前，先对任务进行分类：

- **只读**：在不改动文件的前提下解释、检查或评审。可在独立路径或受管路径下
  直接执行。不要创建过程性产物。
- **独立写入**：仅修改 PGen 所属的产物，且目标位置确切、不在 Router 管理的
  Case 之内。可直接执行。
- **受管写入**：修改已在 Router v5 store 中注册的源 Locator。当前一律拒绝：
  受管写入需要 v5 pgen Goal，而该 Goal 尚未实现。请将请求路由给
  `entity-router`。

每次写入前，运行：

```bash
python3 <entity-pgen-skill>/scripts/pgen_preflight.py \
  --router-home <controller-root> \
  --operation write \
  --target <site_id:/exact/absolute/path>
```

从本 `SKILL.md` 解析 `<entity-pgen-skill>`；不要假设当前工作目录就是技能目录。
对每个预期目标运行 preflight，或对它们最窄的共同父目录运行。
仅当其返回 `"allowed": true` 时才继续。preflight 会查询 Router v5 store，
检查目标 Locator 是否落在已注册的 Case 源、identity 根目录或活动运行之下；
它绝不从祖先目录推断受管状态。如果报告 `router-required`，则不要写入；将
目标、检测到的 Case、请求的变更及原因返回给 `entity-router`。
绝不要修改 Router 的控制状态。

即使失败（退出码 2）也总会打印 JSON。其中 `store_present` 字段表明注册表
是否被实际查询过：`true` 表示已确认 `standalone-write` 目标未注册；`false`
表示 Router store 缺失或不可读，此时 standalone 仅意味着“无法检查”——应
将其视为警告而非确认；`null` 表示在查询之前评估就已失败（例如 `--target`
无效）。

对于未被 Router 注册的目标，仅当用户选定了确切位置且只要求 PGen 领域交付物
时，才按 standalone 处理。含义模糊的工作区创建、持久化的模拟工作，或任何
延续到构建、运行、恢复或分析的请求，都路由给 Router。

## 范围

处理：

- 在 standalone 模式下设计新 PGen 及配套 TOML；
- 修改或评审已有的 PGen/TOML 组合；
- 在实现变更的同时维护 `docs/design.md`；
- 检查归一化、坐标基、API 用法以及 PGen-TOML 一致性；
- 修复已归因于 PGen 代码或配置的问题。

路由至他处：

- 受管 Case 生命周期与跨领域模拟工作流 -> `entity-router`；
- 依赖配置、CMake 配置与编译执行 -> `entity-env-build`；
- 归属尚不明确的故障 -> 将证据返回给 package Router；
- Entity 引擎或框架改动 -> 将限定了范围的交接返回给 package Router；
- 模拟输出访问与可视化 -> `entity-nt2py`；科学分析路由给 `entity-router`。

不要向核心技能添加平台特定的元数据或调用配置。

## 核心规则

1. 将 `docs/design.md`、`pgen.hpp` 与配套 TOML 视为一个整体来维护。
2. 在修改 PGen 或 TOML 之前，先阅读当前设计与实现。若不存在设计文档，则从当前文件重构一份最小化设计，并将推断出的决定标注为“推断”。
3. 设计中覆盖 PGen 的每个核心组件：基本配置、初始电磁场、初始粒子、边界、自定义行为与自定义输出。未使用的组件标注为 `not-used`，而不是省略。
4. 保持设计简洁。记录意图、相关 TOML 映射与当前状态；仅在为消除歧义所必需时才加入公式或实现细节。
5. 对实质性改变物理模型、归一化或实现方向的决定，要先确认。当未决问题不构成阻塞时，继续安全的局部工作。
6. 在可行时，以当前活动的源码检出为准核实 Entity 版本、API 签名、归一化与坐标基约定。随附 references 针对 Entity v1.4.4，其效力次于当前源码证据。
7. 当变更影响 PGen 与 TOML 的共同契约时，两者须一起修改，然后更新对应的设计章节与当前状态。
8. 在任何运行提交之前，向用户展示参数卡，并用 `python3 <entity-pgen-skill>/scripts/pgen_preflight.py confirm <input.toml> --by <actor>` 记录确认（未逐项审查而接受默认值时加 `--confirm-defaults`）。该命令会写出 `<input.toml>.decisions.json`；当记录缺失或其 `input_sha256` 与 TOML 不再匹配时，Router 的 plan 门禁会拒绝签发 plan。任何 TOML 编辑后都要重新运行 `confirm`。

## 工作方法

根据请求调整工作深度：

1. **定位**：找到活动的 Entity 源码检出、PGen、TOML 与 `docs/design.md`；只检查与任务相关的证据。
2. **识别受影响的设计**：确定涉及哪些核心组件与 TOML 键。在实现之前先解决阻塞性的物理决策。
3. **加载 references**：阅读下方相关的参考文件，并将与版本相关的论断同活动检出对照。
4. **设计与实现**：创建或更新 `docs/design.md`，然后进行相应的 PGen 与 TOML 修改。局部修正时，在同一轮中更新设计与实现。
5. **验证**：检查受影响的设计-PGen-TOML 契约，并运行与任务相称的静态、编译、冒烟或物理检查。
6. **记录状态**：更新设计文档中的当前状态，并报告哪些已实现、已验证、未决或已移交。

对于纯解释类请求，阅读并解释现有设计与实现，不要创建过程性产物。对于评审，报告具体的冲突与证据；除非确有必要，不要将任务扩大为全面重设计。

## 设计文档

将所有 PGen 设计材料存放在 `docs/` 下。默认使用单个 `docs/design.md`；仅当 PGen 确实需要时才增加辅助文档。

使用如下紧凑结构：

```markdown
# <name> Design

## 1. Goal
State the physical problem, intended behavior, and important exclusions.

## 2. Basic Configuration
Record the Entity version, engine, metric, dimensions, normalization/basis, and special build or data requirements.

## 3. Initial Electromagnetic Fields
State: not-used | planned | implemented | verified
Describe the intended fields and matching TOML parameters.

## 4. Initial Particles
State: not-used | planned | implemented | verified
Describe species, distributions, and matching TOML parameters.

## 5. Boundaries
State: not-used | planned | implemented | verified
Describe field and particle boundaries and matching TOML parameters.

## 6. Custom Behavior
State: not-used | planned | implemented | verified
Describe any ext_current, ext_force/ExternalFields, CustomPostStep, CustomParticleUpdate, or other hooks and their TOML parameters.

## 7. Custom Output
State: not-used | planned | implemented | verified
Describe CustomFieldOutput, CustomStat, and matching TOML names.

## 8. PGen-TOML Contract
Record only the key mappings and constraints that must remain synchronized.

## 9. Current Status
List completed, pending, open, and verified work.

## 10. Important Changes
Record only changes that alter the physical model, interfaces, or TOML contract.
```

当问题需要时，Agent 可以扩展、合并或精简各小节，但必须保留核心组件覆盖与当前状态记录。

## Reference 路由

所有 references 描述的都是 Entity v1.4.4。只阅读与受影响设计相关的文件。

| 需求 | References |
|---|---|
| 归一化、单位或坐标基 | `references/00-normalization.md` |
| PGen 结构、traits、构造函数或参数 | `references/01-skeleton.md` |
| 初始电磁场 | `references/02-init-fields.md` |
| 初始或补充注入的粒子 | `references/03-particle-injection.md` |
| 外部电流 | `references/04-ext-current.md` |
| 外力或外部场 | `references/05-ext-force.md` |
| 边界条件 | `references/06-boundary.md` |
| 自定义场输出或统计量 | `references/07-custom-output.md` |
| 自定义时间步或粒子更新 | `references/08-custom-post-step.md` |
| TOML 结构与参数 | `references/09-toml-config.md` |
| 高阶场或粒子算法 | `references/10-higher-order.md` |
| 现有 Entity PGen 模式 | `references/pgens-index.md` |

对于新 PGen，从 `00`、`01` 和 `09` 开始，然后加载设计所选定的特性 references。对于已有 PGen，从其当前文件开始，只加载受影响组件所需的 references。当某个 API 模式不确定时使用 `pgens-index.md`，然后在活动检出中检查所引用的实现。

## 一致性与验证

在受影响范围内检查三组关系：

1. `docs/design.md` <-> `pgen.hpp`；
2. `docs/design.md` <-> TOML；
3. `pgen.hpp` <-> TOML。

包含以下相关检查：

- PGen traits 与 TOML 的 engine、metric 和维度匹配；
- `params.get()` 的键与 TOML `[setup]` 中的名称和类型匹配；
- 粒子种类的数量、顺序、属性与索引相互一致；
- 场与粒子的边界设置与已实现的 hook 匹配；
- 自定义输出名称与 TOML 请求一致；
- 归一化与坐标基明确且一致；
- 设计所需的特殊算法、构建选项与外部数据均已声明；
- 设计状态如实反映实际获得的证据。

除非实际执行过，否则不要声称完成了编译、冒烟测试或物理验证。局部修改不需要重新检查算例中无关的部分。

## 交付物

对于新 PGen，产出：

```text
pgens/<name>/
|-- pgen.hpp
|-- <name>.toml
`-- docs/
    `-- design.md
```

额外的设计笔记、图或验证记录仅在需要时才放入 `docs/`。运行时数据表放在 `docs/` 之外合适的数据目录中。

当需要构建或运行验证时，将当前检出的 identity、PGen/TOML 路径、设计要求与未解决的约束交接给负责的技能。
