# 04 — 外部电流源（ext_current）

> 基于 Entity v1.4.4

## 何时使用

需要在 Ampere 定律中添加外部源电流时。触发关键词：外部电流、天线驱动、axion current、Wald current、J_ext、电流源项。

**仅适用于 Minkowski 度量（SRPIC）。GRPIC 不支持 ext_current。**

---

## API 签名

### 官方 API（只能访问坐标）

```cpp
struct ExtCurrent {
    // 所有三个分量都必须定义
    Inline auto jx1(const coord_t<D>& x) const -> real_t;
    Inline auto jx2(const coord_t<D>& x) const -> real_t;
    Inline auto jx3(const coord_t<D>& x) const -> real_t;

    // 内部参数
    real_t coeff, k, omega, B0;
};
```

**实例名 `ext_current` 强制**，引擎通过 C++20 concept 检测。

### 引擎修改 API（可访问 EM 场和时间）

```cpp
// 需要修改 Entity 引擎源码（ampere_mink.hpp）来扩展 Context
struct ExtCurrent {
    template <class Context>
    Inline auto jx1(const Context& ctx) const -> real_t {
        // ctx.x_Ph  — 物理坐标
        // ctx.em(i1, i2, em::bx1)  — 读取当前 EM 场（引擎修改后可用）
        // ctx.time  — 当前模拟时间
        // ctx.dx    — 网格间距
    }
};
```

**重要**：Context 扩展需要修改 `src/engines/srpic/ampere_mink.hpp`。这是**引擎修改**，路由到 entity-core-dev。

---

## 参数说明

| 参数 | 含义 | 单位 |
|------|------|------|
| `coord_t<D> x` | 当前网格点的物理坐标 | 代码单位 |
| `real_t` 返回值 | 外部电流密度分量 | j₀ = n₀·q₀·c（需补偿归一化） |
| `coeff = skindepth0² / larmor0` | Ampere 归一化补偿系数 | — |

---

## 归一化补偿（关键！）

**参见 `00-normalization.md` 的完整推导。**

Ampere 离散化公式：
```
dE/dt = - (larmor0 / (ppc0 · skindepth0²)) × (J_deposited + J_external)
```

**ext_current 中返回的每个电流分量必须预先乘以 `skindepth0² / larmor0`**：

```cpp
struct ExtCurrent {
    real_t larmor0, skindepth0;
    real_t coeff;  // = skindepth0² / larmor0（在构造函数中计算）

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        // 物理电流 × 归一化补偿
        return coeff * epsilon * omega * B0 * math::sin(k * x[0] - omega * time);
    }
};
```

---

## 所需 Includes

```cpp
#include "utils/numeric.h"  // ZERO, ONE, SQR, math::
```

不需要额外 archetype — ext_current 被引擎内核直接调用。

---

## 代码示例

### 示例 1: 静态电流源（Wald vacuum 概念验证）

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

// 在 PGen 中
ExtCurrent ext_current;

PGen(...) : ext_current { larmor0, skindepth0, amplitude } {}
```

### 示例 2: 行波电流源（axion-PIC 模式）

```cpp
struct ExtCurrent {
    real_t coeff, epsilon, omega, k, B0;
    real_t time;  // 需要在 CustomPostStep 或外部更新

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        return coeff * epsilon * omega * B0
             * math::sin(k * x[0] - omega * time);
    }
    Inline auto jx2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto jx3(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

**问题**：官方 ext_current 只能访问坐标，无法访问 `time`。time 依赖的电流源需要：
1. 在 `CustomPostStep` 中更新 ext_current 的时间成员（如果 ext_current 不是 const）
2. 或者修改引擎让 Context 包含 time → entity-core-dev

---

## 约束与不兼容

| 约束 | 说明 |
|------|------|
| **仅 Minkowski** | ext_current 只在 SRPIC 引擎中有效。GRPIC 不支持 |
| **三个分量都必须定义** | 即使不需要的也要返回 ZERO。未定义的分量 = 未定义行为 |
| **不能访问实时 EM 场（官方 API）** | 只能读坐标。需要读场的用 Context 扩展（引擎修改） |
| **不能直接读 time** | 需要在 CustomPostStep 中通过 ext_current 的成员变量传 time（如果不是 const） |

---

## 常见陷阱

1. **忘记乘以 skindepth0²/larmor0** — ext_current 返回的值直接进入 Ampere 内核被 larmor0/skindepth0² 缩放。不补偿 → 电流强度数量级错误。**这是最常见的 ext_current bug**
2. **GRPIC 中尝试用 ext_current** — 编译失败或运行时未定义行为。GR 中需要修改 Ampere 求解器
3. **时间依赖电流源无 time 访问** — 官方 API 没有时间参数。需要通过成员变量传递并在 CustomPostStep 中更新
4. **EM 场访问的限制** — Context 中的 EM 场访问是引擎修改，不在标准 API 中。如果 PGen 需要读实时 B/E 来算电流 → 标记为引擎修改
5. **三个分量全部定义** — 漏掉一个未被检测的 jx 方法可能导致该分量行为异常（取决于 trait 检测逻辑）
