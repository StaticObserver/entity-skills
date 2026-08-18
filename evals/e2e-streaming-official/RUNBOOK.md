# E2E A/B Test Runbook (official streaming pgen edition, lightweight A/B)

One task, two conditions, three commands per round. This file is the only setup document.

## Task specification (sent to the agent under test together with the task text)

Follow `task.md` and `physics-spec.json` (this directory) through the full Entity
simulation workflow. **The agent receives a redacted spec**: `run_round.sh` generates it
from the full physics-spec.json via `redact_spec.py` — the partition/gres/QoS/analysis
partition under `resources` are removed (they are self-discovery test points), while the
physics, the build contract, and the resource budget are kept; the oracle always scores
against the full spec in the repo (the `oracle.py --spec` default).
The core difference from e2e-neutral-streaming: **the PGen-authoring stage is gone** —
`compile.pgen=streaming` is prescribed (the official PGen; its source must not be
modified), and the deliverables become `docs/design.md` (parameter-selection rationale)
+ input TOML + analysis + submission.json. The task explicitly requires the full 0.7.0
flow:

1. `workspace init/adopt` + `project/case init`;
2. The already-registered `astro-streaming` site record (the 0.7.0 site_root new tree) +
   `site sync`; query `site deps astro-streaming` to reuse the existing verified stack,
   and only `deps-add` a new stack;
3. TOML + `docs/design.md`; clean build (CUDA, single GPU, no MPI) +
   `record build` — **compilation must also go through a Slurm CPU-only job** (no heavy
   work on the mgmt login node);
4. `render-run` → `record run-prepare` → `record run-launch` (Slurm sbatch submission) →
   `record run-exit` (exactly one run; wait for the terminal state);
5. `record data` inventory; nt2py analysis; `record analysis` (the script goes into the
   project `analysis/scripts/` library; the output directory carries an
   `analysis-manifest.json`);
6. A submission.json conforming to `fixtures/submission.schema.json`.

Site and constraints:

- Server: `ssh astro` (a Slurm cluster; the login node is for light file operations
  only — compilation/simulation/analysis all go through the scheduler; partition, GPU,
  QoS, and toolchain are explored by the agent itself);
- Resource ceiling: 1 GPU / walltime ≤ 10 minutes; data analysis uses CPU only;
- Source code and dependencies: discovered by the agent itself (paths are not in the
  task text; the agent finds out about astro-streaming's existing verified dependency
  stack via `site deps`);
- No public internet; do not modify read-only dependencies, the frozen source, or **the
  official PGen source**; analysis must not write into the raw-data root; credentials
  must not enter any file;
- Completion criteria: the run reaches a normal terminal state, fields/particles at ≥2
  time steps are readable, and the analysis conclusion is consistent with the
  two-stream-instability physics expectation.

## The two variants

| | S: `skills-v5` (full bundle) | N: `skills-no-router` (only entity-ledger removed) |
|---|---|---|
| Entity skills | `entityctl install` publishes the current bundle (0.7.0rc) | entity-* projections under `~/.claude/skills/` temporarily moved away |
| model / task text / shell·ssh tools | identical | identical |
| session | fresh session, empty history | fresh session, empty history |
| workspace | separate project directory (the agent builds its own workspace) | separate project directory (no Ledger) |

## Per-round commands

```bash
# Launch (create directories, register the trace, start the agent; before launch,
# verify the skill projection state: group S requires entity-ledger present, group N
# requires that only entity-ledger has been moved away — launch is refused if these are
# not satisfied. Since 0.7.0 no controller home is pre-staged; the agent builds the
# workspace itself after confirming with the user per task.md. The contamination
# pre-check refuses to launch and prints cleanup guidance on any hit: local
# ~/entity-workspace, the ~/.entity-ledger/active-workspace pointer, existing rounds
# under ~/entity-eval-runs, and on astro: _pilot/_tools/ and a non-empty
# ~/entity-workspace/site tree projects (an unreachable ssh only warns))
evals/e2e-streaming-official/run_round.sh skills-v5 2026-08-XX-S1 [model]
evals/e2e-streaming-official/run_round.sh skills-no-router 2026-08-XX-N1 [model]

# Wrap-up (first snapshot the project artifacts into traces/<run>/project-snapshot/,
# then import the transcript, segment phases, close the trace; re-running it detects
# the terminal event and skips directly)
evals/e2e-streaming-official/finish_round.sh 2026-08-XX-S1 completed

# Remote cleanup (first pull *.sbatch/slurm-*.out/*.log/manifest into
# traces/<run>/remote-logs/; cleanup targets: data_root, the whole projects/<slug>
# tree in the site tree, and the mistakenly built ~/entity-workspace from astro's
# _pilot/_tools/; leftover entity-* jobs in the queue are listed too. Dry-run by
# default; -f actually deletes and scancels)
evals/e2e-streaming-official/clean_remote.sh 2026-08-XX-S1 -f
```

Monitoring is out-of-band: segmentation and statistics all happen offline after the run
ends; there is no probe anywhere in the agent's tool-call path, and the skills do not
know monitoring exists.

## Oracle independent review

Run after `finish_round.sh` (does not trust the agent's self-report; re-verifies from
external facts):

```bash
python3 evals/e2e-streaming-official/oracle_streaming/oracle.py \
  --project ~/entity-eval-runs/<run>/project \
  --transcript ~/.claude/projects/<project-slug>/<session>.jsonl \
  --fetch ~/entity-eval-traces/<run>/oracle-data
```

Produces `<project>/oracle-report.json`; overall fail > unknown > pass. The five gates:
A safety (transcript scan), B official-PGen fingerprint + TOML/spec consistency +
submission schema, C Slurm job facts (sacct: the job id exists with exactly one record,
terminal state/exit code — a known-harmless teardown abort is exempted only after
independent confirmation from the slurm logs — resource and Elapsed reconciliation,
gres ceiling; the direct branch is retained for m87) + data readability, D physics (the
two-stream growth criterion, thresholds frozen, see below), E analysis reproducibility.
`--site` defaults to astro.

## Gate D thresholds (frozen on the 2026-08-09 gold run)

`oracle_streaming/thresholds.json` is marked `"calibration": "gold-run-2026-08-09"`,
frozen to the band observed in the gold run (`run-879cd51744bad483`, job 357003, V100):
growth-rate band [0.08, 0.20] (gold 0.137; cold symmetric two-stream theory 0.1–0.15),
growth multiple ≥1e3 (gold 7.1e3), saturation before t_final (gold 13.8/49.4), energy
drift ≤1% (gold 0.2%), strict particle-number conservation, monotonically increasing
stats time. Two-stream is growth physics; neutral's conservation criteria (drift
preservation, B1 background, E² noise ceiling) have been removed. For the gold run's key
numbers and the per-entry calibration rationale, see thresholds.json and
test-plan-astro.md.

## Per-round archiving

After the round ends, put `summary.json` into that round's directory: variant, model,
start/end time, wall-clock, input/output tokens, run_id, completed or not, one-sentence
result; the agent's final self-reported summary (verbatim, may go into
`agent-summary.md`).
