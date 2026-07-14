# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a skill pack for teaching AI coding agents to work with [Entity](https://github.com/entity-toolkit/entity), an open-source C++20 general-relativistic particle-in-cell (PIC) plasma simulation code. Entity uses Kokkos for GPU portability, MPI for multi-node parallelism, and ADIOS2 for data output.

The repo contains two layers:
- **Root level** — the live skill pack: `SKILL.md` (entry point) + `knowledge/` (reference docs)
- **`EntitySkillPackVault/`** — the Obsidian design/planning vault (mostly Chinese with English technical terms) that drives development of the skill pack

## Repo Structure

```
.
├── SKILL.md                          # Skill entry point (invoked by agents)
├── README.md                         # Human-facing install/usage guide
├── knowledge/
│   ├── entity/                       # Entity-specific reference material
│   │   ├── 01-build-env.md           # CMake options, GPU flags, compile commands
│   │   ├── 01b-install-methods.md    # Dep installation: pip, Docker, Spack, manual
│   │   ├── 02-toml-config.md         # Complete TOML parameter reference
│   │   ├── 03-pgen-guide.md          # Problem generator C++ API guide
│   │   └── 04-debug.md              # Compile & runtime error diagnosis
│   └── nt2py/                        # Python analysis toolkit reference
│       ├── 01-data-loading.md        # Installation, output files, Data API
│       ├── 02-fields.md              # xarray field plotting & movies
│       └── 03-particles-stats.md     # Phase-space, spectra, diagnostics
└── EntitySkillPackVault/             # Design/planning workspace (Obsidian vault)
    ├── Home.md                       # Vault entry point (Chinese)
    ├── 10-Architecture/              # Architecture docs, knowledge model, agent model
    ├── 20-Skills/                    # Skill specifications for each task domain
    ├── 30-Playbooks/                 # Reusable workflow definitions
    ├── 40-Development/               # Development plan, backlog, acceptance criteria
    ├── 50-References/                # Source-of-truth rules, local overlays
    └── 90-Templates/                 # Run manifests, simulation plans, design notes
```

## How the Skill Works

`SKILL.md` is the entry point that AI agents invoke. It defines a 4-stage workflow:
1. **Environment & Compilation** → `knowledge/entity/01-build-env.md`
2. **Simulation Configuration** → `knowledge/entity/02-toml-config.md` + `03-pgen-guide.md`
3. **Run & Debug** → `knowledge/entity/04-debug.md`
4. **Analyze Results** → `knowledge/nt2py/*.md`

Key principles embedded in the skill:
- The skill teaches agents **where to look** in the current Entity checkout, not to memorize APIs
- Simulation work (TOML edits, pgen changes, scripts) is separated from development work (modifying Entity core source)
- Local forks and experimental branches must be labeled as overlays, not confused with upstream Entity behavior
- The current Entity checkout is always more authoritative than the skill pack's summaries

## Version Compatibility

- Entity `v1.4.x` → Kokkos 5.x (C++20), ADIOS2 >= 2.11.0
- Entity `v1.3.x` → Kokkos 4.x, ADIOS2 2.10.x (do not mix with 1.4.x deps)
- ADIOS2 < 2.11 uses `cxx11_mpi`/`cxx11` CMake targets; >= 2.11 uses `cxx_mpi`/`cxx`

## Vault Conventions

The `EntitySkillPackVault/` is an Obsidian vault written primarily in Chinese. Key files:
- `Home.md` — main navigation hub
- `10-Architecture/Entity Skill Pack Architecture.md` — target architecture (router + core + task skills + playbooks + templates)
- `10-Architecture/Knowledge Model and Version Strategy.md` — source-of-truth hierarchy, version buckets, known drift areas
- `40-Development/Development Plan.md` — phased roadmap from current state to full skill pack

The vault describes a target architecture (router dispatching to specialized simulation/development/analysis/debug/docs skills) that is only partially implemented. The current root-level skill pack is a simpler single-SKILL.md design.
