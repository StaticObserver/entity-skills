# JSON Contracts

Use this reference when creating, repairing, or validating `requirements.json` and `entity-deps.local.json`.

**Authoritative schema source**: `scripts/entity_schema.py` — this document is the human-readable mirror. When they differ, the Python file is the source of truth.

## File Roles

`requirements.json` is the source of truth for the current Entity build request. It changes when the user changes backend, MPI, output, PGen, debug/test intent, build directory, install choice, or other compile options.

`entity-deps.local.json` is the local dependency checkpoint. It is reusable only when it satisfies the current `requirements.json`.

`env.sh` is derived from `entity-deps.local.json`.

`entity-build.sh` is derived from `requirements.json + env.sh`.

Do not reconstruct state from chat history or transient shell variables when these files exist.

## Path Roles

Require these locations before writing artifacts:

- `ENTITY_CHECKOUT`: Entity source checkout (e.g. `$ENTITY_WORKDIR/entity-1.4.3/`).
- `ENTITY_WORKDIR`: root of the entity workspace. Contains Entity sources, shared `deps/`, and `problems/`.

Default layout:

```text
$ENTITY_WORKDIR/                          ← ROOT
├── entity-<version>/                     ← ENTITY_CHECKOUT
├── deps/                                 ← shared dependencies
│   ├── kokkos/<version>/
│   ├── hdf5/<version>/
│   ├── adios2/<version>/
│   ├── sources/                          ← dep source code
│   └── scripts/                          ← generated build scripts
└── problems/
    └── <pgen>/
        ├── build/                        ← cmake build tree
        └── _build/                       ← tool-generated artifacts
            ├── requirements.json
            ├── entity-deps.local.json
            ├── .entity-session.json
            ├── env.sh
            ├── entity-build.sh
            ├── build-logs/
            └── generated/source-builds/
```

Keep `ENTITY_CHECKOUT` clean by default. Do not write control JSON, generated scripts, or CMake build directories into the source tree unless the user explicitly asks.

## requirements.json

Required shape:

```json
{
  "schema_version": 1,
  "generated_at": "",
  "entity": {
    "checkout_root": "",
    "version_bucket": "",
    "dependency_profile": "modern",
    "workdir": ""
  },
  "environment": {
    "backend": "cuda|hip|cpu|unspecified",
    "gpu_arch": "",
    "mpi": false,
    "gpu_aware_mpi": false,
    "output": true,
    "dependency_versions": {
      "kokkos": "",
      "adios2": "",
      "hdf5": ""
    },
    "dependency_policy": "reuse-existing|allow-local-build|unspecified"
  },
  "compile": {
    "cxx_standard": "20",
    "pgen": "",
    "pgens": "",
    "precision": "single",
    "deposit": "zigzag",
    "shape_order": 1,
    "debug": false,
    "tests": false,
    "build_intent": "smoke|production|debug|unspecified",
    "build_dir": "",
    "install": false,
    "install_prefix": "",
    "jobs": "",
    "cmake_cxx_flags": "",
    "extra_cmake_options": []
  },
  "artifacts": {
    "dependency_checkpoint_json": "",
    "env_sh": "",
    "entity_build_sh": "",
    "logs_dir": "",
    "generated_dir": ""
  },
  "decisions": {},
  "status": {
    "complete": false,
    "ready_for_dependency_planning": false,
    "ready_for_entity_build_script": false
  },
  "build_result": {}
}
```

Completion rules:

- `entity.checkout_root` is required before generating `entity-build.sh`.
- `entity.workdir` is required before writing artifacts.
- Entity versions before `1.4.0` are unsupported. `entity.dependency_profile`, when present, must be `modern`.
- Entity `1.4.0`–`1.4.2` support CPU builds only; `environment.backend=cuda` requires Entity `1.4.3` or newer.
- `compile.cxx_standard` must be `20`.
- `environment.dependency_versions` may pin exact source-build tags. If omitted, generated source-build scripts use and record the supported defaults.
- `compile.pgen` or `compile.pgens` is required before generating `entity-build.sh`. Use one, not both.
- `compile.build_dir` may be generated if omitted, but must be written back before script generation.
- `environment.output=true` must align with `compile` output option in generated CMake.
- `environment.mpi` and `environment.gpu_aware_mpi` must align with generated CMake.
- `environment.backend` must align with generated Kokkos backend options.
- The supported profile requires Kokkos `5.x`, ADIOS2 `2.11.x`, and ADIOS2 built with Kokkos support.

## entity-deps.local.json

Required shape:

```json
{
  "schema_version": 1,
  "generated_at": "",
  "requirements": {
    "path": "",
    "embedded": {
      "entity": {},
      "environment": {},
      "compile": {}
    }
  },
  "target": {},
  "entity": {},
  "candidates": {},
  "selected": {
    "cmake": {},
    "compiler": {},
    "gpu_toolkit": {},
    "mpi": {},
    "kokkos": {},
    "hdf5": {},
    "adios2": {}
  },
  "decisions": {},
  "paths": {
    "PATH": [],
    "CMAKE_PREFIX_PATH": [],
    "LD_LIBRARY_PATH": [],
    "DYLD_LIBRARY_PATH": [],
    "extra_env": {},
    "modules": [],
    "pre_commands": []
  },
  "build_scripts": {},
  "compatibility": {
    "status": "unknown|pass|partial|fail",
    "checked_at": "",
    "checks": [],
    "issues": []
  },
  "env_sh": {
    "path": "",
    "status": "missing|generated|failed",
    "generated_at": "",
    "validation": {}
  },
  "status": {
    "checkpoint": "missing|partial|complete|stale|incompatible",
    "satisfies_requirements_json": false,
    "ready_for_entity_build": false,
    "reuse_notes": []
  }
}
```

Selected dependency entries should use this shape when possible:

```json
{
  "name": "",
  "version": "",
  "provider": "module|system|local-prefix|source-build|entity-dependencies|unknown|none",
  "prefix": "",
  "bin": "",
  "include": "",
  "lib": "",
  "cmake_config": "",
  "compiler_signature": "",
  "mpi_signature": "",
  "environment": {},
  "compile_config": {},
  "validation": {}
}
```

`requirements.embedded` stores only the fields that decide whether a checkpoint
can be reused for the current request: checkout/workdir/version profile,
backend, output, MPI mode, GPU-aware MPI, pgen/pgens, C++ standard, precision,
deposit, shape order, debug/tests, and build intent. `entity_compat.py` fails
when this snapshot differs from the current `requirements.json`.

## Modules

System modules to load in `env.sh` can be recorded as an ordered list under `paths.modules`:

```json
{
  "paths": {
    "modules": [
      "compiler/gcc/12.2.0",
      "compiler/cmake/3.25.0",
      "compiler/dtk/24.04"
    ]
  }
}
```

Each entry generates `module load <name>` inside an `if command -v module` guard. Modules load before PATH setup.

## Pre-Commands

Arbitrary shell commands injected into `env.sh` before PATH/modules setup. Use for sourcing module system init scripts or setting up non-standard environments:

```json
{
  "paths": {
    "pre_commands": [
      "source /etc/profile.d/modules.sh",
      "export CUSTOM_VAR=value"
    ]
  }
}
```

Each string is emitted verbatim as a shell line. Use sparingly — prefer dedicated fields (`extra_env`, `modules`) when they exist.

## Extra Environment Variables

Site-specific environment variables that `entity_generate.py env` should write into `env.sh` can be recorded under `paths.extra_env`:

```json
{
  "paths": {
    "extra_env": {
      "ROCM_PATH": "/opt/rocm",
      "OMPI_CC": "hipcc",
      "OMPI_CXX": "hipcc",
      "HSA_OVERRIDE_GFX_VERSION": "9.0.6"
    }
  }
}
```

Each key-value pair becomes `export KEY=VALUE` in the generated `env.sh`. Use this for system-specific variables that the generic path-derivation logic cannot know about (DTK/ROCm paths, MPI wrapper overrides, GPU runtime environment settings).

## CUDA-specific selected fields

```json
{
  "selected": {
    "compiler": {
      "cc": "/path/to/gcc",
      "cxx": "/path/to/kokkos/bin/nvcc_wrapper",
      "host_cxx": "/path/to/g++"
    },
    "kokkos": {
      "nvcc_wrapper": "/path/to/kokkos/bin/nvcc_wrapper",
      "cuda_arch": "AMPERE80"
    }
  }
}
```

MPI-specific selected fields:

```json
{
  "selected": {
    "mpi": {
      "enabled": true,
      "mpicxx": "/path/to/mpicxx",
      "mpirun": "/path/to/mpirun",
      "wrapper_show": "",
      "gpu_aware_mpi": false
    }
  }
}
```

## Decisions Overrides

Users may acknowledge known compatibility-check deviations via `decisions` overrides. An override entry in `entity-deps.local.json.decisions` tells `entity_compat.py` to downgrade a specific FAIL check to WARN, allowing the build to proceed.

```json
{
  "decisions": {
    "nvcc_version_override": {
      "value": "accept nvcc 12.0 for 12.2 requirement",
      "source": "user",
      "confirmed_at": "2026-06-22T00:00:00Z",
      "reason": "CUDA 12.0 is the only available toolkit on this node"
    }
  }
}
```

Override keys are mapped to compat check IDs in `entity_schema.py:COMPAT_OVERRIDE_MAP`. An override is valid when its value is truthy (non-empty string, true bool, or dict with `value`/`confirmed_at`/`source`).

Current override map:
| Check ID | Override Key |
|----------|--------------|
| `compiler.version.nvcc` | `nvcc_version_override` |

Separate from check-specific overrides, `decisions.compatibility_warnings_accepted`
can acknowledge a warning-only compatibility result for explicit debugging flows.
Generation commands still require `--allow-warnings`; by default only
`compatibility.status=pass` may generate `env.sh` or `entity-build.sh`.

## Compatibility Result

`compatibility.status=pass` requires:

- `scripts/entity_compat.py` has written the latest compatibility result;
- current `requirements.json` is represented in `entity-deps.local.json.requirements`;
- required dependencies are selected;
- selected C++ standard, Kokkos family, ADIOS2 family, and ADIOS2 Kokkos support match the Entity version profile;
- selected compiler/toolchain is consistent;
- CUDA builds use Kokkos `nvcc_wrapper`;
- MPI-on/off is consistent across selected dependencies;
- ADIOS2/HDF5 serial/MPI mode is consistent with MPI requirement;
- required `*Config.cmake` paths or prefixes exist;
- runtime library paths exist where required.

Use `partial` only for non-blocking issues explicitly safe before Entity build.
By default, `partial` and `warn` are blocking for generated artifacts.

The compatibility result also records checker coverage. Coverage explains what
the current checker proved; it does not create a new pass path:

```json
{
  "compatibility": {
    "status": "pass",
    "checker_version": 1,
    "checked_at": "",
    "coverage": {
      "requirements_checkpoint_match": "implemented",
      "dependency_path_existence": "implemented",
      "compiler_signature": "partial",
      "path_list_existence": "not_implemented",
      "cmake_package_probe": "not_implemented"
    },
    "checks": [],
    "issues": []
  }
}
```

Required checks marked `partial` or `not_implemented` should be treated as known
limitations, not silently folded into a complete proof.

Run:

```bash
python3 scripts/entity_compat.py requirements.json --checkpoint entity-deps.local.json
```

## Generated Artifacts

After `env.sh` generation, update:

```json
{
  "env_sh": {
    "path": "/abs/path/env.sh",
    "status": "generated",
    "generated_at": "",
    "validation": {
      "bash_syntax": "pass|fail",
      "commands": []
    }
  }
}
```

After `entity-build.sh` generation or execution, update `requirements.json`:

```json
{
  "artifacts": {
    "entity_build_sh": "/abs/path/entity-build.sh"
  },
  "build_result": {
    "status": "not_run|running|pass|fail",
    "started_at": "",
    "finished_at": "",
    "exit_code": 0,
    "run_id": "",
    "runner_log": "",
    "script": "",
    "configure_command": "",
    "build_command": "",
    "expected_executable": ""
  }
}
```
