# New Simulation

Use for a new or incomplete simulation. Skip a phase only when current evidence
proves its readiness.

## Flow

1. **Orient**
   - Select `ENTITY_WORKDIR`, exact Entity checkout, Case ID, goal, and
     done-when conditions.
   - Create or recover the Case, refresh evidence, and verify state.
2. **PGen** — `pgen.design`, `pgen.edit`, or `pgen.verify`
   - Owner: `entity-pgen`.
   - Inputs: checkout API, `pgen.hpp`, matching TOML, `docs/design.md` as
     applicable.
   - Required result: synchronized PGen/TOML/design evidence.
   - Set `pgen=verified` only after the affected contracts are checked.
3. **Build** — `build.plan`, `build.compile`, or `build.monitor`
   - Owner: `entity-env-build`.
   - Inputs: verified PGen hash, checkout identity, backend, MPI, precision,
     output, and required compile options.
   - Required result: recorded build identity and executable evidence.
   - Set `build=pass` only after the build result and executable are verified.
4. **Run**
   - Continue with `run-simulation.md` only when PGen and matching build are
     current.
5. **Inspect**
   - Continue with `analyze-run.md` only when requested or required by the
     Workflow done-when conditions.

At every boundary, close the current Action and let the Router verify artifacts
before starting the next execution domain.
