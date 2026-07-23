# 06 — 边界条件（MatchFields / FixFieldsConst / AtmFields）

> 基于 Entity v1.4.4

## 何时使用

当需要非 PERIODIC 边界条件时使用。触发关键词：开放边界、匹配边界、固定边界、大气边界、吸收边界、视界边界、导体边界、MatchFields、FixFields、AtmFields。

**如果所有方向都是 PERIODIC，请跳过本参考。**

---

## 边界条件类型概览

### 场边界条件

| TOML 值 | 含义 | PGen 中对应的方法 |
|------------|---------|------------------------------|
| `"PERIODIC"` | 周期边界 | 不需要 |
| `"MATCH"` | 匹配边界 | `MatchFields(time)` 或 `MatchFieldsInX1/X2/X3(time)` |
| `"FIXED"` | 固定值边界 | `FixFieldsConst(time, bc_in, em)` |
| `"ATMOSPHERE"` | 大气边界 | `AtmFields(time)` |
| `"CUSTOM"` | 自定义 | 引擎扩展 |
| `"HORIZON"` | 视界边界（仅 GR） | 不需要（自动处理） |
| `"CONDUCTOR"` | 导体边界 | `FixFieldsConst` |

### 粒子边界条件

| TOML 值 | 含义 | 配对要求 |
|------------|---------|---------------------|
| `"PERIODIC"` | 周期边界 | — |
| `"ABSORB"` | 吸收边界 | — |
| `"ATMOSPHERE"` | 大气边界 | 与场 ATMOSPHERE 配对 |
| `"CUSTOM"` | 自定义 | — |
| `"REFLECT"` | 反射边界 | 与场 CONDUCTOR 配对 |
| `"HORIZON"` | 视界边界 | — |

---

## MatchFields（MATCH 边界）

### 函数签名

```cpp
// Generic MATCH (same for all directions)
auto MatchFields(simtime_t time) const -> FieldSetterType;

// Direction-specific MATCH
auto MatchFieldsInX1(simtime_t time) const -> FieldSetterType;
auto MatchFieldsInX2(simtime_t time) const -> FieldSetterType;
auto MatchFieldsInX3(simtime_t time) const -> FieldSetterType;
```

### 参数说明

| 参数 | 含义 |
|-----------|---------|
| `time` | 当前模拟时间（用于随时间变化的边界场） |
| 返回值 | 一个场设置器结构体（接口与 InitFields 相同） |

### 代码示例

```cpp
// Simple constant matching field
template <Dimension D>
struct MatchData {
    Inline auto bx1(const coord_t<D>&) const -> real_t { return 1.0; }
    Inline auto ex2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex3(const coord_t<D>&) const -> real_t { return ZERO; }
};

auto MatchFields(simtime_t time) const {
    return MatchData<D>{};
}
```

**MatchFields 与 MatchFieldsInX1/X2/X3 的区别**：
- `MatchFields` 对所有 MATCH 方向通用
- `MatchFieldsInX1` 仅用于 X1 方向的 MATCH 边界；X2/X3 可以使用不同的实现

### TOML 配置

```toml
[boundaries]
  fields    = [["MATCH"], ["PERIODIC"]]     # X1=MATCH, X2=PERIODIC
  particles = [["ABSORB"], ["PERIODIC"]]
  match_ds  = 0.5                           # Matching layer width
```

---

## FixFieldsConst（FIXED 边界）

### 函数签名

```cpp
auto FixFieldsConst(simtime_t time, const bc_in& bc, const em& comp) const
    -> std::pair<real_t, bool>;
```

### 参数说明

| 参数 | 含义 |
|-----------|---------|
| `time` | 当前时间 |
| `bc` | 哪个边界：`bc_in::Mx1`（左）、`bc_in::Px1`（右）、`bc_in::Mx2`、`bc_in::Px2`、…… |
| `comp` | 哪个分量：`em::ex1`、`em::bx2`、`em::dx3`、…… |
| 返回值 `pair<real_t, bool>` | 数值 + 是否应用 |

### 代码示例

```cpp
auto FixFieldsConst(simtime_t time, const bc_in& bc, const em& comp) const
    -> std::pair<real_t, bool> {

    // X1 left boundary → time-dependent drive
    if (bc == bc_in::Mx1) {
        real_t ramp = time < t_transition
            ? time / t_transition
            : (time > t_transition + t_duration
                ? (t_transition + t_duration - time) / t_duration + 1.0
                : 1.0);

        if (comp == em::ex3) {
            return { amplitude * ramp * math::cos(omega * time), true };
        }
    }

    // Unhandled components → not applied
    return { ZERO, false };
}
```

### TOML 配置

```toml
[boundaries]
  fields    = [["FIXED"], ["PERIODIC"]]
  particles = [["REFLECT"], ["PERIODIC"]]   # FIXED field + REFLECT particles = CONDUCTOR
```

---

## AtmFields（ATMOSPHERE 边界）

### 函数签名

```cpp
auto AtmFields(simtime_t time) const -> FieldSetterType;
```

返回值是一个场设置器（接口与 InitFields 相同），用于设置大气层中的场值。

### 代码示例

```cpp
template <Dimension D>
struct AtmData {
    real_t Bsurf, Rstar, omega, time;

    Inline auto bx1(const coord_t<D>& x) const -> real_t {
        return Bsurf * SQR(Rstar) / SQR(x[0]);
    }
    Inline auto ex2(const coord_t<D>& x) const -> real_t {
        return -omega * x[0] * this->bx1(x) * math::sin(x[1]);
    }
};

auto AtmFields(simtime_t time) const {
    return AtmData<D>{ Bsurf, Rstar, omega, time };
}
```

### TOML 配置

```toml
[boundaries]
  fields    = [["ATMOSPHERE"]]
  particles = [["ATMOSPHERE"]]

  [boundaries.atmosphere]
    temperature = 0.01
    density     = 1.0
    height      = 1.0
    species     = [1, 2]    # Which species participate in the atmosphere
    ds          = 0.5
    g           = 1.0       # Gravitational acceleration
```

---

## 动态切换边界条件（在 CustomPostStep 中）

在运行时动态切换边界类型：

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    if (time >= t_open) {
        metadomain.setFldsBC(bc_in::Mx1, FldsBC::MATCH);
        metadomain.setFldsBC(bc_in::Px1, FldsBC::MATCH);
        metadomain.setPrtlBC(bc_in::Mx1, PrtlBC::ABSORB);
        metadomain.setPrtlBC(bc_in::Px1, PrtlBC::ABSORB);
    }
}
```

**注意**：使用 `setFldsBC`/`setPrtlBC` 的 PGen 必须使用非 const 的 `Metadomain<S, M>&`（参见 `01-skeleton.md`）。

---

## 球坐标与 GR 特殊情况

| 情况 | 边界条件设置 |
|------|-------------|
| Spherical theta 边界 | 自动设置（无需在 TOML 中指定） |
| Spherical phi 边界 | 自动为 PERIODIC（由于 2-pi 周期性） |
| GR HORIZON 边界 | 自动设置（无需在 TOML 中指定，也不需要 pgen 方法） |

在这些情况下，TOML 只需为**未被自动处理**的维度设置边界条件。例如，2D Spherical 只需为 rmin 边界设置边界条件。

---

## 必需的头文件

```cpp
#include "enums.h"     // bc_in, em, FldsBC, PrtlBC
```

---

## 约束与不兼容性

| 约束 | 说明 |
|------------|-------------|
| CONDUCTOR 场 + REFLECT 粒子 | 必须配对 |
| ATMOSPHERE 场 + ATMOSPHERE 粒子 | 必须配对 |
| HORIZON 仅限 GR | SRPIC 中不存在视界边界 |
| MatchFields 与 MatchFieldsInX1 的优先级 | 两者同时定义时，方向专用版本优先 |
| FixFieldsConst 的 bc_in 参数 | 必须使用 `bc_in::Mx1`，而不是 `"x1"` 字符串 |

---

## 常见陷阱

1. **match_ds 太小** — 匹配层太薄 → 场在边界处振荡 → 增大 match_ds（取模拟域的 5-10%）
2. **忘记设置粒子边界条件** — 只设置了场的边界条件而没有设置粒子的 → 粒子堆积或泄漏
3. **球坐标的维度设置错误** — 2D Spherical 的边界条件数组只需要 1 个元素（r 方向）；theta 和 phi 会自动处理
4. **AtmFields 不完整** — 大气边界需要在 TOML 中配置 `[boundaries.atmosphere]` 才能正常工作
5. **动态边界条件后忘记恢复** — 如果 setFldsBC 是永久性更改，后续所有步都会受到影响。使用一个标志位确保只切换一次
