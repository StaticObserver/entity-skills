# 00 — 归一化约定（基准单位）

> 基于 Entity v1.4.4

## 何时使用

**必读内容**。Entity 使用一套基准单位制，代码中所有物理量都以归一化形式表示。不掌握归一化约定会在 InitFields（场初始化）和 ext_current（外部电流）中导致数值量级错误——这是 PGen 开发中最常见也最隐蔽的 bug。

触发场景：任何需要编写 InitFields、ext_current，或理解引擎内部数值行为的时候。

---

## 基准单位概述

Entity 的内核（Ampere 求解器、pusher、沉积）使用一套基准单位制进行归一化。在大多数情况下，用户只需要使用"物理单位"——TOML 中的参数如 `larmor0`、`extent` 等都是以物理单位指定的。

### PIC 方程（CGS 单位，正交归一基）

```
∂B/(c∂t) = -∇×E
∂E/(c∂t) = ∇×B - (4π/c) J

d(βᵢγᵢ)/(c dt) = (qᵢ/(mᵢ c²)) (E + βᵢ×B)
dxᵢ/(c dt) = βᵢ

J = (1/V) Σ_{i∈V} qᵢ wᵢ βᵢ c
```

### 基准量定义

引入一个**基准粒子**：电荷 q₀ > 0，质量 m₀。在均匀磁场 B₀ 中，该粒子以 βγ = 1 在垂直于磁场的平面内运动时的 Larmor 半径为：

```
ρ₀ = m₀ c² / (q₀ B₀)
```

在高斯单位制中，我们自由选取 **q₀/m₀ ≡ 1** 和 **c ≡ 1**，因此 **B₀ ≡ 1/ρ₀**。

对于一个由电荷为 -q₀ 的静止离子和电荷为 q₀ 的基准粒子组成、数密度均为 n₀ 的等离子体，其振荡频率和趋肤深度为：

```
ω₀² = 4π n₀ q₀² / m₀
d₀ ≡ 1/ω₀
```

基准电流密度和数密度：

```
J₀ ≡ 4π q₀ n₀
n₀ ≡ PPC₀ / V₀
```

### 完整基准量表

| 符号 | 描述 | 定义 | 代码实现 |
|------|------|------|---------|
| c | 光速 | ≡ 1 | — |
| PPC₀ | 每格基准粒子数 | 基础量 | `Simulation::params().ppc0()` |
| d₀ | 基准趋肤深度 | 基础量 | `Simulation::params().skindepth0()` |
| ρ₀ | 基准 Larmor 半径 | 基础量 | `Simulation::params().larmor0()` |
| V₀ | 基准网格体积 | 见下文 V₀ 定义 | `Simulation::params().V0()` |
| n₀ | 基准数密度 | ≡ PPC₀ / V₀ | `Simulation::params().n0()` |
| 4πq₀ | 基准粒子电荷 | ≡ (n₀ d₀²)⁻¹ | `Simulation::params().q0()` |
| m₀ | 基准粒子质量 | ≡ q₀ | —（无独立变量） |
| σ₀ | 基准磁化参数 | ≡ (d₀/ρ₀)² | `Simulation::params().sigma0()` |
| B₀ | 基准磁场强度 | ≡ ρ₀⁻¹ | `Simulation::params().B0()` |
| J₀ | 基准电流密度 | ≡ 4πq₀ n₀ | — |

**关键提示**：代码中的 `q0()` 返回的是 **4πq₀**，而不是 q₀ 本身。m₀ 在代码中没有独立变量，因为在高斯单位制中我们可以选取 m₀ ≡ q₀。在 TOML 中，某个物种的 `charge` = qᵢ/q₀，`mass` = mᵢ/m₀，两者均为无量纲量。

### 归一化方程

定义 q̃ᵢ ≡ qᵢ/q₀，m̃ᵢ ≡ mᵢ/m₀，**e** ≡ **E**/B₀，**b** ≡ **B**/B₀，**j** ≡ 4π**J**/J₀：

```
∂b/∂t = -∇×e
∂e/∂t = ∇×b - (J₀/B₀) j

d(βᵢγᵢ)/dt = (q̃ᵢ/m̃ᵢ) B₀ (e + βᵢ×b)
dxᵢ/dt = βᵢ

j = (V₀/V)·(1/PPC₀)·Σ_{i∈V} q̃ᵢ wᵢ βᵢ
```

输出数据中的所有场量都是相对于基准值的比值，这些量对分辨率和粒子采样不敏感。

### 基准体积 V₀ 的定义

```
V₀ ≡ (Δx)^D                            (Cartesian coordinates)
V₀ ≡ √(det h)|_{r=Δr/2, θ=Δθ/2}       (spherical coordinates, first cell near the pole)
```

其中 D 是模拟维度。最终用户无需知道 V₀ 的具体数值——像 V₀ 和 n₀ 这样的因子在归一化之后都会相互抵消。

### 物理量换算

任何公式中的物理量都通过以下替换转换为无量纲量：

```
n → ñ n₀,   m → m̃ m₀,   q → q̃ q₀
B → b B₀,   E → e B₀,   4πJ → j J₀,   ct → t
```

代入等价关系后，所有基准未知量最终都归结为 ρ₀ 和 d₀，不会残留额外的因子。

**示例**：等离子体静止质量能量密度与磁场能量密度之比

```
U_B / (ρ_p c²) ≡ (B²/8π) / (n_p m_p c²)
                = (b / 2 ñ_p m̃_p) · (d₀/ρ₀)²
                = (b / 2 ñ_p m̃_p) · σ₀
```

其中 ñ_p = n_p/n₀，m̃_p = m_p/m₀，b = B/B₀。

---

## Ampere 内核归一化（关键！）

### Ampere 离散化公式

引擎的 Ampere 求解器使用如下离散化：

```
dE/dt = - (larmor0 / skindepth0²) × J_total
```

其中 `J_total = J_deposited + J_external`。

### 对外部电流的约束

由于 Ampere 内核前面带有一个 `-larmor0/skindepth0²` 的缩放因子，你在 ext_current 中返回的电流值进入引擎时会被**自动乘上**该因子。

**这意味着 ext_current 的返回值必须预先补偿**：

```
text_current_return_value = physical_current × (skindepth0² / larmor0)
```

### 对 InitFields 的约束

InitFields 定义的场值直接写入 EM 数组，**不经过 Ampere 内核**。因此：

- **InitFields 返回的场值采用代码归一化单位**——直接返回即可，无需额外的归一化系数
- 引擎内部通过 B0 = 1/larmor0 之类的关系处理所有单位换算

---

## 单位域边界

Entity 中不同的代码区域使用不同的单位约定：

| 代码区域 | 使用的单位 | 含义 |
|----------|---------|------|
| InitPrtls | **物理单位** | 位置 = 全局物理坐标，速度 = 局部正交归一基 |
| CustomPostStep | **代码单位** | fields.em 中的值已经是归一化的代码单位 |
| InitFields | **代码归一化单位** | 返回的 ex/bx 直接写入 EM 数组，无需额外系数 |
| ext_current | **代码单位（预补偿）** | 返回的 jx 必须包含 skindepth0²/larmor0 补偿 |
| Ampere Kernel | **代码单位** | 内部自动应用 larmor0/(ppc0·skindepth0²) 因子 |
| CustomFieldOutput | **代码单位** | 直接读取 domain.fields.em |

---

## 完整推导链

以 axion-PIC 项目为例，演示为什么需要 `skindepth0²/larmor0` 补偿：

### 物理方程
```
dE/dt = -J_a - J_plasma
J_a = ε · ω · B · sin(kx - ωt)   (axion contribution to current)
```

### 数值离散化
```
E_new = E_old - Δt · (larmor0/skindepth0²) · J_total
```

### 为使电场变化与行波解 dE/dt = -ε·ω·B·sin(kx-ωt) 一致
```
J_ext = ε · ω · B · sin(kx-ωt) · (skindepth0² / larmor0)
       ^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^
       Physical current           Normalization compensation coefficient
```

### 验证公式
```
coef = skindepth0² / larmor0
```

---

## 代码示例

### InitFields 中的正确用法

```cpp
template <Dimension D>
struct InitFields {
    real_t larmor0, skindepth0;

    InitFields(real_t l0, real_t s0) : larmor0(l0), skindepth0(s0) {}

    // Field values returned directly (code normalized units)
    Inline auto bx1(const coord_t<D>&) const -> real_t {
        return B0_physical;
    }

    // Field values returned directly (code normalized units)
    Inline auto ex1(const coord_t<D>& x) const -> real_t {
        return -epsilon * B0_physical * math::cos(k * x[0]);
    }
};
```

### ext_current 中的正确用法

```cpp
struct ExtCurrent {
    real_t larmor0, skindepth0;
    real_t coeff;  // = skindepth0² / larmor0

    ExtCurrent(real_t l0, real_t s0)
        : larmor0(l0), skindepth0(s0), coeff(SQR(s0) / l0) {}

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        // Physical current × compensation coefficient
        return coeff * epsilon * omega * B0 * math::sin(k * x[0] - omega * time);
    }
};
```

---

## 常见陷阱

1. **在 InitFields 中多乘/多除了归一化系数**——最隐蔽的 bug。InitFields 返回的场值采用代码归一化单位，直接写出即可。多余的操作会导致场值量级完全错误。症状：磁场弱了 N 倍，所有物理结果都是错的
2. **忘记给 ext_current 乘上 skindepth0²/larmor0**——电流强度错误，导致 dE/dt 的量级不正确
3. **混淆物理单位和代码单位**——在 InitPrtls 中使用了代码单位的值，或在 CustomPostStep 中直接拿物理值做比较
4. **larmor0 和 skindepth0 的选取不合理**——例如 larmor0 过大导致 B0 过小，或 skindepth0 过小导致 n0 爆炸

### 来自 axion-PIC 的真实教训

在 axion-PIC 开发过程中，InitFields 最初错误地写成了 `return -epsilon * B0 * cos(k*x) / larmor0`。这个 bug 是在真空测试中发现 DivE 非零时被发现的。改正为直接返回代码归一化值之后，DivE 恢复为零。与此同时，ext_current 正确地保留了 `skindepth0²/larmor0` 补偿。
