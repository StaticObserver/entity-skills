# New Simulation

Use for a new or incomplete simulation. Skip a phase only when current evidence
proves its readiness.

## Flow

1. **Orient**
   - Select controller root, Case label/UID, one source authority, execution
     sites, phase-required roots, transfer policy, goal, and done-when.
   - Register site profiles; create or recover Locator-based Case state outside
     the source checkout; refresh evidence and verify state.
2. **PGen** — `pgen.design`, `pgen.edit`, or `pgen.verify`
   - Owner: `entity-pgen`.
   - Inputs: checkout API, `pgen.hpp`, matching TOML, `docs/design.md` as
     applicable.
   - Write roots: the exact `pgen.hpp`, matching TOML, and affected path under
     `docs/`; never authorize the whole Case directory.
   - Required result: synchronized PGen/TOML/design evidence.
   - Set `pgen=verified` only after the affected contracts are checked.
3. **Source** — `source.materialize`
   - Owner: Router `playbook-sync`.
   - Materialize exact `git-ref`, immutable dirty `snapshot`, verified
     `shared`, or verified `external` source at the build site.
   - Set `source=ready` only after a fresh site probe verifies the revision.
4. **Build** — `build.plan`, `build.compile`, or `build.monitor`
   - Owner: `entity-env-build`.
   - Inputs: verified PGen hash, checkout identity, backend, MPI, precision,
     output, and required compile options.
   - Required result: recorded build identity and executable evidence.
   - Set `build=pass` only after the build result and executable are verified.
5. **Run**
   - Continue with `run-simulation.md` only when PGen and matching build are
     current.
6. **Inspect**
   - Continue with `analyze-run.md` only when requested or required by the
     Workflow done-when conditions.

At every boundary, close the current Action and let the Router verify artifacts
before starting the next execution domain.
