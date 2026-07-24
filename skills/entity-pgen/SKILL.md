---
name: entity-pgen
description: Design, implement, explain, review, and modify Entity problem generators (PGen), together with their companion TOML configuration and docs/design.md. Suitable for well-scoped, clearly bounded PGen-domain work that can be used directly, including standalone new or existing PGens, initial fields or particles, boundaries, custom behavior, output, normalization, and PGen-TOML consistency. Writes inside ledger-managed cases are currently refused (managed writes must be recorded via the ledger's record primitive); route case lifecycle, cross-domain work, builds, runs, unclassified failures, Entity core changes, and scientific analysis to the corresponding owning skill.
---

# Entity PGen

## Purpose

Develop `pgen.hpp` and its TOML configuration as a single design unit. Use `docs/design.md` as the authoritative design document and the record of current completion status. Keep design, PGen implementation, and TOML consistent without forcing every task through a fixed pipeline.

Use the bundled references as an on-demand knowledge base. Load only what the current task needs, and verify version-sensitive details against the currently active Entity source checkout.

## Execution Modes and Write Gating

Classify the task before loading domain references or modifying files:

- **Read-only**: explain, inspect, or review without changing files. May proceed
  directly under standalone or managed paths. Do not create procedural artifacts.
- **Standalone write**: modifies only PGen-owned artifacts, with an exact target
  location that is not inside a ledger-managed case. May proceed directly.
- **Managed write**: modifies a source locator already registered in the ledger
  v5 store. Currently always refused: managed writes must be recorded via the
  ledger's record primitive; the pgen skill does not post to the ledger directly.
  Route the request to `entity-ledger`.

Before every write, run:

```bash
python3 <entity-pgen-skill>/scripts/pgen_preflight.py \
  --ledger-home <controller-root> \
  --operation write \
  --target <site_id:/exact/absolute/path>
```

Resolve `<entity-pgen-skill>` from this `SKILL.md`; do not assume the current
working directory is the skill directory. Run preflight for each intended
target, or for their narrowest common parent directory. Proceed only when it
returns `"allowed": true`. Preflight queries the ledger v5 store to check
whether the target locator falls under a registered case source, identity root,
or active run; it never infers managed status from ancestor directories. If it
reports `router-required`, do not write; return the target, the detected case,
the requested change, and the reason to `entity-ledger`. Never modify the
ledger's control state.

JSON is always printed, even on failure (exit code 2). The `store_present`
field indicates whether the registry was actually queried: `true` means the
`standalone-write` target was confirmed unregistered; `false` means the ledger
store is missing or unreadable, in which case standalone only means "could not
check" — treat it as a warning, not a confirmation; `null` means evaluation
failed before the query (e.g. an invalid `--target`).

For targets not registered with the ledger, treat them as standalone only when
the user has chosen an exact location and requests only PGen-domain deliverables.
Ambiguous workspace creation, persistent simulation work, or any request that
continues into build, run, resume, or analysis is routed to the ledger.

## Scope

Handle:

- designing a new PGen and its companion TOML in standalone mode;
- modifying or reviewing an existing PGen/TOML pair;
- maintaining `docs/design.md` alongside implementation changes;
- checking normalization, coordinate bases, API usage, and PGen-TOML consistency;
- fixing problems already attributed to PGen code or configuration.

Route elsewhere:

- managed case lifecycle and cross-domain simulation workflows -> `entity-ledger`;
- dependency setup, CMake configuration, and build execution -> `entity-env-build`;
- failures whose attribution is not yet clear -> return evidence to the package ledger;
- Entity engine or framework changes -> return a scoped handoff to the package ledger;
- simulation output access and visualization -> `entity-nt2py`; route scientific analysis to `entity-ledger`.

Do not add platform-specific metadata or invocation configuration to core skills.

## Core Rules

1. Maintain `docs/design.md`, `pgen.hpp`, and the companion TOML as one unit.
2. Before modifying the PGen or TOML, read the current design and implementation. If no design document exists, reconstruct a minimal design from the current files and mark inferred decisions as "inferred".
3. Cover every core PGen component in the design: basic configuration, initial electromagnetic fields, initial particles, boundaries, custom behavior, and custom output. Mark unused components as `not-used` rather than omitting them.
4. Keep the design concise. Record intent, the relevant TOML mappings, and current status; include formulas or implementation details only when needed to remove ambiguity.
5. Confirm first before decisions that materially change the physical model, normalization, or implementation direction. When open questions are not blocking, continue with safe local work.
6. Where feasible, verify Entity version, API signatures, normalization, and coordinate-basis conventions against the currently active source checkout. The bundled references target Entity v1.4.4 and are subordinate to current source evidence.
7. When a change affects the shared contract between PGen and TOML, modify both together, then update the corresponding design section and current status.
8. Before any run submission, show the user the parameter card and record confirmation with `python3 <entity-pgen-skill>/scripts/pgen_preflight.py confirm <input.toml> --by <actor>` (add `--confirm-defaults` when accepting defaults without item-by-item review). This command writes `<input.toml>.decisions.json`; the ledger's record run-prepare gate refuses registration when the record is missing or its `input_sha256` no longer matches the TOML. Re-run `confirm` after any TOML edit.

## Working Method

Adjust working depth to the request:

1. **Locate**: find the active Entity source checkout, the PGen, the TOML, and `docs/design.md`; inspect only evidence relevant to the task.
2. **Identify the affected design**: determine which core components and TOML keys are involved. Resolve blocking physics decisions before implementing.
3. **Load references**: read the relevant reference files below, and check version-sensitive claims against the active checkout.
4. **Design and implement**: create or update `docs/design.md`, then make the corresponding PGen and TOML changes. For local fixes, update design and implementation in the same pass.
5. **Verify**: check the affected design-PGen-TOML contracts, and run static, build, smoke, or physics checks proportionate to the task.
6. **Record status**: update the current status in the design document, and report what is implemented, verified, pending, or handed off.

For pure explanation requests, read and explain the existing design and implementation without creating procedural artifacts. For reviews, report concrete conflicts with evidence; do not expand the task into a full redesign unless truly necessary.

## Design Document

Keep all PGen design material under `docs/`. Use a single `docs/design.md` by default; add auxiliary documents only when the PGen genuinely needs them.

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

When the problem requires it, the Agent may extend, merge, or trim sections, but must preserve coverage of the core components and the current-status record.

## Reference Routing

All references describe Entity v1.4.4. Read only the files relevant to the affected design.

| Need | References |
|---|---|
| Normalization, units, or coordinate basis | `references/00-normalization.md` |
| PGen structure, traits, constructor, or parameters | `references/01-skeleton.md` |
| Initial electromagnetic fields | `references/02-init-fields.md` |
| Initial or replenishment particle injection | `references/03-particle-injection.md` |
| External current | `references/04-ext-current.md` |
| External force or external fields | `references/05-ext-force.md` |
| Boundary conditions | `references/06-boundary.md` |
| Custom field output or statistics | `references/07-custom-output.md` |
| Custom time step or particle update | `references/08-custom-post-step.md` |
| TOML structure and parameters | `references/09-toml-config.md` |
| Higher-order field or particle algorithms | `references/10-higher-order.md` |
| Existing Entity PGen patterns | `references/pgens-index.md` |

For a new PGen, start with `00`, `01`, and `09`, then load the feature references selected by the design. For an existing PGen, start from its current files and load only the references needed for the affected components. When an API pattern is uncertain, use `pgens-index.md`, then inspect the referenced implementations in the active checkout.

## Consistency and Verification

Check three relationships within the affected scope:

1. `docs/design.md` <-> `pgen.hpp`;
2. `docs/design.md` <-> TOML;
3. `pgen.hpp` <-> TOML.

Include these checks where relevant:

- PGen traits match the TOML engine, metric, and dimensions;
- `params.get()` keys match the names and types in the TOML `[setup]`;
- particle species count, order, attributes, and indices are mutually consistent;
- field and particle boundary settings match the implemented hooks;
- custom output names match the TOML requests;
- normalization and coordinate basis are explicit and consistent;
- special algorithms, build options, and external data required by the design are all declared;
- the design status faithfully reflects the evidence actually obtained.

Do not claim build, smoke-test, or physics verification as complete unless it was actually executed. Local changes do not require re-checking unrelated parts of the case.

## Deliverables

For a new PGen, produce:

```text
pgens/<name>/
|-- pgen.hpp
|-- <name>.toml
`-- docs/
    `-- design.md
```

Additional design notes, figures, or verification records go into `docs/` only when needed. Runtime data tables go in an appropriate data directory outside `docs/`.

When build or run verification is needed, hand off the current checkout's identity, the PGen/TOML paths, the design requirements, and unresolved constraints to the owning skill.
