# Development Plan

## Goal

Turn this vault into a maintainable Entity skill pack that supports both single-agent use and collaboration among multiple specialized agents.

## Phase 0: Vault Foundation

Status: in progress.

Deliverables:

- Obsidian vault structure;
- architecture notes;
- skill specifications;
- development plan;
- initial templates.

Acceptance:

- the vault opens as a coherent Obsidian knowledge base;
- every major design note is reachable from [[Home|Home]];
- the skill boundaries for simulation and development are clear.

## Phase 1: Minimal Skill Pack

Deliverables:

- `SKILL.md` router;
- `core/source-of-truth.md`;
- `core/code-map.md`;
- `skills/entity-sim.md`;
- `skills/entity-dev.md`;
- run manifest template;
- development design note template.

Acceptance:

- a single agent can route a simulation request to `entity-sim`;
- a single agent can route a source-code request to `entity-dev`;
- both skills require checkout/version probing;
- both skills defer version-sensitive details to files in the current checkout.

## Phase 2: Analysis and Debug Skills

Deliverables:

- `skills/entity-analysis.md`;
- `skills/entity-debug.md`;
- analysis report template;
- debugging workflow;
- nt2py source-of-truth notes.

Acceptance:

- the analysis skill distinguishes visual, numerical, regression, and unresolved evidence;
- the debug skill covers build/runtime/output/checkpoint/performance categories;
- common debug conclusions include evidence and remaining uncertainty.

## Phase 3: Playbooks and Local Overlays

Deliverables:

- new simulation playbook;
- reproduce run playbook;
- add pgen playbook;
- add output quantity playbook;
- modify kernel playbook;
- checkpoint restart playbook;
- local overlays for the StaticObserver fork and experimental branches.

Acceptance:

- local overlays are labeled as local behavior;
- official upstream behavior is not conflated with fork behavior;
- every playbook has inputs, outputs, and stop conditions.

## Phase 4: Packaging and Validation

Deliverables:

- final skill-pack directory;
- README install instructions;
- smoke examples;
- validation checklist;
- optional GitHub publishing plan.

Acceptance:

- the skill pack can be copied into an agent skills directory;
- relative links work;
- an agent can complete a simulation routing test without missing files;
- docs state the currently supported Entity version buckets.
