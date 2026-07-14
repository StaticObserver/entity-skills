# Entity Case Skill 规范

## 使命

维护一个 Entity simulation case 的一致性。

一个 case 不是单独的 TOML，也不是单独的 `pgen.hpp`，而是：

```text
TOML + pgen.hpp + setup 参数 + species + boundaries + output requests
```

本 skill 的第一职责是让 agent 理解 PGen 的结构和 API，然后检查 TOML 与 PGen 是否一致。

## 不适用场景

本 skill 不负责：

- 构建 Kokkos/ADIOS2/MPI/HDF5 环境；
- 选择 CMake backend；
- 修改 Entity `src/` 核心代码；
- 分析输出数据的物理结论；
- 写长期交接文档。

这些分别交给 env-build、core-dev、analysis 和 docs。

## PGen Source of Truth

PGen API 高度版本敏感。使用前必须从目标 Entity checkout 核对：

- `src/global/traits/pgen.h`；
- `pgens/*/pgen.hpp`；
- `examples/*/pgen.hpp`；
- `src/engines/reporter.*` 中报告的 PGen hooks；
- `src/engines/*/fields_bcs.*`；
- `src/engines/*/fieldsolvers.*`；
- `src/engines/engine.hpp` 中调用 PGen hooks 的位置。

Skill 中的 API 总结只能作为导航，不能替代当前 checkout。

## PGen 文件结构

典型 case 目录：

```text
pgens/<name>/
├── pgen.hpp       # 必需，编译期选择
├── <name>.toml    # 推荐，参考输入
└── <name>.py      # 可选，可视化或分析脚本
```

Entity 通过 CMake 选项选择 PGen：

```bash
cmake -B build/<name> -D pgen=<name>
```

如果 `pgen.hpp` 修改了，通常需要重新编译 Entity。

## PGen 顶层结构

PGen 必须位于 `namespace user` 中，典型结构如下：

```cpp
namespace user {
  using namespace ntt;

  template <SimEngine::type S, class M>
  struct PGen {
    static constexpr auto D { M::Dim };

    static constexpr auto engines {
      ::traits::pgen::compatible_with<SimEngine::SRPIC> {}
    };
    static constexpr auto metrics {
      ::traits::pgen::compatible_with<Metric::Minkowski> {}
    };
    static constexpr auto dimensions {
      ::traits::pgen::compatible_with<Dim::_2D, Dim::_3D> {}
    };

    const SimulationParams& params;
    Metadomain<S, M>& metadomain;

    PGen(const SimulationParams& p, Metadomain<S, M>& m)
      : params { p }
      , metadomain { m } {}
  };
}
```

注意：旧资料中可能出现 `static constexpr auto engines = { SimEngine::SRPIC }` 这类写法。当前 checkout 是否支持，必须以 `src/global/traits/pgen.h` 和现有 pgen 为准。1.4.x 常见写法是 `traits::pgen::compatible_with<...>{}`。

## Compatibility Traits

PGen 应声明支持的：

- engines；
- metrics；
- dimensions。

常见 engine：

- `SimEngine::SRPIC`；
- `SimEngine::GRPIC`。

常见 metric：

- `Metric::Minkowski`；
- `Metric::Spherical`；
- `Metric::QSpherical`；
- `Metric::Kerr_Schild`；
- `Metric::QKerr_Schild`；
- `Metric::Kerr_Schild_0`。

常见 dimension：

- `Dim::_1D`；
- `Dim::_2D`；
- `Dim::_3D`。

TOML 中的 `simulation.engine`、`grid.metric.metric` 和 `grid.resolution` 维度必须与 PGen traits 一致。

## 参数读取

PGen 通常从 `SimulationParams` 读取 TOML 参数：

```cpp
const auto value = params.template get<real_t>("setup.value", 1.0);
const auto required = params.template get<real_t>("setup.required");
```

约定：

- PGen 自定义参数优先放在 `[setup]` 下；
- 有默认值的参数应记录默认值；
- 必需参数应在参考 TOML 或 case note 中明确；
- 参数路径必须和 TOML 层级一致。

## Field Initialization：`init_flds`

如果 PGen 提供初始场，通常定义一个 field initializer，并在 PGen 中放置名为 `init_flds` 的成员。

```cpp
template <Dimension D>
struct InitFields {
  Inline auto ex1(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
  Inline auto ex2(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
  Inline auto ex3(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }

  Inline auto bx1(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
  Inline auto bx2(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
  Inline auto bx3(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
};

InitFields<D> init_flds;
```

规则：

- 成员名通常必须是 `init_flds`；
- 方法名按 `ex1/ex2/ex3`、`bx1/bx2/bx3`；
- 参数通常是 physical coordinates；
- SRPIC 通常按 local tetrad/orthonormal basis 给场；
- GRPIC 场 basis 和坐标约定必须按当前 checkout/wiki 核对；
- 代码会处理 staggering 和内部转换，但不能把 code units 与 physical units 混用。

## Particle Initialization：`InitPrtls`

`InitPrtls` 在 simulation start 时对每个 local domain 初始化粒子：

```cpp
void InitPrtls(Domain<S, M>& local_domain) {
  // inject particles
}
```

常见职责：

- 根据 TOML species 初始化电子、离子、正电子、光子等；
- 使用 built-in energy/spatial distribution；
- 使用 `arch::InjectUniform...` 或 `arch::InjectNonUniform...`；
- 从 `[setup]` 读取密度、温度、漂移速度、层宽等参数；
- 注意 species index 与 TOML `[[particles.species]]` 的一致性。

注意：

- Entity 代码中 species index 经常是 1-indexed；
- C++ 容器访问经常是 0-indexed；
- agent 必须根据当前 API 和调用点确认这一点，不能凭直觉混用。

## Spatial 和 Energy Distribution

PGen 可以定义自定义空间分布和能量/速度分布。

典型用途：

- current sheet；
- shock；
- turbulence；
- localized injection；
- atmosphere；
- beam / streaming setup。

设计要求：

- 分布函数应明确输入坐标是 physical coordinates 还是 code coordinates；
- 速度/动量 basis 必须明确；
- 随机数 pool 的使用必须符合 Kokkos/device 约束；
- 分布参数应来自 `[setup]` 或 PGen constructor。

## Boundary Hooks

PGen 可以提供 field boundary behavior。

常见 hooks：

```cpp
auto MatchFields(simtime_t time) const -> FieldProvider;
auto MatchFieldsInX1(simtime_t time) const -> FieldProvider;
auto MatchFieldsInX2(simtime_t time) const -> FieldProvider;
auto MatchFieldsInX3(simtime_t time) const -> FieldProvider;
```

以及 fixed-field behavior：

```cpp
auto FixFieldsConst(simtime_t time, const bc_in& bc, em comp) const
  -> std::pair<real_t, bool>;
```

注意：

- 具体签名随版本变化，必须以 `fields_bcs` 和 `traits/pgen.h` 为准；
- TOML boundary 如果使用 `MATCH`、`FIXED` 或 `CUSTOM`，PGen 必须提供对应逻辑；
- spherical/GR 边界可能由框架自动设置一部分，不能照搬 cartesian 逻辑。

## Runtime Hook：`CustomPostStep`

`CustomPostStep` 在 timestep 末尾调用：

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
  // custom injection, boundary changes, diagnostics support, etc.
}
```

常见用途：

- runtime particle injection；
- 改变 boundary condition；
- 维护自定义 buffer；
- 执行 case-specific physics。

风险：

- `Domain` 内部 raw quantities 往往是 code units；
- 删除 charged particles 可能破坏 charge conservation；
- 在这里实现外部源可能绕过正确的 field solver/source path；
- 如果功能属于核心算法，应该路由到 core-dev，而不是塞进 PGen。

## External Force：`ext_force`

PGen 可定义名为 `ext_force` 的成员，为指定 species 提供外力。

典型形式：

```cpp
struct ExtForce {
  std::vector<int> species;

  Inline auto fx1(spidx_t sp, simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
  Inline auto fx2(spidx_t sp, simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
  Inline auto fx3(spidx_t sp, simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
};

ExtForce ext_force;
```

注意：

- 签名必须按当前 checkout 核对；
- species 列表与 TOML species 必须一致；
- force basis 和单位必须明确；
- 部分 methods 可能是 optional，由 traits 检测。

## External Current：`ext_current`

PGen 可定义名为 `ext_current` 的成员，为 Ampere law 提供外部电流源。

典型形式：

```cpp
struct ExtCurrent {
  Inline auto jx1(simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
  Inline auto jx2(simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
  Inline auto jx3(simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
};

ExtCurrent ext_current;
```

注意：

- 官方上游可能限制 `ext_current` 只用于 Minkowski/SRPIC 路径；
- 本地 fork 可能扩展过它，但必须标为 local overlay；
- 时间 staggering、source time 和 field solver 调用点是高风险点；
- 任何涉及 `src/kernels/ampere*` 或 engine time ownership 的改动都应路由到 core-dev。

## Custom Field Output

TOML 中可以请求 custom field output：

```toml
[output.fields]
custom = ["my_field"]
```

PGen 需要提供对应 hook，例如：

```cpp
void CustomFieldOutput(
    const std::string& name,
    array_t<real_t*>& buffer,
    std::size_t index,
    timestep_t step,
    simtime_t time,
    Domain<S, M>& domain) {
  if (name == "my_field") {
    // fill buffer
  }
}
```

注意：

- 具体 buffer 类型和签名必须以当前 checkout 为准；
- custom field 名称必须与 TOML `custom` 列表一致；
- 输出 quantity 应尽量 resolution-independent；
- 如果 quantity 需要从粒子重新 deposit，必须说明 oracle 和数值误差。

## Custom Stats

TOML 中可以请求 custom scalar stats：

```toml
[output.stats]
custom = ["my_stat"]
```

PGen 需要提供对应 hook。1.4.x 中常见签名包含 `name`、`step`、`time`、`domain`，但必须以 checkout 为准：

```cpp
real_t CustomStat(
    const std::string& name,
    timestep_t step,
    simtime_t time,
    const Domain<S, M>& domain) const;
```

注意：

- stats 通常会跨 local domains 做 reduction；
- 返回值应明确是否是 sum、average 或局部量；
- 名称必须与 TOML `custom` 一致。

## Custom Particle Update

Entity 支持 case-specific particle update hook，用于定制粒子 push 或边界响应。

典型模式是 PGen 返回一个 functor：

```cpp
template <class D>
auto CustomParticleUpdate(simtime_t time, spidx_t sp, D& domain) const
  -> CustomPrtlUpdate;
```

functor 在 device/kernel context 中运行，必须满足 Kokkos 约束。

用途：

- 特殊反射边界；
- 速度重采样；
- case-specific particle update；
- payload 更新。

风险：

- host/device 捕获错误；
- species index 混用；
- 位置坐标和 metric transform 使用错误；
- 与标准 pusher、boundary condition 或 charge conservation 交互复杂。

## PGen API 检查表

Agent 在读写 PGen 时至少检查：

- `namespace user` 是否正确；
- `PGen` template 参数是否符合当前版本；
- compatibility traits 是否与 TOML 匹配；
- constructor 是否保存 `params` 和必要的 `metadomain`；
- `init_flds` 是否存在且名称正确；
- `InitPrtls` 是否使用正确 species；
- `[setup]` 参数是否全部在 TOML 中有说明；
- boundaries 是否需要对应 hooks；
- custom output/stat 名称是否与 TOML 一致；
- `CustomPostStep` 是否误用 code units/physical units；
- ext_force/ext_current 是否受 engine/metric 限制；
- 修改 PGen 后是否提醒重新编译。

## TOML-PGen 契约

TOML 和 PGen 是同一个 case 的两半。Agent 不能只检查其中一个。

TOML 提供：

- engine、metric、dimension；
- grid、boundaries、scales；
- species 定义；
- output requests；
- PGen 自定义 `[setup]` 参数。

PGen 提供：

- 对 engine/metric/dimension 的 compile-time compatibility；
- 初始场；
- 初始粒子；
- 自定义边界、外力、电流、输出和 runtime hooks；
- 对 `[setup]` 参数的解释。

## 契约 1：Engine / Metric / Dimension

TOML 中这些字段必须与 PGen traits 一致：

```toml
[simulation]
engine = "SRPIC"  # or "GRPIC"

[grid]
resolution = [nx, ny, nz]  # 长度决定维度

[grid.metric]
metric = "Minkowski"
```

检查规则：

- `simulation.engine` 必须在 PGen `engines` traits 中；
- `grid.metric.metric` 必须在 PGen `metrics` traits 中；
- `grid.resolution` 推出的维度必须在 PGen `dimensions` traits 中；
- GRPIC case 不应误用只支持 SRPIC 的 PGen；
- spherical/GR metric 的 boundary 和 coordinate 规则不能照搬 Minkowski/cartesian case。

如果这三者不一致，case 不成立，应先修 TOML 或 PGen traits。

## 契约 2：Species

TOML 中 `[[particles.species]]` 定义了 species 的顺序、label、mass、charge、pusher 和容量：

```toml
[particles]
ppc0 = 16

[[particles.species]]
label = "electrons"
mass = 1.0
charge = -1.0
maxnpart = 1000000

[[particles.species]]
label = "positrons"
mass = 1.0
charge = 1.0
maxnpart = 1000000
```

PGen 中常见使用方式：

- `InitPrtls` 按 species index 注入粒子；
- `ext_force.species` 指定受力 species；
- custom output/stats 可能按 species 累积 moments；
- `CustomParticleUpdate` 通常按 `spidx_t sp` 分支。

检查规则：

- PGen 使用的 species index 是否存在；
- PGen 使用的 species label 是否与 TOML 一致；
- 1-indexed API 与 0-indexed container access 是否被正确区分；
- massless species 是否使用合适 pusher；
- photon/emission species 是否在 TOML 中定义；
- `maxnpart` 是否覆盖初始注入和 runtime injection；
- `tracking`、payload 数量是否满足 PGen 使用。

## 契约 3：`[setup]` 参数

`[setup]` 是 PGen 自定义参数空间。

TOML：

```toml
[setup]
bg_B = 1.0
temperature = 1e-3
cs_width = 0.1
```

PGen：

```cpp
bg_B { params.template get<real_t>("setup.bg_B", 1.0) }
cs_width { params.template get<real_t>("setup.cs_width") }
```

检查规则：

- PGen 所有 `params.get("setup.*")` 都应在 case note 中列出；
- 没有默认值的 `setup.*` 参数必须在 TOML 中出现；
- 有默认值的参数也应在文档中说明默认值；
- 参数单位必须明确：code units、physical units、`m0 c^2`、`n0`、`B0` 等；
- 参数名不能和旧 pgen 或旧分支残留混淆；
- 如果 PGen 改了 `[setup]` 参数名，对应 TOML 必须同步修改。

## 契约 4：Scales 与 PGen 物理量

TOML 中 `[scales]` 给出归一化尺度，PGen 读取或隐含使用这些尺度。

常见字段包括：

- `larmor0`；
- `skindepth0`；
- 推导出的 `B0`、`n0`、`q0`、`sigma0`、`omegaB0`。

检查规则：

- PGen 中读取 `scales.*` 的位置必须与 TOML 一致；
- 初始场强、温度、密度、漂移速度等是否使用同一套归一化；
- `InitPrtls` 中 physical coordinates 与 `Domain` 内 code units 不要混用；
- `CustomPostStep` 中 raw `domain` quantities 通常是 code units，应谨慎比较。

## 契约 5：Boundaries 与 PGen Hooks

TOML boundary 决定框架如何处理边界：

```toml
[grid.boundaries]
fields = [["MATCH"], ["PERIODIC"]]
particles = [["ABSORB"], ["PERIODIC"]]
```

如果 TOML 使用：

- `MATCH`：PGen 可能需要 `MatchFields` 或 `MatchFieldsInX*`；
- `FIXED`：PGen 可能需要 `FixFieldsConst`；
- `CUSTOM`：PGen 必须提供对应 custom behavior；
- `ATMOSPHERE`：TOML 需要 atmosphere 参数，PGen 也可能假设特定 species；
- runtime boundary change：PGen 可能在 `CustomPostStep` 中调用 `metadomain.setFldsBC` 或 `setPrtlBC`。

检查规则：

- TOML boundary type 是否被当前 engine/metric 支持；
- PGen 是否提供所需 hook；
- hook 是否覆盖对应方向；
- spherical/GR 自动边界是否被误手动指定；
- particle boundary 与 field boundary 是否物理一致；
- runtime 改 boundary 是否有明确触发时间和风险说明。

## 契约 6：Output Requests 与 PGen Custom Hooks

TOML 中标准输出不一定需要 PGen hook：

```toml
[output.fields]
quantities = ["E", "B", "Rho", "N"]
```

但 custom output 必须和 PGen 对齐：

```toml
[output.fields]
custom = ["my_field"]

[output.stats]
custom = ["my_stat"]
```

检查规则：

- `output.fields.custom` 中每个名称是否由 `CustomFieldOutput` 处理；
- `output.stats.custom` 中每个名称是否由 `CustomStat` 处理；
- custom 名称大小写是否完全一致；
- custom quantity 的单位、basis、staggering 是否明确；
- 如果 PGen 在 `CustomPostStep` 预计算 output buffer，要检查更新时机；
- 如果 output 依赖粒子 moments，要说明 smoothing 和 species selection。

## 契约 7：Radiation / Emission / Payloads

如果 TOML species 使用：

- `radiative_drag`；
- `emission`；
- `n_payloads_real`；
- `n_payloads_int`；
- `tracking`。

PGen 必须配合：

- 定义 photon species；
- 正确引用 emission species index；
- 不覆盖 reserved payload；
- 在 custom particle update 中正确维护 payload；
- 在 output/analysis 中记录 payload 语义。

## 契约 8：Checkpoint 与 Restart

Checkpoint 主要是运行可靠性问题，不属于 PGen API 核心。但 case 设计仍要注意：

- `CustomPostStep` 中的 runtime state 是否能从 checkpoint 恢复；
- PGen constructor 中的随机初始化是否在 restart 后稳定；
- custom buffers 或 local flags 是否需要 checkpoint 支持；
- runtime boundary changes 是否依赖 `time`/`step`，restart 后是否重复触发。

如果 case 有不可 checkpoint 的 runtime state，必须在 run manifest 中记录。

## 契约 9：修改边界与重新编译

只修改 TOML 通常不需要重新编译。

需要重新编译的情况：

- 修改 `pgen.hpp`；
- 新增或删除 PGen hook；
- 修改 compatibility traits；
- 修改 compile-time CMake options；
- 更换 CMake `pgen`；
- 修改 Entity `src/`。

只需要重新运行的情况：

- 修改 `[setup]` 数值但 PGen 参数名不变；
- 修改 runtime、resolution、extent、output interval；
- 修改 standard output quantities；
- 修改 checkpoint policy。

灰区：

- 修改 custom output name，需要确认 PGen 是否已支持；
- 修改 species 数量或顺序，需要确认 PGen index 是否仍正确；
- 修改 metric/dimension，即使不改 PGen，也可能因 traits 不支持而需要改 PGen 并重编。

## Case 一致性检查顺序

Agent 应按这个顺序检查 case：

1. 确认 Entity checkout 和版本桶。
2. 读取当前 `input.example.toml`，确认 TOML 层级。
3. 读取目标 TOML。
4. 读取目标 `pgen.hpp`。
5. 从 PGen 提取 traits。
6. 对齐 engine/metric/dimension。
7. 对齐 species index、label、mass、charge、pusher、payload。
8. 列出 PGen 读取的 `[setup]` 参数，并和 TOML 对齐。
9. 对齐 boundaries 与 PGen boundary hooks。
10. 对齐 custom fields/stats 与 PGen output hooks。
11. 检查 units、basis、coordinate convention。
12. 判断是否需要重新编译。
13. 输出 case consistency report。

## 输出契约

本 skill 输出 PGen 相关结论时，应包含：

```yaml
pgen:
  path:
  entity_version_bucket:
  supported_engines:
  supported_metrics:
  supported_dimensions:
  hooks_detected:
    init_flds:
    InitPrtls:
    MatchFields:
    FixFieldsConst:
    CustomPostStep:
    ext_force:
    ext_current:
    CustomFieldOutput:
    CustomStat:
    CustomParticleUpdate:
  setup_parameters:
    required:
    optional:
  toml_contract:
    toml_path:
    engine:
    metric:
    dimension:
    species:
    setup_parameters:
    scales:
    boundaries:
    output_custom_fields:
    output_custom_stats:
    checkpoint_restart_risks:
    needs_rebuild:
  risks:
    -
```
