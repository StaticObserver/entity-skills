# Dependency Policy

Use this reference when selecting C++ dependency sources during environment probing (Phase 2).

## Priority Order

For C++ compilers and libraries, search in this order:

1. **System modules/packages** — `module load`, `dnf`/`apt`/`brew`, or system paths
2. **Spack** — `spack find`, `spack load`
3. **Source-build** — last resort; generate scripts with `entity_generate.py deps`

## Conda Warning

Do **not** use conda for C++ build tools. Conda's bundled `libstdc++` and linker configuration cause subtle ABI issues when mixed with system or Spack-built libraries.

## Python Environment

For Python, conda is the first and recommended choice. Python runtime dependencies (e.g. for analysis scripts) follow the standard conda/pip workflow.

## Core Dependencies

These are always required:

- CMake (minimum version in `entity_schema.py:MIN_CMAKE_VERSION`)
- A C++ compiler (GCC, Clang, or `hipcc` for HIP)
- Kokkos (version family determined by Entity profile)

## Conditional Dependencies

| Condition | Required | Notes |
|-----------|----------|-------|
| `environment.backend=cuda` | CUDA toolkit, `nvcc`, Kokkos `nvcc_wrapper` | Record both wrapper path and host compiler |
| `environment.backend=hip` | HIP/ROCm toolkit, `hipcc` | Include ROCm/DTK version preference |
| `environment.mpi=true` | `mpicxx`, `mpirun`, MPI modules | Don't enable just because mpicxx exists |
| `environment.output=true` | ADIOS2 + HDF5 | Match serial/MPI context with MPI requirement |

## Profile Matching

Entity `1.4.0` and newer use one supported dependency profile:

| Profile | Entity Version | C++ Standard | Kokkos | ADIOS2 | ADIOS2 Kokkos Support |
|---------|---------------|--------------|--------|--------|-----------------------|
| `modern` | >= 1.4.0 | 20 | 5.x | 2.11.x | ON |

Entity versions before `1.4.0` are unsupported.
Entity `1.4.0`–`1.4.2` are CPU-only; CUDA requires Entity `1.4.3` or newer.
