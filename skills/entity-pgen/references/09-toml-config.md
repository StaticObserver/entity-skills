# 09 — TOML 配置参考

> 基于 Entity v1.4.4

## 何时使用

**必读内容**。每个 PGen 都需要一个配套的 TOML 文件。本参考涵盖 Entity 支持的所有 TOML 节区与参数。

适用于：创建新的 TOML、验证现有 TOML 的正确性、理解 TOML 参数如何映射到 C++ 代码。

---

## TOML 语法约定

Entity 使用标准 TOML v1.0 格式，并遵循以下约定：

| 约定 | 说明 |
|------------|-------------|
| 字符串值使用 **PascalCase** | `"SRPIC"` 而非 `"srpic"`，`"Minkowski"`、`"PERIODIC"`、`"Boris"` |
| bool 值使用**小写** | `true` / `false`（TOML 标准） |
| 数组 | 方括号：`resolution = [256, 256]` |
| 数组的数组 | `extent = [[0.0, 10.0], [0.0, 10.0]]`（二维需要 2 对内层方括号） |
| 嵌套表 | `[grid.metric]` 或扁平化的 `[grid]` + 缩进的 `metric = "..."` —— 两种写法均可 |
| 表数组 | `[[particles.species]]`（双方括号），用于可重复的节区 |

---

## 必需节区

### `[simulation]`

| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `name` | string | 输出文件名前缀 | **必需** |
| `engine` | string | `"SRPIC"` 或 `"GRPIC"` | **必需** |
| `runtime` | float (>0) | 最大运行时长（代码单位） | **必需** |
| `number` | int | MPI 域的数量 | `1`（无 MPI）；`MPI_SIZE`（MPI） |
| `decomposition` | array<int> (1-3) | MPI 分解；`-1` = 自动 | `[-1, -1, -1]` |

### `[grid]`

| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `resolution` | array<uint> (1-3) | 每个维度的网格分辨率 | **必需** |
| `extent` | array<[float,float]> (1-3) | 每个维度的物理范围 [min, max] | **必需** |
| `dim` | short (1,2,3) | 维度数 | 从 resolution 推断 |

### `[grid.metric]`

| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `metric` | string | 参见 Metrics 枚举表 | — |
| `coord` | string | `"cartesian"`, `"spherical"`, `"qspherical"` | — |

#### Spherical 坐标专用
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `qsph_r0` | float | QSpherical 的 r0（负值 → 接近均匀网格） | `0.0` |
| `qsph_h` | float (-1→1) | 角坐标映射参数 | `0.0` |

#### Kerr-Schild 专用（GRPIC）
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `ks_a` | float (0→1) | 黑洞自旋参数 | `0.0` |
| `ks_rh` | float | 视界半径 | 自动推断 |

### `[particles]`

| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `ppc0` | float (>0) | 基准每格粒子数 | **必需** |
| `nspec` | uint | 粒子种类数 | **必需** |
| `use_weights` | bool | 使用粒子权重（当 PGen 包含注入时必须为 true） | `false` |
| `clear_interval` | uint | 死亡粒子清理间隔（步数） | `100` |
| `spatial_sorting_interval` | uint | 空间排序间隔 | `0`（禁用） |

### `[[particles.species]]`（表数组 —— 每个粒子种类一个）

| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `label` | string | 粒子种类标签 | `"s<INDEX>"` |
| `mass` | float (>=0) | 质量（基准单位 m0） | **必需** |
| `charge` | float | 电荷（基准单位 q0） | **必需** |
| `maxnpart` | uint (>0) | 每个 MPI 任务的最大粒子数 | **必需** |
| `pusher` | string | `"Boris"`, `"Vay"`, `"Boris,GCA"`, `"Vay,GCA"`, `"Photon"`, `"None"` | 有质量：Boris，无质量：Photon |
| `n_payloads_real` | ushort | 额外的实数型 payload 槽位 | `0` |
| `n_payloads_int` | ushort | 额外的整数型 payload 槽位 | `0` |
| `tracking` | bool | 启用粒子追踪（需要编译时设置 TRACKING=ON） | `false` |
| `radiative_drag` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |
| `emission` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |

---

## 常用可选节区

### `[scales]`

**参见 `00-normalization.md`**。

| 参数 | 类型 | 说明 |
|-----------|------|-------------|
| `larmor0` | float | 基准 Larmor 半径（B0 = 1/larmor0） |
| `skindepth0` | float | 基准趋肤深度（n0 = 1/(larmor0·skindepth0²)） |
| `n0` | float | 基准数密度 |
| `B0` | float | 基准磁场（引擎内置 = 1/larmor0） |
| `sigma0` | float | 基准磁化参数 |
| `omegaB0` | float | 基准回旋频率 |

### `[boundaries]`

| 参数 | 类型 | 说明 |
|-----------|------|-------------|
| `fields` | array<string> (1-3) | 每个维度的场边界条件：`"PERIODIC"`, `"MATCH"`, `"FIXED"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"HORIZON"`, `"CONDUCTOR"` |
| `particles` | array<string> (1-3) | 每个维度的粒子边界条件：`"PERIODIC"`, `"ABSORB"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"REFLECT"`, `"HORIZON"` |

**简写语法**：
```toml
# Same BC for all dimensions
boundaries = { fields = ["PERIODIC"], particles = ["PERIODIC"] }

# 2D per-dimension specification
[boundaries]
  fields = [["PERIODIC"], ["PERIODIC"]]
  particles = [["PERIODIC"], ["PERIODIC"]]
```

**配对约束**：`CONDUCTOR` 场边界条件必须与 `REFLECT` 粒子边界条件配对。`HORIZON` 仅在 GR 中有效。

#### `[boundaries.match]` / `[boundaries.absorb]` / `[boundaries.atmosphere]`
参见 `06-boundary.md`。

### `[algorithms]`

| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `current_filters` | ushort | 电流平滑次数（需要电荷守恒时设为 0） | `0` |

#### `[algorithms.timestep]`
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `CFL` | float (0→1) | CFL 数 | `0.95` |
| `correction` | float | 光速修正因子 | `1.0` |
| `dt` | float | 固定时间步长 | 从 CFL 推断 |

#### `[algorithms.deposit]`
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `enable` | bool | 启用电流沉积 | `true` |
| `order` | ushort (0→10) | 粒子形状函数阶数 | — |

#### `[algorithms.fieldsolver]`
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `enable` | bool | 启用电场求解器 | `true` |
| `delta_x/y/z` | float | 高阶模板系数（二阶） | `0.0` |
| `beta_xy/yx/xz/zx/yz/zy` | float | 非对角修正系数 | `0.0` |

#### `[algorithms.gr]`（仅 GRPIC）
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `pusher_eps` | float (>0) | 数值微分步长 | `1e-6` |
| `pusher_niter` | ushort (>0) | Newton-Raphson 迭代次数 | `10` |

#### `[algorithms.gca]`（Guiding Center）
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `e_ovr_b_max` | float (0→1) | GCA 有效性的最大 E/B | `0.9` |
| `larmor_max` | float | GCA 的最大 Larmor 半径 | `0.0` |

### `[setup]` —— PGen 专用参数

**这是 PGen 开发的核心节区**。所有自定义参数都在这里定义：

```toml
[setup]
  temperature = 0.01
  drift_ux = 0.1
  Bmag = 1.0
  Btheta = 0.0
  filling_fraction = 0.5
  injection_frequency = 100
```

在 pgen.hpp 中通过 `params.template get<T>("setup.key")` 读取。参数类型可以是 `real_t`、`int`、`std::string`、`std::vector<real_t>`。

### `[output]`

| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `format` | string | `"disabled"`, `"hdf5"`, `"BPFile"` | `"hdf5"` |
| `interval` | uint (>0) | 输出间隔（步数） | `1` |
| `interval_time` | float | 输出间隔（时间），-1 表示禁用 | `-1.0` |
| `separate_files` | bool | 每个时间步单独一个文件 | `true` |

#### `[output.fields]`
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `enable` | bool | | `true` |
| `quantities` | array<string> | `"E"`, `"B"`, `"J"`, `"divE"`, `"Rho"`, `"Charge"`, `"N"`, `"Nppc"`, `"T0i"`, `"Tij"`, `"Vi"`, `"D"`, `"H"`, `"divD"`, `"A"` | `[]` |
| `custom` | array<string> | 自定义场量（参见 07-custom-output.md） | `[]` |
| `mom_smooth` | ushort | 矩平滑窗口 | `0` |
| `interval` / `interval_time` | | 覆盖全局设置 | |
| `downsampling` | array<uint> (1-3) | 降采样 | `[1,1,1]` |

#### `[output.particles]`
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `enable` | bool | | `true` |
| `species` | array<int> | 要输出的粒子种类（空 = 全部） | `[]` |
| `stride` | uint (>1) | 每 N 个粒子输出 1 个 | `100` |

#### `[output.spectra]`
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `enable` | bool | | `true` |
| `e_min` / `e_max` | float | 能量范围 | `1e-3` / `1e3` |
| `log_bins` | bool | 对数分箱 | `true` |
| `n_bins` | uint | 分箱数量 | `200` |

#### `[output.stats]`
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `enable` | bool | | `true` |
| `interval` | uint | 统计输出间隔 | `100` |
| `quantities` | array<string> | `"B^2"`, `"E^2"`, `"T00"` 等 | `["B^2","E^2","T00"]` |
| `custom` | array<string> | 自定义统计量（参见 07-custom-output.md） | `[]` |

#### `[output.checkpoint]`
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `interval` | uint | checkpoint 间隔 | `1000` |
| `keep` | int | 保留数量（0=关闭，-1=不限） | `2` |
| `walltime` | string | 超时前强制写 checkpoint（`"HH:MM:SS"`） | `"00:00:00"` |
| `write_path` / `read_path` | string | checkpoint 路径 | |
| `is_resuming` | bool | 从 checkpoint 恢复 | 自动推断 |

#### `[output.debug]`
| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `as_is` | bool | 不做转换直接输出原始场 | `false` |
| `ghosts` | bool | 包含 ghost 单元 | `false` |

### `[diagnostics]`

| 参数 | 类型 | 说明 | 默认值 |
|-----------|------|-------------|---------|
| `interval` | int (>0) | 日志记录间隔 | `1` |
| `blocking_timers` | bool | 分阶段的阻塞式计时器 | `false` |
| `colored_stdout` | bool | 彩色输出 | `true` |
| `log_level` | string | `"VERBOSE"`, `"WARNING"`, `"ERROR"` | `"VERBOSE"` |

### `[radiation]`（如需要）

完整的辐射参数（drag 和 emission）参见 `input.example.toml`。

---

## 最小可用 TOML 骨架

```toml
[simulation]
  name     = "my_run"
  engine   = "SRPIC"
  runtime  = 100.0

[grid]
  resolution = [256, 256]
  extent     = [[-10.0, 10.0], [-10.0, 10.0]]

  [grid.metric]
    metric = "Minkowski"
    coord  = "cartesian"

[boundaries]
  fields     = [["PERIODIC"], ["PERIODIC"]]
  particles  = [["PERIODIC"], ["PERIODIC"]]

[scales]
  larmor0     = 1.0
  skindepth0  = 1.0

[algorithms]
  current_filters = 0

  [algorithms.timestep]
    CFL = 0.45

[particles]
  ppc0  = 32.0
  nspec = 2

  [[particles.species]]
    label    = "electrons"
    mass     = 1.0
    charge   = -1.0
    maxnpart = 5e6

  [[particles.species]]
    label    = "positrons"
    mass     = 1.0
    charge   = 1.0
    maxnpart = 5e6

[output]
  format        = "BPFile"
  interval_time = 10.0

  [output.fields]
    quantities = ["E", "B", "Rho"]

[diagnostics]
  log_level = "VERBOSE"
```

---

## 常见陷阱

1. **数组的数组嵌套错误** —— 二维边界条件需要 `[["PERIODIC"], ["PERIODIC"]]`，而不是 `["PERIODIC", "PERIODIC"]`
2. **布尔值首字母大写** —— `True` / `False` 不是合法的 TOML
3. **PascalCase 写成了小写** —— `engine = "srpic"` 无法被识别
4. **粒子种类标签与 PGen 代码不匹配** —— PGen 使用从 1 开始的索引进行注入，但 TOML 中的顺序不同
5. **忘记设置 use_weights = true** —— 包含粒子注入的 PGen 必须设置此项，否则权重逻辑会出错
6. **[setup] 参数名打错** —— TOML 中的键与 `params.get()` 必须逐字符完全一致
