# Harness Refactor Plan

Date: 2026-06-20

## Bottom Line

The project should stop growing as a detailed Entity encyclopedia and be rebuilt as a set of small harnesses that force the agent to inspect the target checkout, select the right workflow, and produce verifiable handoff artifacts.

The current root skill is useful but too broad: one `SKILL.md` routes build, TOML, PGen, run, debug, and analysis into a single workflow, while `knowledge/` stores long parameter and API references that are likely to drift. The vault already describes a better architecture, but that design has not been translated into the installable skill pack.

The refactor should therefore be a contraction, not an expansion.

## Harness Engineering View

A good harness is not a textbook. It should:

- classify the task quickly;
- require the smallest source-of-truth probe needed for the task;
- constrain the allowed edit surface;
- produce an artifact that another agent or future session can verify;
- stop before claiming unverified version-specific facts.

For this project, the harness should make Entity work reproducible and auditable. Its main job is to keep the agent from guessing about Entity versions, PGen hooks, TOML keys, Kokkos/ADIOS2 combinations, output quantities, and local fork behavior.

## Current Drift

### 1. The live skill is a single broad funnel

`SKILL.md` currently describes a four-stage general workflow:

- environment and compilation;
- simulation configuration;
- run and debug;
- analysis.

That is convenient for a README-style guide, but it is too wide for a reliable agent harness. It mixes tasks with different risk profiles and different validation standards.

### 2. Detailed references are treated like stable knowledge

The largest tracked files are detailed references:

- `knowledge/entity/02-toml-config.md`;
- `knowledge/entity/03-pgen-guide.md`;
- `knowledge/entity/04-debug.md`;
- `knowledge/nt2py/03-particles-stats.md`.

These are useful as orientation, but TOML layouts, PGen hook signatures, output names, and dependency requirements are version-sensitive. The harness should point to current checkout files first and treat these notes as secondary examples.

### 3. The vault architecture and live package are out of sync

The vault says the target is:

```text
SKILL.md
core/source-of-truth.md
core/code-map.md
skills/entity-sim.md
skills/entity-dev.md
templates/run-manifest.yaml
templates/dev-design-note.md
```

The tracked package instead has:

```text
SKILL.md
knowledge/entity/*.md
knowledge/nt2py/*.md
```

This creates two competing mental models: the vault thinks in terms of task harnesses, while the live package behaves like a reference bundle.

### 4. Case work is split incorrectly in the live package

The vault made the right call that TOML and PGen are one case contract. In the tracked package they are separate long documents. That invites the agent to edit a TOML key without checking whether the selected PGen, species, dimensions, boundaries, and outputs actually match.

### 5. Analysis is allowed to become too interpretive too early

The first analysis harness should train the agent to inspect output safely with `nt2py`, shrink selections before loading, check logs and stats, and label evidence strength. Broad physics diagnosis should come later and should not be implied by a successful plot.

## Target Architecture

The next live package should have this shape:

```text
SKILL.md
core/
  source-of-truth.md
  checkout-probe.md
  code-map.md
skills/
  entity-sim.md
  entity-dev.md
  entity-analysis.md
  entity-debug.md
templates/
  run-manifest.yaml
  dev-design-note.md
  analysis-report.md
references/
  toml-orientation.md
  pgen-orientation.md
  nt2py-orientation.md
```

The important change is semantic:

- `core/` contains durable rules and lookup paths.
- `skills/` contains executable workflows and stop conditions.
- `templates/` contains handoff artifacts.
- `references/` contains non-authoritative examples, not presumed facts.

`SKILL.md` should be a router only. It should not carry Entity API details.

## Harness Boundaries

### Router

Purpose: classify the request and load the minimum task harness.

Rules:

- Always load `core/source-of-truth.md` and `core/checkout-probe.md`.
- Load only one primary task harness at a time.
- State whether a secondary harness may be needed.
- Do not summarize detailed Entity APIs.

### Simulation Harness

Purpose: produce a reproducible run or case setup.

Allowed surface:

- TOML;
- case-local `pgen.hpp`;
- build/run scripts;
- scheduler scripts;
- run manifest.

Required checks:

- checkout/version probe;
- `input.example.toml`;
- selected `pgens/*/pgen.hpp` or `examples/*/pgen.hpp`;
- TOML/PGen consistency over engine, metric, dimensions, species, setup keys, boundaries, and outputs.

Stop condition: do not claim physics validation without analysis evidence.

### Development Harness

Purpose: modify Entity source or design a source-level change.

Allowed surface:

- `src/framework`;
- `src/engines`;
- `src/kernels`;
- `src/output`;
- `src/global/traits`;
- tests;
- examples/pgens when needed.

Required checks:

- checkout/version probe;
- current call path;
- owner boundary;
- host/device boundary;
- tests or smoke checks.

Stop condition: separate verified repo facts from proposed design.

### Analysis Harness

Purpose: turn run output into evidence-backed diagnostics.

Required checks:

- output directory;
- `.err`, `.info`, `.log`, stats CSV;
- TOML/PGen paths when available;
- lazy data access before memory-heavy loads.

Evidence labels:

- `visual`;
- `numerical`;
- `regression`;
- `unresolved`.

Stop condition: no broad physics conclusion from a plot alone.

### Debug Harness

Purpose: diagnose build, runtime, output, checkpoint, performance, or numerical failures.

Required checks:

- preserve failing command and environment;
- read the artifact closest to the failure;
- minimize the case;
- propose one change at a time;
- rerun the smallest useful check.

Stop condition: every diagnosis needs evidence and remaining uncertainty.

## Migration Map

| Current file | New role |
| --- | --- |
| `SKILL.md` | Replace with thin router. |
| `knowledge/entity/01-build-env.md` | Split into `skills/entity-debug.md` build section plus `references/build-orientation.md`. |
| `knowledge/entity/01b-install-methods.md` | Move to `references/build-orientation.md`; keep as optional lookup only. |
| `knowledge/entity/02-toml-config.md` | Shrink into `references/toml-orientation.md`; authoritative path is target checkout `input.example.toml`. |
| `knowledge/entity/03-pgen-guide.md` | Shrink into `references/pgen-orientation.md`; authoritative paths are target checkout traits and pgens. |
| `knowledge/entity/04-debug.md` | Convert into `skills/entity-debug.md` workflow and failure taxonomy. |
| `knowledge/nt2py/*.md` | Merge into `skills/entity-analysis.md` plus `references/nt2py-orientation.md`. |
| `CLAUDE.md` | Keep as contributor orientation, but update after package layout changes. |
| `EntitySkillPackVault/` | Keep ignored; use as design source, not installable package content. |

## First Refactor PR Scope

Keep the first PR deliberately small:

1. Add `core/source-of-truth.md`, `core/checkout-probe.md`, and `core/code-map.md`.
2. Replace `SKILL.md` with a thin router.
3. Add `skills/entity-sim.md` and `skills/entity-dev.md`.
4. Add `templates/run-manifest.yaml` and `templates/dev-design-note.md`.
5. Move existing long `knowledge/` files under `references/` without expanding them.
6. Update `README.md` to describe the harness model.

Do not add playbooks in the first PR. Do not deepen the TOML or PGen reference. Do not solve local overlay modeling yet.

## Acceptance Criteria

The refactor is successful when:

- a simulation request loads simulation guidance, not source-development guidance;
- a source-code request loads development guidance, not run-operation guidance;
- both simulation and development require checkout/version probing before version-sensitive advice;
- TOML/PGen changes are treated as one case contract;
- large reference docs are clearly marked non-authoritative;
- every workflow has an explicit output artifact;
- no installed skill file needs the Obsidian vault to function.

## Deletion And Shrink Rules

Use these rules while editing:

- Delete duplicated command recipes if the same rule exists in a harness and a reference.
- Keep tables only when they are stable decision aids.
- Replace version-sensitive API details with "check these files" unless the note is explicitly scoped to a version bucket.
- Prefer checklists over prose explanations.
- Keep the router under 80 lines.
- Keep each task harness under 150 lines unless real validation logic requires more.
- Keep references clearly optional and non-authoritative.

## Proposed Next Step

Implement the first refactor PR as a structural change only. Do not rewrite the science or dependency facts in the same pass. The goal is to make the package enforce the right behavior before improving individual knowledge notes.
