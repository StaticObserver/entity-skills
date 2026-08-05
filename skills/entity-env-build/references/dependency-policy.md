# 依赖策略

在环境探测（第 2 阶段）期间选择 C++ 依赖来源时，使用本参考。

## 优先级顺序

对于 C++ 编译器与库，按以下顺序搜索：

0. **Site deps 注册表** — `entityctl site deps <site> --json` 导出的
   verified 栈（签名与当前 requirements 匹配）直接复用其 packages;
   见 SKILL.md 第 2 节的查找顺序。注册表里的 `env_sh` 路径仅供人读与
   审计——env-build 的环境始终由 `entity_generate.py env` 从当前
   checkpoint 的 packages 重建，不直接 source 注册表的 env.sh
1. **系统 modules/软件包** — `module load`、`dnf`/`apt`/`brew` 或系统路径
2. **Spack** — `spack find`、`spack load`
3. **源码构建** — 最后手段；用 `entity_generate.py deps` 生成脚本

## Conda 警告

**不要**用 conda 提供 C++ 构建工具。conda 自带的 `libstdc++` 与链接器配置在与系统或 Spack 构建的库混用时会导致隐蔽的 ABI 问题。

## Python 环境

对于 Python，conda 是首选且推荐的选择。Python 运行时依赖（例如分析脚本）遵循标准的 conda/pip 工作流程。

## 核心依赖

以下始终必需：

- CMake（最低版本见 `entity_schema.py:MIN_CMAKE_VERSION`）
- 一个 C++ 编译器（GCC、Clang，或 HIP 时用 `hipcc`）
- Kokkos（版本族由 Entity profile 决定）

## 条件依赖

| 条件 | 必需项 | 备注 |
|-----------|----------|-------|
| `environment.backend=cuda` | CUDA 工具包、`nvcc`、Kokkos `nvcc_wrapper` | 同时记录 wrapper 路径与 host 编译器 |
| `environment.backend=hip` | HIP/ROCm 工具包、`hipcc` | 包含 ROCm/DTK 版本偏好 |
| `environment.mpi=true` | `mpicxx`、`mpirun`、MPI modules | 不要仅因 mpicxx 存在就启用；OpenMPI 必须 >= 5.0.0（见下文） |
| `environment.output=true` | ADIOS2 + HDF5 | 串行/MPI 上下文与 MPI 需求匹配 |

## Profile 匹配

Entity `1.4.0` 及更新版本使用一个受支持的依赖 profile：

| Profile | Entity 版本 | C++ 标准 | Kokkos | ADIOS2 | ADIOS2 Kokkos 支持 |
|---------|---------------|--------------|--------|--------|-----------------------|
| `modern` | >= 1.4.0 | 20 | 5.x | 2.11.x | ON |

`1.4.0` 之前的 Entity 版本不受支持。
Entity `1.4.0`–`1.4.2` 仅支持 CPU；CUDA 要求 Entity `1.4.3` 或更新。

## OpenMPI 最低版本

当选定的 MPI 是 OpenMPI 时，版本必须满足
`entity_schema.py:MIN_OPENMPI_VERSION`（>= 5.0.0）。较旧的 OpenMPI 4.x
版本在 `srun` 下有已知的 ORTE/PMI 启动失败。兼容性检查
`mpi.openmpi_min_version` 在低于最低版本时失败；请选择更新的 module
或源码构建 OpenMPI 5.x，而不是 override。
