# Entity Compile Options Reference

Source: https://entity-toolkit.github.io/wiki/content/1-getting-started/1-compile-run/

Use this reference when generating the compile fields of `requirements.json`, and when generating `entity-build.sh` after `entity-deps.local.json` is complete, compatibility is `pass`, and `env.sh` has been generated.

## Configure Mode

Run CMake from the Entity repository root:

```bash
cmake -B <build-dir> -D pgen=<PROBLEM_GENERATOR> <options...>
```

Problem generator rules:

- `pgen` can be the name of a built-in problem generator in `pgens/`, for example `reconnection`.
- `pgen` can point to a generator in the `entity-pgens` submodule; in that case use a `pgens/` path, such as `pgens/kelvin-helmholtz`, and ensure the submodule is initialized.
- `pgen` can be a relative or absolute path to a directory containing `pgen.hpp`.

Boolean CMake options use `ON` or `OFF`.

## Entity Build Options

| Option | Description | Values | Default | Notes |
| --- | --- | --- | --- | --- |
| `pgen` | Problem generator | Built-in name, `pgens/...`, or a path containing `pgen.hpp` | Required | Changing `pgen` requires a fresh configure/build. |
| `pgens` | Multiple problem generators | Comma-separated generator names/paths | Optional | New in Entity 1.4.0. Use only when the request explicitly needs multiple generators. |
| `precision` | Floating-point precision | `single`, `double` | `single` | Build-time numeric type. |
| `deposit` | Current deposition scheme | `zigzag`, `esirkepov` | `zigzag` | |
| `shape_order` | Interpolation order for deposit and pusher | `1` to `11` | `1` | |
| `output` | Enable output | `ON`, `OFF` | `ON` | Default means the dependency environment usually needs ADIOS2/HDF5 support. |
| `mpi` | Enable multi-node support | `ON`, `OFF` | `OFF` | Enable only when the current requirements need MPI. |
| `gpu_aware_mpi` | Enable GPU-aware MPI communication | `ON`, `OFF` | `ON` | Unless confirmed, keep the conservative environment default `OFF`. |
| `DEBUG` | Enable debug mode | `ON`, `OFF` | `OFF` | For debug builds. |
| `TESTS` | Compile unit tests | `ON`, `OFF` | `OFF` | Required before running `ctest`. |
| `CMAKE_CXX_STANDARD` | C++ language standard | `20` | `20` | Entity versions before `1.4.0` are not supported. |

## Entity Version Profiles

The Entity version determines the default C++ standard and dependency families:

| Entity version | Profile | C++ standard | Kokkos | ADIOS2 | ADIOS2 Kokkos support |
| --- | --- | --- | --- | --- | --- |
| `1.4.0` and newer | `modern` | `20` | `5.x` | `2.11.x` | `ON` |

Exact source build tags can be pinned in `requirements.environment.dependency_versions`, but must stay within the profile's version family unless the user explicitly accepts an override.

## Kokkos and Backend Options

These options apply when compiling Kokkos/ADIOS2 in-tree together with Entity. When using external Kokkos/ADIOS2, these libraries usually do not need these flags, but the Entity backend configuration must still match the selected dependency JSON and `env.sh`.

| Option | Description | Values | Default | Notes |
| --- | --- | --- | --- | --- |
| `Kokkos_ENABLE_CUDA` | Enable the CUDA backend | `ON`, `OFF` | `OFF` | CUDA builds should use the Kokkos `nvcc_wrapper` as `CXX`. |
| `Kokkos_ENABLE_HIP` | Enable the HIP backend | `ON`, `OFF` | `OFF` | Use together with a ROCm/HIP environment. |
| `Kokkos_ENABLE_SYCL` | Enable the SYCL backend | `ON`, `OFF` | `OFF` | Present among the upstream options; use only when the dependency plan supports it. |
| `Kokkos_ENABLE_OPENMP` | Enable the OpenMP backend | `ON`, `OFF` | `OFF` | Common CPU backend. |
| `Kokkos_ARCH_***` | Select the CPU/GPU architecture | Kokkos architecture keyword | Auto-detected by Kokkos | Prefer specifying the architecture explicitly when the compile node differs from the run node. |

Architecture examples from the wiki:

- NVIDIA A100: `-D Kokkos_ARCH_AMPERE80=ON`
- NVIDIA V100: `-D Kokkos_ARCH_VOLTA70=ON`
- AMD MI250X: `-D Kokkos_ARCH_AMD_GFX90A=ON`

## Build, Install, and Test Commands

After configure:

```bash
cmake --build <build-dir> -j <NCORES>
```

If `-j <NCORES>` is omitted and only `-j` is used, CMake may use as many threads as possible. Without `-j`, compilation uses a single core.

Expected executable:

```text
<build-dir>/src/entity.xc
```

Optional install:

```bash
cmake --install <build-dir>
```

The default install location is `./bin`; override with:

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

- Ensure ROCm is loaded and discoverable, e.g., with `rocminfo`.
- Set `CMAKE_PREFIX_PATH` to the ROCm prefix, usually `/opt/rocm`.
- Use `CC=hipcc` and `CXX=hipcc`; in rare cases also pass `-D CMAKE_CXX_COMPILER=hipcc -D CMAKE_C_COMPILER=hipcc`.
- Compile with the appropriate Kokkos HIP backend and architecture flags, e.g., `-D Kokkos_ENABLE_HIP=ON -D Kokkos_ARCH_AMD_GFX90A=ON` for MI250X.
- On machines with multiple AMD agents, identify the target GPU from `rocminfo`/`rocm-smi`; at runtime `HSA_OVERRIDE_GFX_VERSION`, `HIP_VISIBLE_DEVICES`, and `ROCR_VISIBLE_DEVICES` may be needed.

## Build-Phase Rules for This Skill

- Write the Entity compile options into `requirements.json` before generating build scripts.
- Generate `entity-build.sh` from `requirements.json + env.sh`; do not treat hand-written configure/build commands as a source of truth.
- `entity-build.sh` must source the generated `env.sh` before configure.
- Read environment inputs from `entity-deps.local.json` and compile inputs from `requirements.json`; do not reconstruct state from shell history.
- Use a fresh build directory when changing `pgen`, backend, MPI, precision, deposit, shape order, `DEBUG`, or `TESTS`.
- Keep the `output`, `mpi`, and backend options consistent with the dependency checkpoint.
- When `requirements.environment.output=true`, do not configure `output=ON` unless ADIOS2/HDF5 compatibility has passed.
- When `requirements.environment.mpi=false`, do not accidentally use MPI-only ADIOS2/HDF5 targets.
- When `requirements.environment.backend=cuda`, use the Kokkos `nvcc_wrapper` selected in the JSON as `CXX`.
