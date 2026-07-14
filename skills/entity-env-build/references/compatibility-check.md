# Compatibility Check

Use this reference after `entity-deps.local.json` is written or repaired, and before generating `env.sh`.

The check answers one question: can this exact `requirements.json + entity-deps.local.json` pair safely generate an environment for the requested Entity build?

Each result includes `checker_version` and `coverage`. Coverage values are
explicit: `implemented` means mechanically checked, `partial` means only part of
the contract is checked, and `not_implemented` means a pass result must not be
read as proof for that item.

Use the bundled checker first:

```bash
python3 scripts/entity_compat.py requirements.json --checkpoint entity-deps.local.json
```

If the checker cannot evaluate a site-specific condition, add evidence manually to the same result shape rather than bypassing the check.

## Required Result Shape

Write results to `entity-deps.local.json.compatibility`:

```json
{
  "status": "pass|fail|partial",
  "checker_version": 1,
  "checked_at": "",
  "coverage": {
    "requirements_checkpoint_match": "implemented",
    "compiler_signature": "partial",
    "cmake_package_probe": "not_implemented"
  },
  "checks": [
    {
      "id": "",
      "status": "pass|fail|warn|skip",
      "summary": "",
      "evidence": {},
      "remediation": ""
    }
  ],
  "issues": []
}
```

Only `status=pass` may continue to `env.sh` generation.

## 1. Request And Checkpoint Consistency

> **Implementation status: Mostly implemented** — `entity_compat.py` checks schema version, `ENTITY_CHECKOUT`/`ENTITY_WORKDIR` mismatch, `requirements.path` existence, and the reusable `requirements.embedded` snapshot for backend, MPI, output, profile, and compile-option drift.

Check:

- `entity-deps.local.json.requirements` points to or embeds the current `requirements.json`.
- `requirements.schema_version` and checkpoint `schema_version` are supported.
- `ENTITY_CHECKOUT` equals `requirements.entity.checkout_root`.
- `ENTITY_WORKDIR` equals `requirements.entity.workdir`.
- requested backend, MPI, output, dependency profile, and compile options match checkpoint selections.

Fail if the checkpoint was produced for a different Entity checkout, workdir, backend, MPI mode, output mode, or dependency profile.

## 2. Entity Version Profile

> **Implementation status: Implemented** — `entity_compat.py` validates profile detection, C++ standard, Kokkos/ADIOS2 version-family match, and ADIOS2 Kokkos support mode.

Reject Entity versions before `1.4.0`. `requirements.entity.dependency_profile`, when present, must be `modern`.

Check:

- Entity `1.4.0` and newer use `C++20`, Kokkos `5.x`, ADIOS2 `2.11.x`, and ADIOS2 Kokkos support `ON`.
- CUDA builds require Entity `1.4.3` or newer; Entity `1.4.0`–`1.4.2` are CPU-only.
- `requirements.compile.cxx_standard` matches the profile.
- selected Kokkos and ADIOS2 versions match the profile family.
- ADIOS2 `compile_config` or generated script metadata records the expected Kokkos support mode.

Fail on an unsupported Entity version or dependency-family mismatch.

## 3. Toolchain Consistency

> **Implementation status: Partial** — `entity_compat.py` validates that `compiler.cxx`/`cc` paths exist and are executable. Signature consistency across dependencies is not yet compared automatically.

Check:

- selected `cmake`, `compiler.cc`, and `compiler.cxx` exist and are executable.
- compiler can report a version.
- compiler supports the required C++ standard.
- all selected source-build or prefix dependencies record the same compiler signature, or an explicitly accepted compatible wrapper relationship.
- `compiler.host_cxx` is recorded when `compiler.cxx` is Kokkos `nvcc_wrapper`.

Evidence should include executable paths, version output, and compiler signature strings.

## 4. Backend Check

> **Implementation status: Partial** — CUDA nvcc_wrapper and ADIOS2 flag conflicts are checked. HIP toolkit prefix existence is checked. CPU backend checks and GPU architecture validation are not automated.

For `backend=cpu`:

- CPU compiler supports the required C++ standard.
- selected Kokkos has a CPU backend such as Serial/OpenMP enabled.

For `backend=cuda`:

- CUDA toolkit and `nvcc` exist.
- selected C++ compiler is Kokkos `nvcc_wrapper`.
- `NVCC_WRAPPER_DEFAULT_COMPILER` or `compiler.host_cxx` is valid.
- CUDA compiler and host compiler versions are mutually plausible.
- `requirements.environment.gpu_arch` is set or a safe default/auto-detection decision is recorded.
- selected Kokkos was built with CUDA and the requested architecture.

For `backend=hip`:

- ROCm/HIP tools exist, for example `hipcc`.
- selected Kokkos has HIP enabled.
- requested AMD GPU architecture is recorded.
- ROCm prefix is discoverable through `CMAKE_PREFIX_PATH` or equivalent environment.

## 5. MPI Check

> **Implementation status: Partial** — MPI selection presence is checked but MPI wrapper output, compiler-family compatibility, and ADIOS2/HDF5 serial/MPI consistency are not validated.

When `requirements.environment.mpi=false`:

- Entity build will use `mpi=OFF`.
- ADIOS2 and HDF5 selections are serial-compatible.
- no MPI-only ADIOS2/HDF5 target is selected accidentally.

When `requirements.environment.mpi=true`:

- `mpicxx` and `mpirun` exist and are executable.
- `mpicxx --show` or equivalent wrapper output is recorded.
- MPI wrapper uses the selected compiler family or a user-confirmed compatible compiler.
- ADIOS2 and HDF5 are MPI-enabled.
- Kokkos/ADIOS2/HDF5/Entity will be built in one compiler/MPI context.
- `gpu_aware_mpi=true` has evidence or an explicit risk acceptance.

## 6. Dependency Presence And Discovery

> **Implementation status: Implemented** — `entity_compat.py` validates that `prefix`, `cmake_config`, and `bin` paths exist on disk. Structural completeness (non-empty fields) is checked separately.

For each required dependency, check both files and CMake discovery.

Always required:

- CMake executable.
- selected C/C++ compiler.
- Kokkos prefix or source-build result.
- Kokkos `KokkosConfig.cmake`.

Required when `output=true`:

- HDF5 prefix or source-build result.
- HDF5 CMake config, usually `hdf5-config.cmake` or `HDF5Config.cmake`.
- ADIOS2 prefix or source-build result.
- ADIOS2 `ADIOS2Config.cmake`.

Run or emulate a CMake package lookup when practical:

```bash
cmake -S <probe-src> -B <probe-build> -DCMAKE_PREFIX_PATH="<paths>"
```

At minimum, verify that every recorded `cmake_config` path exists and its prefix is included in `paths.CMAKE_PREFIX_PATH`.

## 7. ADIOS2, HDF5, And Kokkos Mode Compatibility

> **Implementation status: Partial** — ADIOS2 Kokkos support mode vs. profile is checked. ADIOS2_USE_Kokkos + CUDA conflict is detected. Serial/MPI mode consistency is not yet automated.

Check:

- ADIOS2/HDF5 serial-vs-MPI mode matches `requirements.environment.mpi`.
- ADIOS2 Kokkos support is `ON` only for the `modern` profile unless explicitly overridden.
- ADIOS2 must not enable `ADIOS2_USE_Kokkos=ON` and `ADIOS2_USE_CUDA=ON` at the same time.
- If ADIOS2 Kokkos support is `ON`, Kokkos prefix is discoverable before ADIOS2 in `CMAKE_PREFIX_PATH`.
- ADIOS2 and HDF5 were built with a compatible compiler signature.
- HDF5 C and C++ library availability matches the ADIOS2 build.

## 8. Runtime Loader Paths

> **Implementation status: Not yet implemented** — Path entries recorded in `paths.*` are not yet validated for existence.

Check:

- every `PATH`, `CMAKE_PREFIX_PATH`, `LD_LIBRARY_PATH`, and `DYLD_LIBRARY_PATH` entry recorded in checkpoint exists unless it is intentionally absent on the current OS.
- library directories for selected dependencies are included where dynamic libraries are used.
- no source checkout build directory is required as a runtime library path unless explicitly recorded.

On macOS, check `DYLD_LIBRARY_PATH`; on Linux, check `LD_LIBRARY_PATH`.

## 9. Source-Build Script Readiness

> **Implementation status: Partial** — Source-build scripts with `status=generated` and no install evidence are flagged. Individual script option validation is not automated.

When selected dependencies have provider `source-build`:

- generated script path exists and is executable.
- script source is recorded in `build_scripts`.
- generated version profile and C++ standard match `requirements`.
- script install prefix matches selected dependency prefix.
- build logs exist after execution, or status is still `generated` and compatibility must remain `partial`/`fail`.

Do not mark compatibility `pass` for a dependency that only has a generated script but no completed install evidence.

## 10. Entity Build Readiness

> **Implementation status: Not yet implemented** — Performed implicitly by `generate_entity_build_sh.py` (pgen requirement, CMake option derivation). Not a standalone check in `entity_compat.py`.

Check:

- `requirements.compile.pgen` is set.
- selected dependency paths can produce the CMake options needed by `entity-build.sh`.
- `requirements.compile.cxx_standard`, backend, MPI, output, debug, tests, precision, deposit, and shape order are internally consistent.
- expected build directory is under `ENTITY_WORKDIR` unless the user explicitly chose otherwise.

This check does not compile Entity. It only decides whether generating `env.sh` and then `entity-build.sh` is safe.

## Status Rules

Use `fail` when a required dependency, required path, version family, compiler mode, backend mode, or MPI/output mode is incompatible.

Use `partial` only when the missing item is expected to be created next and no Entity build will start before rechecking, for example generated source-build scripts that have not run yet.

Use `pass` only when all required selected dependencies are installed/discoverable and every requested mode has evidence.
