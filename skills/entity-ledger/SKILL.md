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
records established facts into the Case ledger, so any session can tell where
the project stands and what the next step is.

Public model:

```text
Project → Case → Identity → Evidence
```

Case/identity IDs, hashes, Locators, and paths are derived by the controller;
do not ask the user to provide or manage these fields.

## Read project status first

When entering a project, run first:

```bash
python3 scripts/entityctl.py status --project-root <project>
```

The output is a human-readable project dashboard:

- **Readiness board**: status and evidence for the six cells
  source / pgen / build / run / data / analysis (which cell is missing, which
  is stale, run exit codes);
- **Run ledger**: which runs have been executed, on which machine, in what
  state — the run sequence is the research trajectory;
- **Pending decisions**: unconfirmed parameters, out-of-band changes, and
  other matters requiring a decision;
- **Suggested next steps**: derived from current facts (not stored, never
  stale).

`--live` additionally probes the current state of the scheduler/processes;
`--json` returns the machine-readable contract; `show --project-root
<project>` prints the Case fact details. status and show are read-only and
never write state.

## Deterministic primitives

The CLI is an auxiliary tool; each command does exactly one deterministic
thing, and you orchestrate the sequence according to the user's goal. Writing
primitives carry their own evidence probes — verify first, then record; on
failure nothing is written, and after fixing the cause you simply rerun the
same command:

```bash
# Generate (does not write state)
python3 scripts/entityctl.py render-run \
  --project-root <project> --toml <input.toml> --site <site> \
  [--gpus N] [--walltime HH:MM:SS] [--precision single|double] [--executable <path>]
  # --walltime left empty (default) sets no time limit; the partition/QoS default applies
python3 scripts/entityctl.py snapshot-source --project-root <project>

# Record (probe evidence first, then write to the ledger)
python3 scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  record run-prepare --project-root <project> --toml <input.toml> --site <site> [...]
python3 scripts/entityctl.py record run-launch --project-root <project> [--run-id <id>]
python3 scripts/entityctl.py record run-exit  --project-root <project> [--run-id <id>] [--reclassify]
python3 scripts/entityctl.py record build --project-root <project> --site <site> \
  --checkpoint <deps-checkpoint.json> --executable <path>
python3 scripts/entityctl.py record data --project-root <project> [--run-id <id>]
python3 scripts/entityctl.py record intent --project-root <project> --text "<current research goal>"
```

Key semantics:

- `record run-prepare` requires the parameters to be confirmed (the pgen
  skill's `pgen_preflight.py confirm <input> --by <actor>` writes
  `<input>.decisions.json`); after the TOML changes, re-confirmation is
  required.
- The `record run-launch` receipt guarantees exactly-once: repeated
  execution does not resubmit, and rerunning after a process interruption
  adopts the already-submitted job; jobs submitted outside the Ledger are
  adopted into the ledger with `--adopt-job` / `--adopt-pid`.
- Once a run is on the scheduler it is an in-flight fact and does not occupy
  project state; while waiting you can analyze the previous run or develop
  the next PGen, and `status --live` probes progress at any time.
- When a run exits non-zero, `record run-exit` uses the run_root log evidence
  to recognize the known teardown abort at exit: stdout (ANSI stripped)
  shows the final step satisfying `Step: N [of M]` with `N >= M - 1`, and
  the stderr tail matches a known glibc `malloc_consolidate()` abort
  signature — with both pieces of evidence the run is booked `completed`
  with an `exit_anomaly` note (the real exit_code is preserved); with either
  missing it stays `failed`. For a run already booked `failed`, once the log
  evidence is available, use `--reclassify` to re-judge it (skips the
  scheduler probe, only valid for `failed`, any other state errors out with
  zero writes).
- `record build` requires the env-build checkpoint to be
  `compatibility: pass` and the parameters to be confirmed; once recorded,
  run primitives may omit `--executable`.
- `record intent` records the current research goal (the dashboard "goal"
  line). The intent is the only stored "pointer" — all-green artifacts do
  not mean the work is done; the goal can only be recorded explicitly. It
  keeps you from drifting as you explore; a new goal replaces the old one
  (history stays in the audit events).
- Management commands: `doctor`, `install`, `site add/list/discover`,
  `store migrate`, `submission create/verify`, `export`. Probe with
  `site discover` before writing a site profile; after a crash, use
  `doctor` to check the installation and storage.

Internal mechanisms (receipts, executor, scheduler backends, live probing
details) are only needed for debugging — see
`references/ledger-runtime.md`; multi-site directory ownership is covered in
`references/workspace-layout.md`.

## Owner skills

`entity-pgen` owns PGen/TOML/design, `entity-env-build` owns dependencies
and builds, `entity-nt2py` owns data access and analysis. Apply **free
exploration, strict convergence** to them: give them the semantic goal, the
input identity, boundaries, and acceptance criteria, and let them choose
their internal methods; the Ledger only records established facts that have
been re-probed, and does not perform their domain reasoning.

## Destructive operations

Deleting raw data always requires explicit user authorization, a precise
manifest, protected source/build/dependency roots, and a receipt outside the
deletion target. Never infer deletion authorization from a broad request.

## Reporting

Report primitive execution results, the exact source/build/run identities,
the execution site, the verified outputs/effects, unresolved decisions, and
whether status is cached or live. Internal receipts and storage fields are
diagnostic details, not normal user-facing work content.
