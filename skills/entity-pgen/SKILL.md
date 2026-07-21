---
name: entity-pgen
description: Design, implement, explain, review, and modify Entity problem generators together with matching TOML configurations and docs/design.md. Use directly for bounded PGen-domain work with an exact target, including standalone new or existing PGens, initial fields or particles, boundaries, custom behavior, output, normalization, and PGen-TOML consistency. Writes inside a Router-managed Case are currently refused (the v5 pgen Goal is not yet implemented); route Case lifecycle, cross-domain work, builds, runs, untriaged failures, Entity core changes, and scientific analysis to their owners.
---

# Entity PGen

## Purpose

Develop `pgen.hpp` and its TOML configuration as one design unit. Keep `docs/design.md` as the authoritative design and current completion record. Preserve consistency among the design, PGen implementation, and TOML without forcing every task through a rigid pipeline.

Use the bundled references as an on-demand knowledge base. Load only what the current task needs and verify version-sensitive details against the active Entity checkout.

## Execution Modes and Write Gate

Classify the task before loading domain references or modifying files:

- **Read-only**: explain, inspect, or review without changing files. This may
  run directly in standalone or managed paths. Do not create process artifacts.
- **Standalone write**: modify only PGen-owned artifacts at an exact target
  that is not inside a Router-managed Case. This may run directly.
- **Managed write**: modify a source Locator registered by the Router v5
  store. Currently refused: managed writes require a v5 pgen Goal, which is
  not yet implemented. Route the request to `entity-router`.

Before every write, run:

```bash
python3 <entity-pgen-skill>/scripts/pgen_preflight.py \
  --router-home <controller-root> \
  --operation write \
  --target <site_id:/exact/absolute/path>
```

Resolve `<entity-pgen-skill>` from this `SKILL.md`; do not assume the current
working directory is the skill directory.
Run the preflight for each intended target or for their narrow common parent.
Proceed only when it returns `"allowed": true`. The preflight queries the
Router v5 store and checks whether the target Locator falls under a registered
Case source, identity root, or active run; it never infers managed state from
ancestor directories. If it reports `router-required`, do not write; return
the target, detected Case, requested change, and reason to `entity-router`.
Never modify Router control state.

For a target not registered by Router, treat it as standalone only
when the user selected an exact location and requested PGen-domain deliverables
only. Route ambiguous workspace creation, persistent simulation work, or any
request that continues into build, run, recovery, or analysis to Router.

## Scope

Handle:

- designing a new PGen and matching TOML in standalone mode;
- modifying or reviewing an existing PGen/TOML pair;
- maintaining `docs/design.md` alongside implementation changes;
- checking normalization, coordinate basis, API usage, and PGen-TOML consistency;
- fixing a problem already attributed to PGen code or configuration.

Route elsewhere:

- managed Case lifecycle and cross-domain simulation workflows -> `entity-router`;
- dependency setup, CMake configuration, and compilation execution -> `entity-env-build`;
- failures whose owner is still unclear -> return evidence to the package Router;
- Entity engine or framework changes -> return a scoped handoff to the package Router;
- simulation output access and visualization -> `entity-nt2py`; scientific analysis routes to `entity-router`.

Do not add platform-specific metadata or invocation configuration to the core skill.

## Core Rules

1. Treat `docs/design.md`, `pgen.hpp`, and the matching TOML as one maintained unit.
2. Read the current design and implementation before changing either PGen or TOML. If no design exists, reconstruct a minimal one from the current files and label inferred decisions as inferred.
3. Cover every core PGen component in the design: basic configuration, initial electromagnetic fields, initial particles, boundaries, custom behavior, and custom output. Mark unused components as `not-used` instead of omitting them.
4. Keep the design concise. Record intent, relevant TOML mapping, and current state; add formulas or implementation detail only when they are needed to make the design unambiguous.
5. Confirm decisions that materially change the physical model, normalization, or implementation direction. Continue with safe local work when open questions do not block it.
6. Verify Entity version, API signatures, normalization, and coordinate-basis conventions from the active checkout when available. The bundled references target Entity v1.4.4 and are secondary to current source evidence.
7. Modify PGen and TOML together when the change affects their shared contract, then update the corresponding design section and current status.

## Working Method

Adapt the depth of work to the request:

1. **Orient**: locate the active Entity checkout, PGen, TOML, and `docs/design.md`; inspect only the evidence relevant to the task.
2. **Identify the affected design**: determine which core components and TOML keys are involved. Resolve blocking physics decisions before implementation.
3. **Load references**: read the relevant reference files below and compare version-sensitive claims with the active checkout.
4. **Design and implement**: create or update `docs/design.md`, then make the corresponding PGen and TOML changes. For a local correction, update the design and implementation in the same pass.
5. **Verify**: check the affected design-PGen-TOML contract and run available static, compile, smoke, or physics checks appropriate to the task.
6. **Record state**: update the design's current status and report what is implemented, verified, open, or handed off.

For explanation-only requests, read and explain the existing design and implementation without creating process artifacts. For reviews, report concrete conflicts and evidence; do not expand the task into a full redesign unless required.

## Design Document

Store all PGen design material under `docs/`. Use one `docs/design.md` by default; add supporting documents only when the PGen genuinely needs them.

Use this compact structure:

```markdown
# <name> Design

## 1. Goal
State the physical problem, intended behavior, and important exclusions.

## 2. Basic Configuration
Record the Entity version, engine, metric, dimensions, normalization/basis, and special build or data requirements.

## 3. Initial Electromagnetic Fields
State: not-used | planned | implemented | verified
Describe the intended fields and matching TOML parameters.

## 4. Initial Particles
State: not-used | planned | implemented | verified
Describe species, distributions, and matching TOML parameters.

## 5. Boundaries
State: not-used | planned | implemented | verified
Describe field and particle boundaries and matching TOML parameters.

## 6. Custom Behavior
State: not-used | planned | implemented | verified
Describe any ext_current, ext_force/ExternalFields, CustomPostStep, CustomParticleUpdate, or other hooks and their TOML parameters.

## 7. Custom Output
State: not-used | planned | implemented | verified
Describe CustomFieldOutput, CustomStat, and matching TOML names.

## 8. PGen-TOML Contract
Record only the key mappings and constraints that must remain synchronized.

## 9. Current Status
List completed, pending, open, and verified work.

## 10. Important Changes
Record only changes that alter the physical model, interfaces, or TOML contract.
```

The Agent may expand, merge, or shorten subsections when the problem requires it, but must retain the core component coverage and current-state record.

## Reference Router

All references describe Entity v1.4.4. Read only the files relevant to the affected design.

| Need | References |
|---|---|
| Normalization, units, or coordinate basis | `references/00-normalization.md` |
| PGen structure, traits, constructors, or parameters | `references/01-skeleton.md` |
| Initial electromagnetic fields | `references/02-init-fields.md` |
| Initial or replenished particles | `references/03-particle-injection.md` |
| External current | `references/04-ext-current.md` |
| External force or external fields | `references/05-ext-force.md` |
| Boundary conditions | `references/06-boundary.md` |
| Custom field output or statistics | `references/07-custom-output.md` |
| Custom timestep or particle updates | `references/08-custom-post-step.md` |
| TOML structure and parameters | `references/09-toml-config.md` |
| Higher-order field or particle algorithms | `references/10-higher-order.md` |
| Existing Entity PGen patterns | `references/pgens-index.md` |

For a new PGen, begin with `00`, `01`, and `09`, then load the feature references selected by the design. For an existing PGen, begin with its current files and load only the references needed for the affected components. Use `pgens-index.md` when an API pattern is uncertain, then inspect the referenced implementation in the active checkout.

## Consistency and Verification

Check three relationships over the affected scope:

1. `docs/design.md` <-> `pgen.hpp`;
2. `docs/design.md` <-> TOML;
3. `pgen.hpp` <-> TOML.

Include the relevant checks:

- PGen traits match TOML engine, metric, and dimensions;
- `params.get()` keys match TOML `[setup]` names and types;
- species count, order, properties, and indexing agree;
- field and particle boundary settings match implemented hooks;
- custom output names match TOML requests;
- normalization and coordinate basis are explicit and consistent;
- special algorithms, build options, and external data required by the design are declared;
- the design status reflects the evidence actually obtained.

Do not claim compilation, smoke testing, or physics validation unless it was performed. A local modification does not require rechecking unrelated parts of the case.

## Deliverables

For a new PGen, produce:

```text
pgens/<name>/
|-- pgen.hpp
|-- <name>.toml
`-- docs/
    `-- design.md
```

Keep additional design notes, figures, or validation records under `docs/` only when needed. Keep runtime data tables outside `docs/` in an appropriate data directory.

When build or run verification is required, hand off the current checkout identity, PGen/TOML paths, design requirements, and unresolved constraints to the owning skill.
