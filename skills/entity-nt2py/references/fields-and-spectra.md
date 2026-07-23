# 场与能谱

当进行惰性场操作、派生场量和预计算能谱相关工作时使用本参考文档。
在 nt2py v1.5.3 中，两个容器都是由 Dask 数组支撑的 `xarray.Dataset`
对象。

## 目录

- 场数据模型与重映射
- 惰性选取
- 派生量
- 能谱数据模型
- 安全绘图示例
- 源码依据

## 场数据模型

`data.fields` 以物理时间作为维度 `t`，空间维度由坐标系决定，
模拟步数 `s` 是沿 `t` 的一个坐标。

```python
fields = data.fields
print(dict(fields.sizes))
print(list(fields.data_vars))
print(fields.coords)
print(fields.attrs)
```

典型维度为：

```text
Cartesian: (t, x), (t, y, x), or (t, z, y, x)
Spherical: (t, r), (t, th, r), or (t, ph, th, r)
```

使用实际的 `fields.dims` 和 `fields.data_vars`；不要从 PGen 名称推断
维度或可用的量。

### 名称重映射

默认重映射去掉前导 `f` 并转换分量索引：

| 原始 Entity 名称 | Cartesian | Spherical/qspherical |
|---|---|---|
| `fE1`, `fE2`, `fE3` | `Ex`, `Ey`, `Ez` | `Er`, `Eth`, `Eph` |
| `fB1`, `fB2`, `fB3` | `Bx`, `By`, `Bz` | `Br`, `Bth`, `Bph` |
| `fT01_2` | `Ttx_2` | `Ttr_2` |

坐标名从 `X1/X2/X3` 映射为 `x/y/z` 或 `r/th/ph`。单元边坐标
以 `<coord>_min` 和 `<coord>_max` 的形式暴露。

## 惰性选取

构造和选取 fields 数据集不会加载场数组。绘图、`.values`、`.load()`
和 `.compute()` 才会触发读取。

```python
# Select physical time, then reduce space before computing.
snapshot = data.fields.sel(t=10.0, method="nearest")
plane = snapshot["Bz"].isel(z=0) if "z" in snapshot.dims else snapshot["Bz"]
subset = plane.sel(x=slice(-5.0, 5.0)) if "x" in plane.dims else plane
array = subset.values
```

用 `.isel(t=-1)` 取最后一个输出索引。用 `.sel(t=..., method="nearest")`
按物理时间选取。步数是坐标 `s`，不是单独的维度；映射模拟步数时，
按时间索引选取或检查 `data.fields.s`。

在大型运行上避免以下模式：

```python
data.fields.values          # Dataset has no single safe bulk array
data.fields.compute()       # reads every field and timestep
data.fields.Bz.mean("t")    # still lazy, but plotting it reads all timesteps
```

仅当有意做全时域归约时，最后一个表达式才是合理的。

## 派生量

让算术运算保持在 xarray 中，使选取保持可组合并由 Dask 支撑：

```python
f = data.fields
if {"Ex", "Ey", "Ez", "Bx", "By", "Bz"} <= set(f.data_vars):
    e_dot_b = f.Ex * f.Bx + f.Ey * f.By + f.Ez * f.Bz
    view = e_dot_b.isel(t=-1)
```

对于球坐标输出，使用 `Er/Eth/Eph` 和 `Br/Bth/Bph`。绘图之前先选取
一个时间，并归约到一两个空间维度。

## 能谱数据模型

`data.spectra` 同样是惰性的，但物种由数据变量名表示，而不是 `sp`
维度。典型结构：

```text
dimensions: t, E
coordinates: t, E, s
data variables: N_1, N_2, N_3, ...
```

先检查变量，再显式选取一个：

```python
if data.spectra_defined:
    print(list(data.spectra.data_vars))
    spectrum = data.spectra["N_1"].isel(t=-1)
    spectrum.sel(E=slice(1.0, 100.0)).plot()
```

不要写 `data.spectra.sel(sp=1)`：v1.5.3 没有 `sp` 坐标。以 `sN`
开头的原始变量会被包含进来，并去掉前导 `s`；例如 `sN_1` 变为 `N_1`。

能量坐标由原始的 `sEbn` 分箱边界构建。当间距看似线性时，nt2py 使用
算术分箱中心，否则使用几何中心。将 `E` 视为输出提供的坐标；仅当
模拟契约给出时，才施加物理解释或归一化。

## 安全绘图示例

```python
from pathlib import Path
import matplotlib.pyplot as plt

out = Path("analysis/figures")
out.mkdir(parents=True, exist_ok=True)

quantity = data.fields["Bz"].isel(t=-1)
while quantity.ndim > 2:
    quantity = quantity.isel({quantity.dims[0]: 0})

quantity.plot()
plt.savefig(out / "Bz-last.png", dpi=150, bbox_inches="tight")
plt.close()
```

在真实分析中，优先显式选择维度，而不是这种通用的 `while` 归约；
该循环只是编写盘点工具时的防御性示例。

## 源码依据

- 场容器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/fields.py>
- 能谱容器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/spectra.py>
- 默认重映射：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/data.py>
