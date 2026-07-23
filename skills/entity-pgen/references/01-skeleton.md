# 01 — PGen 骨架

> 基于 Entity v1.4.4

## 何时使用

**必读内容**。这是所有 PGen 的起点。定义了 PGen 结构体的结构、编译期兼容性检查、构造函数签名以及参数读取模式。

---

## API 签名

### PGen 结构体模板

```cpp
namespace user {
  using namespace ntt;

  template <SimEngine::type S, class M>
  struct PGen {
    // Compatibility declarations (required)
    static constexpr auto engines {
      ::traits::pgen::compatible_with<SimEngine::SRPIC> {}
    };
    static constexpr auto metrics {
      ::traits::pgen::compatible_with<Metric::Minkowski> {}
    };
    static constexpr auto dimensions {
      ::traits::pgen::compatible_with<Dim::_1D, Dim::_2D, Dim::_3D> {}
    };

    // Members
    const SimulationParams& params;
    Metadomain<S, M>&       metadomain;  // or const Metadomain<S, M>&
    const real_t            D = M::Dim;  // Dimension abbreviation

    // TOML parameters (read from [setup])
    real_t param1, param2;

    // Sub-structures (defined by other references)
    InitFields<D> init_flds;  // Optional (field remains zero when absent)

    // Constructor
    PGen(const SimulationParams& p, Metadomain<S, M>& m)
      : params { p }, metadomain { m }, ...
      , init_flds { ... } {}

    // The following methods are optional, define as needed:
    // void InitPrtls(Domain<S, M>&);
    // void CustomPostStep(timestep_t, simtime_t, Domain<S, M>&);
    // auto MatchFields(simtime_t) const -> ...;
    // auto FixFieldsConst(...) const -> ...;
    // ...
  };
}
```

---

## 参数说明

### 模板参数

| 参数 | 含义 | 何时确定 |
|------|------|---------|
| `S` | `SimEngine::type` 枚举：`SRPIC` 或 `GRPIC` | 编译时由 CMake 确定 |
| `M` | 度规类（例如 `Metric<Dim::_2D, Coord::Cartesian>`） | 编译时由 TOML 的 grid.metric 确定 |

### Trait 枚举值

#### 引擎
| 枚举值 | 含义 |
|--------|------|
| `SimEngine::SRPIC` | 狭义相对论 PIC |
| `SimEngine::GRPIC` | 广义相对论 PIC |

#### 度规
| 枚举值 | 含义 | 适用引擎 |
|--------|------|---------|
| `Metric::Minkowski` | 平直时空（笛卡尔/球坐标） | SRPIC、GRPIC |
| `Metric::Spherical` | 球坐标 | SRPIC |
| `Metric::QSpherical` | 修正球坐标（可调网格间距） | SRPIC |
| `Metric::Kerr_Schild` | Kerr-Schild 坐标（旋转黑洞） | GRPIC |
| `Metric::QKerr_Schild` | 修正 Kerr-Schild | GRPIC |
| `Metric::Kerr_Schild_0` | Kerr-Schild 零自旋极限 | GRPIC |

#### 维度
| 枚举值 | 含义 |
|--------|------|
| `Dim::_1D` | 1D |
| `Dim::_2D` | 2D |
| `Dim::_3D` | 3D |

### Trait 声明语法

```cpp
// Declare compatibility with multiple engines:
static constexpr auto engines {
  ::traits::pgen::compatible_with<SimEngine::SRPIC, SimEngine::GRPIC> {}
};

// Compatible with only one:
static constexpr auto metrics {
  ::traits::pgen::compatible_with<Metric::Minkowski> {}
};

// Partial dimensions:
static constexpr auto dimensions {
  ::traits::pgen::compatible_with<Dim::_2D> {}
};
```

### 构造函数签名选择

```cpp
// Use const Metadomain — no need to dynamically modify BCs
PGen(const SimulationParams& p, const Metadomain<S, M>& m);

// Use non-const Metadomain — needed when CustomPostStep
// calls metadomain.setFldsBC() or metadomain.setPrtlBC()
PGen(const SimulationParams& p, Metadomain<S, M>& m);
```

### 参数读取

`SimulationParams` 提供模板方法 `get<T>(key, default)`：

```cpp
// Read from TOML
real_t temperature = params.template get<real_t>("setup.temperature");
int    n_species   = params.template get<int>("particles.nspec");

// With default value
real_t Bmag = params.template get<real_t>("setup.Bmag", 1.0);
int    freq = params.template get<int>("setup.injection_frequency", 100);

// Read arrays
auto xi_min = params.template get<std::vector<real_t>>("setup.xi_min");
```

**重要**：`params.template get<>()` 中的键直接对应 TOML 路径，层级之间用 `.` 分隔。

---

## 必需的 include

```cpp
#pragma once

#include "global.h"
#include "enums.h"

#include "traits/pgen.h"           // compatible_with mechanism
#include "utils/error.h"           // raise::Error, raise::KernelError
#include "utils/numeric.h"         // SQR, ZERO, ONE, math namespace

// Field initialization
#include "archetypes/field_setter.h"

// Particle injection
#include "archetypes/energy_dist.h"
#include "archetypes/spatial_dist.h"
#include "archetypes/particle_injector.h"

// Utilities
#include "archetypes/utils.h"

// Framework
#include "framework/domain/metadomain.h"
#include "framework/domain/domain.h"
```

---

## 最小可运行 PGen

Entity 的特性检测通过 `if constexpr` 实现——不存在的方法/成员会被静默跳过。因此，最小 PGen 骨架只需要 trait 声明加一个空构造函数。

### 可选成员/方法概览

以下成员/方法**全部是可选的**（引擎通过 traits 检测其存在性，若不存在则跳过）：

| 成员/方法 | 缺失时的行为 |
|-----------|--------------|
| `init_flds` | 场保持为零（真空） |
| `InitPrtls()` | 不注入粒子（纯场模拟） |
| `CustomPostStep()` | 无时间步钩子 |
| `MatchFields()` | MATCH 边界不可用 |
| `FixFieldsConst()` | FIXED 边界不可用 |
| `AtmFields()` | ATMOSPHERE 边界不可用 |
| `ext_current` | 无外部电流源 |
| `ext_force` | 无外力 |
| `ExternalFields()` | 无外部 E/B/力 |
| `CustomFieldOutput()` | 无自定义场输出 |
| `CustomStat()` | 无自定义统计 |
| `CustomParticleUpdate()` | 无自定义粒子更新 |

编译只要求 `pgens/<name>/pgen.hpp` 存在（CMake 的 `set_problem_generator()` 只检查此文件）。

### 代码示例：最简骨架（仅 traits + 空构造函数）

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

### 代码示例：带 InitFields 的最小 PGen

```cpp
#pragma once

#include "global.h"
#include "enums.h"
#include "traits/pgen.h"

#include "archetypes/field_setter.h"
#include "archetypes/utils.h"
#include "framework/domain/metadomain.h"

namespace user {
  using namespace ntt;

  template <Dimension D>
  struct InitFields {
    Inline auto bx1(const coord_t<D>&) const -> real_t { return 1.0; }
    Inline auto ex1(const coord_t<D>&) const -> real_t { return ZERO; }
  };

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
      ::traits::pgen::compatible_with<Dim::_2D> {}
    };

    const SimulationParams& params;
    Metadomain<S, M>&       metadomain;
    InitFields<D>           init_flds;

    PGen(const SimulationParams& p, Metadomain<S, M>& m)
      : params { p }, metadomain { m } {}
  };
} // namespace user
```

这个最小 PGen 只在 2D SRPIC Minkowski 中设置 Bx1=1.0 的均匀 B 场，不含粒子。所有其他 PGen 都从此骨架扩展而来。

---

## 约束与不兼容项

- **init_flds 实例名是强制的**——代码通过 C++20 concepts 检测名为 `init_flds` 的成员
- **Trait 声明必须与 TOML 匹配**——如果 TOML 中是 `engine = "GRPIC"` 但 traits 只声明了 SRPIC 兼容性，编译会失败
- **D = M::Dim**——标准缩写约定；后续的 InitFields 和所有方法都使用 D 而不是显式维度

---

## 常见陷阱

1. **忘记 `using namespace ntt`**——ZERO、ONE、SQR、math::cos 等都在 ntt 命名空间中
2. **为未使用的维度声明 traits**——会导致未测试维度的编译失败；只声明实际支持的维度
3. **const 与非 const Metadomain 选择错误**——使用了 const 但之后需要 setFldsBC() 会导致编译失败。在 const 就足够时使用非 const 则没有问题（只是约束稍微宽松）
4. **`get<type>()` 前缺少 `template` 关键字**——因为 PGen 本身是模板类，调用模板方法需要写成 `params.template get<>()`
5. **`Dim::_2D` 与 `Dim::_3D`**——`_2D` 不是 `2D`（前导下划线是枚举命名约定）；写错会导致编译错误
6. **球坐标的维度**——2D 球坐标实际上是 (r, theta)，但 Entity 内部仍将其视为维度 2。边界会自动处理 phi 方向的周期性
