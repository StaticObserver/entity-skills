# MPI Build Notes

## Policy

OpenMPI source builds are **intentionally not auto-generated**. Prefer, in this order:

1. System MPI (`mpicxx`, `mpirun` in PATH)
2. Module MPI (`module load openmpi/...`)
3. User-provided MPI (user-specified prefix)
4. Source build (only with explicit user approval and a reviewed build script)

## Why Not Auto-Generate

- MPI builds depend heavily on site-specific networking (InfiniBand, UCX, libfabric)
- A wrong MPI configuration silently produces binaries that build fine but hang at runtime
- The system/module MPI is almost always the right choice

## When MPI Is Needed

Only when `requirements.environment.mpi=true`. Do not enable MPI merely
because mpicxx exists on the system.

## MPI Consistency Requirements

When MPI is enabled:
- `mpicxx` and `mpirun` must exist and be executable
- The MPI wrapper must use the selected compiler family
- Kokkos, ADIOS2, and HDF5 must all be built in the same MPI/compiler context
- GPU-aware MPI (`gpu_aware_mpi=true`) requires explicit evidence or risk acceptance

## If a Source Build Is Unavoidable

Record the reason in `entity-deps.local.json.decisions`. The build script
(`entity_generate.py deps --deps mpi`) generates a stop script that explains
why auto-generation is not supported.
