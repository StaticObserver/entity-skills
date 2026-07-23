# CLI 与原始读取器

当需要快速命令行检查，或精确的原始数组读取比高层惰性容器更合适时，
使用本参考文档。

## 目录

- CLI 范围与选取语法
- 何时使用原始读取器
- 选择读取器
- 核心读取器工作流
- 读取器约束
- 源码依据

## v1.5.3 中的 CLI 范围

安装后的命令是 `nt2`：

```bash
nt2 version
nt2 show /path/to/data-root
nt2 plot /path/to/data-root --what fields --isel "t=0"
```

`nt2 show` 构造 `nt2.Data` 并打印其盘点。`nt2 plot` 目前只实现了
`--what fields`。虽然 `particles` 和 `spectra` 是可接受的选项名，
但这两条路径在 v1.5.3 中都会抛出 `NotImplementedError`。

### 选取语法

用分号分隔多个选择器：

```bash
nt2 plot /path/to/data-root \
  --what fields \
  --fields "E.*;B.*" \
  --sel "x=slice(-5.0, 5.0);y=0.0" \
  --isel "t=0;z=0"
```

CLI 将切片选择器与标量选择器分开处理。它先应用带 `method="nearest"`
的标量 `.sel`，然后是切片 `.sel`，最后是 `.isel`。`--fields` 条目是
供 `inspect` 访问器使用的正则表达式。

如果结果没有 `t` 维度，CLI 保存 `<data-root-basename>.png`。如果时间
仍然存在，它会以数据根目录的 basename 命名创建一个 inspect 影片。

选取解析器对每个参数值使用 Python `eval()`。只在可信的、手动控制的
命令行中使用它。绝不要把不可信的用户、文件、scheduler 或网络内容
插值进 `--sel` 或 `--isel`。

## 何时使用原始读取器

常规分析优先使用 `nt2.Data`，因为它提供坐标重映射、跨步检查、
Dask 支撑的场/能谱，以及粒子选取层。

在以下情况使用原始读取器：

- 检查精确的存储变量名或属性；
- 从一个输出步读取一个已知数组；
- 诊断高层容器构造失败；
- 在不构建完整数据集的情况下验证文件形状/布局；
- 实现一个有严格边界的自定义读取器工作流。

原始读取立即返回 NumPy 数组。它们不提供惰性加载或自动内存保护。

## 选择读取器

```python
from pathlib import Path
from nt2.readers.adios2 import Reader as BP5Reader
from nt2.readers.hdf5 import Reader as HDF5Reader

data_root = Path("/path/to/data-root")
reader = BP5Reader()  # choose HDF5Reader() for .h5 output
```

没有 `h5py` 也允许导入 `HDF5Reader`，但在安装 `nt2py[hdf5]` 之前，
打开 HDF5 文件会抛出 `ImportError`。

## 核心读取器工作流

```python
steps = reader.GetValidSteps(str(data_root), "fields")
if not steps:
    raise ValueError("No readable field steps")

step = steps[-1]
names = reader.ReadCategoryNamesAtTimestep(
    str(data_root), "fields", "f", step
)
name = sorted(names)[0]

attrs = reader.ReadAttrsAtTimestep(str(data_root), "fields", step)
shape = reader.ReadArrayShapeAtTimestep(
    str(data_root), "fields", name, step
)
array = reader.ReadArrayAtTimestep(
    str(data_root), "fields", name, step
)

print(step, name, shape, array.shape, attrs.get("Coordinates"))
```

主要的公共方法有：

| 方法 | 用途 |
|---|---|
| `GetValidSteps(path, category)` | 列出可读的步数编号 |
| `GetValidFiles(path, category)` | 列出可读的类别文件名 |
| `ReadAttrsAtTimestep(...)` | 读取文件级属性 |
| `ReadCategoryNamesAtTimestep(...)` | 列出匹配原始前缀的名称 |
| `ReadArrayAtTimestep(...)` | 立即读取一个数组 |
| `ReadArrayShapeAtTimestep(...)` | 读取存储的形状元数据 |
| `ReadFieldCoordsAtTimestep(...)` | 读取原始的 `X1/X2/X3` 中心 |
| `ReadEdgeCoordsAtTimestep(...)` | 读取原始边坐标 |
| `ReadFieldLayoutAtTimestep(...)` | 返回 `Layout.L` 或 `Layout.R` |
| `ReadPerTimestepVariable(...)` | 收集 `Time`、`Step` 或其他标量 |

类别是字面量字符串：`fields`、`particles` 或 `spectra`。前缀和变量名
是原始的磁盘上名称，如 `f`、`p`、`s`、`fB3` 或 `pX1_1`；不应用高层
重映射。

## 读取器约束

- 有效性检查会打开每个候选文件，并跳过抛出 `OSError` 的文件。
- 文件名仍必须遵循 `<category>.<8-digit-step>.<format>`。
- `ReadArrayAtTimestep` 读取整个存储的数组；先检查形状。
- HDF5 数据数组位于 `Step0` 之下；BP5 变量通过 ADIOS2 读取。
- 场布局在高层容器中可能需要转置；原始读取器返回存储的布局。
- 读取器 API 使用 PascalCase，因为那是已发布的公共接口。

## 源码依据

- CLI：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/cli/main.py>
- 基础读取器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/readers/base.py>
- BP5 读取器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/readers/adios2.py>
- HDF5 读取器：<https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/readers/hdf5.py>
