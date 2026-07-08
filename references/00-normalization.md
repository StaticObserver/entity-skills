# 00 — 归一化约定（Fiducial Units）

> 基于 Entity v1.4.4

## 何时使用

**必读**。Entity 使用 fiducial 单位系统，所有物理量在代码中都以归一化形式表示。不掌握归一化约定会导致 InitFields（场初始化）和 ext_current（外部电流）的数值数量级错误，这是 PGen 开发中最常见也最隐蔽的 bug。

触发场景：任何需要写 InitFields、ext_current、或理解引擎内部数值行为时。

---

## Fiducial Units 全景

Entity 的内核（Ampere 求解器、pusher、沉积）使用 fiducial 单位系统进行归一化。大多数情况下用户只需要和"物理单位"打交道——TOML 中的 `larmor0`、`extent` 等参数都以物理单位指定。

### PIC 方程组（CGS 单位制，正交归一基）

```
∂B/(c∂t) = -∇×E
∂E/(c∂t) = ∇×B - (4π/c) J

d(βᵢγᵢ)/(c dt) = (qᵢ/(mᵢ c²)) (E + βᵢ×B)
dxᵢ/(c dt) = βᵢ

J = (1/V) Σ_{i∈V} qᵢ wᵢ βᵢ c
```

### 基准量（Fiducial Quantities）定义

引入一个**基准粒子**：电荷 q₀ > 0，质量 m₀。在均匀磁场 B₀ 中，该粒子在垂直平面内以 βγ = 1 运动时的 Larmor 半径为：

```
ρ₀ = m₀ c² / (q₀ B₀)
```

在高斯单位制中，自由选取 **q₀/m₀ ≡ 1** 且 **c ≡ 1**，因此 **B₀ ≡ 1/ρ₀**。

由电荷 -q₀ 的静态离子和电荷 q₀ 的基准粒子组成、数密度均为 n₀ 的等离子体，其振荡频率和趋肤深度为：

```
ω₀² = 4π n₀ q₀² / m₀
d₀ ≡ 1/ω₀
```

基准电流密度和数密度：

```
J₀ ≡ 4π q₀ n₀
n₀ ≡ PPC₀ / V₀
```

### 基准量完整表格

| 符号 | 描述 | 定义 | 代码实现 |
|------|------|------|---------|
| c | 光速 | ≡ 1 | — |
| PPC₀ | 基准每网格粒子数 | 基础量 | `Simulation::params().ppc0()` |
| d₀ | 基准趋肤深度 | 基础量 | `Simulation::params().skindepth0()` |
| ρ₀ | 基准 Larmor 半径 | 基础量 | `Simulation::params().larmor0()` |
| V₀ | 基准网格体积 | 见下方 V₀ 定义 | `Simulation::params().V0()` |
| n₀ | 基准数密度 | ≡ PPC₀ / V₀ | `Simulation::params().n0()` |
| 4πq₀ | 基准粒子电荷 | ≡ (n₀ d₀²)⁻¹ | `Simulation::params().q0()` |
| m₀ | 基准粒子质量 | ≡ q₀ | —（无独立变量） |
| σ₀ | 基准磁化参数 | ≡ (d₀/ρ₀)² | `Simulation::params().sigma0()` |
| B₀ | 基准磁场强度 | ≡ ρ₀⁻¹ | `Simulation::params().B0()` |
| J₀ | 基准电流密度 | ≡ 4πq₀ n₀ | — |

**关键注意**：代码中的 `q0()` 返回的是 **4πq₀**，不是 q₀ 本身。m₀ 在代码中没有独立变量，因为 Gaussian 单位制下可以选择 m₀ ≡ q₀。TOML 中 species 的 `charge` = qᵢ/q₀，`mass` = mᵢ/m₀，均无量纲。

### 无量纲化后的方程组

定义 q̃ᵢ ≡ qᵢ/q₀，m̃ᵢ ≡ mᵢ/m₀，**e** ≡ **E**/B₀，**b** ≡ **B**/B₀，**j** ≡ 4π**J**/J₀：

```
∂b/∂t = -∇×e
∂e/∂t = ∇×b - (J₀/B₀) j

d(βᵢγᵢ)/dt = (q̃ᵢ/m̃ᵢ) B₀ (e + βᵢ×b)
dxᵢ/dt = βᵢ

j = (V₀/V)·(1/PPC₀)·Σ_{i∈V} q̃ᵢ wᵢ βᵢ
```

输出数据中的所有场量均为归一化后对基准值的比值，这些量对分辨率和粒子采样不敏感。

### 基准体积 V₀ 的定义

```
V₀ ≡ (Δx)^D                            （笛卡尔坐标）
V₀ ≡ √(det h)|_{r=Δr/2, θ=Δθ/2}       （球坐标，极点附近第一个网格）
```

其中 D 为模拟维度。终端用户不需要知道 V₀ 的具体数值——所有 V₀、n₀ 等因子在无量纲化后已相互抵消。

### 物理量转换

任意公式中的物理量通过以下替换转化为无量纲量：

```
n → ñ n₀,   m → m̃ m₀,   q → q̃ q₀
B → b B₀,   E → e B₀,   4πJ → j J₀,   ct → t
```

代入等价关系后，所有基准未知量最终简化为 ρ₀ 和 d₀，不应残留其他额外因子。

**示例**：等离子体静止质量能密度与磁场能密度之比

```
U_B / (ρ_p c²) ≡ (B²/8π) / (n_p m_p c²)
                = (b / 2 ñ_p m̃_p) · (d₀/ρ₀)²
                = (b / 2 ñ_p m̃_p) · σ₀
```

其中 ñ_p = n_p/n₀，m̃_p = m_p/m₀，b = B/B₀。

---

## Ampere 内核归一化（关键！）

### Ampere 离散化公式

引擎的 Ampere 求解器使用以下离散化：

```
dE/dt = - (larmor0 / skindepth0²) × J_total
```

其中 `J_total = J_deposited + J_external`。

### 对外部电流的约束

因为 Ampere 内核前面有一个 `-larmor0/skindepth0²` 缩放因子，你在 ext_current 中返回的电流值进入引擎后会**自动乘以**这个因子。

**这意味着 ext_current 返回的值必须预先补偿**：

```
text_current_return_value = physical_current × (skindepth0² / larmor0)
```

### 对 InitFields 的约束

InitFields 定义的场值直接写入 EM 数组，**不走 Ampere 内核**。因此：

- **InitFields 返回的场值是 code normalized 单位**，直接写入即可，不需要额外考虑归一化系数
- 引擎内部已经通过 B0 = 1/larmor0 等关系处理了所有单位转换

---

## 单位域边界

Entity 的不同代码区域使用不同的单位约定：

| 代码区域 | 使用单位 | 含义 |
|----------|---------|------|
| InitPrtls | **物理单位** | 位置 = 全局物理坐标，速度 = local tetrad basis |
| CustomPostStep | **代码单位** | fields.em 中的值已经是归一化后的代码单位 |
| InitFields | **code normalized 单位** | 返回的 ex/bx 直接写入 EM 数组，无需额外系数 |
| ext_current | **代码单位（已补偿后）** | 返回的 jx 需包含 skindepth0²/larmor0 补偿 |
| Ampere 内核 | **代码单位** | 内部自动应用 larmor0/(ppc0·skindepth0²) 因子 |
| CustomFieldOutput | **代码单位** | 直接读 domain.fields.em |

---

## 完整推导链

以 axion-PIC 项目为例，展示为什么需要 `skindepth0²/larmor0` 补偿：

### 物理方程
```
dE/dt = -J_a - J_plasma
J_a = ε · ω · B · sin(kx - ωt)   (axion 贡献的电流)
```

### 数值离散化
```
E_new = E_old - Δt · (larmor0/skindepth0²) · J_total
```

### 要让 E 场变化匹配 traveling wave 解 dE/dt = -ε·ω·B·sin(kx-ωt)
```
J_ext = ε · ω · B · sin(kx-ωt) · (skindepth0² / larmor0)
       ^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^
       物理电流                    归一化补偿系数
```

### 验证公式
```
coef = skindepth0² / larmor0
```

---

## 代码示例

### InitFields 中的正确写法

```cpp
template <Dimension D>
struct InitFields {
    real_t larmor0, skindepth0;

    InitFields(real_t l0, real_t s0) : larmor0(l0), skindepth0(s0) {}

    // 场值直接返回（code normalized 单位）
    Inline auto bx1(const coord_t<D>&) const -> real_t {
        return B0_physical;
    }

    // 场值直接返回（code normalized 单位）
    Inline auto ex1(const coord_t<D>& x) const -> real_t {
        return -epsilon * B0_physical * math::cos(k * x[0]);
    }
};
```

### ext_current 中的正确写法

```cpp
struct ExtCurrent {
    real_t larmor0, skindepth0;
    real_t coeff;  // = skindepth0² / larmor0

    ExtCurrent(real_t l0, real_t s0)
        : larmor0(l0), skindepth0(s0), coeff(SQR(s0) / l0) {}

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        // 物理电流 × 补偿系数
        return coeff * epsilon * omega * B0 * math::sin(k * x[0] - omega * time);
    }
};
```

---

## 常见陷阱

1. **InitFields 中额外乘以/除以归一化系数** — 最隐蔽的 bug。InitFields 返回的场值是 code normalized 单位，直接写入即可。额外操作会导致场值数量级全部错误。表现为：B 场弱了 N 倍，所有物理结果不对
2. **ext_current 忘记乘以 skindepth0²/larmor0** — 电流强度不对，导致 dE/dt 数量级错误
3. **混淆物理单位和代码单位** — InitPrtls 中用了代码单位的值，或 CustomPostStep 中直接比较物理值
4. **larmor0 和 skindepth0 选择不合理** — 如 larmor0 太大导致 B0 太小，或 skindepth0 太小导致 n0 爆炸

### axion-PIC 的真实教训

在 axion-PIC 开发中，InitFields 最初错误地写了 `return -epsilon * B0 * cos(k*x) / larmor0`。这个 bug 被发现了是因为 vacuum 测试中 DivE 不为零。修正为直接返回 code normalized 值后 DivE 归零。同时 ext_current 保留了 `skindepth0²/larmor0` 补偿是正确的。
