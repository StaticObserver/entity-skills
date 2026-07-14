---
name: entity-env-build
description: Configure, verify, and execute the build environment and source build flow for Entity. Use when the user needs to build Entity, prepare or repair local dependencies, choose CPU/CUDA/HIP/MPI/output support, generate requirements.json, generate or repair entity-deps.local.json, run compatibility checks, generate env.sh, generate entity-build.sh, or execute the verified build script.
---

# entity-env-build

## Mission

Build a reliable local dependency environment for the current Entity build request, then hand off to the Entity source build step.

This skill has three phases:

1. **Requirement phase**: collect the current user request and write `requirements.json`, including both environment requirements and Entity compile options.
2. **Environment phase**: use `requirements.json` to reuse or repair `entity-deps.local.json`, search local dependency candidates, choose a compatible dependency plan, run compatibility checks, and generate `env.sh`.
3. **Entity build phase**: generate `entity-build.sh` from `requirements.json` and `env.sh`, then execute that script to configure and build Entity.

The environment phase is complete only when:

- the JSON checkpoint satisfies the current request;
- compatibility checks pass;
- `env.sh` has been generated from the JSON;
- the JSON records the `env.sh` path and generation status.

The Entity build phase is complete only when `entity-build.sh` has been generated from `requirements.json + env.sh`, executed, and its configure/build result has been recorded. When designing JSON fields, read `references/json-contracts.md`; when designing configure commands, read `references/entity-compile-options.md`.

## Boundaries

Handle:

- CMake, C++ compiler, Kokkos, CUDA/HIP, MPI, ADIOS2, HDF5 dependency planning;
- user confirmation for build-relevant choices;
- local dependency discovery and candidate selection;
- dependency checkpoint JSON creation or repair;
- compatibility checking;
- generation of `env.sh` from the JSON;
- generation and execution of `entity-build.sh` from `requirements.json + env.sh`.

Do not handle:

- TOML or PGen design;
- physics parameter choices;
- output analysis;
- Entity core source changes.

Route PGen/TOML work to `entity-pgen`, output data access to `entity-nt2py`, and
untriaged runtime or Entity-core work back to the package Router.

## Hard Rules

- Treat the current user request as the first input. Old JSON is reusable only if it satisfies this request.
- Require two explicit locations before writing artifacts: `ENTITY_CHECKOUT` for the Entity source tree and `ENTITY_WORKDIR` for this problem/build workspace. If either is missing or invalid, ask the user to confirm.
- Write the current request to `requirements.json` before using or repairing environment checkpoints.
- Core dependencies are always `CMake`, a C++ compiler, and `Kokkos`. Add `MPI` only when the current request requires parallel/multi-process builds; add `ADIOS2 + HDF5` only when `output=true` (the default).
- Unless the user explicitly accepts the risk, all dependencies must use one consistent, non-conflicting compiler/toolchain.
- Support Entity `1.4.0` and newer only, using `C++20`, `Kokkos 5.x`, and `ADIOS2 2.11.x`. Reject older checkouts. Entity `1.4.0`–`1.4.2` are CPU-only; use ≥`1.4.3` for CUDA. Full compatibility details are in `references/json-contracts.md`, `references/compatibility-check.md`, and `references/dependency-policy.md`.
- Do not enter Entity source compilation until compatibility is `pass` and `env.sh` is generated from `entity-deps.local.json`.
- Do not hand-write the Entity configure/build commands. Generate `entity-build.sh` from `requirements.json` and `env.sh`, then execute it.
- On clusters: never compile on login nodes. Submit Entity builds through the scheduler (SLURM/PBS), or ask the user if no scheduler is available. For GPU backends, login-node builds require two explicit confirmations: (1) `libcuda.so.1` is absent on login nodes; (2) the build may not be runnable there. Show the login-vs-compute difference before asking.

## Build Workflow

Run the skill in this order. Phase 1 collects all user requirements before touching the environment.

```text
Phase 1 — User requirements (no environment probing yet)
  -> ask user for Entity source and workspace locations
  -> ask user for build choices (pgen, backend, MPI, output, intent, options)
  -> write requirements.json
  -> validate requirements.json

Phase 2 — Environment probing and planning
  -> read ~/.entity-env-build/site-notes/<hostname>.md if it exists
  -> locate/read dependency checkpoint JSON (if any)
  -> compare checkpoint against requirements.json
  -> search local dependency candidates
  -> plan compatible selected dependencies
  -> user confirmation gate for ambiguous choices
  -> generate source-build scripts when needed
  -> write entity-deps.local.json
  -> compatibility check (§2i)
  -> generate env.sh

Phase 3 — Entity build
  -> generate entity-build.sh from requirements.json + env.sh
  -> execute entity-build.sh (via scheduler on clusters)
  -> update ~/.entity-env-build/site-notes/<hostname>.md with build result
  -> record build result in requirements.json
```

### Phase 1: Collect User Requirements

**Do not probe the environment until the user has answered the questions in this phase.** The goal is to know what the user wants before checking what is available.

#### 1a. Workspace Location

Ask the user to confirm two paths:

- `ENTITY_CHECKOUT`: where the Entity source lives. Check `$ENTITY_CHECKOUT`, then ask.
- `ENTITY_WORKDIR`: root of the entity workspace. Contains Entity source versions, shared `deps/`, and `problems/`. Check `$ENTITY_WORKDIR`, then ask.

```
$ENTITY_WORKDIR/                          ← ROOT
├── entity-<version>/                     ← ENTITY_CHECKOUT
├── deps/                                 ← shared deps (multi-pgen reuse)
│   ├── kokkos/<version>/
│   ├── hdf5/<version>/
│   ├── adios2/<version>/
│   ├── sources/                          ← dep source code
│   └── scripts/                          ← generated build scripts
└── problems/
    └── <pgen>/
        ├── pgen.toml                     ← pgen config
        ├── build/                        ← cmake build tree
        └── _build/                       ← tool-generated artifacts
            ├── build-logs/
            ├── generated/source-builds/  ← dep cmake build trees
            ├── requirements.json
            ├── entity-deps.local.json
            ├── env.sh
            └── entity-build.sh
```

After confirming both paths, initialize session state:

```bash
python3 -c "
from _json_io import init_session_state
init_session_state(Path('$ENTITY_WORKDIR'))
"
```

If `.entity-session.json` already exists from a previous incomplete session, offer to resume from the last phase. The file tracks `phase`, `completed_steps`, `build_attempts`, and artifact paths.

Default artifact paths (pgen-level, under `_build/`):

```text
$PGEN_DIR/_build/
├── requirements.json
├── entity-deps.local.json
├── .entity-session.json
├── env.sh
├── entity-build.sh
├── build-logs/
└── generated/
    └── source-builds/
```

Shared paths (ROOT-level):
```text
$ENTITY_WORKDIR/deps/
├── kokkos/<version>/
├── hdf5/<version>/
├── adios2/<version>/
├── sources/
└── scripts/
```

Also: `~/.entity-env-build/site-notes/<hostname>.md` — machine-specific knowledge, generated at runtime. Read before environment probing; update after builds and discovered issues.

#### 1b. Build Choices

Ask the user these questions. For each, record a decision even if using the default. Do not probe the system to answer them — these are user intent, not environment discovery.

**Critical rule**: You MUST ask every question in the table below. Do NOT silently apply defaults — the user must see and confirm every choice. If the user says "use defaults", list the defaults explicitly and ask for confirmation.

| Question | Options | Default | Notes |
| --- | --- | --- | --- |
| Problem generator (`pgen`) | built-in name, `pgens/...`, or path | *required* | Changing pgen later requires a fresh build dir |
| CPU or GPU backend? | `cpu` / `cuda` / `hip` | prefer GPU if user expects it | CUDA requires `nvcc_wrapper`; HIP requires ROCm/hipcc |
| Enable MPI? | `true` / `false` | `false` | Don't enable just because mpicxx exists |
| GPU-aware MPI? | `true` / `false` | `false` | Only relevant when MPI + GPU both on |
| Enable output? | `true` / `false` | `true` | `true` implies ADIOS2 + HDF5 |
| Build intent / optimization | `smoke` (-O0) / `debug` (-Og) / `production` (-O2) / `unspecified` | `unspecified` | Affects optimization level (-O1/-O2/-O3/-Ofast) |
| Precision | `single` / `double` | `single` | |
| Deposit scheme | `zigzag` / `esirkepov` | `zigzag` | |
| Shape order | `1` to `11` | `1` | |
| Debug mode? | `true` / `false` | `false` | |
| Compile tests? | `true` / `false` | `false` | |
| Dependency policy | `reuse-existing` / `allow-local-build` | `reuse-existing` | Source build is last resort |

Additional questions that are **required** (not optional) in these scenarios:

| Scenario | Required Question |
| --- | --- |
| Backend is CUDA or HIP | GPU architecture (e.g. `AMPERE80`, `AMD_GFX906`) — NEVER guess or auto-detect at this phase |
| Backend is HIP | ROCm/DTK version preference (e.g. DTK 24.04, 25.04, latest available) |
| Multiple compilers available | Compiler family and version preference (GCC version, Clang version, etc.) |
| Backend is HIP | Optimization level: production defaults to -O2 but warn the user that ROCm/Clang may require -O1 |

Additional questions when the answer is not obvious from context:

- Entity version (auto-detect from checkout if possible; otherwise ask)
- Exact dependency version tags — only if user wants to pin specific versions
- Install prefix — only if user wants `cmake --install`

##### Configuration Confirmation Gate

After collecting all answers and before writing `requirements.json`, you MUST:

1. Present a summary table of ALL configuration choices.
2. Ask the user to confirm: "These are the settings I will use. Confirm or adjust any item."
3. Only proceed to write `requirements.json` after explicit user approval.

Example summary format:

```
Build Configuration Summary:
  ENTITY_CHECKOUT:  /path/to/entity/1.4.3
  ENTITY_WORKDIR:   /home/user                    ← ROOT
  PGen:             reconnection
  Backend:          HIP (ROCm)
  GPU Architecture: AMD_GFX906
  MPI:              ON
  GPU-aware MPI:    OFF
  Output:           ON (ADIOS2 + HDF5)
  Precision:        single
  Deposit:          zigzag
  Shape order:      1
  Optimization:     -O2 (production) — note: may need -O1 for ROCm/Clang
  Debug:            OFF
  Tests:            OFF
  C++ Standard:     20
  Dependency policy: reuse-existing

Proceed with these settings?
```

#### 1c. Write And Validate requirements.json

After collecting all answers, write `requirements.json` following the schema in `references/json-contracts.md`.

Defaults that don't need asking unless the user overrides:

- `entity.dependency_profile`: `modern`; Entity versions before `1.4.0` are unsupported
- `compile.cxx_standard`: `20`
- `environment.dependency_versions`: leave empty; fill after probing if source builds are needed

Validate before proceeding:

```bash
python3 scripts/entity_checkpoint.py validate "$ENTITY_WORKDIR/requirements.json"
```

If validation fails, fix the missing fields or inconsistencies and re-validate. Do not start environment probing until `status=pass`.

### Phase 2: Environment Probing And Planning

Only now — after `requirements.json` is written and validated — begin probing the environment.

#### 2a. Read Site Notes

Before probing, check for machine-specific knowledge:

```
~/.entity-env-build/site-notes/<hostname>.md
```

If the file exists, read it. Use its contents to:
- Skip known-bad dependency combinations
- Prefer known-good combinations
- Warn the user about known issues before they cause failures
- Reference past build history for the same pgen/backend combination

If the file does not exist, note that this is the first build on this machine — all known issues will be discovered fresh. A new site-notes file will be created after the build (or when the first non-obvious issue is encountered).

Update session state: `last_action = "Reading site notes for <hostname>"`

#### 2b. Locate And Read Existing Checkpoint

Default checkpoint filename: `entity-deps.local.json`

Location priority:

1. user-provided path;
2. `requirements.json.artifacts.dependency_checkpoint_json`;
3. `$ENTITY_WORKDIR/entity-deps.local.json`.

If the dependency JSON exists, parse it and check schema. If it does not exist, create a draft checkpoint in memory. Do not let an old complete dependency JSON override `requirements.json`.

Classify checkpoint state:

- `missing`: no usable file;
- `partial`: parseable but missing required sections;
- `stale`: paths, Entity version bucket, target node, or requirements no longer match;
- `complete`: structurally complete for the current requirements;
- `incompatible`: complete enough to evaluate but fails compatibility.

#### 2c. Compare Checkpoint Against requirements.json

Reuse old dependency content only if it satisfies `requirements.json`.

Examples:

- old `backend=cpu`, current `backend=cuda` -> stale for this request;
- old `mpi=false`, current `mpi=true` -> only non-MPI parts may be reused;
- old `output=false`, current default `output=true` -> ADIOS2/HDF5 must be discovered and checked;
- old compiler differs from the current selected MPI wrapper compiler -> stale until confirmed or rebuilt.

Record this comparison under `status.satisfies_requirements_json` and `status.reuse_notes`.

#### 2d. Search Dependency Candidates

Search according to `requirements.json`.

Always search:

- `CMake`;
- C++ compilers;
- `Kokkos`.

Conditional search:

- `environment.backend=cuda`: CUDA toolkit, `nvcc`, Kokkos `nvcc_wrapper`;
- `environment.backend=hip`: HIP/ROCm toolkit, `hipcc`;
- `environment.mpi=true`: `mpicxx`, `mpirun`, MPI modules;
- `environment.output=true`: `ADIOS2`, `HDF5`.

For each candidate, record following the dependency entry shape in `references/json-contracts.md`.

Do not treat a binary alone as sufficient. For CMake-based dependencies, prefer candidates with a valid `*Config.cmake`.

#### 2e. Construct Checkpoint JSON

Construct `entity-deps.local.json` from the requirements and dependency selections:

```bash
python3 scripts/entity_checkpoint.py create "$ENTITY_WORKDIR/requirements.json" \
  --output "$ENTITY_WORKDIR/entity-deps.local.json"
```

To merge with an existing checkpoint:

```bash
python3 scripts/entity_checkpoint.py create "$ENTITY_WORKDIR/requirements.json" \
  --merge "$ENTITY_WORKDIR/entity-deps.local.json" \
  --output "$ENTITY_WORKDIR/entity-deps.local.json"
```

See `references/json-contracts.md` for the full checkpoint schema. Write atomically: temporary file first, then replace the target JSON.

#### 2f. Plan Selected Dependencies

Choose a dependency set that satisfies `requirements.json` with the least conflict.

Core selection: `cmake`, `compiler`, `kokkos`. Conditional: `gpu_toolkit` for CUDA/HIP; `mpi` only when required; `adios2` + `hdf5` when `output=true`.

Selection rules:

- Prefer one consistent compiler/toolchain across all selected dependencies.
- Reject mixed compiler/toolchain combinations unless the user explicitly approves.
- For CUDA, select Kokkos `nvcc_wrapper` as `compiler.cxx` and record the host compiler.
- Use the supported dependency profile: C++20 + Kokkos 5.x + ADIOS2 2.11.x, with ADIOS2 Kokkos support enabled.
- For MPI, keep `mpicxx`, `mpirun`, Kokkos, ADIOS2, HDF5, and Entity in one MPI/compiler context.
- For output, keep ADIOS2 and HDF5 serial/MPI context consistent with the MPI requirement.
- If local source builds are needed, read `references/dependency-build-scripts.md`.

Record rejected candidates and reasons.

#### 2g. User Confirmation Gate

Confirm when:

- backend is unclear or GPU compiler is missing;
- MPI requirement is unclear;
- GPU-aware MPI is requested or risky;
- multiple compatible compilers exist;
- compiler/toolchain consistency requires rebuilding or rejecting existing dependencies;
- multiple CUDA/HIP toolkits or GPU architectures are possible;
- multiple Kokkos/ADIOS2/HDF5 candidates exist;
- source build is required;
- local install prefix or checkpoint path is ambiguous.

Do not ask when:

- the current request is explicit;
- the JSON has a matching confirmed decision and paths still validate;
- only one compatible low-risk option exists;
- a default is safe and cheap to reverse.

Write every decision to JSON:

```json
{
  "value": "",
  "source": "user|request|checkpoint|default|auto-detected",
  "reason": "",
  "confirmed_at": "",
  "alternatives": []
}
```

If later probes invalidate a confirmed decision, mark it stale and re-enter this gate.

#### 2h. Source-Build Dependencies

Only do this after local/system reuse fails and the user has approved source builds.

For each missing dependency, in order: Kokkos → HDF5 → ADIOS2.

**Step 1: Generate and execute build script**

```bash
python3 scripts/entity_generate.py deps "$ENTITY_WORKDIR/requirements.json" \
  --checkpoint "$ENTITY_WORKDIR/entity-deps.local.json" \
  --deps <dep>
```

Generated scripts live under `$ENTITY_WORKDIR/deps/scripts/`. Execute directly:

```bash
bash "$ENTITY_WORKDIR/deps/scripts/build-<dep>.sh"
```

Before executing, read `references/dependency-notes/<dep>.md` so known build issues can be matched against configure/build failures. The build script has `set -euo pipefail` and stops on first failure. If it fails, diagnose using the decision tree in Phase 3 (§3b Build Failure Diagnosis) — many of those entries (compiler optimization bugs, ABI mismatches, GPU arch mismatches) apply to dependency builds too.

**Step 2: Record install evidence**

After the build succeeds, record evidence through the checkpoint tool. Do not hand-edit `selected.<dep>`:

```bash
python3 scripts/entity_checkpoint.py record-install \
  --checkpoint "$ENTITY_WORKDIR/entity-deps.local.json" \
  --dep <dep> \
  --prefix <installed-prefix> \
  --cmake-config <Config.cmake-path> \
  --version <version> \
  --compiler-signature <compiler-signature> \
  --log <install-log>
```

The command validates recorded paths, updates `selected.<dep>`, marks compatibility `unknown`, and forces a fresh compatibility check before proceeding to the next dependency.

**Step 3: Repeat for next dependency**

Kokkos → HDF5 → ADIOS2. Kokkos must build first. HDF5 and Kokkos can in theory be parallel but serial is safer (shared `$ENTITY_WORKDIR/deps/` install prefix). ADIOS2 must wait for both (its CMAKE_PREFIX_PATH includes both prefixes).

**Skip source build when** all of:
- `selected.<dep>.provider != "source-build"` OR already has `validation.installed = true`
- `selected.<dep>.prefix` path exists
- `selected.<dep>.cmake_config` file exists

#### 2i. Compatibility Check

Run compatibility verification directly:

```bash
python3 scripts/entity_compat.py "$ENTITY_WORKDIR/requirements.json" \
  --checkpoint "$ENTITY_WORKDIR/entity-deps.local.json"
```

This writes the result to `entity-deps.local.json.compatibility`. If status is not `pass`:
- Read each FAIL/WARN check's `remediation` field and fix the underlying issue
- Re-run after fixes

Only `compatibility.status=pass` allows `env.sh` generation.

### Phase 3: Entity Build

#### 3a. Generate env.sh From JSON

After compatibility passes, generate a local environment loader. The generator refuses unless `compatibility.status=pass`. Warning-only compatibility results are blocking by default; use `--allow-warnings` only when `decisions.compatibility_warnings_accepted` records an explicit user-confirmed risk acceptance.

```bash
python3 scripts/entity_generate.py env "$ENTITY_WORKDIR/entity-deps.local.json" \
  --output "$ENTITY_WORKDIR/env.sh"
```

`env.sh` is derived from the checkpoint JSON. Do not hand-edit it. For site-specific needs, record them in the JSON:
- `paths.modules`: list of module names → `module load` commands
- `paths.pre_commands`: arbitrary shell lines injected before PATH
- `paths.extra_env`: extra `export VAR=VALUE` lines

After generation, minimally validate: source it and verify `cmake --version`, `"$CXX" --version`.

#### 3b. Generate And Execute entity-build.sh

After `env.sh` is generated, create an Entity build script:

```bash
python3 scripts/entity_generate.py build "$ENTITY_WORKDIR/requirements.json" \
  --env "$ENTITY_WORKDIR/env.sh" \
  --checkpoint "$ENTITY_WORKDIR/entity-deps.local.json" \
  --output "$ENTITY_WORKDIR/entity-build.sh" \
  --run-id "$RUN_ID"
```

`--checkpoint` enables gate validation: the generator verifies compatibility is `pass` and `env.sh` matches the checkpoint. Omit `--checkpoint` only for debugging. A mismatched `env.sh` is treated as stale and blocks generation unless `--allow-stale-env` is explicitly used for debugging.

The generated script sources `env.sh`, runs `cmake -B` configure then `cmake --build`, respects all `requirements.compile` options, and fails fast with `set -euo pipefail`.

Then execute through the lightweight runner, which records `build_result` back to `requirements.json`:

```bash
python3 scripts/entity_run.py build "$ENTITY_WORKDIR/requirements.json" \
  --script "$ENTITY_WORKDIR/entity-build.sh" \
  --run-id "$RUN_ID"
```

Direct `bash entity-build.sh` is a debugging fallback only. For cluster scheduler execution, submit the generated script through the scheduler, then record the result with the runner or update `build_result` from scheduler logs.

Record `entity_build_script.path`, `entity_build_script.status`, `entity_build_script.generated_from`, and execution result back to `requirements.json`.

##### Build Failure Diagnosis

When the build fails, do NOT blindly retry. Diagnose using this decision tree:

**CMake configure failures:**

| Symptom | Likely Cause | Action |
| --- | --- | --- |
| `CMake version too old` | System cmake < 3.16 | Search for newer cmake (module, conda, pip, local prefix) |
| `FindMPI: MPI_C not found` | MPI wrapper compiler mismatch | Check `mpicc --showme` output; consider explicit `-DMPI_C_INCLUDE_DIRS`/`-DMPI_CXX_LIBRARIES` |
| `FindXXX: not found` | Missing cmake config | Verify `CMAKE_PREFIX_PATH` includes dependency prefix; check for `*Config.cmake` |
| `FetchContent / download failed` | No internet on compute node | Ask user: "Network unavailable. Options: (1) find local alternative, (2) upload missing dependency, (3) skip if optional" |

**Compilation failures (cmake --build):**

| Symptom | Likely Cause | Action |
| --- | --- | --- |
| `Broken function found, compilation aborted!` | Compiler optimization bug (common on ROCm/Clang 15) | Immediately ask: "Compiler backend crash at -O2/-O3. Try -O1 instead?" Set `compile.cmake_cxx_flags: "-O1 -DNDEBUG"` |
| `PHI node entries do not match` | Same compiler optimization bug | Same as above — reduce optimization level |
| `undefined reference to ...` | ABI mismatch or missing link library | Check all pre-built deps use same compiler family; verify `LD_LIBRARY_PATH` |
| `error: invalid target ID 'gfxXXX'` | GPU architecture mismatch | Kokkos was built for different GPU arch than current node. Check `Kokkos_ARCH_*` vs node GPU |
| `constraints on a non-templated function` | Entity 1.4.0–1.4.2 + CUDA backend (NVCC EDG frontend does not support C++20 `requires` constraints) | Upgrade Entity to >= 1.4.3. Entity 1.4.3 (PR #210) replaces `requires` with `static_assert`. Do NOT attempt to fix with compiler flags — no flag workaround exists for this EDG limitation |
| `call to consteval function "std::source_location::current" did not produce a valid constant expression` | TOML11 + GCC 12.x host + NVCC EDG (bundled toml11 uses `std::source_location::current()` which EDG rejects as non-constexpr) | Add `-DCMAKE_CXX_FLAGS="-UTOML11_HAS_STD_SOURCE_LOCATION"`. But note this alone is insufficient — the `constraints on a non-templated function` bug (above) also blocks Entity 1.4.0–1.4.2 with CUDA. Upgrade Entity to >= 1.4.3 to fix both |

**SLURM/job failures:**

| Symptom | Likely Cause | Action |
| --- | --- | --- |
| Job pending forever | Wrong partition | Verify partition has required GPU (`sinfo -p <partition>`). CPU nodes can't build GPU targets |
| `CUDA/ROCm not found` on compute node | GPU-less partition | Switch to GPU partition; check `--gres` specification |
| Job killed (OOM) | Insufficient memory | Increase `--mem` or reduce parallel jobs (`-j4` instead of full cores) |

##### Network-Unavailable Scenario

When `FetchContent`, `git clone`, or any network download fails during cmake configure:

**You MUST ask the user before taking action.** Present these options:

1. **Find local alternative**: "I'll search for an existing local installation of this dependency."
2. **Ask user to provide**: "Can you upload or copy the dependency to an accessible path?"
3. **Skip if optional**: "Is this dependency optional and safe to disable?"

After user chooses, record the decision in `decisions` and update `entity-deps.local.json`.

For the specific case of Entity's `plog` FetchContent dependency (common in all Entity builds):
- Run `cmake configure` on a login node (with internet) first
- Set `FETCHCONTENT_FULLY_DISCONNECTED=ON` in CMakeCache.txt before submitting to compute node
- Cache the downloaded content with `FETCHCONTENT_SOURCE_DIR_PLOG`

#### 3c. Handoff / Completion Criteria

Entity build may start only when all are true:

- `status.checkpoint == "complete"` and `satisfies_requirements_json == true`
- `compatibility.status == "pass"`
- `env_sh.status == "generated"`
- `entity_build_script.status == "generated"`

Entity build phase must start by executing `entity-build.sh`. Do not reconstruct state from chat history or transient shell variables.

#### 3d. Update Site Notes

After the build completes (success or failure), update `~/.entity-env-build/site-notes/<hostname>.md`:

**On success:**
- Append a row to the Build History table
- If the dependency combination is new (not already in Known-good Combinations), add it
- Update `last_updated` at the top

**On failure with a newly discovered issue:**
- Add the issue to Known Issues with: symptom, trigger, fix
- Update `last_updated`

**When creating site-notes for the first time on this machine:**
- Use `references/site-notes-template.md` as the starting template
- Fill in Machine Profile with what was learned during environment probing
- Add all discovered issues encountered during this session

The site-notes format is Markdown with structured sections. Keep entries concise — each issue should be one bullet group with Symptom/Trigger/Fix.

## Output Contract

When this skill runs, report:

- current requirements;
- `requirements.json` path and completeness;
- session state (`.entity-session.json`) — phase, completed steps, resumption if applicable;
- site notes file path and whether it was found/created/updated;
- checkpoint path and state;
- whether old JSON was reused, repaired, or rejected;
- selected dependency set;
- user confirmations still needed, if any;
- compatibility result;
- generated `env.sh` path;
- generated `entity-build.sh` path and execution result;
- build history updated in site-notes;
- handoff readiness for Entity build.
