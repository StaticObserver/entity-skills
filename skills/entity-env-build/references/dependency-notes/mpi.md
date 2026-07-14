# MPI Build Notes

## Policy

OpenMPI source build is **intentionally not auto-generated**. Prefer in this order:

1. System MPI (`mpicxx`, `mpirun` in PATH)
2. Module MPI (`module load openmpi/...`)
3. User-provided MPI (user specifies prefix)
4. Source build (only with explicit user approval and a reviewed build script)

## Why Not Auto-Generated

- MPI build depends heavily on site-specific networking (InfiniBand, UCX, libfabric)
- Wrong MPI configuration silently produces correct builds that hang at runtime
- System/module MPI is almost always the right choice

## When MPI Is Needed

Only when `requirements.environment.mpi=true`. Do not enable MPI just because
mpicxx exists on the system.

## MPI Consistency Requirements

When MPI is enabled:
- `mpicxx` and `mpirun` must exist and be executable
- MPI wrapper must use the selected compiler family
- Kokkos, ADIOS2, and HDF5 must all be built in the same MPI/compiler context
- GPU-aware MPI (`gpu_aware_mpi=true`) requires explicit evidence or risk acceptance

## If Source Build Is Required

Record the reason in `entity-deps.local.json.decisions`. The build script
(`entity_generate.py deps --deps mpi`) emits a stop script that explains why
auto-generation is not supported.
