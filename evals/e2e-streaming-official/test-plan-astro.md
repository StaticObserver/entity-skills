# e2e-streaming-official @ astro test plan

> **Phase 0 (adapting the evaluation package to astro) completed 2026-08-05**:
> physics-spec switched to VOLTA70/Slurm/astro-streaming, the gate C sacct
> branch wired in with added unit tests, task.md / clean_remote.sh / RUNBOOK /
> README synced; `pytest tests/` 323 all green.
>
> **Phase 1 (site construction, pilot) completed 2026-08-09**: the pilot
> workspace `~/entity-workspace` was created and adopted;
> sites/astro-streaming.yaml registered and synced; `site init` built the
> `~/entity-compute` new tree + entity-site.yaml on astro; `site discover`
> landed the machine section (partition/QoS measurements match §1 of this
> plan). Both deps-registry stacks in place: the build stack
> `compiler12.3.0-kokkos5.1.0-fba1fb4dcb0d` (GCC 12.3.0 + CUDA 12.6 +
> kokkos 5.1.0-VOLTA70 + hdf5 1.14.5 + adios2 2.11.0; checkpoint
> compatibility pass, parameters confirmed; env.sh under the new tree's
> deps/<stack_id>/), and the analysis stack `stack-882febbd968e` (miniconda
> python 3.12.8 + nt2py 1.5.3, pip-installed this time). run_round.sh now
> sends the agent a redacted spec (redact_spec.py). Issues found are in the
> session report (doctor reported pre-existing 0.6.1 skill projection drift,
> unrelated to this work; the executor sbatch `--gres=gpu:N` does not support
> typed gres — a 0.7.0 design gap that needed a decision before phase 2).
>
> **Phase 2 (TOML calibration + gold run, pilot) completed 2026-08-09**: the
> typed-gres gap is fixed (policy `default_gres` + `--gres`). The full flow:
> project streaming-eval / case twostream-gold (case-b57321c9abf1ce71) →
> snapshot-source → compile (build-volta70-single-002, Slurm jobs 356999/
> 357001, fat CPU-only 32 cores, 4m05s; the binary is self-contained with
> baked rpath) → record build (build-f5171682c1d24b91, hit on the registered
> stack) → render-run/record run-prepare/run-launch
> (**run-879cd51744bad483**, job 357003, fat+gpu:V100:1+qos512 without
> --time; Slurm elapsed 2s, computation ~1s) → run-exit (teardown abort,
> judged completed + exit_anomaly via --reclassify) → record data
> (data-138282d17045e948, 109 files) → analysis (intelhigh job 357006, 11s;
> analysis-eeb468cba15dff30) → record analysis. All six status cells green;
> the oracle self-judged **overall pass** (gate A used an empty transcript in
> the pilot, a vacuous pass). Calibration conclusions: final_time=50 is
> generous (γ=0.137 ω_pe falls in the cold two-stream theory band 0.1–0.15,
> saturates at t≈13.8, growth 7.1e3×, energy drift 0.2%, particle number
> conserved); the Gate D thresholds were frozen to the observed band; the
> official pgen has no seed knob, noted in the spec. The 0.7.0 bugs fixed and
> the gate enhancements from the pilot are in CHANGELOG Fixed and the session
> report (including the incident record of the build-001 tree being
> mistakenly relinked).

Date: 2026-08-05. Evaluation package: `evals/e2e-streaming-official/` (f46f724).
Subject under test: the full 0.7.0 skill flow (Workspace / Computation Site /
deps registry / record primitives / analysis management) + the official
streaming pgen. Agent under test: Claude Code headless. Judge: the five
oracle gates.

## 1. Site facts (measured 2026-08-05 + site-notes)

- Access: `ssh astro` → login node mgmt (40 cores, EL8). **No heavy work on
  mgmt**; compilation also goes through Slurm (CPU-only jobs, ~5 min).
- GPU: compute node gpu1 = V100S-32GB (currently idle) + A100-80GB (occupied
  by another user's long job). **This test uses the V100**: the `fat`
  partition, `--gres=gpu:V100:1`, **no --time** (user-specified; the
  partition default MaxTime is 3 days).
- Partition policy (user-specified 2026-08-05): simulations → fat/gpu1 V100;
  analysis/rendering → intelhigh, falling back to amdlow when queued; no
  analysis jobs on fat.
- QoS: qos512 is available.
- Verified deps (VOLTA70 stack, verified by the axion-grpic build on
  2026-08-04): `~/entity/deps/{kokkos/5.1.0, hdf5/1.14.5, adios2/2.11.0}`.
- Toolchain: GCC 12.3.0 (module gnu12/12.3.0) + CUDA 12.6
  (`~/local/cuda-12.6`); known pitfalls: `NVCC_WRAPPER_DEFAULT_COMPILER` must
  point at the GCC 12.3 g++; `find_package(adios2)` goes through
  `CMAKE_PREFIX_PATH`; `-DADIOS2_ROOT` has no effect.
- Source: Entity v1.4.4 pristine at `~/entity/1.4.4` (includes the official
  pgens; `-DOFFLINE=ON` disables FetchContent); the repo also holds a
  source-cache copy.
- Python (skill tooling/analysis): `~/miniconda3/bin/python3` (3.12.8); the
  system python is too old.

## 2. Differences from the m87-edition plan

| Dimension | m87 edition | astro edition |
|---|---|---|
| scheduler | none (direct backend) | Slurm (sbatch/sacct) |
| Gate C | `.entity-exit-code` evidence | sacct facts (the original neutral gate_c path) |
| GPU | RTX 4070 Ti | V100 (VOLTA70) |
| compilation | direct local | Slurm CPU-only job (fat, 32 CPUs, no gres) |
| site layout | legacy roots | **newly built site_root conventional tree** (see §3 decision) |

## 3. Key decisions

1. **Use the new tree, not the old one**: register a new site
   `astro-streaming` for this test with `site_root = ~/entity-compute`,
   taking the full 0.7.0 path: `site init` builds the tree +
   `entity-site.yaml` marker → `deps-add` books the existing VOLTA70 stack
   into the registry → `--kind analysis` registers the miniconda interpreter.
   The old astro* sites and old trees are left untouched.
2. **The gold run is run by us (Kimi) first**, as the pilot of the 0.7.0
   workflow; official Claude Code rounds start only after the thresholds are
   frozen. Problems found by the pilot are fixed before the real rounds, to
   avoid wasting e2e rounds on a known-broken flow.
3. **Direction of the physics criteria**: two-stream is growth physics (not
   neutral's conservation criteria); when freezing Gate D, the gold run's
   observed band governs, with the focus on growth rate and saturation
   behavior.

## 4. Phase breakdown

### Phase 0: adapt the evaluation package to astro (no site dependency; can start immediately)

- physics-spec.json: switch the compile section to VOLTA70; switch the
  resources section to Slurm (fat, `--gres=gpu:V100:1`, no --time, qos512);
  add the "analysis jobs go to intelhigh/amdlow" constraint (a Gate A check
  item).
- gate_c_job_data.py: restore/wire in the sacct branch (sbatch job id, exit
  code, exactly one job, gres ceiling); keep the direct branch for m87 reuse.
- run_round.sh / clean_remote.sh: switch the site to astro-streaming; cleanup
  confirms no leftover jobs via squeue/sacct.
- task.md: change the resources section to "a Slurm cluster" without naming
  partitions (self-discovery of deps/partitions is a test point; information
  already registered in the site record may be used).
- Acceptance: oracle unit tests all green; RUNBOOK updated.

### Phase 1: site construction (pilot, executed by us)

- `entityctl site init astro-streaming` (site_root=~/entity-compute, ssh).
- `site discover` lands the machine section; `site deps-add` registers the
  VOLTA70 stack (checkpoint from a real requirements resolution);
  `site deps-add --kind analysis` registers the miniconda python.
- Acceptance: `site deps astro-streaming` lists both stacks;
  `entity-site.yaml` is readable on astro; all Locators go through the new
  tree.

### Phase 2: TOML calibration + gold run (pilot, executed by us)

- Run the full 0.7.0 flow once: workspace init (local machine) →
  project/case → snapshot-source → requirements (pgen=streaming, VOLTA70,
  single) → checkpoint confirm → compile job (Slurm, fat, CPU-only) →
  record build → render-run (fat, `--gres=gpu:V100:1`) →
  run-prepare/run-launch → run-exit → record data → record analysis
  (manifest with all fields).
- Calibration points: whether the instability growth is sufficiently observed
  at final_time=50, per-job walltime (target ≤10 min), output volume.
- Freezing: rewrite Gate D thresholds.json to the gold run's observed band
  (growth rate, drift, energy, field noise); confirm the seed semantics (if
  the official pgen has no seed knob, note that in the spec).
- Acceptance: the oracle judges pass on the gold run artifacts; all six
  `status` cells green (analysis cell established).

### Phase 3: official e2e rounds (Claude Code headless)

- `run_round.sh` starts a round; observability trace on; the agent completes
  the task from a clean state.
- The oracle's five gates score; the findings document records skill
  attribution (0.7.0 primitive usage, deps-registry hits, record analysis
  usage).
- Acceptance: oracle overall pass/fail + attribution analysis; comparison
  with the historical rounds (2026-07-22/23).

### Phase 4: cleanup and archiving

- clean_remote.sh (squeue confirms nothing remains); whether to keep or
  delete this tree on astro is the user's call; archive findings; update
  CHANGELOG/README as needed.

## 5. Risks and mitigations

- **gpu1 occupancy changes**: the A100/V100 gets grabbed by other users →
  jobs queue and the e2e round stretches; mitigation: confirm with
  `ssh gpu1 nvidia-smi` before running, and widen the round time window to 3
  hours.
- **V100 compute below the 4070 Ti**: two-stream at 128 cells/ppc 32 scale is
  still minute-level on a V100 — low risk; if it times out, shrink the
  runtime.
- **GCC/CUDA minor-version mixing** (the 12.3+12.6 toolchain vs deps built
  with 12.2/12.0): bh-reconnection has verified this works, and the
  checkpoint records it; if compat fails, fall back to re-resolving with the
  deps' original toolchain.
- **The deps-add env.sh gate**: the VOLTA70 stack has no ready-made env.sh —
  generate one per the stack.yaml convention during the pilot phase.
- **Analysis environment**: whether nt2py is already installed in miniconda
  is unknown; check in phase 1, and if missing, pip-install it into that
  environment (and record it in the stack recipe).

## 6. Definition of done

- Phases 0–2 complete = gold run all green, thresholds frozen, oracle
  self-judged pass.
- All complete = official rounds scored by the oracle + findings archived.
