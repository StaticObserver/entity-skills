# New Simulation Workflow

## Goal

Starting from a physics objective, create a reproducible Entity simulation run.

## Steps

1. Define the physics objective and the minimal diagnostics needed to judge success.
2. Probe the Entity checkout and version.
3. Choose the engine, metric, dimension, and pgen.
4. Read the current `input.example.toml`.
5. Draft the TOML and pgen/setup parameters.
6. Decide the output quantities and cadence.
7. Decide the checkpoint strategy.
8. Build with explicit backend and architecture flags.
9. Run a reduced smoke case.
10. Check metadata, errors, logs, and stats.
11. Record the run manifest.

## Stop Conditions

If the requested behavior requires modifying `src/`, stop and route to development.

If a build or runtime failure cannot be explained by configuration, stop and route to debugging.

If the question is about interpreting output rather than generating a run, stop and route to analysis.
