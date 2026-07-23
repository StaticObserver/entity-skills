# 04 — 外部电流源（ext_current）

> 基于 Entity v1.4.4

## 何时使用

当你需要在安培定律中添加外部源电流时使用。触发关键词：外部电流、天线驱动、轴子电流、Wald 电流、J_ext、电流源项。

**仅适用于 Minkowski 度规（SRPIC）。GRPIC 不支持 ext_current。**

---

## API 签名

### 官方 API（仅可访问坐标）

```cpp
struct ExtCurrent {
    // All three components must be defined
    Inline auto jx1(const coord_t<D>& x) const -> real_t;
    Inline auto jx2(const coord_t<D>& x) const -> real_t;
    Inline auto jx3(const coord_t<D>& x) const -> real_t;

    // Internal parameters
    real_t coeff, k, omega, B0;
};
```

**实例名 `ext_current` 是强制性的**——引擎通过 C++20 concept 检测它。

### 引擎修改版 API（可访问电磁场和时间）

```cpp
// Requires modifying Entity engine source (ampere_mink.hpp) to extend Context
struct ExtCurrent {
    template <class Context>
    Inline auto jx1(const Context& ctx) const -> real_t {
        // ctx.x_Ph  — physical coordinates
        // ctx.em(i1, i2, em::bx1)  — read current EM field (available after engine modification)
        // ctx.time  — current simulation time
        // ctx.dx    — grid spacing
    }
};
```

**重要**：扩展 Context 需要修改 `src/engines/srpic/ampere_mink.hpp`。这属于**引擎修改**——请转交 entity-core-dev。

---

## 参数说明

| 参数 | 含义 | 单位 |
|-----------|---------|-------|
| `coord_t<D> x` | 当前网格点的物理坐标 | 代码单位 |
| `real_t` 返回值 | 外部电流密度分量 | j0 = n0 * q0 * c（需要归一化补偿） |
| `coeff = skindepth0^2 / larmor0` | 安培归一化补偿系数 | — |

---

## 归一化补偿（关键！）

**完整推导见 `00-normalization.md`。**

安培离散化公式：
```
dE/dt = - (larmor0 / (ppc0 * skindepth0^2)) x (J_deposited + J_external)
```

**ext_current 返回的每个电流分量都必须预先乘以 `skindepth0^2 / larmor0`**：

```cpp
struct ExtCurrent {
    real_t larmor0, skindepth0;
    real_t coeff;  // = skindepth0^2 / larmor0 (computed in constructor)

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        // Physical current x normalization compensation
        return coeff * epsilon * omega * B0 * math::sin(k * x[0] - omega * time);
    }
};
```

---

## 必需的头文件

```cpp
#include "utils/numeric.h"  // ZERO, ONE, SQR, math::
```

不需要额外的 archetype——ext_current 由引擎 kernel 直接调用。

---

## 代码示例

### 示例 1：静态电流源（Wald 真空概念验证）

```cpp
struct ExtCurrent {
    real_t coeff, amp;

    ExtCurrent(real_t l0, real_t s0, real_t a)
      : coeff(SQR(s0) / l0), amp(a) {}

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        return coeff * amp * math::sin(x[0]);
    }
    Inline auto jx2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto jx3(const coord_t<D>&) const -> real_t { return ZERO; }
};

// In PGen
ExtCurrent ext_current;

PGen(...) : ext_current { larmor0, skindepth0, amplitude } {}
```

### 示例 2：行波电流源（axion-PIC 模式）

```cpp
struct ExtCurrent {
    real_t coeff, epsilon, omega, k, B0;
    real_t time;  // Must be updated in CustomPostStep or externally

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        return coeff * epsilon * omega * B0
             * math::sin(k * x[0] - omega * time);
    }
    Inline auto jx2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto jx3(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

**问题**：官方 ext_current 只能访问坐标，无法访问 `time`。时间相关的电流源需要：
1. 在 `CustomPostStep` 中更新 ext_current 的 time 成员（前提是 ext_current 不是 const）
2. 或者修改引擎使 Context 包含 time → entity-core-dev

---

## 约束与不兼容性

| 约束 | 说明 |
|------------|-------------|
| **仅限 Minkowski** | ext_current 仅在 SRPIC 引擎中有效。GRPIC 不支持 |
| **必须定义全部分量** | 即使未使用的分量也必须返回 ZERO。未定义的分量 = 未定义行为 |
| **无法访问实时电磁场（官方 API）** | 只能读取坐标。如需访问电磁场，请使用 Context 扩展（引擎修改） |
| **无法直接读取时间** | 必须通过 ext_current 的成员变量传递时间，并在 CustomPostStep 中更新（前提是不是 const） |

---

## 常见陷阱

1. **忘记乘以 skindepth0^2/larmor0**——ext_current 返回的值会直接进入安培 kernel，并被乘以 larmor0/skindepth0^2 进行缩放。不做补偿 → 电流强度量级错误。**这是最常见的 ext_current bug**
2. **试图在 GRPIC 中使用 ext_current**——会导致编译失败或运行时未定义行为。GR 下的安培求解器必须修改
3. **时间相关的电流源却无法访问时间**——官方 API 没有 time 参数。必须通过成员变量传递，并在 CustomPostStep 中更新
4. **电磁场访问限制**——在 Context 中访问电磁场属于引擎修改，不属于标准 API。如果 PGen 需要读取实时 B/E 来计算电流 → 标记为引擎修改
5. **必须定义全部三个分量**——遗漏某个未被检测到的 jx 方法可能导致该分量出现异常行为（取决于 trait 检测逻辑）
