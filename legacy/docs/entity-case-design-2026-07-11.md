# `entity-case` Skill Design

Date: 2026-07-11

Archive status: this proposal has been abandoned. The current architecture instead uses `entity-pgen`, `entity-env-build`, `entity-simulator`, `entity-debug`, and `entity-analysis` working together on a concrete case; this document is not part of the ongoing design context.

## Positioning

`entity-case` helps the user continue developing and using an Entity simulation case.

It handles PGen, TOML, and the run information directly tied to the two. The user may start from a one-line idea, or arrive with an existing PGen, an unfinished design from last time, a ready-to-run case, or a failed run. The skill does not assume a fixed starting point, nor does it require expanding the task into a complete research project.

Typical requests include:

- "Add another particle injection method to this PGen";
- "Continue writing the boundary conditions from last time's design";
- "Help me check whether the PGen and TOML are consistent";
- "Change the mesh and output frequency";
- "Can this case compile in the current Entity checkout?";
- "Run it with the existing executable";
- "Resume from this checkpoint".

`entity-case` does not build dependencies, modify the Entity engine, or analyze the physics results of a simulation. Those tasks go to `entity-env-build`, `entity-core-dev`, and `entity-analysis` respectively.

## Core Principle: Identify State First, Then Continue Work

`entity-case` has no single linear workflow. After taking over, the agent first reads the user-specified workspace, the current Entity checkout, and the files relevant to the request, forming a snapshot of the current state, and then handles only the parts involved in the user's goal.

The state consists of six mutually independent dimensions:

| State dimension | Possible values | Meaning |
|---|---|---|
| `source` | `located` / `uncertain` | Whether the current Entity checkout, version, and case location are clear |
| `case` | `absent` / `partial` / `present` | Whether the PGen, TOML, or design material exists |
| `contract` | `unchecked` / `conflicted` / `consistent` | Whether the relevant parts of the PGen and TOML have been cross-checked |
| `build` | `unknown` / `missing` / `stale` / `ready` | Whether an executable matching the current case exists |
| `run` | `none` / `prepared` / `running` / `completed` / `failed` / `stopped` | State of the current run |
| `decisions` | `clear` / `open` / `blocked` | Whether the key decisions needed for the current task are sufficient |

These states are not a pipeline that must be walked through. For example:

- When only explaining a piece of PGen, it can be `contract: unchecked`, `build: unknown`, `run: none`;
- When modifying an existing TOML, it can be `case: present`, `build: stale`, with no need to create a run;
- When continuing last time's design, it can be `case: partial`, `decisions: open`;
- When resuming a run directly, it can be `case: present`, `build: ready`, `run: stopped`.

State is reconstructed ad hoc by the agent from files and logs by default; the user is not required to maintain extra state files. Only when a simulation is actually run is `run-manifest.yaml` used to persist run identity and state.

## How to Identify State

The agent only inspects evidence relevant to the current request; it does not do purposeless full-repo scans.

### `source`

Check:

- which Entity checkout the user specified;
- the checkout's commit, version, and working-tree status;
- where the case is, and whether multiple same-named copies exist.

Set to `uncertain` when a unique checkout or case cannot be found. Ambiguities that would cause edits in the wrong directory must be resolved before writing code.

### `case`

Check what already exists:

- `pgen.hpp`;
- TOML;
- design notes, TODOs left by the previous session, or uncommitted changes;
- reference PGens pointed out by the user.

Set to `partial` when only some material exists. This is not an error; the agent can continue from what exists.

### `contract`

Only cross-check the contract surfaces affected by the current task:

- PGen traits vs. engine, metric, and dimension in the TOML;
- `params.get` vs. `[setup]`;
- species count, order, mass, charge, and index;
- grid, scales, and boundaries;
- source, force, custom output and their corresponding configuration;
- compile options required by special algorithms.

If it has not been checked, it is `unchecked`; it must not be recorded as `consistent` just because the files parse. After modifying the PGen or TOML, the affected contract surfaces become `unchecked` again; unrelated parts do not all need to be re-verified.

### `build`

Only check when the user wants to compile, run, or judge runnability:

- the Entity commit the executable corresponds to;
- whether it contains the current PGen;
- whether backend, precision, MPI, and special compile options match;
- whether the PGen or related source is newer than the build artifacts.

If a match cannot be proven, it is `unknown`; if a mismatch is known, it is `stale`. When a rebuild is needed, hand explicit build requirements to `entity-env-build`.

### `run`

Only identify when there is run intent or run evidence. Prefer reading scheduler status, process status, exit codes, stdout, stderr, checkpoints, and output; do not guess from chat descriptions.

### `decisions`

Judge only the information necessary to complete the current request:

- information is sufficient, or a risk-free default can be used: `clear`;
- there are undecided items, but the agent can still do drafts, investigation, or other local work: `open`;
- a missing decision would change the implementation direction, physical meaning, or major computational cost: `blocked`.

Do not ask scientific questions unrelated to the current modification in pursuit of a complete design.

## Acting on User Needs

The agent combines "the user's current goal" with the "state snapshot" to choose the minimal action.

| User goal | States to attend to | Action |
|---|---|---|
| Explain existing PGen/TOML | `source`, `case` | Read the relevant implementation and explain; do not require a plan or a verification run |
| Continue last time's design | `source`, `case`, `decisions` | Find the existing design and changes, continue from the unfinished point |
| Locally modify a case | `source`, `case`, `decisions` | Modify the minimal scope and re-verify the affected contract |
| Create a PGen from scratch | `source`, `case`, `decisions` | Collect only the information the current implementation requires, then generate the PGen/TOML |
| Check configuration | `source`, `case`, `contract` | Report concrete conflicts and evidence; do not automatically expand into full case development |
| Compile the current case | `source`, `case`, `contract`, `build` | Organize build requirements and hand them to `entity-env-build` |
| Run a case | `source`, `case`, `contract`, `build`, `run` | Confirm input identity, create a manifest, then launch or generate the command |
| Checkpoint resume | `source`, `case`, `build`, `run` | Verify the checkpoint and input identity, create a new run record |
| Fix a failure | `run` plus failure evidence | Only handle problems attributable to PGen, TOML, or launch configuration; otherwise hand to `entity-debug` |

The agent may perform multiple actions in one task, but does not automatically expand a local request into a full lifecycle. For example, if the user only asks to add a `CustomStat`, completing the code, the corresponding TOML entries, and a local consistency check is enough; resources, compilation, and runs should not be designed automatically.

## Key Decisions

The agent should handle mechanical and low-risk choices itself, and only hand questions that genuinely affect direction to the user.

Typical situations requiring confirmation:

- two implementations would express different physical models;
- normalization, coordinate basis, or unit domain cannot be determined from the current case;
- a modification would break comparability with existing runs;
- existing files, output, or checkpoints need to be overwritten;
- an expensive GPU, multi-node, or long-duration job is about to be submitted;
- the current Entity checkout does not support the requirement and the engine must be modified.

Typical situations that should not block:

- naming and code style that can be clearly inferred from the existing PGen/TOML;
- local organization that does not affect physical meaning;
- read-only checks, drafts, and static verification;
- unfinished design unrelated to the local change the user explicitly requested.

## PGen/TOML Is the Same Case Contract

This is the most important hard boundary of `entity-case`. When modifying one side, the agent must look for whether the other side has a corresponding relationship, but only check the affected parts.

Minimum check rules:

| Modified content | Must check |
|---|---|
| traits | engine, metric, dimension |
| `params.get` | `[setup]` keys, types, and default behavior |
| particle injection | species order, mass, charge, temperature, ppc, and 1-based index |
| fields or source | scales, unit domain, coordinate basis, and engine limitations |
| boundary hook | TOML boundary in every direction |
| custom output/stat | whether it is requested in the TOML and whether names match |
| higher-order feature | TOML algorithm parameters and build options |

`consistent` only means no conflict was found within the checked scope; it does not mean the physical model has been proven correct.

## Optional Artifacts

Artifacts are created as the task requires; not every case must have a complete file set.

### `simulation-plan.md`

Create or update only when:

- designing a new case from a fairly vague idea;
- the task involves multiple interdependent physical or numerical decisions;
- the user wants to save the design to continue next time;
- the existing implementation lacks sufficient design rationale.

The content records only currently useful information: confirmed decisions, current assumptions, to-do items, and success criteria. Unknown parts may be omitted; do not use a large, all-encompassing fixed questionnaire.

### PGen and TOML

These are the most common direct artifacts. Keep the user's existing directory structure; do not migrate to a unified template directory unless the user asks.

### Local Verification Results

For simple tasks, report check results directly in the reply. Only when there are many checks, the results need reuse, or the user asks for a record, write `case-validation.md`. The first version does not introduce a dedicated validation schema.

### `run-manifest.yaml`

Create only when preparing or executing an actual run. Record at least:

- Entity checkout, commit, and executable;
- PGen, TOML, and their hashes;
- launch command, workdir, and resources;
- parent run or checkpoint;
- output, stdout, stderr;
- run status, times, exit code, and scheduler job ID.

Each resume creates a new run record referencing its parent; it does not overwrite the original run.

## References and Tools

The existing `entity-pgen` references continue to serve as the main knowledge base of `entity-case`, loaded by feature:

- normalization;
- PGen skeleton;
- fields;
- particle injection;
- current and force;
- boundaries;
- custom output;
- timestep hooks;
- TOML;
- higher-order methods;
- official PGen index.

The agent should first read the relevant implementation in the current checkout, then use references to supplement with stable rules. When a reference conflicts with the checkout, the checkout wins.

The first version considers only two deterministic tools:

- `check_case_contract.py`: performs reliably automatable local consistency checks on a specified PGen/TOML;
- `run_manifest.py`: creates manifests, computes input hashes, and updates run state.

Do not start by building a complete schema system, a general workflow engine, or a multi-scheduler management layer.

## Boundaries with Other Skills

### `entity-env-build`

`entity-case` provides the current checkout, PGen, and required engine/backend/build features; `entity-env-build` returns the executable and a build record. `entity-case` does not install dependencies or write general build logic.

### `entity-analysis`

`entity-case` delivers the TOML, PGen, run manifest, output location, and existing design goals. `entity-analysis` is responsible for formal diagnosis and physical conclusions, and does not directly modify the case in return.

### `entity-debug`

When the owner is unclear, `entity-debug` does the initial diagnosis. After the problem is confirmed to belong to PGen, TOML, checkpoint parameters, or launch configuration, it is handed back to `entity-case`.

### `entity-core-dev`

Enter only when it is confirmed that the current PGen API cannot fulfill the requirement. `entity-case` should state the missing capability and the extension points already checked, rather than vaguely requesting Entity changes.

## Migrating from `entity-pgen`

The focus of the migration is not adding process, but adding state recognition and run context to the existing PGen capability.

Keep:

- the current feature-organized references;
- hard rules such as normalization, coordinate basis, and unit domain;
- the scenario router and the PGen/TOML self-check;
- the official PGen retrieval entry point.

Adjust:

- `SKILL.md` starts by identifying state and user goal;
- the requirements checklist changes to asking only about what the current modification lacks;
- `simulation-plan.md` changes from a mandatory upfront artifact to an optional continuous design record;
- deliverables are chosen per task, no longer defaulting to a complete case workspace;
- add minimal support for build identity, run, and checkpoint.

Not for now:

- mandatory directory structure;
- a linear phase state machine;
- a fixed seven-step or five-step process;
- a complete validation JSON schema;
- a general remote run platform;
- parameter scans and ensemble orchestration;
- site-specific scheduler rules.

## First-Version Completion Criteria

The first version only needs to prove the following behaviors are reliable:

- the agent can recognize different starting points such as "no case, partial case, existing case, existing run";
- the agent can continue from a design or code left over from last time, rather than re-asking a whole set of questions;
- a local request triggers only local modification and the relevant contract checks;
- key PGen/TOML conflicts can be found;
- when compilation is needed, explicit requirements can be given to `entity-env-build`;
- when preparing a run, executable and input identity can be confirmed and a manifest written;
- resuming does not overwrite the original run;
- problems that do not belong to the case layer are routed to the correct skill.

Verification should cover four real entry points: starting from a one-line idea, modifying an existing PGen, continuing an unfinished design, and running or resuming an existing case. Focus on whether the agent correctly identifies state and controls work scope, not whether it walks through some predetermined process.
