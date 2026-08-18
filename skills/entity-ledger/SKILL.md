---
name: entity-ledger
description: Maintain a deterministic record for the Entity plasma simulation project: environment, source versions, builds, the run ledger, and data status are all documented, so any session (a different machine, a different agent, a mid-run crash) can pick up where the last one left off. Use for cross-session or cross-machine simulation work, run submission and tracking, and results inventory. Bounded read-only questions and standalone PGen/build/analysis edits can go directly to the corresponding owner skill.
---

# Entity Ledger

This skill keeps you from **losing state** while doing plasma simulation
research with Entity: how the build environment was configured, which code
version is in use, which runs have been executed, with what parameters, and
where the results live — these deterministic facts are all on record. You
explore freely (edit the PGen, change parameters, analyze data); the Ledger
records established facts into the Case ledger, so any session can tell
where the project stands and what the next step is.

Public model:

```text
Workspace → Project → Case → Identity → Evidence
```

- **Workspace** is the single working directory: the project trees under
  `projects/`, the site profiles under `sites/`, and the controller state
  under `.ledger/` (ledger.db + source snapshots). The directory is
  self-contained; it can be moved to any machine as a whole and work
  continues after `workspace adopt`.
- **Project** is the research-topic container and holds the source
  authority; **Case** is a well-scoped research thread inside a project
  (one intent + one PGen configuration family + its build/run/data chain).
  A parameter scan = one case with many runs; only a change of intent
  starts a new case.
- **Computation Site** is a conventional file tree on one machine (or an
  HPC access boundary) (`<site_root>/{deps,checkouts,projects}`) plus the
  profile registered in the workspace (`sites/<site>.yaml` is
  authoritative): it holds shared deps, materialized source, and executes
  build/run.

Case/identity IDs, hashes, Locators, and paths are derived by the
controller; do not ask the user to provide or manage these fields.

## Architectural red lines

- **The controller runs only on the development machine**: `entityctl`
  and the workspace (`.ledger/`, `sites/`, `projects/`) exist only on the
  machine where you (the agent) run. A Computation Site is only an ssh
  execution endpoint — the Ledger drives it through the transport.
- **Never scp entityctl, the workspace, or any skill tooling onto a site
  to run it there**; only two kinds of actions are allowed on a site:
  Slurm jobs (sbatch/squeue/sacct) and ordinary file operations (issued
  by the Ledger's transport, or by your own lightweight manual ssh).
  Running the controller on a site is an architectural inversion.
- **Confirm the workspace location with the user before init** (suggested
  default: under the project directory on the development machine). Do
  not create a workspace on a site; a directory containing
  `entity-site.yaml` is a Site tree root, not a workspace.

## Read project status first

First confirm which workspace the controller points at:

```bash
python3 scripts/entityctl.py workspace where
```

Resolution order for the controller home: `--ledger-home` (and the
`ENTITY_LEDGER_HOME`/`ENTITY_ROUTER_HOME` environment variables — all
explicit) > the `ENTITY_WORKSPACE` environment variable > the
`~/.entity-ledger/active-workspace` pointer > the legacy
`~/.entity-ledger` (compatibility fallback). When no workspace is active,
create one with `workspace init <path>` and activate it with `workspace
adopt <path>`; legacy layouts (scattered project directories, the old
`~/.entity-ledger`, site-notes) are absorbed in one pass with `workspace
import` — see `references/migration-guide.md`.

When entering a project, run first:

```bash
python3 scripts/entityctl.py status --project-root <project> [--case <slug>]
```

The output is a human-readable project dashboard (grouped by
project → case):

- **Readiness board**: status and evidence for the six cells
  source / pgen / build / run / data / analysis (which cell is missing,
  which is stale, run exit codes);
- **Run ledger**: which runs have been executed, on which machine, in
  what state — the run sequence is the research trajectory;
- **Pending decisions**: unconfirmed parameters, out-of-band changes, and
  other matters requiring a decision;
- **Suggested next steps**: derived from current facts (not stored, never
  stale).

`--live` additionally probes the current state of the
scheduler/processes; `--json` returns the machine-readable contract;
`show --project-root <project>` prints the Case fact details. status and
show are read-only and never write state. When a project has only one
case, `--case` may be omitted; with multiple cases, every
record/render/status/show command must select one with `--case <slug>`
(omitting it errors out and lists the available cases).

## Deterministic primitives

The CLI is an auxiliary tool; each command does exactly one deterministic
thing, and you orchestrate the sequence according to the user's goal.
Writing primitives carry their own evidence probes — verify first, then
record; on failure nothing is written, and after fixing the cause you
simply rerun the same command:

```bash
# Workspace and project skeleton
python3 scripts/entityctl.py workspace init|adopt|where|import ...
python3 scripts/entityctl.py project init <name>
python3 scripts/entityctl.py case init <project> <name>

# Generate (does not write state)
python3 scripts/entityctl.py render-run \
  --project-root <project> --toml <input.toml> --site <site> \
  [--gpus N] [--walltime HH:MM:SS] [--gres gpu[:type]:count] \
  [--precision single|double] [--executable <path>]
  # --walltime left empty (default) sets no time limit; the partition/QoS default applies
  # --gres left empty (default) uses the site policy's default_gres, else falls back to gpu:<N>;
  # a scheduler-less (direct) Site ignores gres
python3 scripts/entityctl.py snapshot-source --project-root <project>

# Record (probe evidence first, then write to the ledger)
python3 scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  record run-prepare --project-root <project> --toml <input.toml> --site <site> [...]
python3 scripts/entityctl.py record run-launch --project-root <project> [--run-id <id>] [--resubmit]
python3 scripts/entityctl.py record run-exit  --project-root <project> [--run-id <id>] [--reclassify]
python3 scripts/entityctl.py record run-abort --project-root <project> [--run-id <id>] --reason "<reason>"
python3 scripts/entityctl.py record run-correct --project-root <project> [--run-id <id>] \
  --status <completed|failed> --reason "<reason>"
python3 scripts/entityctl.py record build --project-root <project> --site <site> \
  --checkpoint <deps-checkpoint.json> --executable <path>
python3 scripts/entityctl.py record data --project-root <project> [--run-id <id>]
python3 scripts/entityctl.py record intent --project-root <project> --text "<current research goal>"
python3 scripts/entityctl.py record analysis --project-root <project> \
  --script <path relative to scripts/> --data <run_id|data_id> --params '<json>' \
  --output-root <site artifact directory> [--env-stack <stack_id>] [--hardcoded-paths]

# Site profiles, file trees, and the deps registry
python3 scripts/entityctl.py site sync [site]        # profile → db
python3 scripts/entityctl.py site init <site>        # build the <site_root> skeleton + marker on the target machine
python3 scripts/entityctl.py site deps <site>        # registry (human-readable / --json)
python3 scripts/entityctl.py site deps-add <site> --from-checkpoint <entity-deps.local.json>

# Migration (the agent performs the moves; the primitives only inventory and record)
python3 scripts/entityctl.py site plan-migration <site>
python3 scripts/entityctl.py record relocate --project-root <project> \
  --dimension <build|run|data> --identity-id <id> --to <new absolute path>
```

Error contract: a failure prints `{"ok": false, "status": ..., "error":
..., "retryable": ...}` (exit 2). **Only `status: "anomaly"` (a
transient/external failure such as a dropped SSH connection or a remote
crash) is worth retrying as-is**, and then `retryable` is `true`;
`invalid_request`, `needs_decision`, and all other statuses are
deterministic errors (`retryable: false`) — retrying them unchanged will
never work: you must change the input, or escalate the questions in
`decisions` to the user. Do not wrap every call in a fixed-count retry
loop.

Key semantics:

- `record run-prepare` requires the parameters to be confirmed (the pgen
  skill's `pgen_preflight.py confirm <input> --by <actor>` writes
  `<input>.decisions.json`); after the TOML changes, re-confirmation is
  required.
- The `record run-launch` receipt guarantees exactly-once: repeated
  execution does not resubmit, and rerunning after a process interruption
  adopts the already-submitted job; jobs submitted outside the Ledger are
  adopted into the ledger with `--adopt-job` / `--adopt-pid`. When a
  Ledger-submitted job has reached a terminal state and failed (died
  within seconds, CANCELLED, etc.), resubmit it with `--resubmit`: it
  first probes that the old job is truly dead (it refuses while the job
  is still running or no terminal state can be probed), the new
  submission gets its own exactly-once receipt (exactly-once is counted
  "per submission", not "once per run"), the old scheduler record moves
  into the identity's `prior_submissions`, and the event is annotated
  `resubmit: true`.
- Once a run is on the scheduler it is an in-flight fact and does not
  occupy project state; while waiting you can analyze the previous run or
  develop the next PGen, and `status --live` probes progress at any time.
- `record run-exit` trusts the scheduler terminal word before the exit
  code: when sacct reports a non-COMPLETED word such as
  CANCELLED/TIMEOUT/OUT_OF_MEMORY, the run is always booked `failed`
  (even with a 0:0 exit code — a job killed by scancel/OOM can still
  report a clean exit code), and scheduler_state is written into the
  event as well; on COMPLETED, or when there is no scheduler word
  (direct), classification goes by the exit code. When the terminal state
  is a non-zero exit, it uses the run_root log evidence to recognize the
  known teardown abort at exit: stdout (ANSI stripped) shows the final
  step satisfying `Step: N [of M]` with `N >= M - 1`, and the stderr tail
  matches a known glibc `malloc_consolidate()` abort signature — with
  both pieces of evidence the run is booked `completed` with an
  `exit_anomaly` note (the real exit_code is preserved); with either
  missing it stays `failed`. For a run already booked `failed`, once the
  log evidence is available, use `--reclassify` to re-judge it (skips the
  scheduler probe, only valid for `failed`, any other state errors out
  with zero writes).
- `record run-correct` is the manual-correction primitive: when a booked
  terminal state was recorded wrongly (for example a CANCELLED 0:0 job
  mis-booked as completed by an old version), correct between
  completed/failed with `--status completed|failed --reason <reason>`;
  in-flight runs are refused (run-exit them to a terminal state first),
  and correcting to the same state is a no-op. It coexists with
  `--reclassify`: reclassify re-judges from log evidence, run-correct is
  a human declaration — the reason is required and lands in the identity
  and the audit event.
- `record run-abort` is the explicit escape hatch for stuck runs: a site
  that is permanently unreachable (machine decommissioned, SSH broken) or
  an in-flight run confirmed dead can be declared abandoned by a human.
  `--reason` is required and lands in the identity and the audit event;
  it is only valid for in-flight runs (an already-terminal run errors out
  with zero writes). aborted is a terminal state: the run can be
  relocated and migrated, and status --live no longer probes it.
  `--reclassify` does not apply to aborted; if the site recovers, the
  output can still be inventoried with `record data`.
- `record analysis` is the sixth identity dimension: **free execution,
  strict recording** — where and how you run it is none of the Ledger's
  business; recording does after-the-fact evidence probing: the script
  must come from the project's shared script library
  `projects/<p>/analysis/scripts/` (content-hashed; case-level one-off
  scripts are managed by the agent and not recorded), and the artifact
  directory's `analysis-manifest.json` must exist with a data_id matching
  the claim; once the manifest has the `script`/`script_sha256`/`params`
  fields written, they are cross-checked one by one at record time.
  `--params` is optional and defaults to `{}`; note that JSON number
  types affect the analysis_id (`1` and `1.0` are different parameters).
  `analysis_id = hash(data_id, script hash, params)`, idempotent; when
  the parent data is no longer current, the analysis automatically shows
  stale (historical identities are kept, never deleted; a new record
  whose parent data is no longer current is booked as a historical entry,
  not promoted to current). Existing scripts with hardcoded paths are not
  refused — mark them with `--hardcoded-paths` and the dashboard reminds
  you. A Python analysis environment is registered into the deps registry
  with `site deps-add --kind analysis` (only the interpreter's existence
  on the site is required) and referenced by `record analysis
  --env-stack`.
- `record build` requires the env-build checkpoint to be
  `compatibility: pass` and the parameters to be confirmed; once
  recorded, run primitives may omit `--executable`.
- `record intent` records the current research goal (the dashboard "goal"
  line). The intent is the only stored "pointer" — all-green artifacts do
  not mean the work is done; the goal can only be recorded explicitly. It
  keeps you from drifting as you explore; a new goal replaces the old one
  (history stays in the audit events). The db is authoritative: writing
  rewrites the case directory's `intent.md` in sync, and manual edits
  that diverge from the db are flagged as drift in pending decisions.
- The site profile (`sites/<site>.yaml`) is the authority for site
  information; `site sync` refreshes the db. When the profile carries
  `site_root`, new builds/runs land in the new tree
  `<site_root>/projects/<project>/{builds,runs,staging}/<case>/<id>`;
  legacy profiles keep the independent-roots derivation, are flagged
  legacy, and old Locators remain resolvable.
- The deps registry answers "which environments have been used on this
  machine before": verified stacks are recorded with `site deps-add`
  (mismatched evidence means zero writes), and env-build reuses
  `deps/<stack_id>/env.sh` directly from the registry exported by
  `site deps <site> --json` when resolving dependencies.
- The migration trio: `workspace import` (local absorption, dry-run by
  default), `site plan-migration` (read-only inventory producing an
  old-tree → new-tree plan), and `record relocate` (after the agent has
  moved the data, re-probe the evidence and update the Locator; in-flight
  runs are refused; mismatched evidence means zero writes). For the
  workflow and the taboos see `references/migration-guide.md`.
- Management commands: `doctor`, `install`, `site add/list/show/discover`,
  `store migrate`, `submission create/verify`, `export`. Probe with
  `site discover` before writing a site policy (the results land in the
  profile's machine section); after a crash, use `doctor` to check the
  installation and storage.

Internal mechanisms (receipts, executor, scheduler backends, live probing
details) are only needed for debugging — see
`references/ledger-runtime.md`; the Workspace and Site layout is covered
in `references/workspace-layout.md`; the migration workflow in
`references/migration-guide.md`.

## Owner skills

`entity-pgen` owns PGen/TOML/design, `entity-env-build` owns dependencies
and builds, `entity-nt2py` owns data access and analysis. Apply **free
exploration, strict convergence** to them: give them the semantic goal,
the input identity, boundaries, and acceptance criteria, and let them
choose their internal methods; the Ledger only records established facts
that have been re-probed, and does not perform their domain reasoning.

## Destructive operations

Deleting raw data always requires explicit user authorization, a precise
manifest, protected source/build/dependency roots, and a receipt outside
the deletion target. Never infer deletion authorization from a broad
request.

## Reporting

Report primitive execution results, the exact source/build/run
identities, the execution Site, the verified outputs/effects, unresolved
decisions, and whether status is cached or live. Internal receipts and
storage fields are diagnostic details, not normal user-facing work
content.
