# Entity Compile Options Reference

Source: https://entity-toolkit.github.io/wiki/content/1-getting-started/1-compile-run/

Use this reference when generating `requirements.json` compile fields and when generating `entity-build.sh` after `entity-deps.local.json` is complete, compatibility is `pass`, and `env.sh` has been generated.

## Configure Pattern

Run CMake from the Entity repository root:

```bash
cmake -B <build-dir> -D pgen=<PROBLEM_GENERATOR> <options...>
```

Problem generator rules:

- `pgen` can be a built-in problem generator name from `pgens/`, for example `reconnection`.
- `pgen` can point to a generator from the `entity-pgens` submodule; in that case use a `pgens/` path such as `pgens/kelvin-helmholtz` and ensure submodules are initialized.
- `pgen` can be a relative or absolute path to a directory containing `pgen.hpp`.

Boolean CMake options use `ON` or `OFF`.

## Entity Build Options

| Option | Description | Values | Default | Notes |
| --- | --- | --- | --- | --- |
| `pgen` | Problem generator | built-in name, `pgens/...`, or path containing `pgen.hpp` | required | Changing `pgen` requires a new configure/build. |
| `pgens` | Multiple problem generators | comma-separated generator names/paths | optional | Added in Entity 1.4.0. Use only when the request explicitly needs multiple generators. |
| `precision` | Floating point precision | `single`, `double` | `single` | Build-time numerical type. |
| `deposit` | Current deposit scheme | `zigzag`, `esirkepov` | `zigzag` | |
| `shape_order` | Interpolation order for deposit and pusher | `1` to `11` | `1` | |
| `output` | Enable output | `ON`, `OFF` | `ON` | Default means the dependency environment normally needs ADIOS2/HDF5 support. |
| `mpi` | Enable multi-node support | `ON`, `OFF` | `OFF` | Only enable when the current requirements need MPI. |
| `gpu_aware_mpi` | Enable GPU-aware MPI communications | `ON`, `OFF` | `ON` | Keep the conservative environment default `OFF` unless confirmed. |
| `DEBUG` | Enable debug mode | `ON`, `OFF` | `OFF` | Use for debug builds. |
| `TESTS` | Compile unit tests | `ON`, `OFF` | `OFF` | Required before running `ctest`. |
| `CMAKE_CXX_STANDARD` | C++ language standard | `20` | `20` | Entity versions before `1.4.0` are unsupported. |

## Entity Version Profiles

The Entity version determines the default C++ standard and dependency family:

| Entity version | Profile | C++ standard | Kokkos | ADIOS2 | ADIOS2 Kokkos support |
| --- | --- | --- | --- | --- | --- |
| `1.4.0` and newer | `modern` | `20` | `5.x` | `2.11.x` | `ON` |

Exact source-build tags may be pinned in `requirements.environment.dependency_versions`, but they must remain inside the profile's version family unless the user explicitly accepts an override.

## Kokkos And Backend Options

These are used when compiling Kokkos/ADIOS2 in-tree with Entity. When using external Kokkos/ADIOS2, these flags are generally not needed for those libraries, but Entity backend configuration still must remain consistent with the selected dependency JSON and `env.sh`.

| Option | Description | Values | Default | Notes |
| --- | --- | --- | --- | --- |
| `Kokkos_ENABLE_CUDA` | Enable CUDA backend | `ON`, `OFF` | `OFF` | CUDA builds should use Kokkos `nvcc_wrapper` as `CXX`. |
| `Kokkos_ENABLE_HIP` | Enable HIP backend | `ON`, `OFF` | `OFF` | Use with ROCm/HIP environment. |
| `Kokkos_ENABLE_SYCL` | Enable SYCL backend | `ON`, `OFF` | `OFF` | Present in upstream options; only use if the dependency plan supports it. |
| `Kokkos_ENABLE_OPENMP` | Enable OpenMP backend | `ON`, `OFF` | `OFF` | Common CPU backend. |
| `Kokkos_ARCH_***` | Select CPU/GPU architecture | Kokkos architecture keyword | auto-detected by Kokkos | Prefer explicit architecture when compile node differs from run node. |

Architecture examples from the wiki:

- NVIDIA A100: `-D Kokkos_ARCH_AMPERE80=ON`
- NVIDIA V100: `-D Kokkos_ARCH_VOLTA70=ON`
- AMD MI250X: `-D Kokkos_ARCH_AMD_GFX90A=ON`

## Build, Install, And Test Commands

After configure:

```bash
cmake --build <build-dir> -j <NCORES>
```

If `-j <NCORES>` is omitted and only `-j` is used, CMake may use as many threads as possible. Without `-j`, compilation uses one core.

Expected executable:

```text
<build-dir>/src/entity.xc
```

Optional install:

```bash
cmake --install <build-dir>
```

Default install location is `./bin`; override with:

```bash
-D CMAKE_INSTALL_PREFIX=<prefix>
```

Tests:

```bash
cmake -B <build-dir> -D TESTS=ON <options...>
cmake --build <build-dir> -j <NCORES>
ctest --test-dir <build-dir>
ctest --test-dir <build-dir> --output-on-failure
ctest --test-dir <build-dir> -R <regex>
```

## AMD HIP/ROCm Notes

For HIP/ROCm builds:

- Ensure ROCm is loaded and discoverable, for example with `rocminfo`.
- Set `CMAKE_PREFIX_PATH` to the ROCm prefix, often `/opt/rocm`.
- Use `CC=hipcc` and `CXX=hipcc`; in rare cases also pass `-D CMAKE_CXX_COMPILER=hipcc -D CMAKE_C_COMPILER=hipcc`.
- Compile with the appropriate Kokkos HIP backend and architecture flags, for example `-D Kokkos_ENABLE_HIP=ON -D Kokkos_ARCH_AMD_GFX90A=ON` for MI250X.
- On machines with multiple AMD agents, identify the intended GPU from `rocminfo`/`rocm-smi`; runtime may require `HSA_OVERRIDE_GFX_VERSION`, `HIP_VISIBLE_DEVICES`, and `ROCR_VISIBLE_DEVICES`.

## Build Phase Rules For This Skill

- Write Entity compile options into `requirements.json` before generating build scripts.
- Generate `entity-build.sh` from `requirements.json + env.sh`; do not hand-write configure/build commands as the source of truth.
- `entity-build.sh` must source the generated `env.sh` before configure.
- Read environment inputs from `entity-deps.local.json` and compile inputs from `requirements.json`; do not reconstruct state from shell history.
- Use a fresh build directory when changing `pgen`, backend, MPI, precision, deposit, shape order, `DEBUG`, or `TESTS`.
- Keep `output`, `mpi`, and backend options consistent with the dependency checkpoint.
- When `requirements.environment.output=true`, do not configure `output=ON` unless ADIOS2/HDF5 compatibility passed.
- When `requirements.environment.mpi=false`, do not accidentally use MPI-only ADIOS2/HDF5 targets.
- When `requirements.environment.backend=cuda`, use the JSON-selected Kokkos `nvcc_wrapper` as `CXX`.
