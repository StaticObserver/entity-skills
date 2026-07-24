# Entity Skills Overall Architecture

Date: 2026-06-20

Archive status: superseded by `design/architecture.md`; not part of the current design or runtime context.

## 1. Project Positioning

`entity-skills` is, for now, designed as a complete skills package.

It is not an Entity knowledge base, nor a tutorial, but an agent-facing harness: the top-level `SKILL.md` determines which kind of task a user request belongs to, and instructs the agent to load the corresponding concrete skill.

See `design/harness-principles.md` for the design principles. Those principles guide the project design, but are not a runtime dependency of the package.

## 2. Repository Layout

```text
entity-skills/
├── SKILL.md        # top-level router
├── README.md       # package usage instructions
├── core/           # base rules shared by all skills
├── skills/         # concrete task skills
├── playbooks/      # cross-skill composite workflows
├── templates/      # handoff and state templates
├── references/     # non-authoritative reference material
├── design/         # project design working files
└── legacy/         # archive of the old project
```

Boundaries:

- `SKILL.md`, `core/`, `skills/`, `playbooks/`, `templates/`, `references/`, and `README.md` belong to the skills package.
- `design/` only holds design documents and should not be loaded automatically at runtime.
- `legacy/` only holds the old project archive and should not be loaded automatically at runtime.

## 3. Top-Level Router

The top-level `SKILL.md` should be thin.

It does only three things:

- state the goals and non-goals of this package;
- select the skill to load based on the user request;
- require the agent to load only the minimum context needed to complete the current task.

It should not contain detailed Entity API references, TOML parameter tables, PGen details, or analysis code examples.

## 4. Core Modules

`core/` holds the base rules that every skill must follow.

Tentative contents:

- `context.md`: project roles, non-goals, success criteria;
- `source-of-truth.md`: precedence among current checkout, upstream, wiki, references, local overlay, and legacy;
- `checkout-probe.md`: when the target Entity checkout must be inspected;
- `code-map.md`: the locations to check first in the Entity source;
- `state-model.md`: the distinction between current task state, session discoveries, and long-term conventions.

These files hold only stable rules and indexes; they do not copy large blocks of knowledge.

## 5. Task Skills

`skills/` is the body of the project. Each skill owns one task boundary and one verification method.

Six tentative skills:

- `entity-env-build.md`: dependencies, build environment, CMake, MPI, Kokkos, ADIOS2.
- `entity-case.md`: simulation case, including TOML, PGen, run script, and run manifest.
- `entity-analysis.md`: output reading, diagnostics, plotting, evidence grading, and analysis reports.
- `entity-core-dev.md`: Entity source modifications, call paths, owner boundaries, and tests.
- `entity-debug.md`: build/runtime/output/checkpoint/performance/numerical failure diagnosis.
- `entity-docs.md`: long-term handoff artifacts, such as simulation plan, run manifest, analysis report, debug report, dev note.

Important boundaries:

- Running simulations and source development must be kept separate.
- TOML and PGen must be treated as the same case contract.
- No standalone, generalized run-ops skill.
- Output/checkpoint related content goes into analysis or debug.

## 6. Playbooks

`playbooks/` combine multiple skills to handle cross-module tasks.

Tentative playbooks:

- `new-simulation.md`
- `reproduce-run.md`
- `analyze-output.md`
- `debug-failure.md`
- `source-change.md`

A playbook contains only orchestration logic, not large amounts of domain knowledge.

## 7. Templates

`templates/` are the state and handoff mechanism.

Tentative templates:

- `simulation-plan.md`
- `run-manifest.yaml`
- `analysis-report.md`
- `debug-report.md`
- `dev-design-note.md`

Template details will be designed separately later.

## 8. References

`references/` holds only non-authoritative orientation.

Tentative references:

- `build-orientation.md`
- `case-orientation.md`
- `nt2py-orientation.md`
- `version-buckets.md`

References cannot override the current Entity checkout. They only help the agent know what to look up and how.

## 9. Design Order

Design the overall framework first, then refine each piece:

1. Top-level `SKILL.md` router.
2. `core/` base rules.
3. Boundaries and skeletons of the six `skills/`.
4. Minimal fields of the `templates/`.
5. Composition logic of the `playbooks/`.
6. Selection and compression of the `references/`.

At each step, define the boundary, inputs, outputs, and acceptance criteria first, then decide how much knowledge content is needed.
