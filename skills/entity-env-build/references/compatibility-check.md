# Compatibility Check

Use this reference after `entity-deps.local.json` has been written or
repaired, and before generating `env.sh`.

The check answers one question: can this exact pair of
`requirements.json + entity-deps.local.json` safely generate an environment
for the requested Entity build?

Every result includes `checker_version` and `coverage`. Coverage values have
precise meanings: `implemented` means a mechanical check was performed,
`partial` means only part of the contract was checked, and `not_implemented`
means a pass result must never be read as proof of that item.

Prefer the bundled checker:

```bash
python3 scripts/entity_compat.py requirements.json --checkpoint entity-deps.local.json
```

If the checker cannot evaluate a site-specific condition, manually add the
evidence into the same result structure instead of bypassing the check.

## Required result structure

Write the result into `entity-deps.local.json.compatibility`:

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

Only `status=pass` may proceed to `env.sh` generation.

## 1. Request and checkpoint consistency

> **Implementation status: mostly implemented** — `entity_compat.py` checks
> schema versions, execution `site_id` and independent
> source/build/dependency/artifact path mismatches, `requirements.path`
> existence, and drift of the reusable embedded request on backend, MPI,
> output, profile, and compile options.

Checks:

- `entity-deps.local.json.requirements` points to or embeds the current
  `requirements.json`.
- `requirements.schema_version` and the checkpoint's `schema_version` are
  supported.
- The execution site and all resolved schema-v2 Entity paths equal the
  current requirements; schema-v1 `checkout_root/workdir` comparison is for
  legacy compatibility only.
- The requested backend, MPI, output, dependency profile, and compile options
  match the choices in the checkpoint.
- `decisions.parameters` holds a confirmation record whose digest matches the
  parameter card of the current requirements (the `parameters.confirmation`
  check). A missing or stale record fails; before generating `env.sh`,
  re-confirm with `entity_checkpoint.py confirm <requirements> --checkpoint
  <checkpoint> --by <actor>`. An explicit
  `decisions.parameters_confirmation_override` demotes this check to a
  warning like any other recorded override.

Fail if the checkpoint was generated for a different Entity checkout, workdir,
backend, MPI mode, output mode, or dependency profile.

## 2. Entity version profile

> **Implementation status: implemented** — `entity_compat.py` verifies
> profile detection, C++ standard, Kokkos/ADIOS2 version family matching, and
> the ADIOS2 Kokkos support mode.

Reject Entity versions before `1.4.0`. `requirements.entity.dependency_profile`,
if present, must be `modern`.

Checks:

- Entity `1.4.0` and newer use `C++20`, Kokkos `5.x`, ADIOS2 `2.11.x`, with
  ADIOS2 Kokkos support `ON`.
- CUDA builds require Entity `1.4.3` or newer; Entity `1.4.0`–`1.4.2` support
  CPU only.
- `requirements.compile.cxx_standard` matches the profile.
- The selected Kokkos and ADIOS2 versions match the profile version families.
- The ADIOS2 `compile_config` or generated script metadata records the
  expected Kokkos support mode.

Fail on unsupported Entity versions or dependency family mismatches.

## 3. Toolchain consistency

> **Implementation status: partially implemented** — `entity_compat.py`
> verifies that `compiler.cxx`/`cc` paths exist and are executable. Signature
> consistency across dependencies is not yet compared automatically.

Checks:

- The selected `cmake`, `compiler.cc`, and `compiler.cxx` exist and are
  executable.
- The compiler can report its version.
- The compiler supports the required C++ standard.
- All selected source-built or prefix dependencies record the same compiler
  signature, or record an explicitly accepted compatible wrapper
  relationship.
- When `compiler.cxx` is the Kokkos `nvcc_wrapper`, record
  `compiler.host_cxx`.
- When the selected MPI is OpenMPI, its recorded version satisfies
  `entity_schema.py:MIN_OPENMPI_VERSION` (>= 5.0.0).

Evidence should include executable paths, version output, and the compiler
signature strings.

## 4. Backend checks

> **Implementation status: partially implemented** — CUDA nvcc_wrapper and
> ADIOS2 flag conflicts are checked. HIP toolkit prefix existence is checked.
> CPU backend checks and GPU architecture validation are not yet automated.

For `backend=cpu`:

- The CPU compiler supports the required C++ standard.
- The selected Kokkos enables a CPU backend such as Serial/OpenMP.

For `backend=cuda`:

- The CUDA toolkit and `nvcc` exist.
- The selected C++ compiler is the Kokkos `nvcc_wrapper`.
- `NVCC_WRAPPER_DEFAULT_COMPILER` or `compiler.host_cxx` is valid.
- The CUDA compiler and host compiler versions are mutually reasonable.
- `requirements.environment.gpu_arch` is set, or a safe default/auto-detect
  decision is recorded.
- The selected Kokkos was built with CUDA and the requested architecture.

For `backend=hip`:

- ROCm/HIP tools exist, e.g. `hipcc`.
- The selected Kokkos has HIP enabled.
- The requested AMD GPU architecture is recorded.
- The ROCm prefix is discoverable via `CMAKE_PREFIX_PATH` or an equivalent
  environment variable.

## 5. MPI checks

> **Implementation status: partially implemented** — MPI selection existence
> is checked, but MPI wrapper output, compiler family compatibility, and
> ADIOS2/HDF5 serial/MPI consistency are not yet verified.

When `requirements.environment.mpi=false`:

- The Entity build will use `mpi=OFF`.
- The ADIOS2 and HDF5 selections are serial-compatible.
- No MPI-only ADIOS2/HDF5 targets are accidentally selected.

When `requirements.environment.mpi=true`:

- `mpicxx` and `mpirun` exist and are executable.
- The output of `mpicxx --show` or an equivalent wrapper is recorded.
- The MPI wrapper uses the selected compiler family, or a user-confirmed
  compatible compiler.
- ADIOS2 and HDF5 have MPI enabled.
- Kokkos/ADIOS2/HDF5/Entity will be built in the same compiler/MPI context.
- `gpu_aware_mpi=true` has evidence or an explicit risk acceptance.

## 6. Dependency existence and discovery

> **Implementation status: implemented** — `entity_compat.py` verifies that
> `prefix`, `cmake_config`, and `bin` paths exist on disk. Structural
> completeness (non-empty fields) is checked separately.

For each required dependency, check both files and CMake discovery.

Always required:

- The CMake executable.
- The selected C/C++ compiler.
- A Kokkos prefix or source build result.
- The Kokkos `KokkosConfig.cmake`.

Required when `output=true`:

- An HDF5 prefix or source build result.
- The HDF5 CMake config, usually `hdf5-config.cmake` or `HDF5Config.cmake`.
- An ADIOS2 prefix or source build result.
- The ADIOS2 `ADIOS2Config.cmake`.

When feasible, run or simulate a CMake package probe:

```bash
cmake -S <probe-src> -B <probe-build> -DCMAKE_PREFIX_PATH="<paths>"
```

At minimum, verify that each recorded `cmake_config` path exists and that its
prefix is included in `paths.CMAKE_PREFIX_PATH`.

## 7. ADIOS2, HDF5, and Kokkos mode compatibility

> **Implementation status: partially implemented** — The relationship between
> the ADIOS2 Kokkos support mode and the profile is checked. The
> ADIOS2_USE_Kokkos + CUDA conflict is detected. Serial/MPI mode consistency
> is not yet automated.

Checks:

- ADIOS2/HDF5 serial and MPI modes match `requirements.environment.mpi`.
- ADIOS2 Kokkos support is `ON` only for the `modern` profile, unless
  explicitly overridden.
- ADIOS2 must not enable both `ADIOS2_USE_Kokkos=ON` and
  `ADIOS2_USE_CUDA=ON` at the same time.
- If ADIOS2 Kokkos support is `ON`, the Kokkos prefix must be discoverable in
  `CMAKE_PREFIX_PATH` ahead of ADIOS2.
- ADIOS2 and HDF5 were built with compatible compiler signatures.
- HDF5 C and C++ library availability matches the ADIOS2 build.

## 8. Runtime loader paths

> **Implementation status: not implemented** — Path entries recorded in
> `paths.*` are not yet verified for existence.

Checks:

- Every `PATH`, `CMAKE_PREFIX_PATH`, `LD_LIBRARY_PATH`, and
  `DYLD_LIBRARY_PATH` entry recorded in the checkpoint exists, unless it is
  intentionally absent on the current OS.
- When dynamic libraries are used, the library directories of the selected
  dependencies are included.
- Unless explicitly recorded, the build directory of the source checkout is
  not needed as a runtime library path.

Check `DYLD_LIBRARY_PATH` on macOS; check `LD_LIBRARY_PATH` on Linux.

## 9. Source build script readiness

> **Implementation status: partially implemented** — Source build scripts
> with `status=generated` and no install evidence are flagged. Individual
> script option validation is not yet automated.

When the provider of a selected dependency is `source-build`:

- The generated script path exists and is executable.
- The script provenance is recorded in `build_scripts`.
- The generated version profile and C++ standard match `requirements`.
- The script install prefix matches the selected dependency prefix.
- After execution, build logs exist, or the status is still `generated` and
  compatibility must remain `partial`/`fail`.

Do not mark compatibility as `pass` for dependencies that only have generated
scripts without completed install evidence.

## 10. Entity build readiness

> **Implementation status: not implemented** — Performed implicitly by
> `generate_entity_build_sh.py` (pgen requirement, CMake option derivation).
> Not a standalone check in `entity_compat.py`.

Checks:

- `requirements.compile.pgen` is set.
- The selected dependency paths can produce the CMake options required by
  `entity-build.sh`.
- `requirements.compile.cxx_standard`, backend, MPI, output, debug, tests,
  precision, deposit, and shape order are internally consistent.
- The expected build directory equals the immutable `entity.build_root`,
  unless the user explicitly recorded another build identity path.

This check does not compile Entity. It only decides whether it is safe to
generate `env.sh` and then `entity-build.sh`.

## Status rules

Use `fail` when a required dependency, required path, version family,
compiler mode, backend mode, or MPI/output mode is incompatible.

Use `partial` only when the missing items are expected to be created next and
no Entity build will start before a re-check; for example, a source build
script that has been generated but not yet run.

Use `pass` only when all required selected dependencies are
installed/discoverable and every requested mode has evidence.
