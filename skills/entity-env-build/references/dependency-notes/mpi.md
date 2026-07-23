# MPI 构建笔记

## 策略

OpenMPI 源码构建**有意不自动生成**。按以下顺序优先：

1. 系统 MPI（PATH 中的 `mpicxx`、`mpirun`）
2. Module MPI（`module load openmpi/...`）
3. 用户提供的 MPI（用户指定前缀）
4. 源码构建（仅在用户明确批准且构建脚本经过审查时）

## 为什么不自动生成

- MPI 构建严重依赖站点特有的网络（InfiniBand、UCX、libfabric）
- 错误的 MPI 配置会静默地产出能构建成功、但运行时挂起的二进制
- 系统/module MPI 几乎总是正确的选择

## 何时需要 MPI

仅当 `requirements.environment.mpi=true` 时。不要仅因为系统上存在
mpicxx 就启用 MPI。

## MPI 一致性要求

启用 MPI 时：
- `mpicxx` 与 `mpirun` 必须存在且可执行
- MPI wrapper 必须使用选定的编译器族
- Kokkos、ADIOS2 与 HDF5 必须全部在同一个 MPI/编译器上下文中构建
- GPU-aware MPI（`gpu_aware_mpi=true`）需要明确的证据或风险接受

## 如果必须源码构建

在 `entity-deps.local.json.decisions` 中记录原因。构建脚本
（`entity_generate.py deps --deps mpi`）会生成一个停止脚本，解释为什么
不支持自动生成。
