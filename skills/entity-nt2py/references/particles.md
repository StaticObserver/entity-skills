# 粒子

每当读取、选取、绘制或导出粒子输出时使用本参考文档。在 nt2py v1.5.3
中，粒子不是 xarray 数据集，而是使用自定义的、由 Dask 支撑的
`ParticleDataset`，其 `.load()` 返回 pandas DataFrame。

## 目录

- 发现容器
- 加载前先选取
- 只加载需要的列
- 粒子 ID
- 内置粒子绘图
- 缺失的量
- 源码依据

## 发现容器

```python
particles = data.particles
if particles is None:
    raise ValueError("This output has no readable particles")

print(particles.species)
print(particles.steps)
print(particles.times)
print(particles.columns)
print(particles.selection)
```

`particles.nbytes` 不是廉价的元数据属性。它会为粒子索引计算 Dask
内存用量，并可能触及所有已选取的粒子输出。

不要使用 `data.particles.sp`；该属性不存在。物种通过 `.species` 列出，
通过 `.sel(sp=...)` 选取。

默认坐标和动量名称为：

| 坐标系 | 位置 | 动量/四速度 | 其他 |
|---|---|---|---|
| Cartesian | `x`, `y`, `z` | `ux`, `uy`, `uz` | `w`, `id`, `sp` |
| Spherical | `r`, `th`, `ph` | `ur`, `uth`, `uph` | `w`, `id`, `sp` |

只有实际存在于输出中的量才会出现在 `.columns` 中。

## 加载前先选取

`.sel()` 只支持物理时间 `t`、模拟步数 `st`、物种 `sp` 和粒子 ID
`id`：

```python
selected = (
    particles
    .sel(t=10.0, method="nearest")
    .sel(sp=[1, 2])
)
```

选择器可以是标量、列表、切片或二元组。`method="nearest"` 对物理时间
很有用；`st`、`sp` 和 `id` 始终是精确选取。

`.isel()` 只支持时间/步数轴：

```python
last = particles.isel(t=-1)
some_outputs = particles.isel(t=[0, 5, -1])
```

链式选取取交集。交集为空时得到的是空选取，而不是静默恢复全部粒子。

## 只加载需要的列

仅在归约了时间和物种之后再调用 `.load(cols=...)`：

```python
df = (
    particles
    .isel(t=-1)
    .sel(sp=1)
    .load(cols=["x", "ux", "w"])
)

print(df.columns)
```

返回的 DataFrame 还保留索引列 `id`、`sp`、`st` 和 `t`。传入 `cols`
会减少从磁盘读取的粒子数组；省略它则请求所有可用列。

### 空间过滤限制

粒子的 `.sel()` 不接受 `x`、`y`、`z`、`r`、`th` 或 `ph`。先归约
时间步、物种和列，再过滤加载后的 DataFrame：

```python
df = particles.isel(t=-1).sel(sp=1).load(cols=["x", "y", "ux"])
region = df[df["x"].between(-1.0, 1.0) & df["y"].between(-2.0, 2.0)]
```

这仍会读取每个已选取粒子的所请求列。对于非常大的转储，先收窄
输出时间步/物种，或使用原始读取器工作流；不要声称 nt2py 会对
空间坐标做谓词下推。

## 粒子 ID

nt2py 按如下方式构造 `id`：

- 如果某物种有 `pIDX` 和 `pRNK`，用 Cantor 配对将它们组合；
- 如果有 `pIDX` 但没有 rank，直接使用该索引；
- 如果没有跟踪索引，使用 `-100` 作为占位符。

因此，只有当 Entity 输出包含所需的跟踪量时，`id` 才是唯一的跟踪键。
在不同时间或不同运行之间比较 ID 之前，先检查输出配置。

## 内置粒子绘图

先选取，因为这两个方法内部都会调用 `.load()`。

```python
import numpy as np
import matplotlib.pyplot as plt

p = data.particles.isel(t=-1).sel(sp=1)
p.phase_plot(
    x_quantity=lambda df: df["x"].to_numpy(),
    y_quantity=lambda df: df["ux"].to_numpy(),
    xy_bins=(np.linspace(-5, 5, 101), np.linspace(-10, 10, 101)),
)
plt.savefig("phase-space.png", dpi=150, bbox_inches="tight")
plt.close()
```

`phase_plot()` 对 Cartesian 数据默认 `x/ux`，对球坐标数据默认 `r/ur`。
它返回 `pcolormesh` 集合。

```python
p = data.particles.isel(t=-1).sel(sp=[1, 2])
p.spectrum_plot(bins=np.logspace(0, 4, 101))
```

`spectrum_plot()` 的默认量是关于三个动量分量的内部函数。在未核对
分析约定之前，不要把它标注为某种特定的物理能量定义。当 Entity 已经
写入了预期的能谱时优先使用 `data.spectra`，或者传入显式的 `quantity`
函数。

## 缺失的量

不同的物种或时间步可能不包含每个量。nt2py 会在有效输出上构建列
清单，并按每个物种和每个步有条件地拼接存在的量。不要仅仅因为某列
出现在 `.columns` 中就假定它是完整的；在定量使用之前，加载有边界的
选取并验证行数、空值和预期的物种。

## 源码依据

- 粒子容器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/particles.py>
- 读取器粒子命名：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/readers/base.py>
