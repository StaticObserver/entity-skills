---
name: entity-pgen
description: Design, write, and debug Entity problem generators (pgen.hpp + TOML). Use when the user needs to create a new PGen, modify existing PGen code, write matching TOML configs, debug compile/runtime/physics errors in PGen code, or understand Entity's API and normalization conventions for PGen development.
---

# Entity-PGen

## Mission

帮助 Agent 将用户的物理需求转化为正确的、可编译的 Entity Problem Generator（pgen.hpp + TOML config）。本 skill 将 PGen 开发的每个能力拆成独立 reference，Agent 按需匹配、组合。

核心工作流：

```
需求澄清 → 需求文档 → 匹配 references → 设计文档 → 用户确认 → 构建代码+TOML → 三向审计 → 修复 → 交付
```

## Boundaries

**Handle**: 需求引出、PGen 代码编写、TOML 配置、归一化约定、结构完整性检查、代码-TOML 一致性审计。

**Route to other skills**:
- 编译环境、CMake 配置、编译执行 → `entity-env-build`
- Entity 引擎源码修改（Ampere 内核、Context 扩展等）→ `entity-core-dev`
- 数据分析/可视化 → `entity-analysis` 或 `nt2py`

## Hard Rules

1. **归一化**：B0 = 1/larmor0 引擎内置。init_flds 不除以 larmor0。ext_current 乘以 skindepth0²/larmor0 补偿（详见 `references/00-normalization.md`）
2. **坐标基**：SRPIC → local tetrad (orthonormal) basis。GRPIC → coordinate basis。不可混用
3. **单位域**：InitPrtls = 物理单位。CustomPostStep / ext_current = 代码单位
4. **实例名强制**：`init_flds`、`ext_force`、`ext_current` 的名字由 C++20 concept 检测，不可改变
5. **写代码前有确认门**：Step 2 产出 design.md 后，必须取得用户明确确认
6. **审计后才交付**：Step 5-6 的三向审计必须通过，不可跳过
7. **current_filters 默认 0**：依赖电荷守恒的 PGen 必须设 `current_filters = 0`
8. **species 索引 1-based**：arch::InjectUniform* 的 species 参数从 1 开始

## 最小可运行 PGen

Entity 的所有功能检查通过 `if constexpr` 实现——不存在的方法/成员会被静默跳过。因此 PGen 的最小骨架只需要 traits 声明 + 空构造函数：

```cpp
#pragma once
#include "enums.h"
#include "global.h"
#include "traits/pgen.h"
#include "framework/domain/metadomain.h"

namespace user {
  using namespace ntt;

  template <SimEngine::type S, class M>
  struct PGen {
    static constexpr auto engines {
      ::traits::pgen::compatible_with<SimEngine::SRPIC> {}
    };
    static constexpr auto metrics {
      ::traits::pgen::compatible_with<Metric::Minkowski> {}
    };
    static constexpr auto dimensions {
      ::traits::pgen::compatible_with<Dim::_1D> {}
    };
    PGen(const SimulationParams&, const Metadomain<S, M>&) {}
  };
} // namespace user
```

以下成员/方法**全部可选**（引擎通过 traits 检测是否存在，不存在就跳过）：

| 成员/方法 | 不存在时的行为 |
|-----------|--------------|
| `init_flds` | 场保持为零（真空） |
| `InitPrtls()` | 不注入粒子（无粒子模拟） |
| `CustomPostStep()` | 无时间步钩子 |
| `MatchFields()` | MATCH 边界不可用 |
| `FixFieldsConst()` | FIXED 边界不可用 |
| `AtmFields()` | ATMOSPHERE 边界不可用 |
| `ext_current` | 无外部电流源 |
| `ext_force` | 无外部力 |
| `ExternalFields()` | 无外部 E/B/力 |
| `CustomFieldOutput()` | 无自定义场输出 |
| `CustomStat()` | 无自定义统计量 |
| `CustomParticleUpdate()` | 无自定义粒子更新 |

编译只需要 `pgens/<name>/pgen.hpp` 存在即可（CMake 的 `set_problem_generator()` 只检查这个文件）。

## Reference 功能摘要

根据用户需求关键词匹配需要加载的 references：

| Reference | 何时需要 | 触发关键词 |
|-----------|---------|-----------|
| `00-normalization.md` | **必读** | 必读 |
| `01-skeleton.md` | **必读** | 必读 |
| `02-init-fields.md` | 需要初始电磁场 | 磁场、电场、Bx/By/Bz、Ex/Ey/Ez、Wald、dipole、Harris sheet |
| `03-particle-injection.md` | 需要粒子 | 等离子体、粒子、电子、离子、注入、Maxwellian、密度分布、pair plasma |
| `04-ext-current.md` | Ampere 源项（仅 Minkowski） | 外部电流、天线、axion current、J_ext、源项 |
| `05-ext-force.md` | 粒子外力 | 外力、外部加速度、辐射力、external B/E field |
| `06-boundary.md` | 非 PERIODIC 边界 | open boundary、吸收边界、固定边界、大气层、conductor |
| `07-custom-output.md` | 自定义诊断量 | 自定义输出、额外诊断量、derived field |
| `08-custom-post-step.md` | 时间步钩子 | 补充注入、移动窗口、动态边界、piston、周期性注入 |
| `09-toml-config.md` | **必读** | 必读 |

## 开发工作流（7 步）

### Step 1: 需求澄清 → user_requirements.md

加载 `00-normalization.md` 和 `01-skeleton.md` 作为背景知识。

向用户逐项确认以下信息。按顺序询问，不要跳过：

| # | 问题 | 选项/说明 | 默认值 |
|---|------|----------|--------|
| 1 | PGen 名称 | 英文小写+下划线 | **必填** |
| 2 | 物理问题描述 | 自由文本：模拟什么现象？ | **必填** |
| 3 | Simulation engine | `SRPIC` / `GRPIC` | `SRPIC` |
| 4 | Metric | `Minkowski` / `Spherical` / `QSpherical` / `Kerr_Schild` / `QKerr_Schild` | `Minkowski` |
| 5 | 空间维度 | 1D / 2D / 3D | 根据问题推断 |
| 6 | 网格分辨率 + 物理范围 | 每维 [N, extent_min, extent_max] | **必填** |
| 7 | 初始场配置 | B 场？E 场？空间分布？均匀/非均匀？ | 无（真空） |
| 8 | 粒子物种数 + 每个物种的 label/mass/charge | 列表 | 无粒子 |
| 9 | 粒子初始分布 | Uniform / NonUniform？温度？漂移速度？密度？ | — |
| 10 | 边界条件 | PERIODIC / MATCH / FIXED / ABSORB / ... | PERIODIC |
| 11 | 是否需要外部电流/力？ | 描述物理机制 | 无 |
| 12 | 是否需要时间步钩子？ | 补充注入/移动窗口/动态边界/... | 无 |
| 13 | 是否需要自定义输出？ | 额外场量/统计量 | 无 |
| 14 | Fiducial scales | larmor0, skindepth0 | larmor0=1.0, skindepth0=1.0 |
| 15 | 运行时参数 | `runtime`、`ppc0`、`CFL`、`output interval` | runtime=100.0, ppc0=32, CFL=0.45 |

收集完所有答案后，将结果写入 `user_requirements.md`，格式如下：

```markdown
# User Requirements — <pgen_name>

## 物理问题
<描述>

## 模拟参数
| 参数 | 值 |
|------|-----|
| Engine | SRPIC |
| Metric | Minkowski |
| Dimensions | 2D |
| Resolution | [256, 256] |
| Extent | [[-10, 10], [-10, 10]] |
| Boundaries | PERIODIC |
| Runtime | 100.0 |
| larmor0 | 1.0 |
| skindepth0 | 1.0 |
| CFL | 0.45 |

## 场配置
<描述初始 E/B 场>

## 物种列表
| # | Label | Mass | Charge | Pusher | maxnpart |
|---|-------|------|--------|--------|----------|
| 1 | e- | 1.0 | -1.0 | Boris | 5e6 |
| 2 | e+ | 1.0 | 1.0 | Boris | 5e6 |

## 粒子初始分布
<温度、漂移速度、密度、分布类型>

## 外部电流/力
<如适用>

## 时间步钩子
<如适用>

## 自定义输出
<如适用>

## 特殊注意事项
<用户特别提到的约束>
```

向用户展示 `user_requirements.md`，确认无误后进入 Step 2。

### Step 2: 匹配 References → 设计文档 → design.md

**子步骤 2a: 匹配 references**

根据 user_requirements.md 中的功能点，匹配需要加载的 references：

| 需求特征 | 加载的 reference |
|---------|-----------------|
| 有初始场 | `02-init-fields.md` |
| 有粒子 | `03-particle-injection.md` |
| 有外部电流 | `04-ext-current.md` |
| 有外部力 | `05-ext-force.md` |
| 非 PERIODIC 边界 | `06-boundary.md` |
| 有自定义输出 | `07-custom-output.md` |
| 有时间步钩子 | `08-custom-post-step.md` |
| 总是需要 | `00-normalization.md`, `01-skeleton.md`, `09-toml-config.md` |

加载所有匹配的 references，仔细阅读 API 签名、约束和陷阱。

**子步骤 2b: 编写 design.md**

基于需求文档和 references，编写设计文档：

```markdown
# Design — <pgen_name>

## 参考的 References
- 00-normalization.md
- 01-skeleton.md
- 02-init-fields.md  ← 需要初始 B 场
- 03-particle-injection.md  ← 需要粒子注入
- 09-toml-config.md

## PGen 结构
### Traits 声明
- engines: { SRPIC }
- metrics: { Minkowski }
- dimensions: { _2D }

### 成员列表
| 成员 | 类型 | 来源 Reference |
|------|------|---------------|
| params | const SimulationParams& | skeleton |
| metadomain | Metadomain<S,M>& | skeleton |
| init_flds | InitFields<D> | 02-init-fields |
| B0, theta | real_t (from [setup]) | 02-init-fields |

### 定义的方法
| 方法 | 作用 | 来源 Reference |
|------|------|---------------|
| PGen(...) | 构造，从 TOML 读取参数 | skeleton |
| InitPrtls(...) | 初始粒子注入 | 03-particle-injection |

## InitFields 设计
<描述 InitFields 的 struct 结构，每个方法的返回值公式>

## InitPrtls 设计
<描述注入方式、使用的 archetype、参数值>

## TOML [setup] 参数
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| B0 | real_t | 1.0 | 磁场强度 |
| temperature | real_t | 0.01 | 等离子体温度 |

## 边界条件
- Fields: PERIODIC × 2
- Particles: PERIODIC × 2

## 归一化检查清单
- [ ] InitFields 不除以 larmor0
- [ ] ext_current 乘以 skindepth0²/larmor0（如适用）
- [ ] InitPrtls 使用物理单位
- [ ] CustomPostStep 使用代码单位（如适用）
```

### Step 3: 用户确认设计

将 design.md 完整呈现给用户。**必须等待用户明确确认**后才能进入 Step 4。

如果用户提出修改意见，回到 Step 2 修改设计文档，重新确认。

确认话术："以上是完整的设计方案。确认后我将开始编写代码和 TOML。是否需要调整？"

### Step 4: 构建代码

基于 design.md，生成两个文件：

**4a. 生成 `pgen.hpp`**

按以下顺序组装：
1. Include guards + headers（来自 01-skeleton）
2. namespace + using（来自 01-skeleton）
3. InitFields struct（来自 02-init-fields，如设计需要）
4. ext_current / ext_force struct（来自 04/05，如设计需要）
5. PGen struct（来自 01-skeleton）：
   - traits 声明
   - 成员变量
   - 构造函数（params.get 读取 [setup] 参数）
   - InitPrtls()（来自 03，如设计需要）
   - MatchFields / FixFieldsConst / AtmFields（来自 06，如设计需要）
   - CustomPostStep()（来自 08，如设计需要）
   - CustomFieldOutput() / CustomStat()（来自 07，如设计需要）

每个方法加注释标注使用的是物理单位还是代码单位。

**4b. 生成 `<name>.toml`**

基于 09-toml-config.md 和 design.md 中的参数：
1. 填入用户确认的 simulation、grid、metric、boundaries
2. 填入 scales（larmor0, skindepth0）
3. 填入 particles + species（如有粒子）
4. 填入 [setup] section（PGen 专属参数）
5. 填入 output 配置
6. 设置 `current_filters = 0`（电荷守恒默认）

### Step 5: 三向审计

**同时拉起三个独立的审计子 Agent。** 每个子 Agent 只负责一个审计维度，互不干扰。

#### 审计 Agent 1: 代码正确性

```
Prompt: "审计以下 PGen 代码的语法正确性和潜在 bug。检查：
1. C++ 语法是否正确（括号匹配、分号、模板语法）
2. traits 声明是否与用户需求匹配
3. 每个使用的 API 调用是否签名正确（对照 references 中的签名）
4. 单位系统是否正确标记
5. 归一化约定是否正确（InitFields 不除以 larmor0，ext_current 补偿系数）
6. 常见陷阱：1-based vs 0-based 索引混淆、CommunicateFields 遗忘、死粒子电荷守恒
7. 潜在的性能问题
输出：问题列表（严重/警告），每个问题附带具体的代码位置和修复建议"
```

#### 审计 Agent 2: 需求满足度

```
Prompt: "对照 user_requirements.md 审计以下 PGen 代码 + TOML 是否完整实现了用户需求。检查：
1. user_requirements.md 中列出的每一项功能是否都有对应的代码实现
2. 用户指定的物理场在 InitFields 中是否正确设置
3. 用户指定的粒子物种是否全部在 TOML 中定义并在 InitPrtls 中注入
4. 用户指定的边界条件是否在 TOML 中正确配置，是否匹配 MatchFields/FixFieldsConst 的实现
5. 用户的 [setup] 参数是否全部在构造函数中读取和在 TOML 中定义
6. 用户指定的输出需求是否在 TOML 和 CustomFieldOutput/CustomStat 中实现
输出：逐项检查表（✓/✗/⚠），对不满足的项目给出具体缺失描述"
```

#### 审计 Agent 3: 代码-TOML 一致性

```
Prompt: "审计 PGen 代码和 TOML 文件之间的一致性。检查：
1. pgen.hpp 中每个 params.get<T>('setup.xxx') 的 xxx 是否在 TOML [setup] 中有对应项（类型匹配）
2. TOML [setup] 中的每个参数是否在 pgen.hpp 中被读取
3. TOML particles.nspec 是否等于 [[particles.species]] 的数量
4. TOML species label/charge/mass 与代码中 Inject 的 species 索引是否一致
5. grid.dim 是否与 pgen.hpp traits dimensions 兼容
6. grid.metric.metric 是否与 pgen.hpp traits metrics 兼容
7. simulation.engine 是否与 pgen.hpp traits engines 兼容
8. TOML boundaries 的 BC 类型是否有对应的 PGen 方法（如 MATCH→MatchFields, FIXED→FixFieldsConst）
9. [output.fields] custom 列表是否与 CustomFieldOutput 中的 name 匹配
10. [output.stats] custom 列表是否与 CustomStat 中的 name 匹配
输出：不一致项列表，每个附带具体的代码行号和 TOML 行号"
```

三个审计 Agent **并行启动**，等待全部完成后收集结果。

### Step 6: 收集审计结果并修复

1. 汇总三个审计报告，按严重程度排序所有发现的问题
2. 逐个修复，每修复一个在报告中标记 ✓
3. 对于需要用户权衡的问题（如性能 vs 精度），列出选项并询问用户
4. 修复完成后，如果改动较大（≥3 处修改），重新运行审计 Agent 1 做回归检查

审计结果汇总格式：

```markdown
# Audit Summary — <pgen_name>

## Agent 1: 代码正确性
- [ ] 问题 1（严重/警告）: <描述> → 已修复 ✓
- [ ] 问题 2（警告）: <描述> → 需要用户确认...

## Agent 2: 需求满足度
| 需求项 | 状态 | 备注 |
|--------|------|------|
| 初始 B 场 | ✓ | |
| e-/e+ 注入 | ✓ | |
| ... | | |

## Agent 3: 代码-TOML 一致性
- [ ] 不一致 1: <描述> → 已修复 ✓
- [ ] 不一致 2: <描述> → 已修复 ✓
```

### Step 7: 交付

交付前最终检查：
- [ ] pgen.hpp 已通过审计
- [ ] `<name>.toml` 已通过审计
- [ ] 归一化约定已验证（参考 00-normalization.md）
- [ ] 代码注释标注了单位系统

交付内容：
```
pgens/<name>/
├── pgen.hpp          # 最终代码
├── <name>.toml       # 最终 TOML
├── design.md         # 设计文档（供后续参考）
├── user_requirements.md  # 需求文档（供后续参考）
└── audit_summary.md  # 审计报告
```

向用户报告交付物清单，并提示：
- "代码已就绪，下一步：使用 entity-env-build skill 编译和运行"
- "编译命令：`cmake -B build -D pgen=<name>`"

## 引用决策表

部分 reference 之间有互斥或前置依赖：

| 场景 | 决策 |
|------|------|
| ext_current 仅 Minkowski | GR 用户不需要 04。GR + 电流源 → 需要引擎修改 |
| GR init-fields | 需要 dx1/dx2/dx3 + 势方法。参考 02 的 GR 部分 |
| ExternalFields vs ext_force | 选一个即可。ExternalFields 是超集。简单力 → ext_force |
| Replenish 依赖 | 需要 03 (ComputeMomentWithSpecies) + 08 (CustomPostStep) |
| Moving Injector | 需要 03 (注入) + 02 (场重置) + 08 (CustomPostStep) |
| Dynamic BC | PGen 需要 non-const Metadomain。与 MovingWindow 兼容 |
| 无 init_flds 的 PGen | 真空模拟。fields 保持为零 |

## 常用 Agent 操作

### 更新已有 PGen

当用户要求修改已有 PGen 时：
1. 读取现有的 pgen.hpp + TOML + design.md（如有）
2. 修改 user_requirements.md（标记变更项）
3. 进入 Step 2 → 只加载新增功能对应的 references
4. 后续流程同标准工作流

### Debug 已有 PGen

当用户报告 bug/错误时：
1. 加载对应功能的 reference，查 "常见陷阱" section
2. 加载 `00-normalization.md`（最隐蔽的 bug 来源）
3. 如果与 TOML 相关，加载 `09-toml-config.md` 验证参数
4. 启动审计 Agent 1（代码正确性）做针对性审计
5. 输出诊断报告 + 修复建议
