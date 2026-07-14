# Env Build Skill 规范

## 使命

处理 Entity 的依赖环境和编译配置。

这个 skill 只回答一个问题：当前 Entity checkout 应该如何在目标机器上正确配置和编译。

## 触发条件

Router 在以下场景调用本 skill：

- 用户要求编译 Entity；
- 用户要求安装或构建依赖环境；
- 用户需要 CUDA/HIP/MPI/Kokkos/ADIOS2/HDF5 配置建议；
- 用户遇到 CMake、compiler、Kokkos、ADIOS2、MPI 或 GPU backend 相关错误；
- 用户要求生成 Entity configure/build command。

## 不适用场景

本 skill 不负责：

- 写 TOML；
- 写 `pgen.hpp`；
- 判断物理参数；
- 分析输出结果；
- 修改 Entity `src/` 核心功能。

这些任务分别交给 case、analysis 或 core-dev 相关 skill。

## 必做 Checkout 探测

在给出版本相关建议前，先确认当前 Entity checkout：

```bash
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse --short HEAD
git describe --tags --always
```

然后读取或检查：

- `README.md`；
- `dependencies.py`；
- `CMakeLists.txt`；
- `cmake/*.cmake`；
- `dev/runners/`；
- 官方 wiki dependencies 页面。

## 依赖构建总原则

先决定是否需要 MPI，再决定通信栈；先让 Kokkos、HDF5、ADIOS2 处在同一套 compiler/MPI/CUDA/ROCm 语境下，最后再配置 Entity。

推荐顺序：

1. 确认 host compiler、CUDA 或 ROCm。
2. 判断是否需要 MPI。
3. 如果需要 MPI，优先使用系统或集群已有 MPI。
4. 如果必须自建 MPI，并且目标是 GPU/多节点，优先考虑先编译 UCX，再编译 OpenMPI；CPU 或系统生态偏 MPICH 时可考虑 MPICH。
5. 编译 Kokkos，默认优先 GPU backend。
6. 编译 HDF5，优先使用系统/集群已有 HDF5。
7. 编译 ADIOS2，并确保它感知同一套 HDF5、MPI 和必要的 Kokkos。
8. 配置并编译 Entity。

官方 wiki 的 Spack 建议是：优先让 Spack 识别已有 compiler 和大库，尤其是 MPI、CUDA、HDF5，再决定哪些依赖真的需要本地编译。

## MPI 决策

如果不需要多进程：

- Entity 使用 `mpi=OFF`；
- 不编译 OpenMPI 或 MPICH；
- HDF5 和 ADIOS2 使用 serial-compatible 方案；
- 避免混用 MPI ADIOS2 与 serial HDF5。

如果需要 MPI：

- 优先使用系统 module、集群 module 或 Spack external；
- 如果没有可用 MPI，再考虑自建；
- GPU 多节点路线优先考虑 UCX + OpenMPI；
- CPU 路线或系统环境偏 MPICH 时可以考虑 MPICH；
- 不确定 GPU-aware MPI 是否可靠时，Entity build 优先设置 `gpu_aware_mpi=OFF`。

## Entity 版本与依赖矩阵

| Entity 版本桶 | Kokkos | ADIOS2 | 规则 |
| --- | --- | --- | --- |
| `official-v1.4.x` | Kokkos 5.x | ADIOS2 2.11.x | 编译 ADIOS2 时需要带上 Kokkos 依赖。 |
| `legacy-v1.3.x` | Kokkos 4.x | ADIOS2 2.10.x | 不要使用 1.4.x 的依赖组合。 |

这个矩阵是硬约束。Agent 如果无法确认 Entity 版本，应先停下来查 checkout，而不是猜依赖版本。

## Spack 路线

推荐先运行：

```bash
spack compiler add
spack external find
spack env create entity-env
spack env activate entity-env
```

每个包安装前先运行 `spack spec`：

```bash
spack spec kokkos <OPTIONS>
spack spec hdf5 <OPTIONS>
spack spec adios2 <OPTIONS>
```

检查依赖来源：

- `[e]` 表示 external package；
- `[+]` 表示已在 Spack 中安装；
- `[-]` 表示会下载并编译。

只有确认依赖图合理后，再运行 `spack install --add ...`。

## Kokkos 策略

默认优先 GPU backend，除非用户明确要求 CPU-only 或目标机器没有 GPU。

常见选择：

```text
NVIDIA GPU -> +cuda +wrapper cuda_arch=<arch>
AMD GPU    -> +rocm/amdgpu_target=<target> 或对应 Spack/Kokkos 选项
CPU        -> OpenMP 或 Serial
```

Kokkos 始终倾向启用：

```text
+pic +aggressive_vectorization
```

如果 login node 和 compute node CPU/GPU 架构不同，不能盲目信任自动探测。必要时设置目标架构，并在 Spack 中允许非 host-compatible target。

## 常用 Kokkos 架构

Kokkos CMake 使用 `-D Kokkos_ARCH_<ARCH>=ON`。Spack 的选项名不完全相同，例如 NVIDIA 常用 `cuda_arch=80`，AMD 常用 `amdgpu_target=gfx90a` 或当前 Spack/Kokkos package 暴露的等价选项。Agent 必须先用 `spack info kokkos` 和 `spack spec kokkos ...` 核对。

权威参考：

- Kokkos architecture keywords: https://kokkos.org/kokkos-core-wiki/keywords.html#architecture-keywords
- Kokkos 架构选项源码：`cmake/kokkos_arch.cmake`，可从当前 Kokkos checkout 或 https://github.com/kokkos/kokkos/blob/develop/cmake/kokkos_arch.cmake 核对。

### NVIDIA GPU

| 常见硬件 | Kokkos CMake ARCH | CUDA compute capability | 备注 |
| --- | --- | --- | --- |
| V100 | `VOLTA70` | 7.0 | Volta。 |
| T4 | `TURING75` | 7.5 | Turing。 |
| A100 / A30 | `AMPERE80` | 8.0 | 常见 HPC Ampere。 |
| RTX 3090 / A40 / A10 / A16 / A2 | `AMPERE86` | 8.6 | 常见 workstation/cloud Ampere。 |
| Jetson Orin / embedded Ampere | `AMPERE87` | 8.7 | 嵌入式 Ampere。 |
| L4 / L40 / RTX 4090 | `ADA89` | 8.9 | Ada Lovelace。 |
| H100 | `HOPPER90` | 9.0 | Hopper。 |
| Blackwell 系列 | `BLACKWELL100` / `BLACKWELL103` / `BLACKWELL120` / `BLACKWELL121` | 10.0 / 10.3 / 12.0 / 12.1 | 必须按具体 GPU 和 CUDA/Kokkos 版本核对。 |

示例：

```bash
cmake -B build \
  -D Kokkos_ENABLE_CUDA=ON \
  -D Kokkos_ARCH_AMPERE80=ON
```

Spack 示例：

```bash
spack spec kokkos +pic +aggressive_vectorization +cuda +wrapper cuda_arch=80
```

### AMD GPU

| 常见硬件 | Kokkos CMake ARCH | ROCm target | 备注 |
| --- | --- | --- | --- |
| MI50 / MI60 | `AMD_GFX906` 或 `VEGA906` | `gfx906` | 旧 Vega。 |
| MI100 | `AMD_GFX908` 或 `VEGA908` | `gfx908` | CDNA1。 |
| MI200 / MI250 / MI250X | `AMD_GFX90A` 或 `VEGA90A` | `gfx90a` | Frontier/LUMI 常见。 |
| MI300 / MI300X | `AMD_GFX942` | `gfx942` | CDNA3。 |
| MI300A APU | `AMD_GFX942_APU` | `gfx942` | 需要按 ROCm/Kokkos 支持确认。 |
| MI350 | `AMD_GFX950` | `gfx950` | 新硬件必须查当前 Kokkos/ROCm。 |
| Radeon RX 7900 XTX | `AMD_GFX1100` | `gfx1100` | RDNA3。 |
| V620 / W6800 | `AMD_GFX1030` 或 `NAVI1030` | `gfx1030` | RDNA2。 |

示例：

```bash
cmake -B build \
  -D Kokkos_ENABLE_HIP=ON \
  -D Kokkos_ARCH_AMD_GFX90A=ON
```

Spack 示例需要按当前 package 核对：

```bash
spack info kokkos
spack spec kokkos +pic +aggressive_vectorization +rocm amdgpu_target=gfx90a
```

### 常用 CPU

CPU 架构主要用于 CPU-only 或 host-side 优化。GPU build 中是否显式设置 host arch，要看集群编译节点和运行节点是否一致。

| 常见 CPU | Kokkos CMake ARCH | 备注 |
| --- | --- | --- |
| 本机自动探测 | `NATIVE` | 仅当编译节点与运行节点一致时使用。 |
| Intel Skylake Xeon | `SKX` | AVX512 server Skylake。 |
| Intel Ice Lake Xeon | `ICX` | AVX512 Ice Lake server。 |
| Intel Sapphire Rapids | `SPR` | AVX512 Sapphire Rapids。 |
| AMD Zen 2 | `ZEN2` | Rome/Milan 早期相关环境常见。 |
| AMD Zen 3 | `ZEN3` | Milan。 |
| AMD Zen 4 | `ZEN4` | Genoa。 |
| AMD Zen 5 | `ZEN5` | 新硬件需核对 Kokkos 版本。 |
| Fujitsu A64FX | `A64FX` | ARM SVE。 |
| NVIDIA Grace CPU | `ARMV9_GRACE` | Grace / Grace Hopper host。 |
| IBM POWER9 | `POWER9` | Summit 类老系统。 |

如果自动架构识别失败，尤其是在 login node 上编译、compute node 上运行时，应显式设置目标 CPU/GPU 架构。

## HDF5 策略

优先使用系统或集群已有 HDF5。官方 wiki 也建议 MPI、HDF5 这类大库尽量使用已有安装。

如果必须通过 Spack 安装：

```bash
spack spec hdf5 +cxx
spack install --add hdf5 +cxx
```

MPI-off 路线需要 serial-compatible HDF5；MPI-on 路线需要让 HDF5 与同一 MPI 栈一致。

## ADIOS2 策略

ADIOS2 要最后于 Kokkos/HDF5/MPI 决策之后构建。

1.4.x 规则：

- 使用 ADIOS2 2.11.x；
- ADIOS2 编译时需要带上 Kokkos 依赖；
- 如果 Entity 使用 MPI，ADIOS2 也应与同一 MPI/HDF5 语境一致。

1.3.x 规则：

- 使用 ADIOS2 2.10.x；
- 配合 Kokkos 4.x；
- 不套用 1.4.x 的 ADIOS2/Kokkos 规则。

## Entity CMake Options

本 skill 只生成和解释 build configuration。实际选项必须以目标 Entity checkout 的 `CMakeLists.txt` 和 `cmake/` 为准。

### 必需选项

| 选项 | 取值 | 作用 | 注意 |
| --- | --- | --- | --- |
| `-D pgen=<name-or-path>` | `pgens/<name>` 中的 name，或 pgen 路径 | 选择 problem generator | 通常是必需项；换 pgen 需要重新 configure/build。 |

### 物理/数值编译选项

| 选项 | 常见取值 | 作用 | 重新编译风险 |
| --- | --- | --- | --- |
| `-D precision=single|double` | `single`、`double` | 浮点精度 | 会影响数值类型和模板实例化，必须重新编译。 |
| `-D deposit=zigzag|esirkepov` | `zigzag`、`esirkepov` | 电流沉积方案 | 会改变编译期路径，必须重新编译。 |
| `-D shape_order=<n>` | 常见 `1`，高阶按需求设置 | particle shape/interpolation order | 会影响模板实例化和性能，必须重新编译。 |

### 输出与并行选项

| 选项 | 常见取值 | 作用 | 注意 |
| --- | --- | --- | --- |
| `-D output=ON|OFF` | `ON` | 是否启用输出 | `OFF` 可用于极简编译或测试，但真实 run 通常需要 `ON`。 |
| `-D mpi=ON|OFF` | `OFF` 或 `ON` | 是否启用 MPI | 必须与依赖环境中的 MPI/HDF5/ADIOS2 一致。 |
| `-D gpu_aware_mpi=ON|OFF` | 不确定时 `OFF` | 是否使用 GPU-aware MPI | 多节点 GPU 环境常见风险点；不确定先关。 |

### 调试与测试选项

| 选项 | 常见取值 | 作用 | 注意 |
| --- | --- | --- | --- |
| `-D DEBUG=ON|OFF` | `OFF`，排错时 `ON` | 开启断言、bounds checks 或更多诊断 | 编译和运行可能更慢。 |
| `-D TESTS=ON|OFF` | 开发时 `ON` | 编译 tests | core-dev 或 CI 场景使用。 |

### Kokkos backend 选项

Kokkos backend options 必须与依赖环境一致：

```text
-D Kokkos_ENABLE_SERIAL=ON
-D Kokkos_ENABLE_OPENMP=ON
-D Kokkos_ENABLE_CUDA=ON
-D Kokkos_ENABLE_HIP=ON
-D Kokkos_ARCH_<ARCH>=ON
```

同一个 build 目录不要反复切换 backend、pgen、precision、deposit 或 shape_order。需要切换时使用新的 build directory，例如：

```text
build/reconnection-cuda-a100
build/reconnection-cpu-debug
build/turbulence-hip-mi250
```

### 默认建议

如果用户没有给出特殊要求：

- `precision=single`；
- `deposit=zigzag`；
- `shape_order=1`；
- `output=ON`；
- `DEBUG=OFF`；
- `TESTS=OFF`；
- 有 GPU 时默认 GPU backend；
- 只有明确需要多进程或目标 run 需要多节点时才设 `mpi=ON`；
- `gpu_aware_mpi` 不确定时设 `OFF`。

这些默认值是操作建议，不是物理正确性判断。具体 case 的数值方法选择仍需由 case 设计决定。

### 示例 Configure Commands

CPU-only，单进程：

```bash
cmake -B build/<pgen>-cpu \
  -D pgen=<pgen> \
  -D Kokkos_ENABLE_OPENMP=ON \
  -D mpi=OFF \
  -D output=ON \
  -D precision=single
```

NVIDIA A100，单节点：

```bash
cmake -B build/<pgen>-cuda-a100 \
  -D pgen=<pgen> \
  -D Kokkos_ENABLE_CUDA=ON \
  -D Kokkos_ARCH_AMPERE80=ON \
  -D mpi=OFF \
  -D output=ON \
  -D precision=single
```

NVIDIA A100，多节点 MPI，保守关闭 GPU-aware MPI：

```bash
cmake -B build/<pgen>-cuda-a100-mpi \
  -D pgen=<pgen> \
  -D Kokkos_ENABLE_CUDA=ON \
  -D Kokkos_ARCH_AMPERE80=ON \
  -D mpi=ON \
  -D gpu_aware_mpi=OFF \
  -D output=ON \
  -D precision=single
```

AMD MI250/MI250X：

```bash
cmake -B build/<pgen>-hip-mi250 \
  -D pgen=<pgen> \
  -D Kokkos_ENABLE_HIP=ON \
  -D Kokkos_ARCH_AMD_GFX90A=ON \
  -D mpi=ON \
  -D gpu_aware_mpi=OFF \
  -D output=ON
```

开发/测试 build：

```bash
cmake -B build/<pgen>-debug \
  -D pgen=<pgen> \
  -D Kokkos_ENABLE_OPENMP=ON \
  -D DEBUG=ON \
  -D TESTS=ON \
  -D output=ON
```

Build command:

```bash
cmake --build build/<name> -j
```

### 需要重新 Configure/Build 的改动

这些改动应视为需要重新 configure/build：

- 更换 `pgen`；
- 修改 `precision`；
- 修改 `deposit`；
- 修改 `shape_order`；
- 切换 `mpi`；
- 切换 Kokkos backend；
- 修改 Kokkos architecture；
- 切换 `DEBUG` 或 `TESTS`；
- 修改 PGen C++ 代码。

仅修改 TOML 通常不需要重新编译，除非该 TOML 对应的 pgen/setup 依赖新的编译期代码。

## 输出契约

本 skill 的输出应包含：

```yaml
dependency_strategy:
  entity_version_bucket:
  mpi_required:
  mpi_provider: system | openmpi | mpich | none
  ucx_recommended:
  kokkos_version:
  kokkos_backend:
  hdf5_provider:
  adios2_version:
  adios2_provider:
  adios2_needs_kokkos:
  spack_env:
entity_build:
  pgen:
  precision:
  deposit:
  shape_order:
  output:
  mpi:
  gpu_aware_mpi:
  debug:
  tests:
  configure_command:
  build_command:
  build_dir:
  expected_executable:
risks:
  -
```

## 常见失败模式

- `pgen '<name>' not found`；
- `KokkosConfig.cmake` 找不到；
- Kokkos 版本与 Entity 版本不匹配；
- ADIOS2 版本与 Entity 版本不匹配；
- Entity 1.4.x 下 ADIOS2 未带 Kokkos 依赖；
- CUDA host compiler 不兼容；
- `Kokkos_ARCH_*` 或 GPU arch 选错；
- login node 与 compute node 架构不一致；
- MPI wrapper 与 CUDA/HIP toolchain 不一致；
- GPU-aware MPI 编译或运行失败；
- HDF5 与 ADIOS2 的 MPI/serial 语境不一致。
