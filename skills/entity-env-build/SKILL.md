---
name: entity-env-build
description: Configure, verify, and execute Entity dependency and source builds at one explicit execution site. Use for requirements.json, entity-deps.local.json, compatibility checks, env.sh, entity-build.sh, dependency repair, and verified compilation. Inputs use independent site_id, source_checkout, build_root, deps_root, and artifacts_root paths; do not assume a shared ENTITY_WORKDIR.
---

# Entity Environment Build

Own the build-site environment and Entity compilation. This skill may run
standalone with exact paths or as a Router `build.*` Worker. It does not choose
PGen physics, launch simulations, analyze output, or change Entity core.

## Required build-site contract

Before writing or executing anything, obtain these explicit values for the
same logical site:

```json
{
  "schema_version": 2,
  "entity": {
    "site_id": "cluster-a",
    "source_checkout": "/shared/stage/<case_uid>/<source-id>",
    "build_root": "/scratch/build/<case_uid>/<build_id>",
    "deps_root": "/shared/deps/entity",
    "artifacts_root": "/shared/records/<case_uid>/<build_id>",
    "version_bucket": "1.4.0",
    "dependency_profile": "modern"
  }
}
```

- `source_checkout` is the verified materialized revision used by this build.
- `build_root` is one immutable build identity's CMake tree.
- `deps_root` contains reusable dependency prefixes, sources, and generated
  dependency scripts.
- `artifacts_root` contains requirements/checkpoint/env/build script/logs.
- These paths need not share a parent and need not be near Router control,
  source authority, run, or data paths.
- `site_id` is stable across path changes and keys reusable machine notes.

Schema v1 `checkout_root/workdir` is accepted only for explicit legacy
migration. Never generate new state from the old monolithic convention.

When invoked by Router, read the Action request first. Execute only at
`execution_site_id`, use only Locator-authorized paths, and never write Router
control state. A remote Worker returns evidence; the controller commits state.

## Hard gates

- Confirm the exact source revision/snapshot and build ID. Do not build from a
  mutable source authority path when a materialized revision is required.
- Record all user build choices in `requirements.json` before environment
  discovery. Do not infer user intent from installed software.
- Ask/confirm: PGen, backend (`cpu/cuda/hip`), MPI, GPU-aware MPI, output,
  build intent/optimization, precision, deposit, shape order, debug, tests,
  dependency policy, and jobs. For GPU builds also confirm architecture; for
  HIP confirm ROCm/DTK preference and optimization.
- Do not compile until `requirements.json` validates, compatibility is `pass`,
  and `env.sh` was generated from the current checkpoint.
- Dependency source builds require a reviewed plan and explicit permission.
- Do not silently weaken version, compiler, CUDA/ROCm, MPI, HDF5, ADIOS2, or
  Kokkos compatibility failures.
- Preserve build logs and result evidence. A shell exit claim without the
  expected executable/log evidence is not success.

Read `references/json-contracts.md` for field details,
`references/dependency-policy.md` before choosing dependencies,
`references/compatibility-check.md` before overrides, and
`references/entity-compile-options.md` before generating the Entity build.

## Workflow

### 1. Requirements

Write schema-v2 `requirements.json` under `artifacts_root`. Include the five
site/path fields above, source revision identity supplied by Router, Entity
version profile, environment choices, compile choices, and desired artifact
paths. Validate:

```bash
python3 scripts/entity_checkpoint.py validate /artifacts/requirements.json
```

If the result is `partial`, resolve the choice conflict; do not pass
`--allow-partial` for a production build.

### 2. Reuse or construct the dependency checkpoint

Read site notes under `~/.entity-env-build/site-notes/<site_id>.md`, then inspect
the exact `artifacts_root/entity-deps.local.json` if it exists. Reuse it only
when its embedded requirements and all resolved site paths match.

```bash
python3 scripts/entity_checkpoint.py create /artifacts/requirements.json \
  --merge /artifacts/entity-deps.local.json \
  --output /artifacts/entity-deps.local.json
```

Search modules, system packages, existing prefixes, and user-managed installs
before proposing a source build. Record selected compiler/dependency paths,
versions, provider, signatures, validation, and necessary site pre-commands.
Machine-specific fixes belong in site notes/checkpoint data, not this skill.

If a source build is approved:

```bash
python3 scripts/entity_generate.py deps /artifacts/requirements.json \
  --checkpoint /artifacts/entity-deps.local.json
bash /deps/scripts/build-<dependency>.sh
```

Prefixes and source downloads remain under `deps_root`; temporary dependency
builds and logs remain under `artifacts_root`. Build dependency order according
to the selected graph; ADIOS2 waits for the Kokkos/HDF5 prefixes it consumes.

### 3. Compatibility and environment

```bash
python3 scripts/entity_compat.py /artifacts/requirements.json \
  --checkpoint /artifacts/entity-deps.local.json

python3 scripts/entity_generate.py env /artifacts/entity-deps.local.json \
  --output /artifacts/env.sh
```

Compatibility must be `pass`. A documented user-accepted warning may use the
existing override mechanism, but an override cannot conceal a missing binary,
wrong source revision, wrong execution-site path, or ABI/toolchain mismatch.

### 4. Generate and execute the build

```bash
python3 scripts/entity_generate.py build /artifacts/requirements.json \
  --env /artifacts/env.sh \
  --checkpoint /artifacts/entity-deps.local.json \
  --output /artifacts/entity-build.sh

python3 scripts/entity_run.py build /artifacts/requirements.json \
  --script /artifacts/entity-build.sh
```

The generated script configures and builds `entity.build_root` while using
`entity.source_checkout`. It writes logs under `artifacts_root/build-logs`.
Never reuse a build root for another source revision or materially different
compile contract; allocate a new build ID.

On clusters, run configure/build in the context required by site policy. The
generic skill records scheduler kind but does not encode a partition, account,
module stack, or SSH credential.

## Failure and handoff

Diagnose from the first causal error and current JSON/log evidence. Repair only
build-owned state. PGen/TOML errors return to `entity-pgen`; source divergence
or materialization errors return to Router `source.*`; scheduler/run errors
return to Router playbooks; unknown cross-layer causes return as
`failure.triage` evidence.

Success requires:

- compatibility `pass` for the current requirements and site paths;
- generated `env.sh` and `entity-build.sh` tied to the current checkpoint;
- build command exit zero;
- expected executable exists inside the immutable build root;
- logs and build result identify `site_id`, source revision, build ID, and
  relevant hashes/paths.

Return exact artifact Locators and verification, not copied raw run/data state.
