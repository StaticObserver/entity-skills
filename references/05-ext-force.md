# 05 — 外部力（ext_force + ExternalFields）

> 基于 Entity v1.4.4

## 何时使用

需要对粒子施加外力时。触发关键词：外部加速度、非电磁力、辐射反作用力、外部 E/B 场、ExternalFields、辐射压强。

**如果粒子只受 Lorentz force 作用，跳过此 reference。**

---

## 两种方式

| 方式 | 能力 | 复杂度 | 何时用 |
|------|------|--------|--------|
| `ext_force` 实例 | 仅取加速度 fx1/fx2/fx3 | 低 | 简单的空间/时间依赖外力 |
| `ExternalFields` 方法 | 加速度 + 外部 E + 外部 B | 高 | 需要提供场分量，或 per-species 开关 |

---

## 方式一：ext_force 实例

### 签名

```cpp
struct ExtForce {
    // 哪些物种受此力（0-based C++ 索引）
    std::vector<int> species = {0, 1};

    // 加速度分量（local tetrad basis）
    // 所有方法都是可选的——代码检测哪些存在
    Inline auto fx1(int sp, real_t time, const coord_t<D>& x) const -> real_t;
    Inline auto fx2(int sp, real_t time, const coord_t<D>& x) const -> real_t;
    Inline auto fx3(int sp, real_t time, const coord_t<D>& x) const -> real_t;
};

// 实例名 ext_force 强制
ExtForce ext_force;
```

### 参数说明

| 参数 | 含义 | 注意 |
|------|------|------|
| `sp` | 物种索引（就是 species 向量中的值） | 0-based C++ 索引 |
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
    // fx2, fx3 未定义 → 自动为 0
};

// 在 PGen 中
ExtForce ext_force;

PGen(...)
  : ext_force { /* species= */ {0, 1}, amplitude, k, omega } {}
```

---

## 方式二：ExternalFields 方法

### 签名

```cpp
// PGen 的方法（非独立实例）
template <Dimension D>
struct ExtFields {
    // 外部力（可选）
    Inline auto fx1(...) const -> real_t;
    Inline auto fx2(...) const -> real_t;
    Inline auto fx3(...) const -> real_t;

    // 外部 B 场（可选）
    Inline auto bx1(...) const -> real_t;
    Inline auto bx2(...) const -> real_t;
    Inline auto bx3(...) const -> real_t;

    // 外部 E 场（可选）
    Inline auto ex1(...) const -> real_t;
    Inline auto ex2(...) const -> real_t;
    Inline auto ex3(...) const -> real_t;
};

// PGen 方法
auto ExternalFields(simtime_t time, spidx_t sp,
                    const Domain<S, M>& domain) const
    -> std::pair<bool, ExtFields<D>> {
    if (/* per-species 条件 */) {
        return { true, ExtFields<D>{ time, sp, ... } };
    }
    return { false, ExtFields<D>{} };  // 不施加
}
```

### 参数说明

| 参数 | 含义 |
|------|------|
| `time` | 当前模拟时间 |
| `sp` | 物种索引 |
| `domain` | 当前 Domain（可读 mesh 和场） |
| 返回值 `pair<bool, F>` | bool = 是否对该物种施加；F = ExtFields functor |

### 关键区别

- **ExternalFields 每次调用构造新的 ExtFields 实例**（按值返回）
- **可以访问 domain.mesh.metric** → 能做坐标相关的场计算
- **bool 返回值控制 per-species 开关**
- **同时提供力(fx) + B(bx) + E(ex)** → 完全替代 ext_force + ext_current 的部分功能

### 代码示例

```cpp
template <SimEngine::type S, class M>
struct PGen {
    // ... 其他成员 ...

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
        // 只对 species 0 施加
        if (sp == 0) {
            return { true, ExtFields<D>{ time, sp } };
        }
        return { false, ExtFields<D>{} };
    }
};
```

---

## 两种方式取舍

```cpp
// ext_force → 简单、高效、适合不依赖 domain 的力
// ExternalFields → 灵活、可访问 metric/domain、可同时设 E+B+力

// 选 ext_force 当：
// - 只需要加速度
// - 不依赖 domain 的内部状态
// - 对所有物种行为一致

// 选 ExternalFields 当：
// - 需要同时提供外部 E 和 B 场
// - 需要 per-species 条件逻辑
// - 需要读 domain 的状态（如 metric、当前位置的场）
```

---

## 所需 Includes

```cpp
#include "framework/domain/domain.h"  // Domain<S,M> 类型
```

ext_force 不需要额外 archetype include。

---

## 约束与不兼容

| 约束 | 说明 |
|------|------|
| ext_force 和 ExternalFields 选一即可 | ExternalFields 是 ext_force 的超集 |
| ext_force 的 species 是 0-based | 与 InjectUniform 的 1-based 不同！ |
| fx 返回 tetrad basis 加速度 | 和 ext_current 的坐标基约定不同 |
| ExternalFields 的 ExtFields 结构体必须可以按值复制 | 每次调用返回新的实例 |

---

## 常见陷阱

1. **species 索引混淆** — ext_force 用 0-based（`{0, 1}`），粒子注入用 1-based（`{1, 2}`）
2. **basis 混淆** — ext_force 的 fx 是 tetrad basis 加速度，ext_current 的 jx 是坐标基分量
3. **ExternalFields 忘写 bool 判断** — 对所有物种返回 true 等价于 ext_force
4. **ExtFields 中访问未定义的行为** — 只在 ExtFields 用到的方法才定义，其余分量默认为 ZERO
