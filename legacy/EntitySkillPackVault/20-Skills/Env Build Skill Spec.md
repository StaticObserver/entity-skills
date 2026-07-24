# Env Build Skill Spec

## Mission

Handle Entity's dependency environment and build configuration.

This skill answers exactly one question: how should the current Entity checkout be correctly configured and compiled on the target machine.

## Trigger Conditions

The Router invokes this skill when:

- the user asks to compile Entity;
- the user asks to install or build the dependency environment;
- the user needs CUDA/HIP/MPI/Kokkos/ADIOS2/HDF5 configuration advice;
- the user hits CMake, compiler, Kokkos, ADIOS2, MPI, or GPU backend errors;
- the user asks for an Entity configure/build command.

## Out of Scope

This skill does not handle:

- writing TOML;
- writing `pgen.hpp`;
- judging physics parameters;
- analyzing output results;
- modifying Entity `src/` core functionality.

Those tasks go to the case, analysis, or core-dev skills respectively.

## Mandatory Checkout Probe

Before giving version-specific advice, confirm the current Entity checkout:

```bash
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse --short HEAD
git describe --tags --always
```

Then read or inspect:

- `README.md`;
- `dependencies.py`;
- `CMakeLists.txt`;
- `cmake/*.cmake`;
- `dev/runners/`;
- the official wiki dependencies page.

## General Dependency Build Principles

Decide whether MPI is needed first, then the communication stack; get Kokkos, HDF5, and ADIOS2 into the same compiler/MPI/CUDA/ROCm context, and configure Entity last.

Recommended order:

1. Confirm the host compiler, CUDA, or ROCm.
2. Decide whether MPI is needed.
3. If MPI is needed, prefer the MPI already available on the system or cluster.
4. If you must build MPI yourself and the target is GPU/multi-node, prefer building UCX first, then OpenMPI; for CPU or MPICH-leaning system ecosystems, consider MPICH.
5. Build Kokkos, preferring a GPU backend by default.
6. Build HDF5, preferring an existing system/cluster HDF5.
7. Build ADIOS2, making sure it sees the same HDF5, MPI, and the necessary Kokkos.
8. Configure and build Entity.

The official wiki's Spack advice is: first let Spack recognize existing compilers and large libraries — especially MPI, CUDA, HDF5 — then decide which dependencies truly need a local build.

## MPI Decision

If multiple processes are not needed:

- Entity uses `mpi=OFF`;
- do not build OpenMPI or MPICH;
- HDF5 and ADIOS2 use serial-compatible configurations;
- avoid mixing MPI ADIOS2 with serial HDF5.

If MPI is needed:

- prefer a system module, cluster module, or Spack external;
- only consider building your own if no MPI is available;
- for the GPU multi-node route, prefer UCX + OpenMPI;
- for the CPU route or MPICH-leaning system environments, consider MPICH;
- when unsure whether GPU-aware MPI is reliable, prefer `gpu_aware_mpi=OFF` for the Entity build.

## Entity Version and Dependency Matrix

| Entity version bucket | Kokkos | ADIOS2 | Rule |
| --- | --- | --- | --- |
| `official-v1.4.x` | Kokkos 5.x | ADIOS2 2.11.x | ADIOS2 must be built with the Kokkos dependency. |
| `legacy-v1.3.x` | Kokkos 4.x | ADIOS2 2.10.x | Do not use the 1.4.x dependency combination. |

This matrix is a hard constraint. If the agent cannot confirm the Entity version, it should stop and check the checkout rather than guess dependency versions.

## Spack Route

Recommended first steps:

```bash
spack compiler add
spack external find
spack env create entity-env
spack env activate entity-env
```

Run `spack spec` before installing each package:

```bash
spack spec kokkos <OPTIONS>
spack spec hdf5 <OPTIONS>
spack spec adios2 <OPTIONS>
```

Check dependency sources:

- `[e]` means external package;
- `[+]` means already installed in Spack;
- `[-]` means it will be downloaded and built.

Only after confirming the dependency graph is reasonable, run `spack install --add ...`.

## Kokkos Strategy

Prefer a GPU backend by default, unless the user explicitly requests CPU-only or the target machine has no GPU.

Common choices:

```text
NVIDIA GPU -> +cuda +wrapper cuda_arch=<arch>
AMD GPU    -> +rocm/amdgpu_target=<target> or the equivalent Spack/Kokkos options
CPU        -> OpenMP or Serial
```

Kokkos should always lean toward enabling:

```text
+pic +aggressive_vectorization
```

If the login node and compute node CPU/GPU architectures differ, do not blindly trust auto-detection. Set the target architecture when necessary, and allow non-host-compatible targets in Spack.

## Common Kokkos Architectures

Kokkos CMake uses `-D Kokkos_ARCH_<ARCH>=ON`. Spack option names are not identical — for example, NVIDIA commonly uses `cuda_arch=80`, and AMD commonly uses `amdgpu_target=gfx90a` or the equivalent option exposed by the current Spack/Kokkos package. The agent must verify with `spack info kokkos` and `spack spec kokkos ...` first.

Authoritative references:

- Kokkos architecture keywords: https://kokkos.org/kokkos-core-wiki/keywords.html#architecture-keywords
- Kokkos architecture option source: `cmake/kokkos_arch.cmake`, verifiable from the current Kokkos checkout or https://github.com/kokkos/kokkos/blob/develop/cmake/kokkos_arch.cmake.

### NVIDIA GPU

| Common hardware | Kokkos CMake ARCH | CUDA compute capability | Notes |
| --- | --- | --- | --- |
| V100 | `VOLTA70` | 7.0 | Volta. |
| T4 | `TURING75` | 7.5 | Turing. |
| A100 / A30 | `AMPERE80` | 8.0 | Common HPC Ampere. |
| RTX 3090 / A40 / A10 / A16 / A2 | `AMPERE86` | 8.6 | Common workstation/cloud Ampere. |
| Jetson Orin / embedded Ampere | `AMPERE87` | 8.7 | Embedded Ampere. |
| L4 / L40 / RTX 4090 | `ADA89` | 8.9 | Ada Lovelace. |
| H100 | `HOPPER90` | 9.0 | Hopper. |
| Blackwell series | `BLACKWELL100` / `BLACKWELL103` / `BLACKWELL120` / `BLACKWELL121` | 10.0 / 10.3 / 12.0 / 12.1 | Must be verified against the specific GPU and CUDA/Kokkos versions. |

Example:

```bash
cmake -B build \
  -D Kokkos_ENABLE_CUDA=ON \
  -D Kokkos_ARCH_AMPERE80=ON
```

Spack example:

```bash
spack spec kokkos +pic +aggressive_vectorization +cuda +wrapper cuda_arch=80
```

### AMD GPU

| Common hardware | Kokkos CMake ARCH | ROCm target | Notes |
| --- | --- | --- | --- |
| MI50 / MI60 | `AMD_GFX906` or `VEGA906` | `gfx906` | Older Vega. |
| MI100 | `AMD_GFX908` or `VEGA908` | `gfx908` | CDNA1. |
| MI200 / MI250 / MI250X | `AMD_GFX90A` or `VEGA90A` | `gfx90a` | Common on Frontier/LUMI. |
| MI300 / MI300X | `AMD_GFX942` | `gfx942` | CDNA3. |
| MI300A APU | `AMD_GFX942_APU` | `gfx942` | Confirm against ROCm/Kokkos support. |
| MI350 | `AMD_GFX950` | `gfx950` | New hardware; check current Kokkos/ROCm. |
| Radeon RX 7900 XTX | `AMD_GFX1100` | `gfx1100` | RDNA3. |
| V620 / W6800 | `AMD_GFX1030` or `NAVI1030` | `gfx1030` | RDNA2. |

Example:

```bash
cmake -B build \
  -D Kokkos_ENABLE_HIP=ON \
  -D Kokkos_ARCH_AMD_GFX90A=ON
```

The Spack example must be verified against the current package:

```bash
spack info kokkos
spack spec kokkos +pic +aggressive_vectorization +rocm amdgpu_target=gfx90a
```

### Common CPUs

CPU architectures are mainly for CPU-only or host-side optimization. Whether to set the host arch explicitly in a GPU build depends on whether the cluster's build nodes and run nodes match.

| Common CPU | Kokkos CMake ARCH | Notes |
| --- | --- | --- |
| Local auto-detection | `NATIVE` | Use only when the build node and run node match. |
| Intel Skylake Xeon | `SKX` | AVX512 server Skylake. |
| Intel Ice Lake Xeon | `ICX` | AVX512 Ice Lake server. |
| Intel Sapphire Rapids | `SPR` | AVX512 Sapphire Rapids. |
| AMD Zen 2 | `ZEN2` | Common in early Rome/Milan-era environments. |
| AMD Zen 3 | `ZEN3` | Milan. |
| AMD Zen 4 | `ZEN4` | Genoa. |
| AMD Zen 5 | `ZEN5` | New hardware; verify the Kokkos version. |
| Fujitsu A64FX | `A64FX` | ARM SVE. |
| NVIDIA Grace CPU | `ARMV9_GRACE` | Grace / Grace Hopper host. |
| IBM POWER9 | `POWER9` | Older Summit-class systems. |

If automatic architecture detection fails — especially when compiling on a login node and running on compute nodes — set the target CPU/GPU architecture explicitly.

## HDF5 Strategy

Prefer an existing system or cluster HDF5. The official wiki also recommends using existing installations for large libraries like MPI and HDF5.

If you must install via Spack:

```bash
spack spec hdf5 +cxx
spack install --add hdf5 +cxx
```

The MPI-off route needs a serial-compatible HDF5; the MPI-on route needs HDF5 consistent with the same MPI stack.

## ADIOS2 Strategy

ADIOS2 is built last, after the Kokkos/HDF5/MPI decisions.

1.4.x rules:

- use ADIOS2 2.11.x;
- ADIOS2 must be built with the Kokkos dependency;
- if Entity uses MPI, ADIOS2 should be consistent with the same MPI/HDF5 context.

1.3.x rules:

- use ADIOS2 2.10.x;
- pair with Kokkos 4.x;
- do not apply the 1.4.x ADIOS2/Kokkos rules.

## Entity CMake Options

This skill only generates and explains build configuration. Actual options must defer to the target Entity checkout's `CMakeLists.txt` and `cmake/`.

### Required Options

| Option | Value | Purpose | Notes |
| --- | --- | --- | --- |
| `-D pgen=<name-or-path>` | name in `pgens/<name>`, or a pgen path | Selects the problem generator | Usually required; switching pgen requires reconfigure/build. |

### Physics/Numerical Build Options

| Option | Common values | Purpose | Rebuild risk |
| --- | --- | --- | --- |
| `-D precision=single|double` | `single`, `double` | Floating-point precision | Affects numeric types and template instantiation; requires rebuild. |
| `-D deposit=zigzag|esirkepov` | `zigzag`, `esirkepov` | Current deposition scheme | Changes compile-time paths; requires rebuild. |
| `-D shape_order=<n>` | commonly `1`; higher orders as needed | particle shape/interpolation order | Affects template instantiation and performance; requires rebuild. |

### Output and Parallelism Options

| Option | Common values | Purpose | Notes |
| --- | --- | --- | --- |
| `-D output=ON|OFF` | `ON` | Whether to enable output | `OFF` can be used for minimal builds or tests, but real runs usually need `ON`. |
| `-D mpi=ON|OFF` | `OFF` or `ON` | Whether to enable MPI | Must be consistent with the MPI/HDF5/ADIOS2 in the dependency environment. |
| `-D gpu_aware_mpi=ON|OFF` | `OFF` when unsure | Whether to use GPU-aware MPI | Common risk point in multi-node GPU environments; turn it off when unsure. |

### Debug and Test Options

| Option | Common values | Purpose | Notes |
| --- | --- | --- | --- |
| `-D DEBUG=ON|OFF` | `OFF`, `ON` when debugging | Enables assertions, bounds checks, or extra diagnostics | May slow down compile and run. |
| `-D TESTS=ON|OFF` | `ON` during development | Builds tests | Used in core-dev or CI scenarios. |

### Kokkos Backend Options

Kokkos backend options must be consistent with the dependency environment:

```text
-D Kokkos_ENABLE_SERIAL=ON
-D Kokkos_ENABLE_OPENMP=ON
-D Kokkos_ENABLE_CUDA=ON
-D Kokkos_ENABLE_HIP=ON
-D Kokkos_ARCH_<ARCH>=ON
```

Do not repeatedly switch backend, pgen, precision, deposit, or shape_order in the same build directory. Use a new build directory when switching, for example:

```text
build/reconnection-cuda-a100
build/reconnection-cpu-debug
build/turbulence-hip-mi250
```

### Default Recommendations

If the user gives no special requirements:

- `precision=single`;
- `deposit=zigzag`;
- `shape_order=1`;
- `output=ON`;
- `DEBUG=OFF`;
- `TESTS=OFF`;
- default to a GPU backend when a GPU is available;
- set `mpi=ON` only when multi-process is clearly needed or the target run needs multiple nodes;
- set `gpu_aware_mpi=OFF` when unsure.

These defaults are operational advice, not physics-correctness judgments. Numerical method choices for a specific case are still decided by case design.

### Example Configure Commands

CPU-only, single process:

```bash
cmake -B build/<pgen>-cpu \
  -D pgen=<pgen> \
  -D Kokkos_ENABLE_OPENMP=ON \
  -D mpi=OFF \
  -D output=ON \
  -D precision=single
```

NVIDIA A100, single node:

```bash
cmake -B build/<pgen>-cuda-a100 \
  -D pgen=<pgen> \
  -D Kokkos_ENABLE_CUDA=ON \
  -D Kokkos_ARCH_AMPERE80=ON \
  -D mpi=OFF \
  -D output=ON \
  -D precision=single
```

NVIDIA A100, multi-node MPI, conservatively disabling GPU-aware MPI:

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

AMD MI250/MI250X:

```bash
cmake -B build/<pgen>-hip-mi250 \
  -D pgen=<pgen> \
  -D Kokkos_ENABLE_HIP=ON \
  -D Kokkos_ARCH_AMD_GFX90A=ON \
  -D mpi=ON \
  -D gpu_aware_mpi=OFF \
  -D output=ON
```

Development/test build:

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

### Changes That Require Reconfigure/Rebuild

Treat these changes as requiring reconfigure/build:

- switching `pgen`;
- changing `precision`;
- changing `deposit`;
- changing `shape_order`;
- toggling `mpi`;
- switching the Kokkos backend;
- changing the Kokkos architecture;
- toggling `DEBUG` or `TESTS`;
- modifying PGen C++ code.

Modifying only the TOML usually does not require a rebuild, unless the TOML's pgen/setup depends on new compile-time code.

## Output Contract

This skill's output should include:

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

## Common Failure Modes

- `pgen '<name>' not found`;
- `KokkosConfig.cmake` not found;
- Kokkos version does not match the Entity version;
- ADIOS2 version does not match the Entity version;
- ADIOS2 built without the Kokkos dependency under Entity 1.4.x;
- incompatible CUDA host compiler;
- wrong `Kokkos_ARCH_*` or GPU arch selected;
- login node and compute node architectures differ;
- MPI wrapper inconsistent with the CUDA/HIP toolchain;
- GPU-aware MPI fails at compile or run time;
- HDF5 and ADIOS2 MPI/serial contexts are inconsistent.
