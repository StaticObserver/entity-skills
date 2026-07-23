---
name: entity-nt2py
description: 使用 nt2py 读取、检查、可视化和导出 Entity 模拟输出。适用于 nt2py API 问题，以及涉及 Entity 场、粒子、能谱、运行时诊断、绘图、影片、nt2 CLI 或原始 BP5/HDF5 读取器的工作。本技能提供数据访问知识和一个只读盘点探针；它不规定物理诊断方法，也不判断模拟在物理上是否正确。
---

# Entity nt2py

将 nt2py 用作访问 Entity 输出的灵活接口。科学分析保持开放；
只对数据发现、内存使用和原始数据安全性加以约束。

随附的参考文档以 nt2py v1.5.3 为目标。当已安装的软件包和实际输出
与参考文档不一致时，以它们为准。

## 边界

处理范围：

- nt2py 安装与数据根目录定位；
- 场、粒子、能谱和运行时诊断的访问；
- xarray/Dask 选取、绘图、影片与导出；
- `nt2` CLI 以及有边界的原始读取器使用；
- 由用户选定量的推导或可视化代码。

不要仅凭变量名就定义某个量的物理含义、归一化方式或有效性。
当解释尚未确立时，阅读相关的 TOML/PGen 契约或询问用户。
输出损坏或运行失败的诊断不在本技能范围内，应转交他处处理。

## 最小规则

1. 在编写针对具体数据的分析之前，先检查实际的变量、维度、物种和
   nt2py 版本。不要从 PGen 名称推断它们。
2. 在 `.values`、`.load()`、`.compute()` 或绘图之前先选取场和能谱。
   在 `ParticleDataset.load()` 之前先选取粒子时间/物种和所需列。
3. 将 Entity 数据根目录视为只读。绘图、帧、notebook、脚本和导出
   一律写到别处。
4. 将 API 事实与物理解释分开。没有必要的模拟上下文时，不要把
   某个视觉模式或变量名提升为科学结论。
5. 创建产物时，运行相关代码并确认所请求的输出确实存在。用户没有
   要求时，不要强加报告、notebook、脚本或目录格式。

## 探测实际输出

对于概念性的 nt2py 问题，直接阅读相关参考文档。当有实际的数据根目录
可用时，先运行只读探针，再选择具体的变量或选取方式：

```bash
python3 scripts/inspect_nt2_data.py /path/to/data-root
python3 scripts/inspect_nt2_data.py /path/to/data-root \
  --output /path/to/analysis/nt2-inventory.json
```

探针打印 JSON，并可选择将其镜像写入 `--output`。它不会调用
`print(data)`、粒子 `.nbytes`、粒子 `.load()` 或 Dask 计算。它确实会
初始化 `nt2.Data`；该库的初始化会读取坐标/分箱信息，并且在 v1.5.3 中，
为确定形状还会读取第一个已存储的能谱。探针拒绝位于数据根目录内部的
输出路径。将其 JSON 视为当前证据，而不是持久的分析状态机。

如果探针报告版本不匹配，使用它发现的盘点信息，并在依赖版本特定的
示例之前核对已安装 nt2py 的源码或文档。

## 参考文档路由

只阅读当前任务所需的参考文档：

| 任务 | 参考文档 |
|---|---|
| 安装 nt2py、定位数据根目录、初始化 `nt2.Data`、检查诊断 | `references/data-layout-and-loading.md` |
| 选取场、构建派生数组或使用预计算能谱 | `references/fields-and-spectra.md` |
| 选取、加载、绘制或导出粒子 | `references/particles.md` |
| 创建 xarray、inspect、极坐标、相空间或影片输出 | `references/plotting-and-movies.md` |
| 使用 CLI 或读取精确的 BP5/HDF5 数组 | `references/cli-and-raw-readers.md` |

默认使用高层容器。仅当需要精确的存储名称/数组，或高层构造失败时，
才加载原始读取器参考文档。
