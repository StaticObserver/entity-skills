---
name: entity-env-build
description: Configure, verify, and execute Entity dependency and source builds at one explicit execution site. Applies to requirements.json, entity-deps.local.json, compatibility checks, env.sh, entity-build.sh, dependency remediation, and verifiable compilation. Inputs use mutually independent site_id, source_checkout, build_root, deps_root, and artifacts_root paths; do not assume a shared ENTITY_WORKDIR exists.
---

# Entity Environment Build

Responsible for the build site environment and Entity compilation. This skill
can run standalone with exact paths, or work together with the Ledger: once
build verification passes, `entityctl record build` registers the checkpoint
into the Case ledger. It does not choose PGen physics content, does not start
simulations, does not analyze output, and does not modify Entity core code.

## Required build site contract

Before writing or executing anything, obtain the following explicit values for
the same logical site:

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

- `source_checkout` is the verified, materialized source revision used by this
  build.
- `build_root` is the CMake tree for one immutable build identity.
- `deps_root` holds reusable dependency prefixes, sources, and generated
  dependency scripts.
- `artifacts_root` holds requirements/checkpoint/env/build scripts/logs.
- These paths do not need to share a parent directory, nor be near the Ledger
  control paths, source authority paths, run paths, or data paths.
- `site_id` stays stable across path changes and provides the key for reusable
  machine notes.

Schema v1 `checkout_root/workdir` is accepted only for explicit legacy
migration. Never generate new state from the old monolithic conventions.

Execute only on the execution site provided by the caller and on
Locator-authorized paths; never write Ledger control state. Remote workers
return evidence; the controller commits state.

## Hard gates

- Confirm the exact source revision/snapshot and build ID. When a materialized
  revision is required, do not build from a mutable source authority path.
- Record all user build choices in `requirements.json` before probing the
  environment. Do not infer user intent from installed software.
- Ask/confirm: PGen, backend (`cpu/cuda/hip`), MPI, GPU-aware MPI, output,
  build intent/optimization, precision, deposit, shape order, debug, tests,
  dependency policy, and jobs. For GPU builds also confirm the architecture;
  for HIP confirm ROCm/DTK preference and optimization. Record the
  confirmation with `entity_checkpoint.py confirm <requirements.json>
  --checkpoint <entity-deps.local.json> --by <actor>`; until the confirmation
  digest matches the current requirements, the compatibility check fails
  `parameters.confirmation`, and on that failure you must not proceed to
  generate `env.sh` or compile.
- Do not compile until `requirements.json` validates, compatibility is
  `pass`, and `env.sh` is generated from the current checkpoint.
- Dependency source builds require a reviewed plan and explicit permission.
- Do not silently downgrade version, compiler, CUDA/ROCm, MPI, HDF5, ADIOS2,
  or Kokkos compatibility failures.
- Keep build logs and result evidence. A shell exit claim without the expected
  executable/log evidence does not count as success.

See `references/json-contracts.md` for field details; read
`references/dependency-policy.md` before choosing dependencies; read
`references/compatibility-check.md` before overriding; read
`references/entity-compile-options.md` before generating an Entity build.

## Workflow

### 1. Requirements

Write a schema-v2 `requirements.json` under `artifacts_root`. Include the five
site/path fields above, the source revision identity provided by the Ledger,
the Entity version profile, environment choices, compile choices, and the
expected artifact paths. Validate:

```bash
python3 scripts/entity_checkpoint.py validate /artifacts/requirements.json
```

If the result is `partial`, resolve the choice conflicts; do not pass
`--allow-partial` for production builds.

### 2. Reuse or build the dependency checkpoint

Resolve the dependencies of requirements.json in the following lookup order;
use the first hit and fill the gaps layer by layer:

1. **Site deps registry** (authoritative: `sites/<site>.yaml` in the
   workspace): export the registry on the controller and pass it to create —
   ```bash
   entityctl site deps <site_id> --json > /tmp/site-deps.json
   python3 scripts/entity_checkpoint.py create /artifacts/requirements.json \
     --from-registry /tmp/site-deps.json \
     --output /artifacts/entity-deps.local.json
   ```
   A stack whose signature (backend/mpi/gpu_aware_mpi/output/cxx_standard/
   dependency_profile) exactly matches the current requirements and whose
   `status=verified` directly prefills `selected` (each package keeps its
   original provider; provenance is carried by
   `validation.source=site-registry`). The registry may mix in `kind=analysis`
   Python environment stacks — build consumption only matches `kind=build`
   (absent means build). The `env_sh` path in the registry is for human
   reading and auditing only — the environment is always rebuilt by
   `entity_generate.py env` from the current checkpoint's packages. A
   registry hit does not exempt any gate: compatibility must still be `pass`
   before compiling.
2. **`entity-site.yaml` marker**: on machines without a workspace, look for
   `<site_root>/entity-site.yaml` (once the agent finds it, it knows the
   roots manifest), then read `deps/<stack_id>/stack.yaml` for existing
   stacks; a matching stack can be organized into registry JSON and fed via
   `--from-registry`.
3. **On-the-spot discovery fill-in**: dependencies not covered by the
   registry are still searched through the original flow — modules, system
   packages, existing prefixes, and user-managed installs — and the gaps are
   filled with `--from-discovery` or `record-install`.

Then check the exact `artifacts_root/entity-deps.local.json` (if it exists).
Reuse it only when its embedded requirements and all resolved site paths
match.

```bash
python3 scripts/entity_checkpoint.py create /artifacts/requirements.json \
  --merge /artifacts/entity-deps.local.json \
  --output /artifacts/entity-deps.local.json
```

Record the selected compiler/dependency paths, versions, providers,
signatures, verification results, and any required site preamble commands.
Machine-specific fixes belong in the site notes/checkpoint data, not in this
skill.

If a source build is approved:

```bash
python3 scripts/entity_generate.py deps /artifacts/requirements.json \
  --checkpoint /artifacts/entity-deps.local.json
bash /deps/scripts/build-<dependency>.sh
```

Prefixes and source downloads stay under `deps_root`; temporary dependency
builds and logs stay under `artifacts_root`. Determine build order from the
selected dependency graph; ADIOS2 waits for the Kokkos/HDF5 prefixes it
consumes.

**New-stack write-back (verify first, then record)**: after a new dependency
stack completes confirm and compatibility is `pass`, register it in the site
registry so the next resolution hits it directly:

```bash
# Run on the controller; env.sh must already exist at <site_root>/deps/<stack_id>/env.sh
entityctl site deps-add <site_id> --from-checkpoint /artifacts/entity-deps.local.json
```

deps-add writes the stack entry (stack_id, signature, packages, recipe,
status=verified) into the deps registry of `sites/<site>.yaml` and generates
`deps/<stack_id>/stack.yaml` on the site; when the evidence does not match
(unverified checkpoint, missing env.sh) it writes nothing.

### 3. Compatibility and environment

```bash
python3 scripts/entity_compat.py /artifacts/requirements.json \
  --checkpoint /artifacts/entity-deps.local.json

python3 scripts/entity_generate.py env /artifacts/entity-deps.local.json \
  --output /artifacts/env.sh
```

Compatibility must be `pass`. Documented, user-accepted warnings may use the
existing override mechanism, but an override cannot mask missing binaries,
the wrong source revision, wrong execution site paths, or ABI/toolchain
mismatches.

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
Never reuse the same build root for another source revision or a materially
different compile contract; allocate a new build ID.

On clusters, run configure/build in the context required by site policy. The
general skill records the scheduler type but does not encode partitions,
accounts, module stacks, or SSH credentials.

## Failure and handoff

Diagnose from the first causal error and the current JSON/log evidence. Fix
only state owned by the build side. Hand PGen/TOML errors back to
`entity-pgen`; hand source divergence or materialization errors back to
`entity-ledger`; hand scheduler/run errors back to `entity-ledger`; return
unknown cross-layer causes as `failure.triage` evidence.

Success requires:

- compatibility `pass` for the current requirements and site paths;
- the generated `env.sh` and `entity-build.sh` bound to the current
  checkpoint;
- a zero exit code from the build command;
- the expected executables present inside the immutable build root;
- logs and build results identifying the `site_id`, source revision, build
  ID, and relevant hashes/paths.

Return exact artifact Locators and verification information, not copied raw
run/data state.
