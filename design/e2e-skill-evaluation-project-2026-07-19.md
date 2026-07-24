# Entity Skills End-to-End Comparative Evaluation Project

Date: 2026-07-19  
Status: phase one implemented, awaiting gold run  
Revision: from 2026-07-21 the task contract and process monitoring follow `e2e-skill-evaluation-revision-2026-07-21.md`

## 1. Purpose

This project does not evaluate whether an Agent can "talk about Entity"; it evaluates whether it can completely finish a small, real, verifiable simulation task:

```text
Environment confirmation and build → PGen/TOML → Entity compile → Slurm job → output verification → nt2py analysis
```

The same frozen task is given separately to:

- `S`: an Agent with the specified version of Entity skills installed;
- `N`: an Agent of the same model without any Entity skills.

Both groups use the same model, task, tool permissions, source version, compute site, resource budget, and acceptance checker. The only difference can be whether Entity skills are exposed. In the end we look at results, process, safety, and cost together, and do not substitute subjective impressions for evidence.

## 2. Core principles

The evaluation keeps four simple rules:

1. **One task**: both groups receive exactly the same `task.md`.
2. **Two conditions**: only the exposure state of Entity skills changes.
3. **One judge**: an independent oracle directly checks source code, build, scheduler, raw data, and analysis artifacts.
4. **Correctness before efficiency**: safety and physical correctness are hard gates and cannot be offset by speed or tokens.

No hidden chain of thought is captured. Only observable tool calls, brief decisions, external state, artifact fingerprints, and validation results are recorded.

## 3. Test instance: Neutral Streaming Equilibrium

### 3.1 Why it was chosen

The first instance uses a one-dimensional periodic neutral electron-positron plasma in a uniform-streaming equilibrium. It is real enough to cover fields, particles, random seeds, output, and particle analysis; and simple enough that theoretical expectations are clear, computation is cheap, and errors are easy to attribute.

Reconnection, turbulence, or black-hole accretion were not chosen as the first item. Those problems are more scientifically interesting, but they would mix physics modeling error, stochastic fluctuation, compute resources, and workflow quality together, making it hard to judge whether the skills themselves improved execution.

### 3.2 Frozen physics semantics

The PGen is tentatively named `neutral_streaming`, implemented against the SRPIC/Minkowski/Cartesian interface of Entity v1.4.4, but must form an independent consistent unit of `docs/design.md + pgen.hpp + TOML`.

| Item | Frozen value |
|---|---|
| Dimensions and boundaries | 1D, `x ∈ [0, 16]`, periodic boundaries for both fields and particles |
| Grid | 128 active cells |
| Composition | Equal-mass, opposite-charge, equal-density electrons and positrons |
| Particle count | 32 macro-particles per species per cell |
| Temperature | `T = 1e-3` |
| Drift | `u = (0.2, 0, 0)` for both species |
| Initial fields | `B = (1, 0, 0)`, `E = (0, 0, 0)` |
| Randomness | Fixed seed, written into the TOML and the result manifest |
| Build | CUDA, single, zigzag, shape order 1, output ON, MPI OFF |
| Resources | 1 node, 1 GPU, 1 task, at most 10 minutes |

The two species have identical spatial distributions and drift; charge and current cancel overall, and the drift is parallel to the uniform magnetic field, so there is no transverse Lorentz force. The expected solution is therefore nearly stationary: particle count unchanged, mean drift unchanged, uniform magnetic field preserved, and the electric field containing only small fluctuations from finite particle number and discretization.

The formal run's step size, termination time, and output interval are not guessed here. The maintainer first completes a gold run and fixes these values according to actual Entity stability constraints; once fixed, they must not be adjusted based on `S/N` results.

### 3.3 Required outputs

The Agent must produce:

- PGen: `docs/design.md`, `pgen.hpp`, input TOML;
- environment: `requirements.json`, `entity-deps.local.json`, `env.sh`, `entity-build.sh`;
- build: complete build log, the SHA-256 of `entity.xc`, and the source identity;
- run: job ID, submission receipt, terminal scheduler state, run manifest, and raw-data Locator;
- analysis: a re-runnable script, `analysis/report.json`, a short `summary.md`, field and particle plots;
- summary: a public `submission.json` containing only structured Locators, identities, states, and fingerprints.

`submission.json` is the common delivery interface for both groups; the no-skill Agent is not required to mimic Router internal objects.

## 4. How the full environment build is tested

Environment building comes in two modes, to avoid every round being swamped by dependency downloads and cluster fluctuations.

### Main experiment: warm dependencies, cold Entity build

The site provides a read-only set of Kokkos/ADIOS2/HDF5/CUDA dependencies with known versions but without a pre-injected shell. Each Agent must still independently complete:

```text
Site probing → dependency selection → checkpoint → compatibility → env.sh → fresh Entity build
```

The source checkout, build root, run root, and analysis root are new every round. This mode suits repeated comparison and also covers the full environment decision, compatibility convergence, and Entity compile chain.

### Cold-start qualification test: cold dependencies, cold Entity build

After the main experiment is stable, run one more `S/N` pair: given an empty dependency root, dependencies may be built from a frozen local source cache, and public-network availability is forbidden. It tests true dependency source-builds, but is not a repeated item in the first round.

Both modes must pin the exact commit resolved from the Entity `v1.4.4` tag, the dependency version families, the CUDA architecture, and nt2py `v1.5.3`. All versions have their content fingerprints recorded in the experiment manifest.

## 5. Fair comparison

### 5.1 The only experimental variable

| Condition | `S: skills-v5` | `N: no-entity-skills` |
|---|---|---|
| Model and reasoning configuration | Same | Same |
| User task text | Same | Same |
| Generic shell/SSH/git tools | Same | Same |
| Entity source and official docs | Accessible | Accessible |
| Remote site and resource budget | Same | Same |
| Entity skills | Fixed bundle, all available | Not installed, not mounted, not searchable |
| Current session history | New session, empty history | New session, empty history |

`S` uses an isolated install of the repository's v5 commit; it must not use the live bundle on the current machine that still points at v3. `N`'s workspace does not mount this repository or historical Entity skill directories, preventing accidental discovery of answers via full-text search.

### 5.2 Per-round isolation

Each round uses independent:

- local project/worktree;
- Router home (`S`) or ordinary state root (`N`);
- observability trace home;
- remote source/build/staging/run/analysis roots;
- Slurm job name prefix and random run ID.

Shared dependencies may only be reused read-only. Neither group can see the other group's source modifications, logs, analysis reports, or oracle verdicts.

### 5.3 Repetition and ordering

Suggested order:

1. oracle gold run: executed once by the maintainer, not counted in the comparison;
2. pilot: one run each of `S/N`, to fix the evaluation infrastructure without modifying the frozen task;
3. formal: at least 3 paired repetitions, randomly using `S→N` or `N→S`;
4. cold-dependency qualification: one run each of `S/N`;
5. recovery extension: added after the base experiment is stable, not mixed into the first round.

Slurm queueing time is reported separately and not counted toward Agent execution efficiency; compile, run, and analysis times are recorded separately.

## 6. Independent acceptance checker

The Agent's "done" is only a claim. The oracle re-verifies from owner artifacts and external facts.

### Gate A: workspace and safety

- All writes are within this round's allowed roots;
- No credentials enter logs, TOML, scripts, or Git diffs;
- Read-only dependencies and the input source cache are unmodified;
- No duplicate submission of the same run, and no leftover running jobs;
- analysis does not write into the raw-data root.

Any failure invalidates the round and is not compensated by efficiency metrics.

### Gate B: PGen and build

- `docs/design.md`, `pgen.hpp`, and the TOML have consistent physics parameters and naming;
- the source identity covers tracked, modified, and untracked content;
- the environment checkpoint matches this round's site/backend/output/MPI requirements;
- compatibility is a provable pass;
- clean build succeeds, `entity.xc` exists and its fingerprint is recorded;
- the executable fingerprint matches the actual run manifest.

### Gate C: job and data

- exactly one matching job exists in the scheduler;
- the job terminates normally with exit code zero;
- run manifest, input, executable, job ID, and raw-data Locator form one identity chain;
- nt2py can read fields and particles for at least two timesteps from the correct data root;
- no NaN/Inf in the output; time and step increase monotonically.

### Gate D: physical correctness

The oracle does not use Agent-reported numbers; it reads the raw data independently. The first version checks:

- the initial and final particle counts of the two species are equal and each stays constant;
- the change of the final mean `ux` relative to its initial value is within the frozen tolerance;
- volume-averaged `Bx` and magnetic-field energy stay within the frozen tolerance;
- the generated `E²`, net charge, and net current do not exceed the frozen noise ceiling;
- total energy drift does not exceed the frozen tolerance.

Tolerances are produced from the gold run and a set of numerical-resolution reviews, and are written into `oracle/thresholds.json` before the `S/N` results are opened. A tolerance must have a physical quantity definition, normalization, and a computation formula; it cannot just store a mysterious number.

### Gate E: analysis reproducibility

- the analysis script can run again in a clean Python environment;
- it uses the actual nt2py inventory, not variable names guessed from the PGen name;
- it selects timestep/species/columns before loading particle data;
- reported values agree with the oracle's independent computation within rounding error;
- plots and reports are written to the analysis root and do not pollute the raw data.

## 7. How to observe the skills' working process

The existing `tools/skill_observability` acts as the unified collector, recording:

```text
orient → pgen → env/build → plan/apply/status → data/analysis → verify
```

Only the following is collected per phase:

- exposed skill names, bundle revision, and content hash;
- observable SKILL/reference reads;
- at most one brief structured decision per phase;
- tool calls, return statuses, durations, and redacted output fingerprints;
- source/build/job/data/analysis artifact Locators and SHA-256;
- oracle and owner validator pass/fail/unknown.

Three kinds of evidence are strictly separated: an Agent's claim is `declared`, what the collector sees is `observed`, and only independent verifier confirmation is `verified`. "Skill installed" is not written as "skill used", and hidden reasoning is not recorded.

### Gaps that must be filled first

The Router already uses v5 Goal/Plan/Operation/Step, but the observability Router evidence validator still only understands v3 Action request/result. Before the formal run, a `router-operation-v5` validator must be added, verifying at least:

- Goal, Plan, and plan hash;
- Operation/Step journal and owner-site receipts;
- source/build/run identity chain;
- the launch effect has exactly one scheduler job;
- repeated Apply reuses the receipt instead of repeating `sbatch`;
- the terminal Operation agrees with Router status.

The old validator is kept for historical v3 traces; a compatibility branch must not masquerade as v5 proof.

## 8. How results are compared

No single blended-weight total score is used. Results are presented in fixed priority order:

1. **Whether all hard gates pass**: safety, identity chain, job, data, physics, analysis;
2. **Autonomous completion**: number of phases completed, number of user decisions needed, whether manual rescue was required;
3. **Recovery ability**: whether the same identity is continued after interruption, whether duplicate side effects occur;
4. **Execution cost**: native model tokens, tool calls, failed calls, SSH round trips, effective working time;
5. **Resource cost**: compile CPU/GPU time, job GPU-seconds, maximum storage and output size.

The report gives both per-round raw values and paired differences, not just averages. Fewer tool calls is not inherently better; efficiency differences only matter after all the preceding correctness gates pass.

## 9. Recovery extension

After the base project passes, add a standard fault: the scheduler has accepted the submission, but the Controller/Agent is interrupted before the submission result lands on disk. The recovery task continues using the original workspace and external state.

There are only three core criteria:

1. whether the existing job is discovered;
2. whether the same run identity is kept;
3. whether a second submission is avoided.

This extension specifically tests the value of Router v5's receipt/replay, and is not merged with normal end-to-end success rate into one score.

## 10. Suggested repository structure

To be added after the design is confirmed:

```text
evals/e2e-neutral-streaming/
├── README.md
├── task.md
├── experiment.json
├── fixtures/
│   ├── physics-spec.json
│   ├── tool-profile.json
│   └── site-profile.example.json
├── oracle/
│   ├── thresholds.json
│   ├── validate_submission.py
│   ├── validate_physics.py
│   └── summarize_pairs.py
├── variants/
│   ├── skills-v5.json
│   └── no-entity-skills.json
└── tests/
```

Site usernames, authentication information, and actual writable roots are not committed to the repository; they are only injected by local runtime fixtures. The frozen task, oracle formulas, schemas, and redacted results may be committed.

## 11. Implementation order

Phase one builds only the evaluation infrastructure and does not submit real jobs:

1. establish the frozen task/spec/schema;
2. implement the public `submission.json` validator;
3. add v5 Operation evidence to observability;
4. drive both groups' traces and the oracle with fake data and a fake scheduler.

Phase two executes the gold run, freezing the TOML numeric parameters and physics tolerances.

Phase three first runs one real `S/N` pilot. Only after isolation, traces, oracle, and cleanup are all reliable are the 3 formal pairs started. The cold-dependency and recovery extensions come last.

### Phase one implementation record

The common task, physics/tool/site fixtures, both variants, the public submission schema, the scheduler snapshot schema, the submission oracle, the fail-closed physics oracle, and the file-backed fake Slurm have been established under `evals/e2e-neutral-streaming/`. `tools/skill_observability` has gained `evidence router-operation`, which verifies the v5 Plan hash, Operation/Step, three receipts, controller status, and an independent scheduler snapshot, and rejects duplicate matching jobs.

Local tests use the real Router v5 planner/apply/status to drive the fake Slurm, proving that repeated Apply produces only one job; they also verify the public submission's artifact-drift detection and the pre-gold-run gate on formal execution. No real Entity source/build/run has been fixed or executed, and the live controller has not been touched.

## 12. What this evaluation will answer

It will ultimately give clear answers to:

- whether skills improve end-to-end success rate and physical correctness;
- whether the Router truly reduces state confusion, duplicate submissions, and recovery costs;
- whether the PGen/env-build/nt2py contracts reduce rework and erroneous calls;
- whether the skills' context cost buys fewer tool round trips and less manual intervention;
- given that v5 currently only automates the run Goal, whether PGen/build/analysis owner handoff remains the main friction point.

The last item is especially important: this project not only verifies whether the optimization works, it also directly points out which interface should be simplified next.
