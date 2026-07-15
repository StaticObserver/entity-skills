# Entity Skills Package 架构 v3

日期：2026-07-14
状态：当前设计与 runtime 基准

## 目标

`entity-skills` 支持跨机器、跨 filesystem 的 Entity simulation：PGen 设计、
精确 source materialization、环境/build、不可变 run、数据访问和分析，同时
保证可恢复、可验证和 owner 隔离。

## 结构

```text
用户
  -> Entity Router（controller single writer）
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

Router 只掌握控制信息。专业源码、长日志、raw data 和分析产物留在 owner
site。Case 是资源图，而非 workspace 目录。详细路径/状态协议见
`workspace-and-state.md`，Action/Worker 协议见 `router.md`。

## Skill 边界

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
