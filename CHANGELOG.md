# Changelog

All notable changes to the Entity skills bundle are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The bundle is versioned with semantic versioning, starting at 0.x: the first
version considered production-satisfactory will be released as 1.0.0. Schema
versions (store, checkpoint, compat checker) are independent integer
compatibility contracts and are not the product version.

## [Unreleased]

## [0.7.1] - 2026-08-18

### Added

- `project init` now also creates the `analysis/scripts/` general-purpose
  script-library skeleton (idempotent — re-initializing an existing project
  backfills it).
- `record analysis` gains test coverage for the ssh-channel manifest
  evidence probe (fake `run_on_site` channel: happy path books the record;
  a failed probe writes nothing).

### Fixed

Field-verified defect batch from the fresh-machine + all-deps-source-built +
CUDA-backend path (lambda H100 first install, defect report 2026-08-18):

- The env-build generated `build-hdf5.sh` substituted dots with underscores
  when cloning HDF5, composing the nonexistent tag `hdf5-1_14_6`; HDF5 tags
  have used the dotted form since 1.12, so the version is now used verbatim
  (`hdf5-$VERSION`, e.g. `hdf5-1.14.6`).
- The dependency build scripts (kokkos/adios2) assumed `nvcc` was already on
  PATH, but `env.sh` is only generated in the next stage — configure failed
  immediately when the CUDA toolkit was not on the default PATH. For
  cuda/hip backends the generated scripts now export PATH from the
  checkpoint's `selected.gpu_toolkit.bin` (falling back to `prefix/bin`).
- Two wrong fallbacks when `host_cxx` is absent: `selected_compiler()` fell
  back to the C compiler (`NVCC_WRAPPER_DEFAULT_COMPILER=gcc`, missing
  libstdc++ at link time); `compiler_env()` fell back to `CXX` itself
  (self-referential when CXX is nvcc_wrapper). The host compiler is now
  derived from `cc` (gcc→g++, clang→clang++), defaulting to `c++`, matching
  the build-kokkos.sh default.
- The `build` command's build_dir guard treated any non-empty directory as
  an existing build tree: with the documented default layout
  (`artifacts_root = <build_root>/_artifacts`) the requirements/checkpoint
  JSONs alone make build_root non-empty, so every first build was refused
  and callers were trained to pass `--reuse-build-dir` routinely, weakening
  the guard. It now refuses only when actual CMake products
  (`CMakeCache.txt`/`CMakeFiles/`) are detected.
- The site deps registry round trip dropped the compiler's
  `cc`/`cxx`/`host_cxx` (report defect 5): the registry persistence
  whitelists (Ledger `STACK_PACKAGE_KEYS` and env-build
  `REGISTRY_PACKAGE_KEYS`) did not include these keys, while the
  compatibility gate requires `selected.compiler.cxx` — so any checkpoint
  resolved purely `--from-registry` was bound to fail; and `create` merged
  per-entry with `setdefault`, so a probed compiler entry carrying the full
  fields was silently ignored and the gap was unfillable. The three keys are
  now in both whitelists (`DEPENDENCY_ENTRY_KEYS` updated to match), and the
  merge is field-level: discovery only fills fields the registry entry
  lacks, `validation` keeps the registry provenance, and existing fields
  still prefer the registry. Old archives (stacks without compiler fields)
  self-heal via field-level filling; re-running `deps-add` registers an
  enriched stack.
- `compile.shape_order` was silently ineffective with `deposit=zigzag` (the
  default) — report defect 6, which wasted a 741 GB production run: upstream
  only emits `-DSHAPE_ORDER` for `deposit=esirkepov`; otherwise the binary
  falls back to the built-in first-order scheme with no signal anywhere in
  the chain. The compatibility check gains
  `compile.shape_order_requires_esirkepov`: `shape_order != 1` with a
  non-esirkepov deposit fails; the options table in
  `references/entity-compile-options.md` now documents the dependency.

## [0.7.0] - 2026-08-03

The Workspace and Computation Site top-level model lands (design:
`design/workspace-and-computation-site-2026-08-03.md`, development plan:
`design/workspace-development-plan-2026-08-03.md`). The public model becomes
`Workspace → Project → Case → Identity → Evidence`: the Workspace is the
single working directory (the projects/ project tree, sites/ site records,
.ledger/ controller state — self-contained; after a wholesale move,
`workspace adopt` resumes); a Project is the container holding the source
authority; a Case is now one research thread with a clear intent inside a
project (Project 1:N Case); a Computation Site is a conventional file tree
on a compute machine (`<site_root>/{deps,checkouts,projects}`) plus the
authoritative record in the workspace. The store schema upgrades to v3
(projects become project entities, cases carry a `project_uid` foreign key;
`store migrate` chains v1→v2→v3, and the old root→case 1:1 binding upgrades
to one default case per project).

### Added

- Workspace container: `workspace init/adopt/where`; controller home
  resolution order: `--ledger-home` > `ENTITY_WORKSPACE` >
  `~/.entity-ledger/active-workspace` pointer > legacy `~/.entity-ledger`
  (compatibility fallback, one deprecation warning); snapshots resolve with
  the db. workspace.yaml/project.yaml/sites/*.yaml all use a flat+flow YAML
  subset implemented on the standard library (no PyYAML dependency).
- Project/Case split: `project init`, `case init` (intent.md and
  decisions.json skeletons); `--case <slug>` addressing threads through
  status/show/render-run/snapshot-source/record/submission — single-case
  projects resolve automatically, omitting it on a multi-case project fails
  and lists the available cases.
- `record intent` syncs the case directory's intent.md from the db as
  authoritative; manual edits are flagged as drift in the dashboard pending
  items.
- Site records and file trees: `sites/<site>.yaml` becomes the authority
  for site information (transport/scheduler/machine/site_root/projects/
  deps/notes); `site sync` (record → db; db-only entries are reported, not
  deleted), `site list/show` merged views, `site init` (builds the
  `<site_root>` skeleton plus an `entity-site.yaml` marker on the target
  machine, idempotent), `site discover` extended (the machine section lands
  in the record, existing markers are adopted).
- New-tree path derivation: when a profile carries `site_root`, new
  build/run/staging land at
  `<site_root>/projects/<project>/{builds,runs,staging}/<case>/<id>`
  (layout `site-tree`); legacy profiles without `site_root` keep
  independent-roots derivation and are tagged `legacy-roots`; legacy
  Locators remain referenceable.
- Deps registry: `site deps <site>` (human-readable + `--json`) and
  `site deps-add --from-checkpoint` (booked only when confirm +
  compatibility pass + env.sh evidence are all present, zero writes
  otherwise); env-build `entity_checkpoint.py create --from-registry`
  pre-fills `selected` with the verified stack matched by signature
  (probing on the spot for anything missing, the compatibility gate
  unchanged); the `record build` payload and identity carry `stack_id` and
  hint at deps-add when the stack is not registered.
- Migration primitives (agent-driven migration): `workspace import`
  (adopts local projects/ledger.db+snapshots/site-notes/legacy bindings;
  dry-run by default; conflicts are reported, never overwritten),
  `site plan-migration` (read-only inventory of the old tree producing a
  new-tree plan; in-flight runs are marked skip), `record relocate`
  (re-probes evidence after the move and updates the Locator; in-flight
  runs are refused; zero writes on evidence mismatch; writes a
  record.relocate audit event).
- `record run-abort`: an explicit escape hatch for in-flight runs whose
  site is permanently unreachable or confirmed dead — `--reason` is
  required and recorded in the identity and the audit event (actor
  attribution follows the existing mechanism); only usable on in-flight
  runs, terminal runs fail with zero writes. `aborted` joins the
  terminal-state vocabulary: eligible for relocate, no longer skipped by
  plan-migration, no longer probed by status --live; `--reclassify` does
  not apply to aborted (once the site recovers, outputs can still be
  inventoried with `record data`).
- Analysis management (the sixth dimension of the identity chain,
  `design/analysis-management-2026-08-05.md`):
  `record analysis --script/--data/--params/--output-root
  [--env-stack] [--hardcoded-paths]` — execution is free, registration is
  strict: the script must come from the project-wide script library
  `projects/<p>/analysis/scripts/` (content-hashed), and the output
  directory's `analysis-manifest.json` must exist with a data_id matching
  the claimed one; `analysis_id = hash(data_id, script_hash, params)` is
  derived deterministically and idempotently; when the parent data is not
  current, the dashboard analysis cell shows stale (derived at read time,
  historical identities preserved). The dashboard analysis cell upgrades to
  none/established/stale plus a hardcoded_paths warning; `show` gains an
  analyses list. The deps registry gains a `kind` field (`build` default /
  `analysis`); `site deps-add --kind analysis` registers a Python analysis
  environment gated on interpreter existence.
- `references/migration-guide.md` migration guide.
- Typed gres support: site policy gains `default_gres` (format
  `gpu[:type]:count`, e.g. `gpu:V100:1`; profile validation rejects bad
  values); `render-run` / `record run-prepare` gain a `--gres` explicit
  override; resolution order is explicit `--gres` > policy `default_gres` >
  generic `gpu:<N>`; the resolved value is recorded in the run identity's
  compute and rendered verbatim into the sbatch; `site discover` suggests
  `default_gres` when the recommended partition has a single GPU type
  (warning that an explicit choice is needed when there are several). The
  direct backend ignores gres (normalized to "").

### Fixed

- Exposed and fixed by the astro gold run (pilot) live exercise:
  - `record run-launch` reported "execution Site has no staging_root" for
    site-tree profiles (only `site_root`, no explicit roots) — the launch
    path now derives roots via `merged_execution_profile` (prepare/data
    already did);
  - the sacct call in Slurm terminal-state probing missed `-P`; real sacct
    defaults to table output, so exit_code always parsed as None (the test
    fake sacct always emitted pipe-separated output, masking the bug; the
    fake now simulates honestly);
  - teardown-abort log probing only recognized fixed file names
    (simulation.err/out): Entity names logs after simulation.name and
    places them in the output subdirectory, and Slurm merges stderr into
    out by default — probing now covers slurm-<job>.out (evidence in both
    directions) and `<run_root>[/*]/*.err|*.out`;
  - the dashboard pgen cell only scanned the project root and falsely
    reported "no TOML input" under the 0.7.0 source/ authority layout — it
    now also scans the source directory registered in project.yaml.

### Added (rc increment)

- `entityctl install --provider {codex,claude,kimi}` (repeatable): projects
  the bundle only to the specified clients; the default still installs to
  all three. The return payload gains `providers`, recording the clients
  actually installed to.
- env-build build-script build_dir guard: when `compile.build_dir` points
  at an existing non-empty directory, generation is refused (the error
  explains the relink/evidence-distortion risk); an explicit
  `--reuse-build-dir` or `--clean-build` is required — this prevents
  silently relinking an already-registered build after copying requirements
  from a previous round and inheriting its old build_dir.
- `record run-prepare --run-id`: requires the newly derived run to equal
  the id previewed by render-run — run_id is content-addressed on (source,
  TOML, compute, build), so a mismatch proves the inputs drifted after
  render; fails with zero writes instead of silently preparing a second
  run.
- Error-message improvements (postmortem of aborted round S1): `case
  init`'s "no local Site source_root covers the project" now gives
  actionable advice (register a local site record, set source_root to the
  workspace root rather than the whole home, run `site sync`); `workspace
  init` on a Site tree root containing `entity-site.yaml` fails with a
  targeted error (a Site is an ssh execution target; the workspace belongs
  on the development machine).
- Docs: SKILL.md gains an "architecture red lines" section (the controller
  runs only on the development machine, never scp tools to a site, confirm
  the workspace location with the user first);
  `references/workspace-layout.md` gains a site-record format section
  (flat-YAML + JSON flow rules + a fully annotated astro-streaming
  example).
- Production invocation logging (passive invocation logging, a different
  layer from eval traces): the CLI entry points of the four skills
  (entityctl, the ledger executor/remote standalone CLIs, the four
  env-build CLIs, pgen_preflight, inspect_nt2_data) append one JSONL line
  per actual invocation (time/duration/exit_code/redacted argv/cwd/host
  etc.), defaulting to
  `~/.entity-skills/observability/invocations/<yyyy-mm>.jsonl` rotated
  monthly, overridable via `ENTITY_SKILL_INVOCATION_LOG`; all exceptions on
  the logging path are swallowed and host semantics are unchanged; the four
  scripts/ hold byte-identical `_invocation_log.py` copies, with a test
  guarding byte equality against drift; invisible to agents (SKILL.md
  untouched).
- Invocation-logging fix batch (same evaluation report):
  `ENTITY_SKILL_INVOCATION_LOG=off` (case-insensitive exact match) is fully
  silent, and the repo's tests/conftest.py disables it by default via an
  autouse fixture — test traffic (once 90% of invocations) no longer
  pollutes production stats; when logging, agent client environment
  variables (common KIMI_/CLAUDE/CODEX names) are sniffed best-effort to
  add an `agent_hint` field — only variable names are recorded, never
  values (leak-proof), and the field is omitted on no match. All four
  copies updated.
- The error payload gains a machine-readable `"retryable"` boolean
  (`status=="anomaly"` → true, false otherwise); the SKILL.md error-contract
  section states that only anomaly (transient/external failure) is worth
  retrying as-is, while invalid_request/needs_decision require changing the
  input or escalating to a human.
- `record run-correct` (manual correction primitive, companion to B2):
  manual correction between the two booked terminal states
  completed↔failed; `--reason` is required and recorded in the identity
  (the `correction` section) and the audit event (from/to/reason);
  in-flight runs are refused (run-exit to a terminal state first);
  same-state correction is a no-op. Coexists with `--reclassify` (re-judge
  from log evidence); neither replaces the other.
- `record run-launch --resubmit` (I3): resubmits the same run when the
  Ledger-submitted job reached a terminal failed state — first probes that
  the old job is really dead (still running, gone, or no probed terminal
  state all refuse, advising run-exit first), then runs the normal
  preflight+submit; the new submission uses its own exactly-once receipt
  (`run-relaunch-<n>.json`, exactly-once counted per submission), the old
  scheduler record moves into the identity's `prior_submissions`, and the
  event and the return annotate `resubmit: true` and `previous_scheduler`.
  Behavior without the flag is unchanged.

### Fixed (rc increment)

- A v3 bundle reading a pre-workspace (v2/v1) store no longer crashes with
  an `IndexError: project_uid` traceback: `OperationStore` validates meta
  schema_version when opening an existing db and raises a StoreError with
  migration guidance (`entityctl store migrate`) on mismatch; doctor
  reports an unmigrated store as a diagnostic warning and skips export
  (previously export crashed before the warning logic ran). A single check
  covers all OperationStore read paths: export/dashboard/facts/site etc.
- `entity_checkpoint.py create --merge` dropped the old checkpoint's
  `paths.pre_commands`/`modules`/`extra_env` — the regenerated env.sh
  missed module loads; merge now preserves these keys (`modules` takes the
  union of the modules collected from each entry in `selected`), and
  `derive_paths` folds the `modules` carried by dependency entries into
  paths.
- Production-evaluation fix batch
  (`design/skill-production-evaluation-2026-08-17.md`):
  - A non-zero exit from the remote executor is no longer swallowed into
    "Site executor returned invalid JSON": the exit code is checked first
    and the error message carries the stderr tail (last ~500 chars);
    invalid JSON is reported only on zero exit with no JSON on stdout, with
    the stdout head (~200 chars) attached.
  - `_require_case` misleading messages split: an unregistered project path
    (no_project) now states plainly "no project is registered at <path>"
    and advises using the new path or `workspace import`, matching
    registered projects by basename and listing candidates in the message
    (the old-path-after-migration scenario); the create-Case guidance in
    the "project registered but no Case" branch now names the real command
    `entityctl case init <project> <name>` (run-prepare does not create
    Cases); store `get_site` lists registered site candidates for an
    unknown site_id.
  - `record run-exit`'s return for a still-running run gains
    `detail: "run is still running; no state written"`.
  - `doctor --project-root` no longer hits a bare argparse error: doctor is
    a workspace-level diagnostic; it accepts the flag and immediately fails
    with a guidance error (invalid_request, pointing at `status
    --project-root <path>`).
- Slurm terminal-state classification fix (B2: the sacct terminal word
  takes precedence over the exit code): non-COMPLETED terminal words such
  as CANCELLED/TIMEOUT/OUT_OF_MEMORY are always booked failed, even when
  the exit code is 0:0 (jobs killed by scancel/OOM can still report a clean
  exit code — the polar_cap OOM run was therefore misbooked completed by
  the old logic); COMPLETED or no scheduler word (direct) keeps exit-code
  classification and the teardown-abort rescue unchanged; the terminal word
  is also written into the run-exit event payload (`scheduler_state`). No
  new terminal states are added.

### Changed

- **export JSON projects shape change** (breaking): the v2 binding rows
  `{project_root, case_uid, updated_at}` become v3 project entities
  `{project_uid, slug, project_root, created_at, updated_at}`; cases gain a
  `project_uid` field. Scripts consuming `entityctl export` must be
  updated.
- `references/workspace-layout.md` rewritten as the Workspace + Computation
  Site layout contract; the four SKILL.md files and the README are synced
  to the new model; the env-build docs are synced with the deps-registry
  lookup order and write-back flow.
- `pgen_preflight.py`'s controller location now goes through the unified
  `resolve_ledger_home` (workspace-aware; the explicit `--ledger-home`
  entry is unchanged).
- site-notes prose is migrated by `site import-notes` into the notes
  section of the record; `references/site-notes-template.md` is marked
  deprecated.

## [0.6.1] - 2026-07-29

### Fixed

- `entity-pgen` write gate no longer routes managed writes into a dead end:
  the preflight refused every write inside a Ledger-registered Case source
  ("managed writes require a v5 pgen Goal") and bounced the request to a
  Ledger record primitive that does not exist — that Goal kind was retired
  with the plan/apply protocol. Writes inside the Case source authority are
  now allowed (`managed-write`) — the Ledger does not intervene in the PGen
  process; once the change settles, `entityctl snapshot-source` re-probes the
  tree and books the new source identity (re-`confirm` the input TOML before
  `record run-prepare`). Recorded artifact roots (build/run/data identities,
  the active run) stay fail-closed (`router-required`).
- Observability `validate_pgen_preflight` no longer fails real
  `managed-write` outcomes: it required an Action id, controller root, and
  Action-request envelope from the retired plan/apply protocol; it now
  requires only a Case identity.

## [0.6.0] - 2026-07-28

Skill rename: `entity-router` is now `entity-ledger` — the plan/apply
control plane is gone and the skill is a deterministic ledger of project
assets and facts, so the Router name no longer fit. The rename covers the
skill directory, all `entity_router_*.py` modules, the JSON contract kinds
(`entity-ledger.*`, receipt comment prefix `entity-ledger:`), and storage:
the home is now `~/.entity-ledger` with `ledger.db` (`ENTITY_LEDGER_HOME`).
Pre-rename storage is adopted automatically: `ENTITY_ROUTER_HOME` is still
honoured when `ENTITY_LEDGER_HOME` is unset, a legacy `~/.entity-router`
directory is renamed on first access, and a legacy `router.db` is renamed
to `ledger.db` when the store opens. The per-activity playbooks are
removed; their unique semantics (exactly-once launch receipts, external
job adoption, in-flight runs not occupying project state) live in
`SKILL.md`.

Case-centric restructure: the plan/apply control plane is replaced by
deterministic primitives. Agents plan the simulation flow; the CLI reads and
writes deterministic records, renders deterministic scripts, and probes
evidence — big flows are no longer wrapped in code.

### Added

- `entityctl status` human-readable dashboard: readiness board
  (source/pgen/build/run/data/analysis with evidence), run ledger, pending
  items, and derived next steps; `--json` preserves the machine contract.
- Primitive commands: `show`, `render-run`, `snapshot-source`, and
  `record build|run-prepare|run-launch|run-exit|data|intent`. Write
  primitives probe their own evidence before booking facts and fail with
  zero writes; `record run-launch` keeps exactly-once via receipts, runs a
  Slurm preflight before submitting, and can adopt externally submitted
  jobs (`--adopt-job` / `--adopt-pid`).
- `record intent`: the research intent is the only stored pointer, shown on
  the dashboard.
- `store migrate` v1→v2: archives legacy operations to
  `<ledger_home>/archive/`, then installs the slimmed store.
- `record run-exit` recognizes Entity's known harmless teardown abort: when
  the terminal exit code is non-zero but the run_root logs show both the
  final step reached (`Step: N ... [of M]` with `N >= M - 1`, ANSI escapes
  stripped) and a known glibc `malloc_consolidate()` abort signature, the
  run is booked `completed` with an `exit_anomaly` note (the real exit code
  is preserved). Missing or mismatched evidence keeps the run `failed`,
  exactly as before. The new `--reclassify` flag re-judges a run already
  booked `failed` from its log evidence alone (no scheduler probe), and the
  dashboard run cell annotates the anomaly.

### Changed

- Job submission no longer sets a walltime by default: `--walltime` now
  defaults to empty, the rendered sbatch carries no `#SBATCH --time=` line
  (the partition/QoS default limit applies), and the direct backend skips
  its timeout wrapper. An explicit `--walltime HH:MM:SS` behaves exactly as
  before, including format validation.
- `entity-ledger/SKILL.md` rewritten around the research workflow;
  control-plane internals moved to `references/ledger-runtime.md`.
- Store schema v2: drops the operations/steps tables and the whole
  Operation API; concurrency degrades to the `BEGIN IMMEDIATE` file lock,
  events remain as passive audit.
- Local Sites run the executor in-process: `ExecutorClient` calls the same
  validate/execute/verify logic with the same on-disk receipts, skipping
  the content-addressed script copy, the request envelope file, and two
  `python3` spawns per record step. SSH Sites are unchanged.
- The snapshot manifest walk now lives in one place
  (`entity_ledger_common.source_manifest`). The removed duplicate in
  `entity_ledger_remote.py` did not exclude `run-*` directories, so a
  source containing them could get two different snapshot ids depending on
  the path taken; snapshot ids of such sources change (content addressing
  simply writes a new archive).
- Site fingerprinting, identity lookup, and the pgen confirmation
  comparison are unified into shared helpers
  (`site_file_sha256`, `find_identity`, `load_simulation_confirmation`)
  instead of three near-identical copies.

### Removed

- The plan/apply protocol: `entityctl plan/apply/operation cancel`,
  GoalSpec and plan JSON schemas, the planner, the apply engine, and
  claim/lease machinery. Legacy operations are export-archived on migrate.
- Plan/apply-era dead code: `entity_ledger_purge.py` (the `data.purge`
  Action protocol had no producer), the executor kinds
  `build.register.v1` and the direct-backend preflight (no caller),
  `entity_ledger_remote.py`'s snapshot-install half, the duplicate
  `entityctl bundle install` command, and the `--router-home` CLI alias
  (the `ENTITY_ROUTER_HOME` environment variable is still honoured).

## [0.5.0] - 2026-07-22

Observability and reconciliation (Phase 3): out-of-band changes now surface,
drift fails, and skill adoption is measurable.

### Added

- `status --live` reconciliation: the report always carries a `divergences`
  list classifying out-of-band changes between the store and the scheduler:
  - `job_gone`: the recorded job is absent from `squeue`; `confirmed` is true
    when `sacct` also has no record, false when `sacct` is unavailable.
  - `state_mismatch`: the job reached a terminal scheduler state
    (`recorded: submitted`, `observed: <STATE>`) the router never saw.
  - `untracked_job`: a foreign scheduler job runs in the Case run root —
    evidence of control-plane bypass.
  Live status makes at most three bounded scheduler queries.
- `entityctl apply --refresh`: re-executes a completed `data` Goal plan so a
  stale `data-inventory.json` is rebuilt after run artifacts changed.
  Rejected for other Goal kinds. This closes the 0.4.0 known limitation.
- `doctor` hard failures (exit 2, `ok: false`, new `failures` list): client
  bundle installs that drifted from the runtime bundle, and stored Site
  profiles that fail validation.
- `doctor` warnings for leaked active Operations (crash leftovers holding a
  Case), each with the exact `entityctl operation cancel <id>` remedy.
- Skill adoption metrics: the phase-segmentation report
  (`tools/skill_observability/adapters/claude_phases.py`) now carries a
  `skill_adoption` section counting skill-script invocations
  (router/env_build/pgen/nt2py) versus raw equivalents (sbatch/srun/scancel/
  scheduler polls/build tools), direct `sqlite` control-plane surgery, and a
  `skill_call_share` ratio — the clean-comparison metric required by the
  1.0.0 candidate criteria.

### Changed

- The `data.inventory.v1` executor Step always re-walks the run root instead
  of short-circuiting on a previous verified receipt; inventory is a pure
  function of the current run root, which is what makes `--refresh` work.

## [0.4.0] - 2026-07-22

### Added

- New Goal kinds `build` and `data` (Phase 2 e2e coverage):
  - `build` registers an env-build-produced build into the identity chain.
    Hard gates at plan and apply: the checkpoint must have
    `compatibility.status == "pass"` and a `decisions.parameters` confirmation
    digest. The registered build identity feeds subsequent run Goals without
    an explicit `executable`.
  - `data` inventories a run's outputs into a content-hashed
    `data-inventory.json` and advances `current.data_id` / readiness.
- Executor Step kinds `build.register.v1` and `data.inventory.v1`.
- Gates added: run Goal planning now requires a simulation-parameter
  confirmation record (`<input>.decisions.json` written by
  `pgen_preflight.py confirm`) whose `input_sha256` matches the current TOML;
  missing or stale records fail planning with `needs_decision` (Phase 1.5).

### Changed

- Plans now carry `goal_kind`; `validate_plan` checks per-kind key sets and
  Step schemas. Plans written by 0.1.0 remain valid (missing `goal_kind`
  reads as `run`) but should be re-planned.

### Known limitations

- Re-inventorying a run whose outputs changed produces the same Plan, which
  resolves to the completed Operation; a refresh path lands with the
  reconciliation work in 0.5.0.
- `analysis` Goal is not implemented yet; analysis stays with entity-nt2py
  and router records only.

## [0.3.0] - 2026-07-22

### Added

- entity-env-build: build parameter confirmation gate (Phase 1.5, hard fail).
  `entity_checkpoint.py confirm <requirements> --checkpoint <checkpoint>
  --by <actor> [--confirm-defaults]` records `decisions.parameters`
  `{digest, confirmed_by, confirmed_at, defaults, card}`; the compatibility
  check `parameters.confirmation` fails when the record is missing or the
  digest no longer matches the current requirements.
- entity-pgen: `pgen_preflight.py card <input.toml>` prints the simulation
  parameter card; `pgen_preflight.py confirm <input.toml> --by <actor>
  [--confirm-defaults]` writes `<input>.decisions.json`.

## [0.2.0] - 2026-07-22

### Added

- `entityctl site discover <site>`: enumerates Slurm partitions and QoS via
  `sinfo`/`sacctmgr` and suggests `policy.default_*` values (read-only).
- `templates/site-profile.schema.json` documenting the Site profile contract.
- `entityctl submission create/verify`: submission fingerprints are always
  recomputed by the tool from the final artifacts; `verify` reports stale and
  missing artifacts and exits non-zero on drift.
- Executor anomaly remediation: scheduler rejections (invalid QoS/partition)
  now carry the exact repair path (`entityctl site discover` + policy fix).

## [0.1.0] - 2026-07-22

First disciplined release. Baseline: the Entity Router v5 architecture lineage
(store schema 1) with the fixes below. Development plan:
`design/router-development-plan-2026-07-22.md`.

### Added

- `entityctl operation cancel <id>`: terminal escape hatch for pending/running
  Operations; releases the Case so a different Plan can proceed.
- `entityctl store migrate`: store schema migration entry point (shell; no
  schema migrations exist yet). Doctor reports the store schema version and
  points here on mismatch.
- `bundle_version` reported alongside `bundle_hash` in `entityctl doctor` and
  install receipts; single source at `skills/entity-router/VERSION`.
- entity-env-build: `mpi.openmpi_min_version` compatibility check — OpenMPI
  must be >= 5.0.0 when selected (fail below; warn when unrecorded).
- Gates added: re-applying a Plan after a failed Apply reopens the Operation
  and resumes committed Steps instead of deadlocking the Case.

### Fixed

- entity-router executor sbatch now invokes `srun <exe> -input <file>`;
  Entity ignores positional arguments and previously opened the default
  `input` file, burning the first submitted job.
- A failed Apply no longer leaks an active Operation; it finishes as
  `anomaly` and releases the Case (previously forced direct sqlite surgery).
- Missing-store error no longer points at the nonexistent `entityctl migrate`.
- `status --live` degrades to cached controller state with a warning when the
  scheduler query fails, instead of exiting 2.

### Changed

- User-facing "Router v5" strings renamed to plain "Entity Router"; v5 remains
  only as the internal architecture lineage and store schema integer.
- Doctor output keys `v5_store`/`v5_store_available` renamed to
  `store`/`store_available`.
