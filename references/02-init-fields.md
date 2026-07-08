# 02 — 场初始化（InitFields）

> 基于 Entity v1.4.4

## 何时使用

需要设置模拟的初始电磁场配置时。触发关键词：初始 B 场、初始 E 场、磁场位形、电场分布、Wald、dipole、Harris sheet。

**如果模拟不需要初始场（如纯粒子静电），跳过此 reference。**

---

## InitFields 签名

```cpp
template <Dimension D>
struct InitFields {
    // 构造函数：从 TOML [setup] 读取参数
    InitFields(real_t b0, real_t theta, ...);

    // ===== SRPIC: tetrad (orthonormal) basis =====
    Inline auto bx1(const coord_t<D>& x) const -> real_t;
    Inline auto bx2(const coord_t<D>& x) const -> real_t;
    Inline auto bx3(const coord_t<D>& x) const -> real_t;

    Inline auto ex1(const coord_t<D>& x) const -> real_t;
    Inline auto ex2(const coord_t<D>& x) const -> real_t;
    Inline auto ex3(const coord_t<D>& x) const -> real_t;

    // ===== GRPIC 额外: D 场 + 势 =====
    Inline auto dx1(const coord_t<D>& x) const -> real_t;
    Inline auto dx2(const coord_t<D>& x) const -> real_t;
    Inline auto dx3(const coord_t<D>& x) const -> real_t;

    // 或使用势方法（代码通过有限差分计算 B 和 D）
    Inline auto A_1(const coord_t<D>& x) const -> real_t;
    Inline auto A_0(const coord_t<D>& x) const -> real_t;
    Inline auto A_3(const coord_t<D>& x) const -> real_t;

private:
    real_t param1, param2, ...;
};
```

### 实例化

```cpp
// 在 PGen 中声明
InitFields<D> init_flds;

// 在 PGen 构造函数中初始化
PGen(...) : init_flds { B0, theta, ... } {}
```

**init_flds 实例名是强制要求的**（引擎通过 C++20 concept 检测）。

---

## 参数说明

### Coord 参数
- `coord_t<D>` — D 维物理坐标数组。`x[0]` = x1 坐标，`x[1]` = x2 坐标，`x[2]` = x3 坐标
- 在 Cartesian 中：x1=x, x2=y, x3=z
- 在 Spherical 中：x1=r, x2=θ, x3=φ

### SRPIC: Tetrad (Orthonormal) Basis

场值在 **local tetrad (orthonormal) basis** 中返回。代码自动处理坐标转换和交错网格。

| Cartesian 分量 | 物理含义 | Spherical 分量 | 物理含义 |
|---------------|---------|---------------|---------|
| ex1 | Ex | ex1 | Er |
| ex2 | Ey | ex2 | Eθ |
| ex3 | Ez | ex3 | Eφ |
| bx1 | Bx | bx1 | Br |
| bx2 | By | bx2 | Bθ |
| bx3 | Bz | bx3 | Bφ |

### GRPIC: Coordinate Basis

场值在 **coordinate basis** 中返回。额外需要 D 场（电位移矢量）。

**两种方式定义 GR 场：**

**方式一：直接设 B 和 D**
```cpp
Inline auto bx1(const coord_t<D>& x) const -> real_t { return ...; }
Inline auto dx1(const coord_t<D>& x) const -> real_t { return ...; }
```

**方式二：设磁势 A（代码有限差分计算 B = ∇×A）**
```cpp
Inline auto A_1(const coord_t<D>& x) const -> real_t { return ...; }
Inline auto A_0(const coord_t<D>& x) const -> real_t { return ...; }
Inline auto A_3(const coord_t<D>& x) const -> real_t { return ...; }
```

GRPIC 中的 metric API（可从 InitFields 访问）：
- `metric.sqrt_det_h()` — √det(h) = √|g|
- `metric.alpha()` — lapse function
- `metric.beta1()` — shift vector β¹
- `metric.spin()` — 黑洞自旋参数 a
- `metric.template h_<i,j>()` — 空间度规分量 hij

---

## 所需 Includes

```cpp
// 数学工具
#include "utils/numeric.h"     // ZERO, ONE, math::cos, math::sin, SQR

// 坐标和类型
#include "global.h"
#include "enums.h"
```

不需要额外 archetype include —— InitFields 直接返回标量值。

---

## 代码示例

### 示例 1: 均匀 B 场（SRPIC, 2D Cartesian）

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

    // E 场满足 E = -v×B（静止等离子体 → E=0）
    Inline auto ex1(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex3(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

### 示例 2: Harris 电流片（SRPIC, 2D Reconnection）

```cpp
template <Dimension D>
struct InitFields {
    real_t bg_B, bg_Bguide, cs_width;

    InitFields(real_t B, real_t Bg, real_t w)
      : bg_B(B), bg_Bguide(Bg), cs_width(w) {}

    // 反转 Bx1 场
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

### 示例 3: Wald 真空解（GRPIC, Kerr-Schild）

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

代码通过有限差分自动从 A_3 计算 B 和 D 场。

### 示例 4: Field Setter 继承（时间依赖场）

```cpp
// 基础静态场
template <Dimension D>
struct InitFields {
    real_t B0;
    InitFields(real_t b) : B0(b) {}
    Inline auto bx1(const coord_t<D>&) const -> real_t { return B0; }
};

// 扩展：添加旋转 E 场（pulsar magnetosphere）
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

在 PGen 中用 `DriveFields` 替换 `InitFields`，通过 `AtmFields` 或 `MatchFields` 传递时间参数。

---

## 约束与不兼容

| 约束 | 说明 |
|------|------|
| init_flds 实例名强制 | 不能改名，引擎通过名字检测 |
| SR 不需要 dx | 只定义 ex + bx 即可，未定义的分量自动为 0 |
| GR 必须同时设 B 和 D（或 A） | 只设 bx 不设 dx → D 场为 0 → 电场求解器异常 |
| 球坐标的极点 | 使用 `cmp::AlmostZero(math::sin(x[1]))` 判断并特别处理 |
| E×B = 0 约束 | 纯磁场初始化时 E×B=0 必须成立，否则会有人工 Poynting flux |

---

## 常见陷阱

1. **InitFields 中额外乘以/除以归一化系数** — InitFields 返回的场值是 code normalized 单位，直接返回物理值即可，不需要额外考虑 larmor0 等归一化系数。详情见 `00-normalization.md`
2. **球坐标混淆** — 在 Spherical 中 ex2 = Eθ 不是 Ey，物理含义完全不同
3. **SR vs GR basis 混用** — SR 返回 orthonormal basis，GR 返回 coordinate basis。如果在 GR 中误用 SR 的 tetrad 约定，场值会在度规非平凡区域畸变
4. **D 场遗漏** — GR 中只设 bx 不设 dx，代码不报错但电场解算错误
5. **继承式 Field Setter** — 子类需要 `this->` 访问基类成员（因为是模板类）
6. **性能注意** — 每个网格点都会调用这些方法。避免在方法内做重复计算，尽量在构造函数中预先计算常量
