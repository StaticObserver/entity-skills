# Development Skill Spec

## Mission

Help develop Entity features grounded in source-code facts.

This skill goes deeper than simulation operation. After reading the current checkout, it may modify Entity source code.

## Mandatory Preflight

Run before proposing a plan or editing code:

```bash
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse --short HEAD
git describe --tags --always
```

Then inspect the relevant source files. Do not rely only on skill-pack summaries.

## Source Boundaries

Common subsystems:

- `src/framework`: domain, mesh, parameters, containers;
- `src/engines`: algorithm scheduling and engine-owned state;
- `src/kernels`: device numerical kernels;
- `src/output`: ADIOS2/HDF5/stats/checkpoint writing;
- `src/global/traits`: compile-time hook detection;
- `pgens` and `examples`: user-facing customization patterns;
- `tests`: unit and integration tests.

## Workflow

1. Clarify the feature goal and expected behavior.
2. Identify the target subsystem and owner boundary.
3. Trace the current call path.
4. Separate "verified repo fact" from "proposed design".
5. Draft a minimal implementation plan.
6. Make narrowly scoped edits.
7. Run available compile/tests/smoke checks.
8. Record compatibility and risks.

## Engineering Rules

- Preserve backwards compatibility when practically possible.
- Keep host/device boundaries explicit.
- Do not force state that belongs to `Engine` into `Domain`.
- Check traits before adding assumptions about new PGen hooks.
- In some validation tasks, plain particle output is not sufficient as a precise oracle; checkpoint/raw state is needed.

## Required Output

Use the [[90-Templates/Development Design Note Template|Development Design Note template]].

Include:

- source paths inspected;
- verified current behavior;
- proposed behavior;
- changed files;
- tests run;
- tests not run;
- remaining risks.
