# Dependency Build Scripts

Use this reference when local source builds are required after existing system/module/prefix dependencies cannot satisfy `requirements.json`.

## Source Of Rules

The build scripts should follow the same decision model as Entity's `dependencies.py` and the official dependency page:

- Prefer existing system/module `MPI` and `HDF5` when available.
- Use source builds as a last resort.
- Keep compiler/toolchain consistent across Kokkos, HDF5, ADIOS2, MPI, and Entity.
- Use the supported Entity profile: C++20 + Kokkos 5.x + ADIOS2 2.11.x.
- Build ADIOS2 with Kokkos support.
- For CUDA builds, use Kokkos `nvcc_wrapper` after Kokkos is installed.
- Keep generated dependency scripts in `ENTITY_WORKDIR/deps/scripts/`.

Official reference: https://entity-toolkit.github.io/wiki/content/1-getting-started/2-dependencies/

## Script Generator Role

Use `scripts/entity_generate.py deps` to generate local dependency build scripts adapted to this skill's layout.

Expected interface:

```bash
python3 scripts/entity_generate.py deps requirements.json \
  --deps kokkos,hdf5,adios2 \
  --checkpoint entity-deps.local.json
```

Default output directory:

```text
$ENTITY_WORKDIR/deps/scripts/
```

Generated scripts should be reviewed before execution. They are not the source of truth; `requirements.json` and `entity-deps.local.json` are.

Current generator scope:

- `kokkos`, `hdf5`, and `adios2` source-build scripts are generated directly.
- `mpi` emits a deliberate stop script until a reviewed OpenMPI/UCX policy is added.
- every script writes configure/build/install logs under `$ENTITY_WORKDIR/build-logs`.
- Kokkos and ADIOS2 scripts include the official baseline switches such as `CMAKE_CXX_EXTENSIONS=OFF`, position-independent code, disabled ADIOS2 Python/Fortran/ZeroMQ, disabled ADIOS2 tests, and disabled ADIOS2 examples.
- exact Kokkos/ADIOS2/HDF5 source tags can be pinned through `requirements.environment.dependency_versions`.

## Dependency Order

Only generate scripts for missing or incompatible dependencies.

Recommended order:

```text
MPI only if required and no compatible system/module MPI exists
Kokkos
HDF5 only if output=true
ADIOS2 only if output=true
```

## Generated Script Requirements

Every generated script should:

- use `set -euo pipefail`;
- write logs under `$ENTITY_WORKDIR/build-logs`;
- install under a prefix recorded in `entity-deps.local.json`;
- use compilers from `entity-deps.local.json.selected.compiler`;
- preserve MPI on/off and backend choices from `requirements.json`;
- avoid writing into `ENTITY_CHECKOUT`;
- be idempotent enough to re-run after deleting its build directory.

## Recording

After generating scripts, update `entity-deps.local.json.build_scripts`:

```json
{
  "build_scripts": {
    "directory": "/path/to/ENTITY_WORKDIR/generated/source-build-scripts",
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

After a dependency build script is executed, update the corresponding selected dependency entry with prefix, version if known, CMake config path, compiler signature, and validation evidence.
