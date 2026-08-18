# e2e-streaming-official: end-to-end A/B evaluation with the official streaming PGen

Verifies that the full 0.7.0 skill flow (workspace → project/case → site
record → deps registry → the record-primitive chain for
build/run/data/analysis) is usable and verifiable on a real task. Its
relationship to `e2e-neutral-streaming` (historical record, unchanged):

- **Task**: the pgen-authoring stage is gone — the official `streaming`
  PGen is used (selected via `compile.pgen`; modifying its source is
  forbidden); the deliverables are `docs/design.md` (parameter rationale) +
  TOML + analysis + submission.json. The task explicitly requires the full
  0.7.0 flow.
- **Site**: the newly registered `astro-streaming` (`ssh astro`, a Slurm
  cluster, V100S-32GB on gpu1; the 0.7.0 site_root new tree
  `~/entity-compute`, the VOLTA70 deps stack booked into the registry by
  the pilot). The old m87 variant (direct backend, legacy roots) is
  retained in gate C's direct branch.
- **Oracle**: the five gates are isomorphically adapted. Gate B becomes the
  official-PGen fingerprint (pinning the sha256 of `streaming/pgen.hpp` in
  the source-cache, preventing the agent from rewriting the official pgen)
  + TOML/spec consistency + submission schema; gate C goes through Slurm
  sacct (the job id exists with exactly one record, terminal state/exit
  code, resource and Elapsed reconciliation, gres ceiling; a teardown abort
  is exempted only after independent confirmation from the slurm logs; the
  direct exit-file branch is retained for m87); gate D is the two-stream
  growth criterion, **thresholds frozen on the 2026-08-09 gold run**
  (growth-rate band, growth multiple, saturation, energy drift, particle
  number conservation).
- **Gold run (2026-08-09, self-run by the pilot)**:
  `run-879cd51744bad483` (job 357003, V100, Slurm elapsed 2s); the oracle's
  five gates judge overall pass; all six ledger status cells are green.
- **Harness**: reuses the Claude Code headless + skill_observability A/B
  framework (skills-v5 vs skills-no-router; the independent variable is the
  presence of entity-ledger).

## Directory

```text
task.md                        # task text sent to the agent under test
physics-spec.json              # frozen physics semantics (two-stream, official streaming; contains astro Slurm details, oracle only)
redact_spec.py                 # generates the redacted agent-side spec (removes self-discovery answers such as partition/gres/QoS)
fixtures/submission.schema.json
oracle_streaming/            # independent review (five gates + thresholds.json)
run_round.sh                   # start a round (create directories, register the trace, launch the agent)
finish_round.sh                # wrap up (snapshot, import transcript, close the trace)
clean_remote.sh                # remote cleanup (dry-run by default, -f executes)
RUNBOOK.md                     # runbook (the only setup document)
```

## Run steps (gold run / live calibration)

1. Confirm `ssh astro` works, gpu1 is idle (`ssh gpu1 nvidia-smi`), and the
   skill projection state (S/N groups per the RUNBOOK table).
2. `run_round.sh skills-v5 <run-name> [model]` to launch → after the agent
   finishes, `finish_round.sh <run-name> completed`.
3. Oracle review: `oracle_streaming/oracle.py --project <run>/project --fetch <data>`
   (`--site` defaults to astro).
4. `clean_remote.sh <run-name> -f` cleans the remote side (confirm nothing
   remains via squeue/sacct), then archive summary.json.

## Calibration status (phases 0–2 complete, 2026-08-09)

- **TOML parameters**: cells=128/ppc0=32/drift=±0.2/final_time=50/CFL=0.5
  verified by the gold run — two-stream growth from a noise floor of 4.8e-7
  to a peak of 3.4e-3, saturating at t≈13.8; single-field V100 computation
  ~1s (Slurm elapsed 2s), so the walltime budget is extremely generous.
- **Gate D thresholds frozen**: the two-stream growth criteria (growth-rate
  band [0.08,0.20], growth multiple ≥1e3, saturation before t_final, energy
  drift ≤1%, strict particle-number conservation); see the per-entry
  calibration notes in thresholds.json for the rationale.
- **Seed semantics**: the official streaming pgen has no seed knob; the
  effective default is the kernel global sequence; the spec notes this
  (random_seed.calibration=resolved-gold-run).
- **All five oracle gates exercised live**: the pilot gold run self-judged
  overall pass; gate A used an empty transcript in the pilot (vacuous
  pass), while official rounds scan the agent transcript substantively.
