# Dependency Policy

Use this reference when selecting C++ dependency sources during environment probing (Phase 2).

## Priority Order

For C++ compilers and libraries, search in this order:

0. **Site deps registry** — verified stacks exported by `entityctl site deps
   <site> --json` (signature matching the current requirements) are reused
   directly for their packages; see the lookup order in SKILL.md section 2.
   The `env_sh` path in the registry is for human reading and auditing
   only — the env-build environment is always rebuilt by
   `entity_generate.py env` from the current checkpoint's packages; the
   registry's env.sh is never sourced directly
1. **System modules/packages** — `module load`, `dnf`/`apt`/`brew`, or system paths
2. **Spack** — `spack find`, `spack load`
3. **Source build** — last resort; generate scripts with `entity_generate.py deps`

## Conda Warning

Do **not** use conda to provide C++ build tools. conda's bundled `libstdc++` and linker configuration cause subtle ABI problems when mixed with system- or Spack-built libraries.

## Python Environment

For Python, conda is the preferred and recommended choice. Python runtime dependencies (e.g., analysis scripts) follow the standard conda/pip workflow.

## Core Dependencies

Always required:

- CMake (minimum version: see `entity_schema.py:MIN_CMAKE_VERSION`)
- A C++ compiler (GCC, Clang, or `hipcc` for HIP)
- Kokkos (version family determined by the Entity profile)

## Conditional Dependencies

| Condition | Required | Notes |
|-----------|----------|-------|
| `environment.backend=cuda` | CUDA toolkit, `nvcc`, Kokkos `nvcc_wrapper` | Record both the wrapper path and the host compiler |
| `environment.backend=hip` | HIP/ROCm toolkit, `hipcc` | Include ROCm/DTK version preference |
| `environment.mpi=true` | `mpicxx`, `mpirun`, MPI modules | Do not enable merely because mpicxx exists; OpenMPI must be >= 5.0.0 (see below) |
| `environment.output=true` | ADIOS2 + HDF5 | Serial/MPI context must match the MPI requirement |

## Profile Matching

Entity `1.4.0` and newer use one supported dependency profile:

| Profile | Entity version | C++ standard | Kokkos | ADIOS2 | ADIOS2 Kokkos support |
|---------|---------------|--------------|--------|--------|-----------------------|
| `modern` | >= 1.4.0 | 20 | 5.x | 2.11.x | ON |

Entity versions before `1.4.0` are not supported.
Entity `1.4.0`–`1.4.2` supports CPU only; CUDA requires Entity `1.4.3` or newer.

## OpenMPI Minimum Version

When the selected MPI is OpenMPI, the version must satisfy
`entity_schema.py:MIN_OPENMPI_VERSION` (>= 5.0.0). Older OpenMPI 4.x
versions have known ORTE/PMI launch failures under `srun`. The compatibility
check `mpi.openmpi_min_version` fails when the version is below the minimum;
select a newer module or build OpenMPI 5.x from source instead of overriding.
