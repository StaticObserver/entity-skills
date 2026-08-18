# JSON Contracts

`requirements.json` is the user intent plus the build site scope.
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

- `entity.site_id`, `source_checkout`, an immutable `source_revision`,
  `build_root`, and `deps_root`;
- `entity.artifacts_root` is recommended; when omitted it defaults to
  `<build_root>/_artifacts`;
- `compile.pgen` and `environment.backend`;
- a supported Entity version/dependency profile.

`compile.build_dir` defaults to `entity.build_root` and is written back before
script generation. Guard: if that directory already exists and is non-empty
(the typical accident is inheriting a stale `build_dir` from requirements
copied from a previous round), generation is refused — re-linking on top of
it would distort the evidence of the already-registered build; to confirm an
in-place rebuild you must explicitly pass `--reuse-build-dir` (or
`--clean-build`, which empties the tree first). All paths are absolute paths
on `entity.site_id`; they do not imply a common parent directory.
New workflows must use v2. Schema v1 `checkout_root/workdir` exists only for
explicit legacy compatibility.

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
  "stack_id": "",
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

`stack_id` is an optional top-level field: it is written by
`--from-registry` only when the checkpoint's `selected` exactly matches the
packages of a registry stack; after `--from-discovery` fill-in or
`record-install` changes `selected`, the field is removed and demoted to a
`status.reuse_notes` record.

Each selected dependency records the provider, prefix/bin/include/lib/config
paths, version, compiler/MPI signature, environment additions, compile
configuration, and verification. The checkpoint is reusable only when the
embedded requirements, execution site, all five resolved paths, version
profile, and toolchain choices match the current request.

`decisions.parameters` records the compile-parameter confirmation hard gate,
written by `entity_checkpoint.py confirm`:

```json
{
  "digest": "sha256:<hex>",
  "confirmed_by": "<actor>",
  "confirmed_at": "<UTC ISO timestamp>",
  "defaults": false,
  "card": {
    "schema_version": 1,
    "kind": "entity-parameter-card",
    "domain": "build",
    "fields": {"environment.backend": {"value": "cpu", "tier": 1}},
    "digest": "sha256:<hex>"
  }
}
```

`card` is the parameter card derived from requirements at confirmation time
(`entity_schema.py:parameter_card`); `digest` is its digest. When the record
is missing or the digest no longer matches the current requirements, the
compatibility check fails `parameters.confirmation`.

Compatibility status:

- `pass`: the current request can be built with proven dependencies;
- `warn`: only accepted, documented deviations remain;
- `fail`: at least one hard incompatibility exists;
- `unknown`: the checker has not yet verified the current state.

An override records a user decision and can demote a known check to a
warning. It cannot mask missing paths, source/build site mismatch, unsupported
schema/versions, or missing executables.

## Site deps registry and stack_id

A checkpoint may carry a top-level `stack_id`: it references the site deps
stack that this checkpoint consumes (or produced). The registry is maintained
on the Ledger side (the deps section of the workspace `sites/<site>.yaml`)
and exported via `entityctl site deps <site> --json`:

```json
{
  "site_id": "cluster-a",
  "stacks": [
    {
      "stack_id": "gcc12.3.0-kokkos5.1.0-1a2b3c4d",
      "kind": "build",
      "status": "verified",
      "signature": {"backend": "cuda", "mpi": false, "gpu_aware_mpi": false,
                    "output": true, "cxx_standard": "20",
                    "dependency_profile": "modern"},
      "packages": [{"name": "kokkos", "version": "5.1.0",
                    "prefix": "/site/deps/<stack_id>/kokkos", "provider": "module"}],
      "recipe": {"providers": {"kokkos": "module"}, "parameter_digest": "sha256:..."},
      "env_sh": "/site/deps/<stack_id>/env.sh"
    }
  ]
}
```

With `entity_checkpoint.py create --from-registry <registry.json>`, the
first stack whose signature exactly matches the current requirements and
which has `status=verified` and `kind=build` (absent means build; the
registry may mix in `kind=analysis` Python environment stacks, which build
consumption does not match) prefills `selected` (each package keeps its
original provider; provenance is recorded in `validation.source`) and writes
the `stack_id` into the checkpoint; uncovered dependencies are filled in by
`--from-discovery`/on-the-spot probing. Registry entries then undergo the
same compatibility checks as probed entries. After confirm + compatibility
`pass`, a new stack is written back to the registry with
`entityctl site deps-add <site> --from-checkpoint <entity-deps.local.json>`
(zero writes when the evidence does not match).

## Derived artifacts

- `env.sh` exports dependency/toolchain paths from the checkpoint, including
  `ENTITY_DEPS_ROOT`; it does not define `ENTITY_WORKDIR`.
- `entity-build.sh` configures `entity.source_checkout` into
  `entity.build_root` and writes logs to `entity.artifacts_root/build-logs`.
- The `build_result` in requirements records status, timestamps, exit code,
  run ID, runner log, script, and expected executable evidence.

Site-specific modules, preamble commands, and environment overrides belong in
the checkpoint/site notes. Credentials never enter any JSON file.
