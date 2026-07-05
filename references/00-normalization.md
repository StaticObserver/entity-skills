# 00 — 归一化约定（Fiducial Units）

## 何时使用

**必读**。Entitiy 使用 fiducial 单位系统，所有物理量在代码中都以归一化形式表示。不掌握归一化约定会导致 InitFields（场初始化）和 ext_current（外部电流）的数值数量级错误，这是 PGen 开发中最常见也最隐蔽的 bug。

触发场景：任何需要写 InitFields、ext_current、或理解引擎内部数值行为时。

---

## Fiducial Units 全景

Entity 的内核（Ampere 求解器、pusher、沉积）使用以下 fiducial 单位进行归一化。TOML 的 `[scales]` section 允许用户覆盖默认值。

### 用户可设置的 Scales（TOML `[scales]`）

| Scale | 含义 | 默认值 | 推导关系 |
|-------|------|--------|---------|
| `larmor0` | Fiducial Larmor 半径 | 1.0 | B0 = 1 / larmor0 |
| `skindepth0` | Fiducial 等离子体趋肤深度 | 1.0 | n0 = 1 / (larmor0 · skindepth0²) |
| `n0` | Fiducial 数密度 | 从 larmor0, skindepth0 推导 | 见上 |
| `B0` | Fiducial 磁场强度 | **引擎内置 = 1/larmor0** | 不可单独设置 |
| `q0` | Fiducial 元电荷 | 1.0 | — |
| `sigma0` | Fiducial 磁化参数 | B0² / n0 | — |
| `omegaB0` | Fiducial 回旋频率 | q0 · B0 / m0 | m0 由 species mass 决定 |
| `V0` | Fiducial 元体积 | — | 由 dx0 推导 |
| `dx0` | Fiducial 最小网格间距 | — | 由 grid 推导 |

### 用户不能改变的关键关系

```
B0 = 1 / larmor0          ← 引擎内置，不可绕过
n0 = 1 / (larmor0 · skindepth0²)
```

这意味着：一旦用户设置了 `larmor0` 和 `skindepth0`，B0 和 n0 就被锁定了。

---

## Ampere 内核归一化（关键！）

### Ampere 离散化公式

引擎的 Ampere 求解器使用以下离散化：

```
dE/dt = - (larmor0 / (ppc0 · skindepth0²)) × J_total
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

- **InitFields 中的 E/B 场值直接设置，不除以 larmor0**
- 引擎内部已经通过 B0 = 1/larmor0 处理了磁场的归一化

---

## 单位域边界

Entity 的不同代码区域使用不同的单位约定：

| 代码区域 | 使用单位 | 含义 |
|----------|---------|------|
| InitPrtls | **物理单位** | 位置 = 全局物理坐标，速度 = local tetrad basis |
| CustomPostStep | **代码单位** | fields.em 中的值已经是归一化后的代码单位 |
| InitFields | **物理单位（tetrad）** | 返回的 ex/bx 是物理值 |
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
E_new = E_old - Δt · (larmor0/(ppc0·skindepth0²)) · J_total
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

    // 正确：B 场直接返回物理值
    Inline auto bx1(const coord_t<D>&) const -> real_t {
        return B0_physical;  // NOT / larmor0
    }

    // 正确：E 场直接返回物理值（tetrad basis）
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

1. **InitFields 中除以 larmor0** — 最隐蔽的 bug。场值数量级全部错误，但代码不会报错。表现为：B 场弱了 larmor0 倍，所有物理结果不对
2. **ext_current 忘记乘以 skindepth0²/larmor0** — 电流强度不对，导致 dE/dt 数量级错误
3. **混淆物理单位和代码单位** — InitPrtls 中用了代码单位的值，或 CustomPostStep 中直接比较物理值
4. **larmor0 和 skindepth0 选择不合理** — 如 larmor0 太大导致 B0 太小，或 skindepth0 太小导致 n0 爆炸

### axion-PIC 的真实教训

在 axion-PIC 开发中，InitFields 最初错误地写了 `return -epsilon * B0 * cos(k*x) / larmor0`。这个 bug 被发现了是因为 vacuum 测试中 DivE 不为零。修正后移除了 `/larmor0`，DivE 归零。同时 ext_current 保留了 `skindepth0²/larmor0` 补偿是正确的。
