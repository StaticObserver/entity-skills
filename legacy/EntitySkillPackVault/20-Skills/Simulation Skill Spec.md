# Simulation Skill Spec

## Mission

Help users run Entity simulations reproducibly.

This skill focuses on run correctness, run metadata, and first-pass verification. It does not modify Entity core source code by default.

## Allowed Scope

May create or edit:

- TOML input files;
- pgen files under user-controlled case directories;
- build scripts;
- run scripts and Slurm scripts;
- run manifests;
- smoke-test notes.

Avoid modifying:

- `src/engines`;
- `src/kernels`;
- `src/framework`;
- output writer internals.

If these must be modified, route to the [[Development Skill Spec|Development Skill]].

## Required Inputs

Collect or infer:

- physics goal;
- Entity checkout path and version;
- target engine: SRPIC or GRPIC;
- metric and coordinate system;
- dimension;
- pgen choice or custom pgen needs;
- machine and backend: CPU, CUDA, HIP, MPI;
- run scale;
- output requirements;
- checkpoint policy.

## Workflow

1. Probe the checkout and version.
2. Read that checkout's `input.example.toml`.
3. Inspect the chosen pgen and reference TOML.
4. Draft a simulation plan.
5. Generate or update the TOML.
6. Generate the build command.
7. Generate the run command or scheduler script.
8. Run a small smoke test when the user asks and it is feasible.
9. Check `.info`, `.err`, `.log`, stdout, and stats CSV.
10. Write the run manifest.

## Required Output

Use the [[90-Templates/Run Manifest Template|Run Manifest template]].

Include:

- checkout commit;
- build flags;
- pgen;
- TOML path;
- run command;
- output path;
- checkpoint policy;
- validation status;
- known risks.

## Validation Levels

| Level | Meaning |
| --- | --- |
| Config check | TOML and build/run commands are internally consistent. |
| Smoke run | A small run starts and writes the expected metadata. |
| Numerical sanity | Basic stats and output quantities are bounded and reasonable. |
| Physics validation | Domain diagnostics support the target physics conclusions. |

Do not claim a run has passed physics validation before analysis supports it.
