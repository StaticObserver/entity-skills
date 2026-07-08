# 09 — TOML 配置参考

> 基于 Entity v1.4.4

## 何时使用

**必读**。每一个 PGen 都需要一个匹配的 TOML 文件。这份参考覆盖 Entity 支持的所有 TOML section 和参数。

用于：新建 TOML、验证已有 TOML 的正确性、理解 TOML 参数如何映射到 C++ 代码。

---

## TOML 语法约定

Entity 使用标准 TOML v1.0 格式，但有以下约定：

| 约定 | 说明 |
|------|------|
| 字符串值 **PascalCase** | `"SRPIC"` 而非 `"srpic"`, `"Minkowski"`, `"PERIODIC"`, `"Boris"` |
| bool 值 **小写** | `true` / `false`（TOML 标准） |
| 数组 | 方括号：`resolution = [256, 256]` |
| 数组 of 数组 | `extent = [[0.0, 10.0], [0.0, 10.0]]`（2D 需要 2 对内括号） |
| 嵌套表 | `[grid.metric]` 或平铺 `[grid]` + 缩进 `metric = "..."` 两种写法都行 |
| Array of Tables | `[[particles.species]]`（两对方括号）用于重复 section |

---

## 必选 Section

### `[simulation]`

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `name` | string | 输出文件名前缀 | **必选** |
| `engine` | string | `"SRPIC"` 或 `"GRPIC"` | **必选** |
| `runtime` | float (>0) | 最大运行时间（代码单位） | **必选** |
| `number` | int | MPI domain 数量 | `1`（无 MPI）; `MPI_SIZE`（MPI） |
| `decomposition` | array<int> (1-3) | MPI 分解; `-1` = auto | `[-1, -1, -1]` |

### `[grid]`

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `resolution` | array<uint> (1-3) | 每维网格分辨率 | **必选** |
| `extent` | array<[float,float]> (1-3) | 每维物理范围 [min, max] | **必选** |
| `dim` | short (1,2,3) | 维数 | 从 resolution 推断 |

### `[grid.metric]`

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `metric` | string | 见 Metrics 枚举表 | — |
| `coord` | string | `"cartesian"`, `"spherical"`, `"qspherical"` | — |

#### 球坐标专用
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `qsph_r0` | float | QSpherical 的 r0（负值 → 近均匀网格） | `0.0` |
| `qsph_h` | float (-1→1) | 角坐标映射参数 | `0.0` |

#### Kerr-Schild 专用 (GRPIC)
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `ks_a` | float (0→1) | 黑洞自旋参数 | `0.0` |
| `ks_rh` | float | 视界半径 | 推断 |

### `[particles]`

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `ppc0` | float (>0) | Fiducial 每网格粒子数 | **必选** |
| `nspec` | uint | 物种数量 | **必选** |
| `use_weights` | bool | 使用粒子权重（PGen 有注入时必设为 true） | `false` |
| `clear_interval` | uint | 死粒子清理间隔（步数） | `100` |
| `spatial_sorting_interval` | uint | 空间排序间隔 | `0`（禁用） |

### `[[particles.species]]`（Array of Tables — 每个物种一个）

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `label` | string | 物种标签 | `"s<INDEX>"` |
| `mass` | float (>=0) | 质量（fiducial 单位，m0） | **必选** |
| `charge` | float | 电荷（fiducial 单位，q0） | **必选** |
| `maxnpart` | uint (>0) | 每个 MPI task 最大粒子数 | **必选** |
| `pusher` | string | `"Boris"`, `"Vay"`, `"Boris,GCA"`, `"Vay,GCA"`, `"Photon"`, `"None"` | 有质量: Boris，无质量: Photon |
| `n_payloads_real` | ushort | 额外实值 payload | `0` |
| `n_payloads_int` | ushort | 额外整值 payload | `0` |
| `tracking` | bool | 启用粒子追踪（需要编译期 TRACKING=ON） | `false` |
| `radiative_drag` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |
| `emission` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |

---

## 常用可选 Section

### `[scales]`

**参见 `00-normalization.md`**。

| 参数 | 类型 | 说明 |
|------|------|------|
| `larmor0` | float | Fiducial Larmor 半径（B0 = 1/larmor0） |
| `skindepth0` | float | Fiducial 趋肤深度（n0 = 1/(larmor0·skindepth0²)） |
| `n0` | float | Fiducial 数密度 |
| `B0` | float | Fiducial 磁场（引擎内置 = 1/larmor0） |
| `sigma0` | float | Fiducial 磁化参数 |
| `omegaB0` | float | Fiducial 回旋频率 |

### `[boundaries]`

| 参数 | 类型 | 说明 |
|------|------|------|
| `fields` | array<string> (1-3) | 每维场 BC: `"PERIODIC"`, `"MATCH"`, `"FIXED"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"HORIZON"`, `"CONDUCTOR"` |
| `particles` | array<string> (1-3) | 每维粒子 BC: `"PERIODIC"`, `"ABSORB"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"REFLECT"`, `"HORIZON"` |

**简化写法**：
```toml
# 所有维使用相同 BC
boundaries = { fields = ["PERIODIC"], particles = ["PERIODIC"] }

# 2D 逐维指定
[boundaries]
  fields = [["PERIODIC"], ["PERIODIC"]]
  particles = [["PERIODIC"], ["PERIODIC"]]
```

**配对约束**：`CONDUCTOR` 场 BC 必须与 `REFLECT` 粒子 BC 配对。`HORIZON` 只在 GR 中有效。

#### `[boundaries.match]` / `[boundaries.absorb]` / `[boundaries.atmosphere]`
参见 `06-boundary.md`。

### `[algorithms]`

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `current_filters` | ushort | 电流平滑遍数（电荷守恒需要时设 0） | `0` |

#### `[algorithms.timestep]`
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `CFL` | float (0→1) | CFL 数 | `0.95` |
| `correction` | float | 光速修正因子 | `1.0` |
| `dt` | float | 固定时间步长 | 从 CFL 推断 |

#### `[algorithms.deposit]`
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `enable` | bool | 启用电流沉积 | `true` |
| `order` | ushort (0→10) | 粒子形状函数阶数 | — |

#### `[algorithms.fieldsolver]`
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `enable` | bool | 启用电场求解器 | `true` |
| `delta_x/y/z` | float | 高阶模板系数（二阶） | `0.0` |
| `beta_xy/yx/xz/zx/yz/zy` | float | 非对角修正系数 | `0.0` |

#### `[algorithms.gr]`（仅 GRPIC）
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `pusher_eps` | float (>0) | 数值微分步长 | `1e-6` |
| `pusher_niter` | ushort (>0) | Newton-Raphson 迭代次数 | `10` |

#### `[algorithms.gca]`（Guiding Center）
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `e_ovr_b_max` | float (0→1) | GCA 有效性的最大 E/B | `0.9` |
| `larmor_max` | float | GCA 最大 Larmor 半径 | `0.0` |

### `[setup]` — PGen 专属参数

**这是 PGen 开发的核心 section**。所有自定义参数在此定义：

```toml
[setup]
  temperature = 0.01
  drift_ux = 0.1
  Bmag = 1.0
  Btheta = 0.0
  filling_fraction = 0.5
  injection_frequency = 100
```

在 pgen.hpp 中通过 `params.template get<T>("setup.key")` 读取。参数类型可以是 `real_t`, `int`, `std::string`, `std::vector<real_t>`。

### `[output]`

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `format` | string | `"disabled"`, `"hdf5"`, `"BPFile"` | `"hdf5"` |
| `interval` | uint (>0) | 输出间隔（步数） | `1` |
| `interval_time` | float | 输出间隔（时间），-1 禁用 | `-1.0` |
| `separate_files` | bool | 每个时间步单独文件 | `true` |

#### `[output.fields]`
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `enable` | bool | | `true` |
| `quantities` | array<string> | `"E"`, `"B"`, `"J"`, `"divE"`, `"Rho"`, `"Charge"`, `"N"`, `"Nppc"`, `"T0i"`, `"Tij"`, `"Vi"`, `"D"`, `"H"`, `"divD"`, `"A"` | `[]` |
| `custom` | array<string> | 自定义场量（见 07-custom-output.md） | `[]` |
| `mom_smooth` | ushort | 矩平滑窗口 | `0` |
| `interval` / `interval_time` | | 覆盖全局 | |
| `downsampling` | array<uint> (1-3) | 下采样 | `[1,1,1]` |

#### `[output.particles]`
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `enable` | bool | | `true` |
| `species` | array<int> | 输出的物种（空=全部） | `[]` |
| `stride` | uint (>1) | 每 N 个粒子输出 1 个 | `100` |

#### `[output.spectra]`
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `enable` | bool | | `true` |
| `e_min` / `e_max` | float | 能量范围 | `1e-3` / `1e3` |
| `log_bins` | bool | 对数分 bin | `true` |
| `n_bins` | uint | bin 数量 | `200` |

#### `[output.stats]`
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `enable` | bool | | `true` |
| `interval` | uint | 统计输出间隔 | `100` |
| `quantities` | array<string> | `"B^2"`, `"E^2"`, `"T00"` 等 | `["B^2","E^2","T00"]` |
| `custom` | array<string> | 自定义统计量（见 07-custom-output.md） | `[]` |

#### `[output.checkpoint]`
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `interval` | uint | checkpoint 间隔 | `1000` |
| `keep` | int | 保留几个（0=关，-1=无限） | `2` |
| `walltime` | string | 超时前强制 checkpoint（`"HH:MM:SS"`） | `"00:00:00"` |
| `write_path` / `read_path` | string | checkpoint 路径 | |
| `is_resuming` | bool | 从 checkpoint 恢复 | 推断 |

#### `[output.debug]`
| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `as_is` | bool | 输出未经转换的原始场 | `false` |
| `ghosts` | bool | 包含 ghost cells | `false` |

### `[diagnostics]`

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `interval` | int (>0) | 日志间隔 | `1` |
| `blocking_timers` | bool | 分阶段阻塞计时 | `false` |
| `colored_stdout` | bool | 彩色输出 | `true` |
| `log_level` | string | `"VERBOSE"`, `"WARNING"`, `"ERROR"` | `"VERBOSE"` |

### `[radiation]`（如需要）

参见 `input.example.toml` 中的完整辐射参数（drag 和 emission）。

---

## 最简可用 TOML 骨架

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

1. **数组 of 数组嵌套错误** — 2D boundary 需要 `[["PERIODIC"], ["PERIODIC"]]`，不是 `["PERIODIC", "PERIODIC"]`
2. **bool 大写** — `True` / `False` 不是合法 TOML
3. **PascalCase 写成了 lowercase** — `engine = "srpic"` 不被识别
4. **species label 和 PGen 代码不对应** — PGen 中用 1-based 索引注入但 TOML 顺序不同
5. **use_weights 忘了设为 true** — 有粒子注入的 PGen 必须设置，否则权重逻辑异常
6. **[setup] 参数名有 typo** — TOML 和 `params.get()` 中的 key 必须字符级匹配
