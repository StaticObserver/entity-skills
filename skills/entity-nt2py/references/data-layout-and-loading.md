# 数据布局与加载

每当用 nt2py 打开 Entity 输出时使用本参考文档。它描述文件系统契约，
以及在加载数组之前可以检查的状态。

本参考文档以 **nt2py v1.5.3**（`403437a`）为目标。在依赖版本特定行为
之前，先核对已安装的版本：

```python
import nt2

print(nt2.__version__)
```

## 目录

- 安装
- 数据根目录契约
- 分析前先检查
- 运行时诊断
- 初始化检查与失败
- 源码依据

## 安装

nt2py v1.5.3 要求 Python 3.8 或更高版本。BP5 支持默认安装；
HDF5 支持需要可选的 `h5py` 依赖。

```bash
python3 -m pip install "nt2py==1.5.3"
python3 -m pip install "nt2py[hdf5]==1.5.3"  # when reading HDF5 output
```

制作影片额外需要外部 `ffmpeg` 可执行文件。加载数据或绘制静态图
不需要它。

## 数据根目录契约

传入直接包含各类别目录的那个目录，而不是其上层的运行目录：

```text
<data-root>/
├── fields/
│   └── fields.00000001.bp  # or .h5
├── particles/
│   └── particles.00000001.bp
├── spectra/
│   └── spectra.00000001.bp
└── simulation.out          # optional runtime diagnostics
```

类别文件必须匹配 `<category>.<8-digit-step>.bp|h5`。某个类别可以缺失，
但至少需要一个可读的 `fields`、`particles` 或 `spectra` 类别来确定格式。

```python
from pathlib import Path
import nt2

data_root = Path("/path/to/run/data")
data = nt2.Data(str(data_root))
```

`nt2.Data` 自动检测 BP5 与 HDF5，并读取 `Coordinates` 属性。
`cart` 对应 Cartesian；`sph` 和 `qsph` 对应 Spherical。其他坐标系
会被拒绝。

## 分析前先检查

在选取量之前，先使用元数据和容器状态：

```python
print(data.coordinate_system.value)
print(data.attrs)

print(data.fields_defined)
print(data.particles_defined)
print(data.spectra_defined)
```

`print(data)` 或 `data.to_str()` 提供有用的完整盘点，但它不是免费的
元数据操作：报告粒子大小会调用 `.nbytes`，它会在所有有效粒子输出上
计算 Dask 粒子索引。在大型运行上，先检查上面的显式属性，仅当可以接受
该扫描时才打印完整对象。在 v1.5.3 中，`to_str()` 计算 `dt` 时还假定
至少有两个场或能谱输出；对于只有一个步长的已定义 fields/spectra 容器，
它会抛出 `IndexError`。此类运行请使用显式属性。

容器状态如下：

- `data.fields`：一个 `xarray.Dataset`；未定义场时为空。
- `data.particles`：一个 `ParticleDataset`；未定义粒子时为 `None`。
- `data.spectra`：一个 `xarray.Dataset`；未定义能谱时为空。
- `data.diagnostics`：从 `.out` 解析的 `pandas.DataFrame`，或 `None`。

使用容器特有的发现 API，而不要臆测变量名：

```python
if data.fields_defined:
    print(dict(data.fields.sizes))
    print(list(data.fields.data_vars))
    print(data.fields.coords)

if data.particles_defined and data.particles is not None:
    print(data.particles.species)
    print(data.particles.times)
    print(data.particles.columns)

if data.spectra_defined:
    print(dict(data.spectra.sizes))
    print(list(data.spectra.data_vars))
```

不存在 `data.particles.sp` 坐标。用 `data.particles.species` 列出物种，
用 `.sel(sp=...)` 选取它们。

避免把 `data.particles.nbytes` 当作廉价的发现调用：它会为粒子索引计算
Dask 内存用量。

## 运行时诊断

`data.diagnostics` **不**读取 Entity CSV 统计文件。它扫描数据根目录中的
`.out` 文件，并解析文件系统返回的第一个文件。解析器提取步数、物理时间、
子步计时、物种计数，以及可选的物种最小值/最大值。

将其视为可选的运行时信息：

```python
diag = data.diagnostics
if diag is not None:
    print(diag.columns)
    print(diag[["Step", "Time"]].head())
```

不要用该属性作为能量守恒或其他物理统计的证明。当分析明确需要时，
用 pandas 单独读取单独生成的 CSV 文件。

## 初始化检查与失败

初始化不只是打开一个目录。对于场，nt2py 会验证所有可读时间步具有
相同的变量名、形状和内存布局。它还会读取坐标、边坐标、时间、步数
和属性。

直接排查以下常见失败：

- `Could not determine file format`：数据根目录错误或文件名不符合约定。
- HDF5 `ImportError`：在当前 Python 环境中安装 `nt2py[hdf5]`。
- 缺少 `Coordinates`：输出元数据不完整或不兼容。
- `No valid steps found`：类别存在，但不含可读的输出。
- 名称/形状/布局不一致：混入了来自不兼容运行的输出。
- 关于不可读文件的警告：确认部分输出是否可接受。

## 源码依据

- 发布版本：<https://github.com/entity-toolkit/nt2py/releases/tag/v1.5.3>
- 软件包元数据：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/pyproject.toml>
- 数据容器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/data.py>
- 格式检测：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/utils.py>
- 诊断解析器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/diagnostics.py>
