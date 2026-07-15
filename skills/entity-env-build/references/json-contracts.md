# JSON Contracts

`requirements.json` is user intent plus build-site scope.
`entity-deps.local.json` is the site-local dependency checkpoint derived from
that exact request. `env.sh` and `entity-build.sh` are derived artifacts.

## requirements.json schema v2

```json
{
  "schema_version": 2,
  "entity": {
    "site_id": "cluster-a",
    "source_checkout": "/stage/case/source-id",
    "build_root": "/scratch/build/case/build-id",
    "deps_root": "/shared/deps/entity",
    "artifacts_root": "/shared/build-records/case/build-id",
    "source_revision": {"kind": "git", "commit": "", "tree": ""},
    "version_bucket": "1.4.0",
    "dependency_profile": "modern"
  },
  "environment": {
    "backend": "cpu",
    "gpu_arch": "",
    "output": true,
    "mpi": false,
    "gpu_aware_mpi": false,
    "dependency_policy": "reuse-existing"
  },
  "compile": {
    "pgen": "",
    "precision": "single",
    "deposit": "zigzag",
    "shape_order": "1",
    "cxx_standard": "20",
    "debug": false,
    "tests": false,
    "build_intent": "unspecified",
    "jobs": "",
    "build_dir": ""
  },
  "artifacts": {
    "entity_build_sh": "",
    "logs_dir": ""
  }
}
```

Required before validation/build:

- `entity.site_id`, `source_checkout`, immutable `source_revision`,
  `build_root`, and `deps_root`;
- `entity.artifacts_root` is recommended and defaults to
  `<build_root>/_artifacts` only when omitted;
- `compile.pgen` and `environment.backend`;
- supported Entity version/dependency profile.

`compile.build_dir` defaults to `entity.build_root` and is written back before
script generation. All paths are absolute paths on `entity.site_id`; they do
not imply a common parent. New workflows must use v2. Schema v1
`checkout_root/workdir` exists only for explicit legacy compatibility.

## entity-deps.local.json

The checkpoint has the same schema version as its request and records:

```json
{
  "schema_version": 2,
  "requirements": {"path": "", "embedded": {}},
  "target": {"hostname": "", "os": "", "arch": "", "shell": "", "context": "login"},
  "entity": {
    "site_id": "",
    "source_checkout": "",
    "build_root": "",
    "deps_root": "",
    "artifacts_root": "",
    "version_bucket": "",
    "dependency_profile": ""
  },
  "candidates": {},
  "selected": {},
  "decisions": {},
  "paths": {},
  "build_scripts": {"directory": "", "generated_at": "", "scripts": {}},
  "compatibility": {"status": "unknown", "checked_at": "", "checks": [], "issues": []},
  "env_sh": {"path": "", "status": "missing", "generated_at": "", "validation": {}},
  "status": {"checkpoint": "partial", "satisfies_requirements_json": false, "ready_for_entity_build": false, "reuse_notes": []}
}
```

Each selected dependency records provider, prefix/bin/include/lib/config paths,
version, compiler/MPI signatures, environment additions, compile configuration,
and validation. The checkpoint is reusable only if embedded requirements,
execution site, all five resolved paths, version profile, and toolchain choices
match the current request.

Compatibility statuses:

- `pass`: current request is buildable with proven dependencies;
- `warn`: only accepted documented deviations remain;
- `fail`: at least one hard incompatibility;
- `unknown`: checker has not validated current state.

An override records a user decision and may downgrade a known check to a
warning. It may not hide missing paths, source/build-site mismatch, unsupported
schema/version, or absent executables.

## Derived artifacts

- `env.sh` exports dependency/toolchain paths from the checkpoint, including
  `ENTITY_DEPS_ROOT`; it does not define an `ENTITY_WORKDIR`.
- `entity-build.sh` configures `entity.source_checkout` into
  `entity.build_root` and writes logs to `entity.artifacts_root/build-logs`.
- `build_result` in requirements records status, timestamps, exit code, run ID,
  runner log, script, and expected executable evidence.

Site-specific modules, pre-commands, and environment overrides belong in the
checkpoint/site notes. Credentials never enter either JSON file.
