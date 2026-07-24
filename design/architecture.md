# Entity Skills Package Architecture v3

Date: 2026-07-14
Status: current design and runtime baseline

## Goals

`entity-skills` supports cross-machine, cross-filesystem Entity simulations: PGen
design, exact source materialization, environment/build, immutable runs, data
access, and analysis, while guaranteeing recoverability, verifiability, and owner
isolation.

## Structure

```text
User
  -> Entity Router (controller single writer)
       -> site profiles + Locator probes
       -> Case v3 / Workflow / Action v2
       -> immutable staged Worker request
            -> entity-pgen at source authority
            -> entity-env-build at build site
            -> playbook-run at run site
            -> entity-nt2py / analysis near data
       -> controller-side evidence verification
       -> state transition and stale propagation
```

The Router only holds control information. Specialized source code, long logs,
raw data, and analysis artifacts stay at the owner site. A Case is a resource
graph, not a workspace directory. See `workspace-and-state.md` for the detailed
path/state protocol, and `router.md` for the Action/Worker protocol.

## Skill Boundaries

| Skill/domain | Owns |
|---|---|
| `entity-router` | Case lifecycle, sites, source transfer, Actions, run/analysis orchestration |
| `entity-pgen` | authority-site PGen, matching TOML, `docs/design.md` |
| `entity-env-build` | build-site requirements, dependencies, env, compile, build evidence |
| `entity-nt2py` | read-only data access, inventory, selection, plots, export |

Direct skill use is decided by behavioral scope rather than keywords. Bounded
explanation/review and truly standalone domain edits can bypass Router. Case
creation/recovery, cross-domain work, managed writes, source/build/run identity,
or downstream invalidation must use Router.

## Source and identities

Every Case has one editable source authority and zero or more verified replicas.
Formal builds prefer exact Git commits; dirty/untracked work uses immutable
content-hashed snapshots. Shared/user-managed replicas require matching
revision/hash evidence. Authority transfer is explicit and atomic.

Build and run IDs are immutable. Build references SourceRevision; run references
build ID. Raw data remains at the data site by default; analysis runs near data.

## Readiness and failure

Readiness dimensions are `orientation/pgen/source/build/run/data/analysis`.
Each positive status needs current Evidence. Source changes invalidate dependent
build/run; build changes invalidate prepared runs; data changes invalidate
analysis. Offline remote facts become unknown/blocked until reprobed.

Owner-local failures remain with the owner. Cross-layer/unknown failures use a
short `failure.triage` Action. Retry requires changed evidence or an explicit
reason. Entity core changes are outside current skill ownership.

## Runtime files

Reusable runtime code stays inside each `skills/<name>/`. Package design and
historical reviews remain under `design/`/`legacy/` and are not loaded by
runtime skills. Current Router code is Python 3.6-compatible for remote probe
and snapshot helpers; controller tests simulate multiple sites with independent
temporary roots and cover migration, envelopes, revision drift, and immutable
materialization.
