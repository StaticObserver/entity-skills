# 01 — PGen 骨架

## 何时使用

**必读**。这是所有 PGen 的起点。定义 PGen struct 的结构、编译期兼容性检查、构造函数签名、参数读取模式。

---

## API 签名

### PGen Struct 模板

```cpp
namespace user {
  using namespace ntt;

  template <SimEngine::type S, class M>
  struct PGen {
    // 兼容性声明（必选）
    static constexpr auto engines {
      ::traits::pgen::compatible_with<SimEngine::SRPIC> {}
    };
    static constexpr auto metrics {
      ::traits::pgen::compatible_with<Metric::Minkowski> {}
    };
    static constexpr auto dimensions {
      ::traits::pgen::compatible_with<Dim::_1D, Dim::_2D, Dim::_3D> {}
    };

    // 成员
    const SimulationParams& params;
    Metadomain<S, M>&       metadomain;  // 或 const Metadomain<S, M>&
    const real_t            D = M::Dim;  // 维度缩写

    // TOML 参数（从 [setup] 读取）
    real_t param1, param2;

    // 子结构体（由其他 references 定义）
    InitFields<D> init_flds;  // 必选

    // 构造函数
    PGen(const SimulationParams& p, Metadomain<S, M>& m)
      : params { p }, metadomain { m }, ...
      , init_flds { ... } {}

    // 以下方法可选，按需定义：
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

| 参数 | 含义 | 传入时机 |
|------|------|---------|
| `S` | `SimEngine::type` 枚举：`SRPIC` 或 `GRPIC` | 编译期由 CMake 确定 |
| `M` | Metric 类（如 `Metric<Dim::_2D, Coord::Cartesian>`） | 编译期根据 TOML 的 grid.metric 确定 |

### Traits 枚举值

#### Engines
| 枚举值 | 含义 |
|--------|------|
| `SimEngine::SRPIC` | 狭义相对论 PIC |
| `SimEngine::GRPIC` | 广义相对论 PIC |

#### Metrics
| 枚举值 | 含义 | 适用引擎 |
|--------|------|---------|
| `Metric::Minkowski` | 平坦时空（笛卡尔/球坐标） | SRPIC, GRPIC |
| `Metric::Spherical` | 球坐标 | SRPIC |
| `Metric::QSpherical` | 修正球坐标（可调节网格疏密） | SRPIC |
| `Metric::Kerr_Schild` | Kerr-Schild 坐标（旋转黑洞） | GRPIC |
| `Metric::QKerr_Schild` | 修正 Kerr-Schild | GRPIC |
| `Metric::Kerr_Schild_0` | Kerr-Schild 零自旋极限 | GRPIC |

#### Dimensions
| 枚举值 | 含义 |
|--------|------|
| `Dim::_1D` | 一维 |
| `Dim::_2D` | 二维 |
| `Dim::_3D` | 三维 |

### Trait 声明语法

```cpp
// 声明兼容多个引擎：
static constexpr auto engines {
  ::traits::pgen::compatible_with<SimEngine::SRPIC, SimEngine::GRPIC> {}
};

// 只兼容一个：
static constexpr auto metrics {
  ::traits::pgen::compatible_with<Metric::Minkowski> {}
};

// 部分维度：
static constexpr auto dimensions {
  ::traits::pgen::compatible_with<Dim::_2D> {}
};
```

### Constructor 签名选择

```cpp
// 使用 const Metadomain — 不需要动态修改 BC
PGen(const SimulationParams& p, const Metadomain<S, M>& m);

// 使用 non-const Metadomain — 需要在 CustomPostStep 中
// 调用 metadomain.setFldsBC() 或 metadomain.setPrtlBC()
PGen(const SimulationParams& p, Metadomain<S, M>& m);
```

### 参数读取

`SimulationParams` 提供模板方法 `get<T>(key, default)`：

```cpp
// 从 TOML 读取
real_t temperature = params.template get<real_t>("setup.temperature");
int    n_species   = params.template get<int>("particles.nspec");

// 带默认值
real_t Bmag = params.template get<real_t>("setup.Bmag", 1.0);
int    freq = params.template get<int>("setup.injection_frequency", 100);

// 读取数组
auto xi_min = params.template get<std::vector<real_t>>("setup.xi_min");
```

**重要**：`params.template get<>()` 中的 key 直接对应 TOML 路径，用 `.` 分隔层次。

---

## 所需 Includes

```cpp
#pragma once

#include "global.h"
#include "enums.h"

#include "traits/pgen.h"           // compatible_with 机制
#include "utils/error.h"           // raise::Error, raise::KernelError
#include "utils/numeric.h"         // SQR, ZERO, ONE, math namespace

// 场初始化
#include "archetypes/field_setter.h"

// 粒子注入
#include "archetypes/energy_dist.h"
#include "archetypes/spatial_dist.h"
#include "archetypes/particle_injector.h"

// 工具
#include "archetypes/utils.h"

// Framework
#include "framework/domain/metadomain.h"
#include "framework/domain/domain.h"
```

---

## 代码示例：最小 PGen

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

这个最小 PGen 只设了 Bx1=1.0 的均匀磁场，没有粒子，2D SRPIC Minkowski。所有其他 PGen 从比这个骨架扩展而来。

---

## 约束与不兼容

- **init_flds 实例名强制** — 代码通过 C++20 concept 检测名为 `init_flds` 的成员
- **traits 声明必须匹配 TOML** — 如果 TOML 中是 `engine = "GRPIC"`，但 traits 只声明 SRPIC 兼容，编译报错
- **D = M::Dim** — 标准缩略约定，后续 InitFields 和所有方法用 D 而不是显式维度

---

## 常见陷阱

1. **忘记 `using namespace ntt`** — ZERO, ONE, SQR, math::cos 等都在 ntt namespace
2. **traits 声明了不需要的维度** — 会导致代码在未测试的维度下编译失败，建议只声明实际支持的维度
3. **const vs non-const Metadomain 选错** — 如果用了 const 但后面需要 setFldsBC()，编译失败。反过来用 non-const 不会有问题（只是稍微不严格）
4. **`template get<type>()` 前没加 `template` 关键字** — 因为 PGen 本身是模板类，调用模板方法需要 `params.template get<>()`
5. **`Dim::_2D` vs `Dim::_3D`** — `_2D` 不是 `2D`（前导下划线是枚举命名约定），编译错误
6. **Spherical 坐标的维度** — 2D 球坐标实际上是 (r, theta)，但 Entity 内部仍然按维度 2 处理。边界自动处理 phi 维度的周期性
