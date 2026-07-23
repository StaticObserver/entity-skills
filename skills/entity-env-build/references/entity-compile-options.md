# Entity 编译选项参考

来源：https://entity-toolkit.github.io/wiki/content/1-getting-started/1-compile-run/

在生成 `requirements.json` 编译字段时，以及在 `entity-deps.local.json` 完成、兼容性为 `pass`、且已生成 `env.sh` 之后生成 `entity-build.sh` 时，使用本参考。

## Configure 模式

从 Entity 仓库根目录运行 CMake：

```bash
cmake -B <build-dir> -D pgen=<PROBLEM_GENERATOR> <options...>
```

Problem generator 规则：

- `pgen` 可以是 `pgens/` 中的内置 problem generator 名称，例如 `reconnection`。
- `pgen` 可以指向 `entity-pgens` 子模块中的 generator；此时使用 `pgens/` 路径，如 `pgens/kelvin-helmholtz`，并确保子模块已初始化。
- `pgen` 可以是包含 `pgen.hpp` 的目录的相对或绝对路径。

布尔 CMake 选项使用 `ON` 或 `OFF`。

## Entity 构建选项

| 选项 | 描述 | 取值 | 默认值 | 备注 |
| --- | --- | --- | --- | --- |
| `pgen` | Problem generator | 内置名称、`pgens/...` 或包含 `pgen.hpp` 的路径 | 必填 | 更改 `pgen` 需要重新 configure/build。 |
| `pgens` | 多个 problem generator | 逗号分隔的 generator 名称/路径 | 可选 | Entity 1.4.0 新增。仅当请求明确需要多个 generator 时使用。 |
| `precision` | 浮点精度 | `single`、`double` | `single` | 构建期数值类型。 |
| `deposit` | 电流沉积方案 | `zigzag`、`esirkepov` | `zigzag` | |
| `shape_order` | deposit 与 pusher 的插值阶数 | `1` 到 `11` | `1` | |
| `output` | 启用输出 | `ON`、`OFF` | `ON` | 默认意味着依赖环境通常需要 ADIOS2/HDF5 支持。 |
| `mpi` | 启用多节点支持 | `ON`、`OFF` | `OFF` | 仅当当前需求需要 MPI 时启用。 |
| `gpu_aware_mpi` | 启用 GPU-aware MPI 通信 | `ON`、`OFF` | `ON` | 除非确认，否则保持保守的环境默认值 `OFF`。 |
| `DEBUG` | 启用调试模式 | `ON`、`OFF` | `OFF` | 用于调试构建。 |
| `TESTS` | 编译单元测试 | `ON`、`OFF` | `OFF` | 运行 `ctest` 之前必需。 |
| `CMAKE_CXX_STANDARD` | C++ 语言标准 | `20` | `20` | `1.4.0` 之前的 Entity 版本不受支持。 |

## Entity 版本 profile

Entity 版本决定默认的 C++ 标准与依赖族：

| Entity 版本 | Profile | C++ 标准 | Kokkos | ADIOS2 | ADIOS2 Kokkos 支持 |
| --- | --- | --- | --- | --- | --- |
| `1.4.0` 及更新 | `modern` | `20` | `5.x` | `2.11.x` | `ON` |

精确的源码构建标签可以在 `requirements.environment.dependency_versions` 中固定，但必须保持在 profile 的版本族之内，除非用户明确接受 override。

## Kokkos 与后端选项

这些选项用于与 Entity 一起在树内编译 Kokkos/ADIOS2 时。使用外部 Kokkos/ADIOS2 时，这些库通常不需要这些标志，但 Entity 后端配置仍必须与选定的依赖 JSON 及 `env.sh` 保持一致。

| 选项 | 描述 | 取值 | 默认值 | 备注 |
| --- | --- | --- | --- | --- |
| `Kokkos_ENABLE_CUDA` | 启用 CUDA 后端 | `ON`、`OFF` | `OFF` | CUDA 构建应使用 Kokkos `nvcc_wrapper` 作为 `CXX`。 |
| `Kokkos_ENABLE_HIP` | 启用 HIP 后端 | `ON`、`OFF` | `OFF` | 与 ROCm/HIP 环境一起使用。 |
| `Kokkos_ENABLE_SYCL` | 启用 SYCL 后端 | `ON`、`OFF` | `OFF` | 存在于上游选项中；仅当依赖计划支持时使用。 |
| `Kokkos_ENABLE_OPENMP` | 启用 OpenMP 后端 | `ON`、`OFF` | `OFF` | 常见的 CPU 后端。 |
| `Kokkos_ARCH_***` | 选择 CPU/GPU 架构 | Kokkos 架构关键字 | 由 Kokkos 自动检测 | 编译节点与运行节点不同时，优先显式指定架构。 |

来自 wiki 的架构示例：

- NVIDIA A100：`-D Kokkos_ARCH_AMPERE80=ON`
- NVIDIA V100：`-D Kokkos_ARCH_VOLTA70=ON`
- AMD MI250X：`-D Kokkos_ARCH_AMD_GFX90A=ON`

## 构建、安装与测试命令

configure 之后：

```bash
cmake --build <build-dir> -j <NCORES>
```

如果省略 `-j <NCORES>` 而只使用 `-j`，CMake 可能使用尽可能多的线程。不带 `-j` 时编译只用一个核心。

预期可执行文件：

```text
<build-dir>/src/entity.xc
```

可选安装：

```bash
cmake --install <build-dir>
```

默认安装位置是 `./bin`；用以下方式覆盖：

```bash
-D CMAKE_INSTALL_PREFIX=<prefix>
```

测试：

```bash
cmake -B <build-dir> -D TESTS=ON <options...>
cmake --build <build-dir> -j <NCORES>
ctest --test-dir <build-dir>
ctest --test-dir <build-dir> --output-on-failure
ctest --test-dir <build-dir> -R <regex>
```

## AMD HIP/ROCm 注意事项

对于 HIP/ROCm 构建：

- 确保 ROCm 已加载且可发现，例如用 `rocminfo`。
- 将 `CMAKE_PREFIX_PATH` 设为 ROCm 前缀，通常是 `/opt/rocm`。
- 使用 `CC=hipcc` 和 `CXX=hipcc`；少数情况下还要传 `-D CMAKE_CXX_COMPILER=hipcc -D CMAKE_C_COMPILER=hipcc`。
- 使用合适的 Kokkos HIP 后端与架构标志编译，例如 MI250X 用 `-D Kokkos_ENABLE_HIP=ON -D Kokkos_ARCH_AMD_GFX90A=ON`。
- 在有多个 AMD agent 的机器上，从 `rocminfo`/`rocm-smi` 中识别目标 GPU；运行时可能需要 `HSA_OVERRIDE_GFX_VERSION`、`HIP_VISIBLE_DEVICES` 和 `ROCR_VISIBLE_DEVICES`。

## 本技能的构建阶段规则

- 在生成构建脚本之前，把 Entity 编译选项写入 `requirements.json`。
- 从 `requirements.json + env.sh` 生成 `entity-build.sh`；不要把手写 configure/build 命令当作事实来源。
- `entity-build.sh` 必须在 configure 之前 source 生成的 `env.sh`。
- 从 `entity-deps.local.json` 读取环境输入，从 `requirements.json` 读取编译输入；不要从 shell 历史重建状态。
- 更改 `pgen`、backend、MPI、precision、deposit、shape order、`DEBUG` 或 `TESTS` 时使用全新的构建目录。
- 保持 `output`、`mpi` 与 backend 选项与依赖 checkpoint 一致。
- 当 `requirements.environment.output=true` 时，除非 ADIOS2/HDF5 兼容性已通过，否则不要配置 `output=ON`。
- 当 `requirements.environment.mpi=false` 时，不要意外使用仅 MPI 的 ADIOS2/HDF5 目标。
- 当 `requirements.environment.backend=cuda` 时，使用 JSON 中选定的 Kokkos `nvcc_wrapper` 作为 `CXX`。
