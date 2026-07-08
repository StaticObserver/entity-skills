# 06 — 边界条件（MatchFields / FixFieldsConst / AtmFields）

> 基于 Entity v1.4.4

## 何时使用

需要非 PERIODIC 边界条件时。触发关键词：open boundary、匹配边界、固定边界、大气层边界、吸收边界、视界边界、导体边界、MatchFields、FixFields、AtmFields。

**如果所有方向都是 PERIODIC，跳过此 reference。**

---

## BC 类型总览

### 场 BC

| TOML 值 | 含义 | PGen 中的对应方法 |
|---------|------|------------------|
| `"PERIODIC"` | 周期性 | 不需要 |
| `"MATCH"` | 匹配边界 | `MatchFields(time)` 或 `MatchFieldsInX1/X2/X3(time)` |
| `"FIXED"` | 固定值边界 | `FixFieldsConst(time, bc_in, em)` |
| `"ATMOSPHERE"` | 大气层边界 | `AtmFields(time)` |
| `"CUSTOM"` | 自定义 | 引擎扩展 |
| `"HORIZON"` | 视界边界（仅 GR） | 不需要（自动处理） |
| `"CONDUCTOR"` | 导体边界 | `FixFieldsConst` |

### 粒子 BC

| TOML 值 | 含义 | 配对要求 |
|---------|------|---------|
| `"PERIODIC"` | 周期性 | — |
| `"ABSORB"` | 吸收 | — |
| `"ATMOSPHERE"` | 大气层 | 与场 ATMOSPHERE 配对 |
| `"CUSTOM"` | 自定义 | — |
| `"REFLECT"` | 反射 | 与场 CONDUCTOR 配对 |
| `"HORIZON"` | 视界 | — |

---

## MatchFields（MATCH 边界）

### 签名

```cpp
// 通用 MATCH（所有方向用同一个）
auto MatchFields(simtime_t time) const -> FieldSetterType;

// 方向特定 MATCH
auto MatchFieldsInX1(simtime_t time) const -> FieldSetterType;
auto MatchFieldsInX2(simtime_t time) const -> FieldSetterType;
auto MatchFieldsInX3(simtime_t time) const -> FieldSetterType;
```

### 参数说明

| 参数 | 含义 |
|------|------|
| `time` | 当前模拟时间（用于时间依赖边界场） |
| 返回值 | 一个 field setter 结构体（与 InitFields 同接口） |

### 代码示例

```cpp
// 简单的常数匹配场
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

**MatchFields vs MatchFieldsInX1/X2/X3**：
- `MatchFields` 对全部有 MATCH 的方向通用
- `MatchFieldsInX1` 只在 X1 方向的 MATCH 边界使用，X2/X3 可用不同的

### TOML 配置

```toml
[boundaries]
  fields    = [["MATCH"], ["PERIODIC"]]     # X1=MATCH, X2=PERIODIC
  particles = [["ABSORB"], ["PERIODIC"]]
  match_ds  = 0.5                           # 匹配层宽度
```

---

## FixFieldsConst（FIXED 边界）

### 签名

```cpp
auto FixFieldsConst(simtime_t time, const bc_in& bc, const em& comp) const
    -> std::pair<real_t, bool>;
```

### 参数说明

| 参数 | 含义 |
|------|------|
| `time` | 当前时间 |
| `bc` | 哪个边界：`bc_in::Mx1`(左), `bc_in::Px1`(右), `bc_in::Mx2`, `bc_in::Px2`, ... |
| `comp` | 哪个分量：`em::ex1`, `em::bx2`, `em::dx3`, ... |
| 返回值 `pair<real_t, bool>` | 值 + 是否应用 |

### 代码示例

```cpp
auto FixFieldsConst(simtime_t time, const bc_in& bc, const em& comp) const
    -> std::pair<real_t, bool> {

    // X1 左边界 → 时间依赖驱动
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

    // 未处理的分量 → 不应用
    return { ZERO, false };
}
```

### TOML 配置

```toml
[boundaries]
  fields    = [["FIXED"], ["PERIODIC"]]
  particles = [["REFLECT"], ["PERIODIC"]]   # FIXED 场 + REFLECT 粒子 = CONDUCTOR
```

---

## AtmFields（ATMOSPHERE 边界）

### 签名

```cpp
auto AtmFields(simtime_t time) const -> FieldSetterType;
```

返回值是一个 field setter（与 InitFields 相同接口），在 atmosphere 层中设置场值。

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
    species     = [1, 2]    # 哪些物种参与大气层
    ds          = 0.5
    g           = 1.0       # 引力加速度
```

---

## Dynamic BC 切换（CustomPostStep 中）

在运行中动态切换边界类型：

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

**注意**：使用 `setFldsBC`/`setPrtlBC` 的 PGen 必须用 non-const `Metadomain<S, M>&`（见 `01-skeleton.md`）。

---

## 球坐标和 GR 特殊情况

| 情况 | BC 设置 |
|------|--------|
| Spherical θ 边界 | 自动设置（不需要在 TOML 中指定） |
| Spherical φ 边界 | 自动 PERIODIC（因为 2π 周期性） |
| GR HORIZON 边界 | 自动设置（不需要在 TOML 中指定，不需要 pgen 方法） |

在这些情况下，TOML 只设置**不自动处理**的维度。例如 2D Spherical 只需设置 rmin 边界的 BC。

---

## 所需 Includes

```cpp
#include "enums.h"     // bc_in, em, FldsBC, PrtlBC
```

---

## 约束与不兼容

| 约束 | 说明 |
|------|------|
| CONDUCTOR 场 + REFLECT 粒子 | 必须配对使用 |
| ATMOSPHERE 场 + ATMOSPHERE 粒子 | 必须配对使用 |
| HORIZON 仅 GR | SRPIC 中不存在视界边界 |
| MatchFields 和 MatchFieldsInX1 的优先级 | 同时定义时，方向特定的版本优先 |
| FixFieldsConst 的 bc_in 参数 | 必须用 `bc_in::Mx1` 而不是 `"x1"` 字符串 |

---

## 常见陷阱

1. **match_ds 太小** — 匹配层太薄 → 场在边界振荡 → 增加 match_ds (5-10% of domain)
2. **忘了 particle BC** — 只设 fields BC 不设 particles BC → 粒子堆积或泄漏
3. **球坐标设错维度** — 2D Spherical 的 BC 数组只需 1 个元素（r 方向），theta 和 phi 自动处理
4. **AtmFields 不完整** — atmosphere 边界需要 TOML 中的 `[boundaries.atmosphere]` 配置才能正常工作
5. **Dynamic BC 后忘记改回** — 如果 setFldsBC 是永久变更，后续所有步都受影响。用 flag 确保只切换一次
