---
name: entity-router
description: Orchestrate end-to-end Entity astrophysical simulations with controller-authoritative Case v3 state, multi-site Locators, gated PGen/build/run handoffs, immutable source/build/run identities, failure recovery, and context-isolated workers. Use when a request creates, recovers, or continues a Case; spans PGen, build, run, data, or analysis; changes downstream readiness; or requires managed writes. Bounded standalone domain work and read-only explanation may enter the owner skill directly.
---

# Entity Router

Act as the single control plane for a managed Entity simulation. A Case is a
logical resource graph whose source, build, run, data, and analysis resources
may live at different sites.

Read `references/workspace-layout.md` before orienting a Case and
`references/router-runtime.md` before state/site operations. Load one matching
playbook for the current phase.

## Entry and behavior gate

- Direct task-skill use is allowed only for bounded read-only work or a clearly
  standalone owner-domain edit.
- Use Router for Case creation/recovery, persistent or cross-domain work,
  downstream invalidation, execution-site choice, source transfer, build/run,
  and every write to a registered Case resource without an active owner Action.
- Do not route by a noun such as “PGen” alone. Decide from lifecycle scope,
  persistence, managed locators, and requested effects.
- Before dispatching a mutating Worker, create the matching Action Contract.

## Fast read-only run status

For a bounded “is it running / how far has it progressed” request with an exact
run root plus job ID or PID, use `run.status` before the Standard loop. Execute
`scripts/entity_router_status.py` directly in the current agent. This fast path
does not resume or suspend a Case, create or finish an Action, dispatch a
Worker, or write controller evidence. Its quick profile makes at most one
remote call and returns a compact observation.

If the result recommends `observe_only`, report it and stop. Only enter a
normal `run.monitor` Action when the result recommends
`promote_to_run_monitor`, or when the user explicitly requests durable/full
monitoring.

## Deterministic flow façade (feature gated)

The legacy Standard loop remains the default. When `ENTITY_ROUTER_FLOW_V1=1`
is explicitly present, use `scripts/entity_router_flow.py inspect/check` for
orientation and execute an already confirmed immutable flow request through
`execute`. Deterministic runners never accept caller-provided shell text.

Use `execute --prepare --step N` and `execute --resume --step N` only for a
`model.worker.v1` step. The prepared Worker envelope is an artifact, not Case
state; only a structured result with the exact request hash and outputs that
the controller can reprobe may finish the Action. Use `watch` only for an
already-active `run.monitor` Action. Keep using `entity_router_state.py` as the
sole Case writer in every mode.

## Non-negotiable protocol

- Use `scripts/entity_router_site.py` for site profiles, probes, and source
  materialization. Use `scripts/entity_router_state.py` for all controller Case
  mutations. Never edit controller files by hand.
- Controller state is single-writer and never placed in a source checkout.
- Use structured Locators in JSON and `site_id:/absolute/path` on the CLI.
- Select an exact `case_uid`, source revision/snapshot, build ID, and run ID;
  never guess the newest path.
- Each Case has one editable source authority. PGen writes execute there.
- Dirty/untracked source reaches build/run only as an immutable hashed
  snapshot. Mutable rsync/tar content is never a source identity.
- Remote Workers receive immutable staged requests and may not write controller
  state. The Router reprobes file, Git, scheduler, and data evidence before
  committing success.
- Enforce both site and path in every read/write envelope. Keep one active
  mutating Action per Case.
- Never overwrite historical build/run identities or raw data. Raw data remains
  authoritative at the data site and is fetched selectively. Deletion is allowed
  only through an explicitly authorized `data.purge` Action with an exact manifest,
  protected source/build/dependency roots, and an out-of-target purge receipt.
- For v2 migration cleanup, verify the v3 Case first and use
  `finalize-migration` with explicit authorization; never delete run/data roots.

## Control model

```text
Case -> Workflow -> Action -> Worker
```

The Case stores compact memory, resource locators, immutable identities,
readiness, and evidence. The Worker receives one Action request and one owner
skill/playbook. Long logs and scientific artifacts remain at their owner site.

## Domain routing

| Action prefix | Owner | Execution domain |
|---|---|---|
| `pgen.*` | `entity-pgen` | `entity-pgen` |
| `source.*` | `router` | `playbook-sync` |
| `build.*` | `entity-env-build` | `entity-env-build` |
| `run.*` | `playbook-run` | `playbook-run` |
| `data.*` | `entity-nt2py` | `entity-nt2py` |
| `data.purge` | `router` | `router` |
| `analysis.*` | `playbook-analysis` | `playbook-analysis` |
| `failure.*` | `failure-triage` | `failure-triage` |

`entity-nt2py` owns data access, not scientific judgment. Run and analysis
orchestration remain Router playbooks.

## Standard loop

Use this loop for Actions and persistent lifecycle transitions, not for
`run.status`.

1. **Orient**: list registry Cases; register controller/source/execution sites
   and only the roots needed for the current phase. Determine the one source
   authority and transfer policy.
2. **Recover**: read `case.json`, verify site profiles, and refresh fingerprints
   and scheduler observations. Cached remote observations are not current facts.
3. **Decide**: choose only from `workflow.allowed_actions`; resolve decisions
   that change physics or compute commitment.
4. **Start**: record an immutable request with `execution_site_id`, Locator
   inputs/roots, fingerprints, outputs, and acceptance checks.
5. **Dispatch**: bind the Worker to `(case_uid, execution_domain)` and send only
   the staged request plus its owner skill/playbook.
6. **Verify**: inspect owner artifacts and reprobe the execution site. Reject
   wrong-site, outside-root, stale-revision, or unsupported success claims.
7. **Commit**: close the Action with verified evidence and readiness updates.
8. **Continue**: propagate stale state, start a new immutable identity, suspend
   safely, or complete only when every done-when item is proven.

For destructive storage cleanup, load `playbooks/purge-data.md`. Never reuse an
inspection or analysis Action as a deletion envelope.

## Source and failure rules

- Prefer `git-ref` for formal build/run. Use `snapshot` for dirty/untracked
  authority content, `shared` for verified mappings, and `external` for
  user-managed copies whose revision/hash matches.
- Source authority transfer is its own `source.transfer-authority` Action. Prove
  both endpoints identical before switching; never permit dual editability.
- A source change makes dependent build/run state stale. A build change makes
  unlaunched run state stale. Data changes make dependent analysis stale.
- Keep owner-local failures in the owner. When evidence changes the owner,
  close the Action and create a new one. Use `failure.triage` only while the
  owner is unknown.
- Offline sites block or suspend current work; after recovery, probe again.

## Worker result

Require terminal status, actual changed Locators, verification evidence,
blockers, diagnosis, and suggested next owner. A Worker narrative cannot
advance Case state. If sub-agents are unavailable, execute sequentially under
the same immutable Contract and gates. `run.status` never uses a Worker.

Report the exact Case UID, authority revision, execution sites, build/run IDs,
verified outputs, unresolved blockers, and next owner.
