# Workspace and Computation Site: Top-Level Model Design

Date: 2026-08-03. Status: finalized, pending implementation.

## 1. Background: Three Practical Problems

The current version (0.6.x, entity-ledger + owner skills) has exposed three
problems in use:

1. **Agents cannot find the deps on servers or previously used environments.**
   `deps_root`/`artifacts_root` are neither in the site profile nor in the
   ledger; checkpoints are addressed per case and only answer "can this case
   reuse them"; cross-session memory consists only of prose site-notes, with
   no machine-readable registry.
2. **No management of data-analysis code.** The analysis dimension is an empty
   shell in the store/dashboard (no record primitive); analysis scripts are
   scattered across project directories, unregistered, with no version
   correspondence.
3. **Two first-class concepts are missing at the abstraction level**: a
   directory for source maintenance/development/work, and an environment for
   actual computation. The two may be on the same machine or on different
   machines, but they are conceptually separate.

This design solves problems 1 and 3 and draws the boundaries of the core
concepts; problem 2 (analysis) only gets reserved slots and will be designed
separately later.

## 2. Top-Level Model

```text
Workspace (development environment, the single working directory)
└── Projects (research topics, holding the source authority)
    └── Cases (research threads within an intent boundary)
        └── Identity chain: source → build → run → data → analysis (reserved)

Computation Site (compute environment, a conventional file tree + a structured profile)
└── Holds: shared deps stacks, materialized checkouts, projects/<p>/{builds,runs,staging}
```

- A **Workspace** is a real directory, the single working directory for
  development. It records every fact needed to rebuild a project (not the
  large artifacts themselves), so the user can carry the whole directory to
  any machine and start over. One Workspace contains multiple Projects.
- A **Computation Site** is a managed compute environment: on one machine (or
  an access boundary of "HPC login node + scheduler + shared disk"), a
  conventional file tree plus a profile registered in the Workspace. It does
  only three things: hold shared deps, materialize source, and execute
  build/run. It holds no authoritative records; all facts are written back to
  the Workspace, and if the tree on the site is lost it can be rebuilt from
  the profile.
- **Case = intent boundary**: a research thread with a clear intent inside a
  project (one intent + one PGen configuration family + its build/run/data
  chain). A parameter scan = one case with multiple runs; a new case is opened
  only when the intent changes. Run semantics are unchanged (append-only
  ledger entries referencing a build; a restart references a parent).
- Workspace and Computation Site may be on the same machine (the same site
  plays both the dev and compute roles) or on different machines. They are
  always conceptually separate: the Workspace is a portable archive, the
  Computation Site is a rebuildable execution venue.

## 3. Workspace Directory Tree

```text
entity-workspace/                    # the single working directory; location chosen by the user
├── workspace.yaml                   # workspace_id, schema version, creation/migration history
│
├── projects/                        # human-readable tree, where the user's daily work happens
│   └── <project>/
│       ├── project.yaml             # project_id, case list, default site preference
│       ├── source/                  # source authority (name unrestricted, registered in yaml)
│       ├── docs/  scripts/  ...     # user's existing content kept as-is; no enforced structure
│       └── cases/
│           └── <case>/
│               ├── intent.md        # intent (materialized as a human-readable file)
│               ├── decisions.json   # pgen parameter confirmation card
│               └── analysis/        # reserved slot
│
├── sites/                           # structured site profiles = upgraded site-notes
│   └── <site>.yaml
│
└── .ledger/                         # controller state (machine read/write)
    ├── ledger.db                    # migrated from ~/.entity-ledger
    └── snapshots/                   # source snapshot tars (content-addressed)
```

Semantics:

- `projects/` and `sites/` are human-readable, human-writable archives (YAML +
  Markdown); `.ledger/` is machine state. The site profile is authoritative;
  the ledger.db `sites` table is imported/refreshed from it; high-frequency
  facts such as the case identity chain and the run ledger stay in the db.
- Git is not used for versioning; the Workspace is the working directory
  itself.
- **Portability = a self-contained directory.** Migration = rsync the whole
  directory → `entityctl workspace adopt <path>` on the new machine (writes a
  pointer in `~/.entity-ledger/active-workspace`) → continue working. The
  compute site profiles on the old machine are kept as-is (they describe
  remotes and are unaffected by the move). Credentials and SSH private keys
  never enter the profiles; a site profile records only the SSH alias name.

## 4. Computation Site File Tree

```text
<site_root>/                          # e.g. /lustre/.../entity-compute
├── entity-site.yaml                  # site marker: site_id, schema version, roots list
│                                     #   an agent that finds it knows everything (discovery mechanism)
├── deps/                             # shared dependency stacks (site-level, reused across projects)
│   └── <stack_id>/                   #   by toolchain signature, e.g. gcc11-openmpi4.1-hdf5.14
│       ├── <package>/...             #   per-dependency prefixes
│       ├── env.sh
│       └── stack.yaml                #   stack manifest: versions/build recipe/verification status
│
├── checkouts/                        # materialized source (immutable, content-addressed)
│   └── <source_hash>/                #   same hash means same content — natural dedup
│
└── projects/                         # one independent subtree per project, never mixed
    └── <project>/
        ├── builds/<case>/<build_id>/ #   immutable
        ├── runs/<case>/<run_id>/     #   immutable; authoritative location of raw data
        ├── staging/<case>/<op_id>/   #   staging + receipt
        └── analysis/                 #   reserved slot
```

Partitioning logic: the site level holds only shared items that are
**immutable and content-addressed** (deps stacks, checkouts); everything
project-specific and time-accumulating (builds, runs, staging, analysis) goes
into `projects/<project>/`. A person running `ls projects/` on the server
sees the project boundaries, and deletion/archival/quota can all operate per
subtree.

Path segments use slugs (`<project>/<case>`, readable), with stability backed
by the uid + path records in the profiles. A `<project>` subtree sits under
`site_root` by default, and the profile allows per-project overrides (quota
needs).

Raw data gets no separate data_root: the run directory is the authoritative
data location, the inventory manifest of `record data` references paths inside
the run directory, and retrieved content goes into the Workspace's project
area.

## 5. Site Profile (sites/<site>.yaml)

```yaml
site_id: m87
transport: { kind: ssh, alias: m87 }       # or { kind: local }
scheduler: { kind: slurm, default_partition: ..., default_qos: ... }
machine: { os: ..., arch: ..., gpus: ... } # probed and persisted by site discover
site_root: /home/staticobserver/entity-compute
projects:                                  # which project subtrees exist on this site
  - bh-reconnection
deps:                                      # structured deps registry (the core addition)
  - stack_id: gcc11-openmpi4.1-hdf5.14
    status: verified                       # verified / suspect / broken
    packages: [{ name, version, prefix }, ...]
    recipe: ...                            # module list or source-build recipe
notes: |                                   # free-text section, preserving human experience
  ...
```

**The deps registry is the solution to problem 1**: when env-build resolves
`requirements.json`, it first queries the corresponding site's registry; on a
hit that passes verification, it reuses the stack; newly resolved/built
dependency stacks are written back to the registry once confirmed.
`entity-deps.local.json` is still stored per case (build evidence), but the
resolution source changes from "agent probes on the spot" to "registry +
probing to fill gaps".

## 6. Mapping to the Existing Model

| Existing concept | Where it goes in the new model |
|---|---|
| `~/.entity-ledger/ledger.db` + `snapshots/` | `workspace/.ledger/` |
| `project-bindings.json` | the per-project `project.yaml` |
| scattered working directories `~/Documents/<project>/` | `workspace/projects/<project>/` (move the whole directory; internals untouched) |
| `~/.entity-env-build/site-notes/*.md` | the notes section + structured sections of `workspace/sites/<site>.yaml` |
| site profile roots (5 independent roots) | the `site_root` conventional tree + the `entity-site.yaml` marker |
| Case (0.6.x, "one per simulation project") | split into Project (container) + Case (intent boundary) |
| `projects` table root→case 1:1 binding | project 1:N cases (store schema upgrade) |
| analysis empty-shell dimension | kept reserved, designed last |

The contract in `workspace-layout.md` that "ledger.db must never live inside
a source checkout directory" is unchanged: `.ledger/` sits at the workspace
root, not inside any source authority.

## 7. Migration Strategy: Full Migration, Agent-Driven

No "constrain only the increment" compromise for the old layout — the old
trees on the existing 13 sites (build/, builds/, etc.) and the scattered
project directories are all migrated into the new model, so that in the end
only one layout exists.

**Approach: skill first, migration second.** First develop the new model, the
migration primitives, and the migration guide into the skill and put them into
production; then have the agent tidy up the old files in production following
the skill. Division of labor:

- **The skill provides the knowledge**: the target layout, movement rules,
  ordering and taboos (runs in flight are not touched — migrate them after
  they reach a terminal state; inventory hashes before moving, re-probe and
  record after moving), and how to orchestrate the pace given each machine's
  actual situation.
- **entityctl provides deterministic primitives**: supporting the safe
  execution of "move + re-register" — deriving target paths from the new tree,
  re-probing evidence and updating Locators after a move, zero writes on
  failure, rerunnable.
- **The agent does the orchestration**: which machine migrates first, how to
  avoid jobs in flight, how to fix errors — this is exactly the "free
  exploration, strict convergence" principle applied to migration.

Absorbing the Workspace-local parts (projects directories, ledger.db,
site-notes → YAML) is a one-shot local operation done by the `workspace
import` script; tidying the old trees on remote sites cannot be scripted
(machine reachability, runs in flight, and quotas all differ) and is executed
by the agent site by site.

Migration completion criteria: the Locators of all registered resources point
at the new tree paths, and no old path is referenced by any current identity;
old directories are deleted after the agent verifies they are empty.
Credentials never enter the profiles; after `workspace adopt`, the user
reconfigures SSH aliases on the new machine.

## 8. Explicitly Out of Scope (this time)

- Management design for analysis scripts/artifacts (reserved slots: workspace
  `cases/<c>/analysis/`, site `projects/<p>/analysis/`, the analysis dimension
  of the identity chain).
- Full portability of run-ledger-level detail (high-frequency facts live in
  ledger.db and travel with the workspace; the raw data itself on remotes is
  never moved).
- Git-ifying the Workspace, merging multiple workspaces.
