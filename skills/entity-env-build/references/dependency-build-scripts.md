# Dependency Build Scripts

Use this reference when the existing system/module/prefix dependencies cannot satisfy `requirements.json` and a local source build is required.

## Source of the Rules

Build scripts should follow the same decision model as Entity's `dependencies.py` and the official dependencies page:

- Prefer existing system/module `MPI` and `HDF5` (when available).
- Source builds are a last resort.
- Keep the compiler/toolchain consistent across Kokkos, HDF5, ADIOS2, MPI, and Entity.
- Use the supported Entity profile: C++20 + Kokkos 5.x + ADIOS2 2.11.x.
- Build ADIOS2 with Kokkos support.
- For CUDA builds, use the Kokkos `nvcc_wrapper` after the Kokkos installation completes.
- Generated dependency scripts are stored under the execution site's `entity.deps_root/scripts/`.

Official reference: https://entity-toolkit.github.io/wiki/content/1-getting-started/2-dependencies/

## Role of the Script Generator

Use `scripts/entity_generate.py deps` to generate local dependency build scripts adapted to this skill's directory layout.

Expected interface:

```bash
python3 scripts/entity_generate.py deps requirements.json \
  --deps kokkos,hdf5,adios2 \
  --checkpoint entity-deps.local.json
```

Default output directory:

```text
<deps_root>/scripts/
```

Generated scripts should be reviewed before execution. They are not a source of truth; `requirements.json` and `entity-deps.local.json` are.

Current generator scope:

- Directly generates source build scripts for `kokkos`, `hdf5`, and `adios2`.
- `mpi` generates a script that intentionally stops until a reviewed OpenMPI/UCX policy is added.
- Each script writes configure/build/install logs under `entity.artifacts_root/build-logs`.
- The Kokkos and ADIOS2 scripts include the official baseline switches, such as `CMAKE_CXX_EXTENSIONS=OFF`, position-independent code, disabling ADIOS2 Python/Fortran/ZeroMQ, disabling ADIOS2 tests, and disabling ADIOS2 examples.
- Exact Kokkos/ADIOS2/HDF5 source tags can be pinned via `requirements.environment.dependency_versions`.

## Dependency Order

Generate scripts only for missing or incompatible dependencies.

Recommended order:

```text
MPI only if required and no compatible system/module MPI exists
Kokkos
HDF5 only if output=true
ADIOS2 only if output=true
```

## Requirements for Generated Scripts

Each generated script should:

- use `set -euo pipefail`;
- write logs under `entity.artifacts_root/build-logs`;
- install into the prefix recorded in `entity-deps.local.json`;
- use the compiler from `entity-deps.local.json.selected.compiler`;
- preserve the MPI on/off and backend selections from `requirements.json`;
- avoid writing to `ENTITY_CHECKOUT`;
- be idempotent enough to be re-run after deleting its build directory.

## Recording

After generating the scripts, update `entity-deps.local.json.build_scripts`:

```json
{
  "build_scripts": {
    "directory": "/absolute/deps_root/scripts",
    "generated_at": "",
    "scripts": {
      "kokkos": {
        "path": "",
        "status": "generated",
        "source": "entity-env-build/scripts/entity_generate.py deps",
        "based_on": "Entity dependencies.py/wiki dependency generator"
      }
    }
  }
}
```

After the dependency build scripts have been executed, update the corresponding selected-dependency entries with the prefix, version (if known), CMake config path, compiler signature, and verification evidence.
