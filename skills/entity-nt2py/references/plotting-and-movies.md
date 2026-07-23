# 绘图与影片

当使用 nt2py 绘图访问器和动画导出时使用本参考文档。先按容器特有的
参考文档选取一个有边界的数据子集。

## 目录

- 标准 xarray 绘图
- 用 `inspect` 做场总览
- 球坐标与准球坐标绘图
- 单量影片
- 自定义影片
- 低层导出
- 源码依据

## 标准 xarray 绘图

场和能谱使用 xarray 绘图。绘图前先选取一个时间，并将空间数据归约到
一或两个维度：

```python
import matplotlib.pyplot as plt

q = data.fields["Bz"].isel(t=-1)
if "z" in q.dims:
    q = q.isel(z=0)
q.plot()
plt.savefig("Bz-last.png", dpi=150, bbox_inches="tight")
plt.close()
```

绘图会触发 Dask 计算。设置输出路径、关闭图形，并确认预期的文件
确实已创建。

## 用 `inspect` 做场总览

导入 `nt2` 会注册 `Dataset.inspect` 访问器。它接受时间选取后剩余
一或两个维度的数据：

```python
snapshot = data.fields.isel(t=-1)
if "z" in snapshot.dims:
    snapshot = snapshot.isel(z=0)

fig = snapshot.inspect.plot(only_fields=["E.*", "B.*"])
fig.savefig("field-overview.png", dpi=150, bbox_inches="tight")
plt.close(fig)
```

`only_fields` 和 `skip_fields` 是正则表达式列表，从每个变量名的开头
开始匹配。`only_fields` 优先。`plot_kwargs` 将场名正则映射到 xarray
绘图参数。

如果 `t` 仍是维度，`inspect.plot()` 会进入影片模式并要求提供
`name`：

```python
movie_data = data.fields[["Ex", "Bx"]]
if "z" in movie_data.dims:
    movie_data = movie_data.isel(z=0)
ok = movie_data.inspect.plot(
    name="field-overview",
    only_fields=["E.*", "B.*"],
    movie_kwargs={"num_cpus": 4},
)
```

静态图模式返回 Matplotlib `Figure`；影片模式返回 `True` 或 `False`。
去掉 `t` 后超过两个维度会报错。

## 球坐标与准球坐标绘图

`DataArray.polar` 访问器要求恰好两个维度 `r` 和 `th`，且没有时间
维度：

```python
q = data.fields["Br"].isel(t=-1)
im = q.polar.pcolor(cmap="RdBu_r")
plt.savefig("Br-polar.png", dpi=150, bbox_inches="tight")
plt.close()
```

该访问器绘制在直线笛卡尔坐标轴上。常用选项包括 `invert_x`、
`invert_y`、`cbar_position`、`cbar_size`、`title` 和 `label`。
`polar.contour()` 有相同的维度要求。

对于场线，在时间选取后的球坐标数据集上操作：

```python
snapshot = data.fields.isel(t=-1)
snapshot.polar.fieldplot(
    "Br",
    "Bth",
    sample={"template": "dipole", "radius": 2.0, "nth": 24},
)
```

支持的采样模板是 `dipole` 和 `monopole`。场线积分是绘图工具，
不是经过精度认证的物理积分器。

## 单量影片

随时间变化的 `DataArray` 具有 `.movie` 访问器：

```python
q = data.fields["Bz"]
if "z" in q.dims:
    q = q.isel(z=0)
ok = q.movie.plot(
    name="Bz-evolution",
    movie_kwargs={"num_cpus": 4, "framerate": 20},
    cmap="RdBu_r",
)
```

它要求存在 `t` 维度。帧按时间位置索引，而不是作为物理时间值传给
xarray 绘图调用。

## 自定义影片

`Data.makeMovie` 会把物理时间值和 `Data` 对象都传给回调：

```python
def plot_frame(t, data):
    data.fields["Ex"].sel(t=t, method="nearest").plot()

ok = data.makeMovie(
    plot_frame,
    time=list(data.fields.t.values),
    num_cpus=4,
    framerate=20,
)
```

在 v1.5.3 中，当 `data.attrs["simulation.name"]` 存在时，
`Data.makeMovie` 使用该属性作为输出名。当该属性缺失时，它消费
`name=`，否则默认为 `movie`。不要在不先检查该属性的情况下传
`name=`：在属性存在的分支中，v1.5.3 会把该关键字留在
`movie_kwargs` 里，导致 `name` 参数重复。当需要独立控制文件名时，
使用低层导出函数。

## 低层导出

```python
from nt2.plotters.export import makeFrames, makeMovie, makeFramesAndMovie
```

- `makeFrames(plot, times, fpath, data=None, num_cpus=None)` 写出编号的 PNG。
- `makeMovie(input=..., output=..., ...)` 调用外部 `ffmpeg`。
- `makeFramesAndMovie(name=..., plot=..., times=..., ...)` 执行两个阶段。

默认工作进程数是检测到的全部 CPU。在登录节点或共享机器上显式设置
`num_cpus`。组合导出将帧写到 `<name>/frames/` 下，默认输出
`<name>.mp4`。检查布尔返回值和输出文件；帧阶段成功并不保证 ffmpeg
成功。

## 源码依据

- Inspect 访问器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/inspect.py>
- Polar 访问器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/polar.py>
- Movie 访问器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/movie.py>
- 导出函数：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/export.py>
