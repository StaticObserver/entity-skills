# Acceptance Criteria

## System-Level Criteria

- The skill pack supports both single-agent and multi-agent usage.
- All task skills share core knowledge.
- Version-sensitive details are verified from the current checkout.
- Official upstream behavior and local fork behavior are clearly separated.
- Generated artifacts are reproducible and include paths, commits, and commands.

## Simulation Skill Criteria

- Produces a run manifest.
- Reads the current `input.example.toml` before generating TOML guidance.
- Captures build flags and backend.
- Records checkpoint policy.
- Distinguishes config check, smoke run, numerical sanity, and physics validation.

## Analysis Skill Criteria

- Lazily loads data whenever possible.
- Records data path, species, time selection, and output quantities.
- Labels evidence strength.
- Saves script/notebook/report for non-trivial analyses.

## Development Skill Criteria

- Probes the Git checkout before editing.
- Reads the current source code before proposing changes.
- Separates verified facts from proposed designs.
- Lists tests run and tests not run.
- Records compatibility risks.

## Debug Skill Criteria

- Starts from the artifact closest to the error.
- Classifies the failure category.
- Proposes only one change at a time.
- Reports the verification result and remaining uncertainty.
