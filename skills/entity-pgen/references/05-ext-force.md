# 05 — 外力（ext_force + ExternalFields）

> 基于 Entity v1.4.4

## 何时使用

当你需要对粒子施加外力时使用。触发关键词：外部加速度、非电磁力、辐射反作用力、外部 E/B 场、ExternalFields、辐射压。

**如果粒子只受洛伦兹力，请跳过本参考。**

---

## 两种方案

| 方案 | 能力 | 复杂度 | 何时使用 |
|----------|------------|------------|-------------|
| `ext_force` 实例 | 仅加速度 fx1/fx2/fx3 | 低 | 简单的空间/时间相关外力 |
| `ExternalFields` 方法 | 加速度 + 外部 E + 外部 B | 高 | 需要提供场分量，或按物种切换 |

---

## 方案 1：ext_force 实例

### 签名

```cpp
struct ExtForce {
    // Which species are subject to this force (0-based C++ indices)
    std::vector<int> species = {0, 1};

    // Acceleration components (local tetrad basis)
    // All methods are optional — the code detects which ones exist
    Inline auto fx1(int sp, real_t time, const coord_t<D>& x) const -> real_t;
    Inline auto fx2(int sp, real_t time, const coord_t<D>& x) const -> real_t;
    Inline auto fx3(int sp, real_t time, const coord_t<D>& x) const -> real_t;
};

// Instance name ext_force is mandatory
ExtForce ext_force;
```

### 参数说明

| 参数 | 含义 | 备注 |
|-----------|---------|-------|
| `sp` | 物种索引（species 向量中的值） | 0 起始的 C++ 索引 |
| `time` | 当前模拟时间 | 代码单位 |
| `coord_t<D> x` | 粒子物理坐标 | 代码单位 |

### 代码示例

```cpp
struct ExtForce {
    std::vector<int> species = {0, 1};
    real_t amplitude, k, omega;

    Inline auto fx1(int sp, real_t time, const coord_t<D>& x) const -> real_t {
        return amplitude * math::cos(k * x[0] - omega * time);
    }
    // fx2, fx3 undefined → default to 0
};

// In PGen
ExtForce ext_force;

PGen(...)
  : ext_force { /* species= */ {0, 1}, amplitude, k, omega } {}
```

---

## 方案 2：ExternalFields 方法

### 签名

```cpp
// PGen method (not a standalone instance)
template <Dimension D>
struct ExtFields {
    // External force (optional)
    Inline auto fx1(...) const -> real_t;
    Inline auto fx2(...) const -> real_t;
    Inline auto fx3(...) const -> real_t;

    // External B field (optional)
    Inline auto bx1(...) const -> real_t;
    Inline auto bx2(...) const -> real_t;
    Inline auto bx3(...) const -> real_t;

    // External E field (optional)
    Inline auto ex1(...) const -> real_t;
    Inline auto ex2(...) const -> real_t;
    Inline auto ex3(...) const -> real_t;
};

// PGen method
auto ExternalFields(simtime_t time, spidx_t sp,
                    const Domain<S, M>& domain) const
    -> std::pair<bool, ExtFields<D>> {
    if (/* per-species condition */) {
        return { true, ExtFields<D>{ time, sp, ... } };
    }
    return { false, ExtFields<D>{} };  // No force applied
}
```

### 参数说明

| 参数 | 含义 |
|-----------|---------|
| `time` | 当前模拟时间 |
| `sp` | 物种索引 |
| `domain` | 当前 Domain（可访问网格与场） |
| 返回值 `pair<bool, F>` | bool = 是否施加于该物种；F = ExtFields 仿函数 |

### 关键差异

- **ExternalFields 每次调用都会构造一个新的 ExtFields 实例**（按值返回）
- **可访问 domain.mesh.metric** → 支持坐标相关的场计算
- **bool 返回值控制按物种切换**
- **同时提供力（fx）+ B（bx）+ E（ex）** → 完全替代 ext_force + 部分 ext_current 功能

### 代码示例

```cpp
template <SimEngine::type S, class M>
struct PGen {
    // ... other members ...

    template <Dimension D>
    struct ExtFields {
        real_t time;
        spidx_t sp;

        Inline auto fx1(const coord_t<D>& x) const -> real_t {
            return amplitude * math::cos(omega * time);
        }
        Inline auto bx3(const coord_t<D>& x) const -> real_t {
            return B_external * math::sin(k * x[0]);
        }
    };

    auto ExternalFields(simtime_t time, spidx_t sp,
                        const Domain<S, M>& domain) const
        -> std::pair<bool, ExtFields<D>> {
        // Only apply to species 0
        if (sp == 0) {
            return { true, ExtFields<D>{ time, sp } };
        }
        return { false, ExtFields<D>{} };
    }
};
```

---

## 两种方案的取舍

```cpp
// ext_force → simple, efficient, suitable for forces that do not depend on domain
// ExternalFields → flexible, can access metric/domain, can set E+B+force simultaneously

// Choose ext_force when:
// - Only acceleration is needed
// - No dependency on domain's internal state
// - Behavior is uniform across all species

// Choose ExternalFields when:
// - Need to provide external E and B fields simultaneously
// - Need per-species conditional logic
// - Need to read domain state (e.g., metric, current field at position)
```

---

## 所需头文件

```cpp
#include "framework/domain/domain.h"  // Domain<S,M> type
```

ext_force 不需要额外的 archetype 头文件。

---

## 约束与不兼容性

| 约束 | 说明 |
|------------|-------------|
| ext_force 与 ExternalFields 二选一 | ExternalFields 是 ext_force 的超集 |
| ext_force 的 species 为 0 起始 | 与 InjectUniform 的 1 起始不同！ |
| fx 返回 tetrad 基下的加速度 | 与 ext_current 的坐标基约定不同 |
| ExternalFields 的 ExtFields 结构体必须可按值拷贝 | 每次调用都会返回一个新实例 |

---

## 常见陷阱

1. **物种索引混淆** — ext_force 使用 0 起始（`{0, 1}`），粒子注入使用 1 起始（`{1, 2}`）
2. **基混淆** — ext_force 的 fx 是 tetrad 基下的加速度，ext_current 的 jx 是坐标基分量
3. **ExternalFields 缺少 bool 判断** — 对所有物种返回 true 等价于 ext_force
4. **在 ExtFields 中访问未定义行为** — 只定义 ExtFields 中实际使用的方法；所有其他分量默认为零
