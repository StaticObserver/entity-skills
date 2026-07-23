# 02 — 场初始化（InitFields）

> 基于 Entity v1.4.4

## 何时使用

当你需要为模拟设置初始电磁场构型时使用。触发关键词：initial B-field、initial E-field、磁场构型、电场分布、Wald、dipole、Harris sheet。

**如果模拟不需要初始场（例如纯粒子静电问题），请跳过本参考。**

---

## InitFields 签名

```cpp
template <Dimension D>
struct InitFields {
    // Constructor: read parameters from TOML [setup]
    InitFields(real_t b0, real_t theta, ...);

    // ===== SRPIC: tetrad (orthonormal) basis =====
    Inline auto bx1(const coord_t<D>& x) const -> real_t;
    Inline auto bx2(const coord_t<D>& x) const -> real_t;
    Inline auto bx3(const coord_t<D>& x) const -> real_t;

    Inline auto ex1(const coord_t<D>& x) const -> real_t;
    Inline auto ex2(const coord_t<D>& x) const -> real_t;
    Inline auto ex3(const coord_t<D>& x) const -> real_t;

    // ===== GRPIC additional: D field + potential =====
    Inline auto dx1(const coord_t<D>& x) const -> real_t;
    Inline auto dx2(const coord_t<D>& x) const -> real_t;
    Inline auto dx3(const coord_t<D>& x) const -> real_t;

    // Or use the potential method (code computes B and D via finite differences)
    Inline auto A_1(const coord_t<D>& x) const -> real_t;
    Inline auto A_0(const coord_t<D>& x) const -> real_t;
    Inline auto A_3(const coord_t<D>& x) const -> real_t;

private:
    real_t param1, param2, ...;
};
```

### 实例化

```cpp
// Declare in PGen
InitFields<D> init_flds;

// Initialize in PGen constructor
PGen(...) : init_flds { B0, theta, ... } {}
```

**init_flds 实例名是强制的**（引擎通过 C++20 concepts 检测它）。

---

## 参数说明

### Coord 参数
- `coord_t<D>` — D 维物理坐标数组。`x[0]` = x1 坐标，`x[1]` = x2 坐标，`x[2]` = x3 坐标
- Cartesian 中：x1=x，x2=y，x3=z
- Spherical 中：x1=r，x2=θ，x3=φ

### SRPIC：Tetrad（正交归一）基

场值以**局部 tetrad（正交归一）基**返回。代码自动处理坐标变换和交错网格放置。

| Cartesian 分量 | 物理含义 | Spherical 分量 | 物理含义 |
|---------------|---------|---------------|---------|
| ex1 | Ex | ex1 | Er |
| ex2 | Ey | ex2 | Eθ |
| ex3 | Ez | ex3 | Eφ |
| bx1 | Bx | bx1 | Br |
| bx2 | By | bx2 | Bθ |
| bx3 | Bz | bx3 | Bφ |

### GRPIC：坐标基

场值以**坐标基**返回。需要额外定义 D 场（电位移矢量）。

**定义 GR 场的两种方式：**

**方法 1：直接设置 B 和 D**
```cpp
Inline auto bx1(const coord_t<D>& x) const -> real_t { return ...; }
Inline auto dx1(const coord_t<D>& x) const -> real_t { return ...; }
```

**方法 2：设置磁势 A（代码通过有限差分计算 B = ∇×A）**
```cpp
Inline auto A_1(const coord_t<D>& x) const -> real_t { return ...; }
Inline auto A_0(const coord_t<D>& x) const -> real_t { return ...; }
Inline auto A_3(const coord_t<D>& x) const -> real_t { return ...; }
```

GRPIC 中的度规 API（可从 InitFields 访问）：
- `metric.sqrt_det_h()` — √det(h) = √|g|
- `metric.alpha()` — lapse 函数
- `metric.beta1()` — shift 矢量 β¹
- `metric.spin()` — 黑洞自旋参数 a
- `metric.template h_<i,j>()` — 空间度规分量 hij

---

## 必需的 Include

```cpp
// Math utilities
#include "utils/numeric.h"     // ZERO, ONE, math::cos, math::sin, SQR

// Coordinates and types
#include "global.h"
#include "enums.h"
```

不需要额外的 archetype include —— InitFields 直接返回标量值。

---

## 代码示例

### 示例 1：均匀 B 场（SRPIC，2D Cartesian）

```cpp
template <Dimension D>
struct InitFields {
    real_t Bmag, Btheta, Bphi;

    InitFields(real_t b, real_t theta, real_t phi)
      : Bmag(b)
      , Btheta(theta * static_cast<real_t>(constant::deg2rad))
      , Bphi(phi * static_cast<real_t>(constant::deg2rad)) {}

    Inline auto bx1(const coord_t<D>&) const -> real_t {
        return Bmag * math::cos(Btheta);
    }
    Inline auto bx2(const coord_t<D>&) const -> real_t {
        return Bmag * math::sin(Btheta) * math::sin(Bphi);
    }
    Inline auto bx3(const coord_t<D>&) const -> real_t {
        return Bmag * math::sin(Btheta) * math::cos(Bphi);
    }

    // E-field satisfies E = -v×B (static plasma → E=0)
    Inline auto ex1(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex3(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

### 示例 2：Harris 电流片（SRPIC，2D 重联）

```cpp
template <Dimension D>
struct InitFields {
    real_t bg_B, bg_Bguide, cs_width;

    InitFields(real_t B, real_t Bg, real_t w)
      : bg_B(B), bg_Bguide(Bg), cs_width(w) {}

    // Reversing Bx1 field
    Inline auto bx1(const coord_t<D>& x) const -> real_t {
        return bg_B * math::tanh(x[1] / cs_width);
    }
    // Guide field
    Inline auto bx3(const coord_t<D>&) const -> real_t {
        return bg_Bguide;
    }
    Inline auto bx2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex1(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex3(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

### 示例 3：Wald 真空解（GRPIC，Kerr-Schild）

```cpp
template <class M, Dimension D>
struct InitFields {
    const M& metric;

    InitFields(const M& m) : metric(m) {}

    Inline auto A_3(const coord_t<D>& x) const -> real_t {
        // Wald: A_φ = (B0/2) * Σ * sin²θ
        real_t r = x[0];
        real_t th = x[1];
        real_t a = metric.spin();
        real_t sigma = SQR(r) + SQR(a * math::cos(th));
        return 0.5 * B0 * sigma * SQR(math::sin(th));
    }

    Inline auto A_1(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto A_0(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

代码自动通过有限差分从 A_3 计算 B 和 D 场。

### 示例 4：场设置器继承（随时间变化的场）

```cpp
// Base static field
template <Dimension D>
struct InitFields {
    real_t B0;
    InitFields(real_t b) : B0(b) {}
    Inline auto bx1(const coord_t<D>&) const -> real_t { return B0; }
};

// Extension: add rotating E-field (pulsar magnetosphere)
template <Dimension D>
struct DriveFields : public InitFields<D> {
    real_t omega, time;
    DriveFields(real_t b, real_t om, real_t t)
      : InitFields<D>(b), omega(om), time(t) {}

    Inline auto ex2(const coord_t<D>& x) const -> real_t {
        return -omega * x[0] * this->bx1(x) * math::sin(x[1]);
    }
    Inline auto ex3(const coord_t<D>& x) const -> real_t {
        return omega * x[0] * this->bx1(x) * math::cos(x[1]);
    }
};
```

在 PGen 中，将 `InitFields` 替换为 `DriveFields`，并通过 `AtmFields` 或 `MatchFields` 传递时间参数。

---

## 约束与不兼容性

| 约束 | 说明 |
|------|------|
| init_flds 实例名是强制的 | 不能重命名；引擎按名称检测它 |
| SR 不需要 dx | 只需定义 ex + bx；未定义的分量默认为 0 |
| GR 必须同时设置 B 和 D（或 A） | 只设置 bx 而不设置 dx → D 场为 0 → 电场求解异常 |
| 球坐标中的极点 | 使用 `cmp::AlmostZero(math::sin(x[1]))` 检测并特殊处理 |
| E×B = 0 约束 | 纯磁场初始化时必须满足 E×B=0，否则会产生人为的 Poynting 通量 |

---

## 常见陷阱

1. **在 InitFields 中额外地乘以或除以归一化系数** —— InitFields 返回的场值是代码归一化单位下的值；直接返回物理值即可。无需考虑 larmor0 等额外的归一化系数。详见 `00-normalization.md`
2. **球坐标混淆** —— 在 Spherical 坐标中，ex2 = Eθ，而不是 Ey；物理含义完全不同
3. **混淆 SR 与 GR 的基** —— SR 返回正交归一基，GR 返回坐标基。如果在 GR 中误用 SR 的 tetrad 约定，场值在度规非平庸的区域会发生畸变
4. **忘记 D 场** —— 在 GR 中只设置 bx 而不设置 dx；代码不会报错，但电场解是错误的
5. **基于继承的场设置器** —— 派生类需要 `this->` 才能访问基类成员（因为它是模板类）
6. **性能注意事项** —— 这些方法会对每个格点调用。避免在方法内重复计算；尽可能在构造函数中预先计算常量
