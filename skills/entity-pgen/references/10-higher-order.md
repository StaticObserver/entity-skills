# 10 — 高阶方法（场模板与粒子形状函数）

> 基于 Entity v1.4.4

## 何时使用

当用户需要以下能力时加载本参考：

- 自定义场求解器模板（stencil）以抑制 Cherenkov 不稳定性或数值色散
- 高于一阶的粒子形状函数以提高数值精度
- 降低数值加热，从而允许在更低分辨率下运行
- 配置 `[algorithms.fieldsolver]` 的非对角项（`beta_xy` 等）

**前置条件**：`09-toml-config.md` 中 `[algorithms.fieldsolver]` 与 `[algorithms.deposit]` 的参数表。

---

## 1. 广义场模板

### 背景

基于 Blinne 等人（2018）的工作，Entity 支持通过 `[algorithms.fieldsolver]` 中的 `delta` 和 `beta` 参数自定义 Maxwell 求解器的有限差分模板。这可以显著降低数值色散并抑制 Cherenkov 不稳定性。

关键头文件：`kernels/faraday_mink.hpp`

### 参数

所有参数都在 `[algorithms.fieldsolver]` 下配置（见 `09-toml-config.md` 中的列表）：

| 参数 | 说明 |
|-----------|-------------|
| `delta_x`、`delta_y`、`delta_z` | 对角方向的二阶偏移修正系数 |
| `beta_xy`、`beta_yx` | x-y 平面交叉项模板系数 |
| `beta_xz`、`beta_zx` | x-z 平面交叉项模板系数 |
| `beta_yz`、`beta_zy` | y-z 平面交叉项模板系数 |

### 关键约束

> **模板是针对特定 CFL 优化的；必须使用与该模板匹配的 CFL。**

论文（Blinne et al. 2018）的 CFL 使用归一化约定（Yee 极限为 1）。Entity 的
CFL 是标准约定——`dt = CFL * dx0`，其中 `dx0 = metric.dxMin()`（见
`src/framework/parameters/algorithms.cpp`）——因此换算需除以 √(N_dim)：
- **2D**：Entity CFL = 论文 CFL / √2
- **3D**：Entity CFL = 论文 CFL / √3

### 预定义模板

#### 2D 模板

| 求解器 | 优化目标 | 论文 CFL | Entity CFL | delta_x/y | beta_xy/yx |
|--------|--------------|-----------|------------|-----------|------------|
| Yee | — | 1.0 | 1/√2 ≈ 0.707 | 0.0 | 0.0 |
| Cowan | min1 | 0.99 | 0.99/√2 | -0.122 | 0.108 |
| Cowan | min2 | 0.985 | 0.985/√2 | -0.120 | 0.106 |
| Cowan | min3 | 0.97 | 0.97/√2 | -0.125 | 0.11 |
| Cowan | min4 | 0.975 | 0.975/√2 | -0.1252 | 0.110 |
| Cowan | min5 | 0.98 | 0.98/√2 | -0.1255 | 0.111 |
| Cowan | min6 | 0.98 | 0.98/√2 | -0.1228 | 0.108 |
| Lehe | min1 | 0.99 | 0.99/√2 | -0.117 | 0.1 |
| Lehe | min2 | 0.97 | 0.97/√2 | -0.124 | 0.11 |
| Lehe | min3 | 0.97 | 0.97/√2 | -0.118 | 0.101 |
| Lehe | min4 | 0.975 | 0.975/√2 | -0.120 | 0.104 |
| Lehe | min5 | 0.98 | 0.98/√2 | -0.121 | 0.106 |
| Lehe | min6 | 0.975 | 0.975/√2 | -0.118 | 0.102 |

**TOML 示例（2D Cowan min3）**：

```toml
[algorithms.fieldsolver]
  enable   = true
  delta_x  = -0.125
  delta_y  = -0.125
  beta_xy  = 0.11
  beta_yx  = 0.11

[algorithms.timestep]
  CFL = 0.686    # ≡ 0.97 / sqrt(2)
```

#### 3D 模板

| 求解器 | 优化目标 | 论文 CFL | Entity CFL | delta_x/y/z | beta_(all 6) |
|--------|--------------|-----------|------------|-------------|--------------|
| Yee | — | 1.0 | 1/√3 ≈ 0.577 | 0.0 | 0.0 |
| — | min1 | 0.5 | 0.5/√3 | -0.00867 | -0.00867 |
| — | min2 | 0.5 | 0.5/√3 | -0.00733 | -0.00867 |
| — | min3 | 0.5 | 0.5/√3 | -0.006 | -0.00667 |
| — | min4 | 0.1 | 0.1/√3 | -0.048434 | -0.048434 |

> 对于 3D 模板，delta_x = delta_y = delta_z，且全部 6 个 beta 参数相同。

### Yee（默认）模板

不设置任何 delta/beta 参数即得到标准 Yee 网格。`delta_x/y/z = 0`，`beta_* = 0`。

---

## 2. 高阶粒子形状函数

### 背景

在 Entity v1.3.0 之前，仅支持一阶粒子形状函数。现在通过 Esirkepov（2001）电流沉积方案支持 **1 至 11 阶**。

关键头文件：
- `kernels/particle_shapes.hpp`
- `kernels/current_deposit.hpp`
- `kernels/particle_pusher_sr.hpp`

### 构建配置

高阶形状函数是一个**编译期选项**，通过 CMake 参数启用：

```bash
cmake -B build \
  -D deposit=esirkepov \
  -D shape_order=<N>
```

- `<N>` = 1 到 11 的整数
- 必须指定 `deposit=esirkepov`（Esirkepov 方案，保证电荷守恒）

### 效果

- **数值加热显著降低**：在周期性边界条件的漂移等离子体测试中，高阶形状函数允许在远低于 Debye 长度的分辨率下运行，而不会出现失控的数值加热
- **精度提升**：电流沉积与粒子推进的数值精度得到提高

### 性能开销

| 维度 | 计算开销 |
|-----------|-------------------|
| 1D | **可忽略** |
| 2D | 中等 |
| 3D | **可能很大** |

### 重要说明

> **强烈建议在降低分辨率之前先进行收敛性测试。**

高阶形状函数不能替代正确的物理分辨率，它只是对数值方法的改进。

### 对应的 TOML 参数

`[algorithms.deposit]` 部分（定义见 `09-toml-config.md`）：

```toml
[algorithms.deposit]
  enable = true
  order  = 4   # Must match cmake -D shape_order=N
```

---

## 常见陷阱

1. **CFL 不匹配** — 直接使用论文中的模板值而未换算 CFL（忘记除以 √(N_dim)），导致 CFL 条件不匹配
2. **shape_order 与 TOML order 不一致** — CMake 的 `-D shape_order=N` 与 TOML 的 `algorithms.deposit.order` 必须一致
3. **忘记启用 esirkepov** — 高阶形状函数要求 `-D deposit=esirkepov`；默认的沉积方案无法使用
4. **盲目使用高阶形状函数** — 在 3D 中，11 阶形状函数的计算开销可能非常大；请先运行收敛性测试
5. **模板仅适用于 Minkowski** — 广义场模板目前仅在 Minkowski 度规下可用（见 `faraday_mink.hpp`）

---

## 与 PGen 开发的关系

高阶方法**主要在 TOML 配置层面设置**，不直接影响 PGen 代码。但以下场景需要注意：

| 场景 | PGen 注意事项 |
|----------|-------------------|
| 非零模板参数 | 不影响 PGen 代码；仅涉及 TOML 配置 |
| 高阶形状函数 | 不影响 PGen 代码；仅涉及构建选项 + TOML |
| CFL 调整 | TOML 的 `algorithms.timestep.CFL` 必须与模板匹配 |
| 降低分辨率 | PGen 中的物理场/粒子可能需要重新归一化 |
