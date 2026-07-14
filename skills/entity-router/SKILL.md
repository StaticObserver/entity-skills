---
name: entity-router
description: Orchestrate end-to-end Entity astrophysical simulations with persistent Case state, gated PGen and build handoffs, immutable run identities, failure recovery, and context-isolated workers. Use when a request spans Entity PGen/TOML design, environment build, simulation launch or restart, workspace recovery, or nt2py-assisted analysis.
---

# Entity Router

Act as the control plane for an Entity simulation. Keep global state in the
Case, execute one gated Action at a time, and delegate domain work to a
Case-bound Worker when sub-agents are available.

## Non-negotiable Rules

- Select an exact Case, checkout, and run; never guess the newest candidate.
- Use `scripts/entity_router_state.py` for every `_case/` mutation. Never edit
  `case.json`, events, Action requests, or Action results by hand.
- Treat files, hashes, logs, processes, and scheduler queries as evidence.
  Chat summaries and Worker claims are not state transitions.
- Keep one active mutating Action per Case.
- Restrict every Worker to the Action Contract read/write roots.
- Never overwrite a historical run or raw output. Changed parameters and
  checkpoint continuation require a new run identity.

Read `references/workspace-layout.md` when locating a real workspace. Read
`references/router-runtime.md` when creating or closing Actions, recovering a
Case, or managing Workers.

## Control Objects

```text
Case -> Workflow -> Action -> Worker
```

- **Case** persists the simulation scope, critical memory, readiness, and
  evidence pointers.
- **Workflow** represents the current user goal and done-when conditions.
- **Action** is the atomic state transition and context-isolation boundary.
- **Worker** executes one domain using the immutable Action request.

The Router retains only control context. Do not load child skill bodies or
long domain references into the Router context.

## Domain Routing

| Action prefix | Execution domain | Worker loads |
|---|---|---|
| `pgen.*` | `entity-pgen` | `../entity-pgen/SKILL.md` |
| `build.*` | `entity-env-build` | `../entity-env-build/SKILL.md` |
| `data.*` | `entity-nt2py` | `../entity-nt2py/SKILL.md` |
| `run.*` | `playbook-run` | matching run/resume playbook only |
| `analysis.*` | `playbook-analysis` | `playbooks/analyze-run.md`; load `entity-nt2py` only as data-access support |
| `failure.triage` | `failure-triage` | relevant evidence only; no speculative skill |

`entity-nt2py` does not own scientific interpretation. Run operations belong
to Router playbooks and do not form an `entity-simulator` skill.

## Standard Loop

1. **Orient**
   - Locate `ENTITY_WORKDIR`, exact checkout, and exact Case.
   - List existing Cases with the state tool before creating a new one.
   - Create a Case only after its identity and user goal are clear.
2. **Recover**
   - Read `case.json`, then refresh fingerprints and dynamic run evidence.
   - Verify the Case control files before choosing an Action.
3. **Decide**
   - Read one matching playbook.
   - Choose only from `workflow.allowed_actions`.
   - Resolve decisions that materially change the physical model or compute
     commitment before starting the Action.
4. **Start**
   - Create an immutable Action request with the current Case revision,
     explicit owner, inputs, write roots, outputs, and acceptance checks.
5. **Dispatch**
   - Reuse a Worker bound to the same `(case_id, execution_domain)`.
   - Otherwise create a fresh Worker without inherited conversation history.
   - Send only the Action request path and the selected skill/playbook path.
6. **Verify**
   - Inspect changed files, logs, hashes, process or scheduler state.
   - Reject outputs outside write roots or unsupported success claims.
7. **Commit**
   - Close the Action with the state tool, recording verified outputs,
     readiness updates, blockers, and the next Action.
8. **Continue or stop**
   - Continue the playbook, suspend safely, or complete the Workflow only when
     every done-when item has evidence.

## Worker Protocol

Bind Workers by `(case_id, execution_domain)`. Reuse them when returning from
PGen to build and back to PGen. Do not repurpose a Worker for another Case.

A Worker must:

- read its Action request before any write;
- read exactly one owner skill or the named playbook fragment;
- stay inside read/write roots and preserve protected paths;
- write only owner artifacts, never `_case/`;
- return status, changed paths, verification evidence, blockers, diagnosis,
  and suggested next owner;
- avoid direct Worker-to-Worker instructions.

Keep an idle Worker isolated on Case switch when capacity allows. Rebuild it
from disk when unavailable, stale, context-heavy, or trapped in an unchanged
failure loop. Runtime Agent IDs are ephemeral and never enter Case state.

If sub-agents are unavailable, execute the Action sequentially in the current
context using the same Contract and gates. This is a degraded isolation mode.

## Failure Routing

- Keep domain-local diagnosis and the smallest repair in the current Worker.
- When evidence changes the owner, close the failed Action and create a new
  Action for that owner.
- Use `failure.triage` only when the cause remains cross-layer or unknown.
- Require a changed fingerprint or explicit reason before retrying.
- Preserve unsupported Entity-core failures and report the missing capability;
  do not invent an unavailable child skill.

## Completion Report

Report the exact Case, checkout, build, and run paths; Workflow and terminal
Action state; artifacts changed; verification performed; unresolved blockers;
and next owner. Keep the report concise because the durable record is on disk.
