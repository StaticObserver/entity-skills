# Entity Skill Pack Architecture

## Problem

Entity-related work naturally falls into several categories:

- simulation runs: configuration, building, running, monitoring, restarting;
- result analysis: reading output, plotting, verifying numerical and physical behavior;
- feature development: modifying C++/Kokkos/MPI/ADIOS2 code and verifying changes;
- troubleshooting: diagnosing build, runtime, numerical, output, and cluster environment problems.

If all of this is stuffed into one very large skill, shallow run guidance and deep source-development knowledge get mixed together. The result is hard to maintain and more prone to hallucinating version-specific APIs.

## System Approach

Adopt an Entity Skill Pack:

```text
entity-skillpack/
├── SKILL.md                  # router / dispatcher
├── core/                     # shared source facts and foundational knowledge
├── skills/                   # task-oriented skills
├── playbooks/                # reusable workflows
└── templates/                # structured handoff and artifact templates
```

In this Obsidian vault, the above directories exist as design notes:

- [[20-Skills/Router Skill Spec|Router Skill Spec]]
- [[Knowledge Model and Version Strategy|Knowledge Model and Version Strategy]]
- [[40-Development/Development Plan|Development Plan]]

## Components

### Router

The router should be thin: it only classifies the user request and loads the minimal necessary task skill:

- simulation request -> simulation skill;
- analysis request -> analysis skill;
- source feature request -> development skill;
- failure diagnosis -> debug skill;
- artifact/report writing -> docs skill.

### Core Knowledge

Core knowledge is shared by all skills and all agents. It stores stable orientation and source-of-truth rules, rather than a full copy of the Entity documentation.

It should contain:

- version and checkout detection;
- official authoritative information sources;
- a code map;
- concepts and terminology;
- common pitfalls;
- local overlays that must not be confused with upstream behavior.

### Task Skills

Each task skill owns one workflow and one verification standard.

- Simulation skill: reproducible experiment runs.
- Analysis skill: evidence-based interpretation of output.
- Development skill: implementation and testing grounded in source facts.
- Debug skill: cross-workflow failure diagnosis.
- Docs skill: long-term notes, run manifests, design notes, and PR summaries.

## Boundaries

### Simulation vs. Development

Simulation work may edit pgens, TOML, scripts, and analysis artifacts. By default it does not modify the Entity core source.

Development work may modify the Entity core, but must first inspect the current checkout and clearly identify the relevant source paths, traits, kernels, engine, or writer boundaries.

### Official vs. Local

Only upstream behavior confirmed from the current checkout or the official wiki may be written into the shared core.

User forks, experimental branches, and project-specific behavior should go into local overlays, clearly labeled as such.

## Phase-One Implementation Goal

Build a minimal viable skill pack first:

```text
SKILL.md
core/source-of-truth.md
core/code-map.md
skills/entity-sim.md
skills/entity-dev.md
templates/run-manifest.yaml
templates/dev-design-note.md
```

Then add analysis, debug, docs, and playbooks afterward.
