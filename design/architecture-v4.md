# Entity Skills Architecture v4: Shared Control State and a Model-Efficient Entry Point

Date: 2026-07-18
Status: implemented and locally accepted

Acceptance snapshot (2026-07-18):

| Item | Result |
|---|---|
| Shared state | `bh-reconnection` resolved via the shared project binding to a controller-local Case; Case revision 65, sha256, size, and mtime were all unchanged before and after the query |
| Three-client install | All 12 skill projections for Codex, Claude Code, and Kimi Code resolved to bundle `sha256:ea3d59bcac8cb9cfcae46e52d2e809d0ac24cd447cb094e27660142330d301b6` |
| Single-writer contract | Parallel writers were rejected; after an explicit handoff the new Agent could continue; lease expiry did not block recovery |
| Query efficiency | A real project inspect took 1 tool round-trip, 0 remote calls, 0 approvals, 2,281 B of output, and passed the correctness hard gate |
| Regression | All Router/observability (84), PGen (3), and env-build (18) tests passed; Python 3.6 grammar, JSON, skill quick validation, and `git diff --check` passed |

Native Claude/Kimi sessions have been imported into the shared trace for locating context cost; however, the two are not matched-scenario comparisons of the same task, so cross-provider token reduction remains marked `not_assessed`. Real SSH build/run/nt2 staging and the m87 live canary are later gates in the long-term flow plan; they are not substitute evidence for this round's shared-state architecture completeness, and no remote compute was triggered in this round.

## 1. Problem and Goals

Recent `bh-reconnection` practice exposed four coupled problems:

1. Codex, Claude Code, and Kimi Code each installed a full copy of the skills, and versions could drift;
2. the authority boundaries among project source, client-private directories, Router Cases, remote `_tools`, and session logs were not intuitive enough;
3. although Cases were shared, events and Actions lacked Agent/session/bundle provenance;
4. Agents directly drove the `show -> start-action -> SSH -> finish-action` primitives, so even simple queries triggered many model turns and context re-injection.

The goal of v4 is not to remove the Router's safety constraints, but to push them down into deterministic programs:

- all Agents on the same machine discover and read project state from one shared control area;
- control facts live on the Agent's machine by default, so recovery still works when the remote is unavailable;
- the remote only owns execution artifacts and raw data, while the control side only stores Locators, identities, and last-verification evidence;
- every state write is traceable to an Agent run and a skill bundle;
- ordinary queries call a single compact read-only entry point, creating no Action and modifying no Case;
- project source, control state, execution evidence, and run traces each have exactly one authoritative location.

## 2. File Placement and Single Authority

### 2.1 Shared area on the control machine

The default control root is `$ENTITY_ROUTER_HOME` or `~/.entity-router`. It lives on the Agent's machine and belongs to no client:

```text
~/.entity-router/
├── registry.json                 # Case UID -> control root, rebuildable index
├── project-bindings.json         # project root -> Case UID, the sole project-binding fact
├── sites/<site_id>.json          # site/transport/root description
└── cases/<case_uid>-<label>/
    ├── case.json                 # current control snapshot
    ├── events.jsonl              # append-only state events and actor provenance
    ├── actions/<action_id>/
    │   ├── request.json          # immutable Action request and initiating actor
    │   └── result.json           # verification result and closing actor
    ├── history/
    └── evidence/
```

Codex, Claude Code, Kimi Code, and ordinary shells under the same OS user all read this location. Client-private directories must not hold a second set of Cases, project bindings, or readiness state.

`project-bindings.json` stores only the normalized absolute project root and `case_uid`. It does not copy `case.json`; resolution always goes through `registry.json` to find the current control root. When an Agent starts from any subdirectory of a project, it discovers the Case by longest-ancestor matching.

### 2.2 Project Git repository

The project repository holds reviewable, mergeable scientific facts:

```text
<project>/
└── problems/<pgen>/
    ├── pgen.hpp
    ├── <pgen>.toml
    └── docs/design.md
```

The repository does not store mutable Router state, Agent-private memory, client skill copies, or session exports. A PGen has exactly one canonical `docs/design.md`; superseded designs go into an explicit archive and must not sit alongside the current design as two candidate authorities.

Project bindings are also not written into the repository by default, because a Case is a resource local to the control machine; if cross-control-machine migration is ever needed, export a signed/checksummed handoff manifest instead of committing a mutable `case.json`.

### 2.3 Remote execution site

The remote owns:

- content-addressed source snapshots/materializations;
- immutable build/run identity;
- build logs, scheduler receipts, raw data, and analysis artifacts;
- a content-addressed runner cache.

Remote Workers do not write control state. When the control machine cannot reach the remote:

- `case.json`, Action request/result, and historical evidence remain readable;
- old evidence is explicitly labeled as the last observation and is not promoted to current fact;
- `entityctl inspect` returns the local control snapshot;
- only an explicit live probe attempts a remote connection, and failure only affects dynamic fields.

### 2.4 Skills and traces

The shared product directory and run traces use `~/.entity-skills`:

```text
~/.entity-skills/
├── bundles/<bundle-hash>/         # read-only, versioned complete skill bundle
├── current                         # current bundle selector
└── observability/runs/...          # unified cross-client trace
```

The Codex/Claude/Kimi discovery directories should ultimately contain only thin adapters or install projections pointing at the same bundle; development must not happen directly in those directories. Traces only reference Case/Action/evidence and do not become a second set of state.

## 3. Shared Runtime Interface

`entity_router_state.py`, `entity_router_site.py`, and the flow runner remain internal safety primitives. Ordinary Agents use `scripts/entityctl.py`:

```text
entityctl doctor
entityctl bundle install --source-root <entity-skills-repo>/skills
entityctl project bind --project-root <path> --case <uid>
entityctl project resolve --project-root <path>
entityctl inspect [--case <uid> | --project-root <path>]
entityctl run-status [--case <uid> | --project-root <path>] --job-id/--pid ...
```

Contract:

- `inspect` only reads local shared state, `state_mutated=false`, and normal output stays under 4 KiB;
- `run-status` derives the exact site/run root from the Case, then performs at most one remote call;
- queries do not resume/suspend the Case and do not create or complete Actions;
- writes still go through the state tool as single-writer, subject to revision/envelope/identity constraints;
- later `change/build/run` high-level transactions reuse the deterministic flow and do not expose long primitive chains to the model.

## 4. Actor Provenance

Every mutation and Action records:

```json
{
  "run_id": "provider-session-or-run-id",
  "provider": "codex|claude|kimi|...",
  "client": "desktop|cli|...",
  "session_id": "native-session-id-or-empty",
  "model": "model-id-or-empty",
  "bundle_hash": "sha256:...-or-empty"
}
```

Fields come from explicit CLI arguments or the following environment variables:

```text
ENTITY_AGENT_RUN_ID
ENTITY_AGENT_PROVIDER
ENTITY_AGENT_CLIENT
ENTITY_AGENT_SESSION_ID
ENTITY_AGENT_MODEL
ENTITY_SKILLS_BUNDLE_HASH
```

When an older client provides no identity, `run_id=unattributed` is recorded — kept compatible, but attribution must never be forged. Later, `ENTITY_ROUTER_REQUIRE_ACTOR=1` can reject identity-less mutations in production multi-Agent environments.

Provenance is audit information; it stores no hidden reasoning and does not change the grade of scientific evidence.

### 4.1 Workflow writer lease

A managed write transaction may hold a short-term lease of 60–3600 seconds in `control.writer_lease`. The lease records `lease_id`, the full actor, and acquired/expires times; it lives with the Case in the control machine's shared area.

- `entityctl writer acquire/status/handoff/release` is the public entry point;
- while an active lease exists, every Case mutation must match both the actor run ID and the lease ID;
- handoff atomically swaps the holder under the same Case lock/revision and writes an append-only event;
- `entityctl flow execute/watch` must hold a lease; inspect/check/status never take a lease;
- a write transaction must acquire the lease first, then freeze the flow request against the new revision obtained after acquisition; otherwise the revision produced by lease acquisition itself would cause the old request to be rejected by the concurrency gate, as intended;
- after a lease expires it does not keep blocking recovery, and old records remain auditable.

## 5. Model/Program Division of Labor

### Handled by the model

- turning user goals into structured targets and acceptance criteria;
- deciding physics parameters, compute resources, data retention, and anomaly handling;
- performing PGen/analysis work that genuinely requires scientific judgment;
- producing reports at `needs_decision`, new anomalies, and terminal states.

### Handled by the program

- project -> Case discovery and Case compact summaries;
- revision, allowed action, site/path, identity chain, and bundle checks;
- Action start/stage/dispatch/reprobe/finish;
- scheduler/PID polling and duplicate-state suppression;
- actor/trace correlation and result truncation.

`Case -> Workflow -> Action -> Worker` is an internal state model; every Agent is no longer required to restate it step by step and drive it manually in context.

## 6. Optimization Plan and Completion Gates for This Round

### WP1: Shared state and project discovery

Implement `entity_router_project.py`:

- write `~/.entity-router/project-bindings.json` by default;
- support bind/resolve/list/unbind;
- validate the Case UID and project directory on bind;
- resolve with longest-ancestor matching from project subdirectories;
- use file locks and atomic writes so concurrent clients cannot corrupt the registry.

Completion gate: two different processes get the same Case UID from the same project root; no state is written into the project repository.

### WP2: Actor provenance

- add global actor arguments and environment-variable parsing to the state CLI;
- store the actor on all new events;
- Action requests store the initiating actor, results store the closing actor;
- sync templates and contract tests.

Completion gate: tests can precisely recover the attribution of two different Agent runs from `events.jsonl` and request/result.

### WP3: High-level read-only entry points

- `entityctl doctor` reports shared paths, bundle identity, and provenance configuration health;
- `entityctl inspect` outputs a compact Case summary;
- `entityctl run-status` derives the run site/root from the Case and reuses a one-shot status probe;
- all read-only commands explicitly return `state_mutated=false`.

Completion gate: inspect writes no files; run-status makes at most one remote call; normal summaries stay under 4 KiB.

### WP4: Content-addressed publishing, docs, contracts, and validation

- `entityctl bundle install` publishes a content-addressed bundle from the single source;
- `~/.entity-skills/current` atomically selects the current bundle, and the three-client skill directories only hold symlink projections;
- replaced three-client directories go into a timestamped local backup, never silently deleted;
- update SKILL, workspace/runtime references, README, and the runtime file contract;
- add project/entityctl/provenance tests;
- run Router, PGen, env-build, observability, Python compile, and quick validation;
- after validation, sync Codex, Claude Code, and Kimi Code, and check source/install hashes.

Completion gate: all three clients' discovery resolves to the same physical bundle; existing v3 Cases can still be shown/verified, old Actions remain readable, and new fields are backward compatible.

### WP5: Multi-Agent attribution, single-writer coordination, and efficiency hard gates

- add Claude transcript and Kimi multi-agent wire adapters;
- store `agent_run_id/native_session_id/native_agent_id` uniformly on events, aligned with Action actors;
- make the deterministic flow the default transaction entry of `entityctl flow`;
- add the 60–3600 second writer lease, explicit handoff, and public CLI;
- make the efficiency collector check correctness invariants, absolute gates, relative reduction, and native tokens together;
- add a real controller-local query canary and provider session baselines.

Completion gate: parallel writers are rejected, and a new writer can continue after handoff; a simple state query completes in one turn, with no remote call, no Case change, and output under 4 KiB; tokens stay `not_assessed` when no platform-native usage data exists.

## 7. Follow-up Migration Plan

After this round, continue in the following order, without quietly expanding the state model in this round:

1. Continuously calibrate the efficiency gates with real tasks: 1 tool call / 1 remote call for status, 1 tool call for ordinary parameter queries, and no more than 4 model wake-ups for a full build/run by default.

These follow-up capabilities may only reference the shared state and provenance established in this round; they must not create new project state files.
