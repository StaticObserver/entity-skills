---
name: entity-router
description: Plan, apply, recover, and inspect managed Entity simulation operations through one GoalSpec-driven control plane. Use for persistent or cross-site simulation work, run submission, Case migration/recovery, downstream identity changes, or any managed lifecycle effect. Bounded read-only questions and standalone owner-skill edits may enter the owner skill directly.
---

# Entity Router

Entity Router turns one user goal into one verified Operation. Keep the public
model small:

```text
Project → Goal → Operation → Evidence
```

The controller derives Case/Operation IDs, hashes, Locators, paths, bindings,
claims, Step order, and recovery state. Do not ask the user to provide or manage
those fields.

## Entry boundary

Use Router when work is persistent, crosses PGen/build/run/data/analysis, selects
an execution Site, changes an immutable identity, or writes a managed Case
resource. Enter an owner skill directly only for a bounded read-only task or a
clearly standalone edit with no managed lifecycle effect.

Read `references/workspace-layout.md` only when Site/root ownership is unclear.
Read `references/router-runtime.md` only for internal debugging.

## Public interface

Normal work uses only:

```bash
python3 scripts/entityctl.py plan \
  --project-root <project> --goal <goal.json> --output <plan.json>

python3 scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  apply --plan <plan.json>

python3 scripts/entityctl.py status --project-root <project> [--live]
```

Administrative commands are `doctor`, `install`, `site add/list/discover`,
`operation cancel <id>`, `store migrate`, `submission create/verify`, and
`export`. Use `site discover` to enumerate legal Slurm partitions/QoS before
writing site policy. Use `operation cancel` only to abandon an active
Operation and release the Case; a failed Apply already releases the Case, and
re-applying the same Plan resumes it. `submission create` recomputes all
fingerprints from the final artifacts; `submission verify` fails on any later
drift.

## GoalSpec

GoalSpec contains only user semantics. The executable Goal kinds are `run`,
`build`, and `data`:

```json
{
  "schema_version": 1,
  "kind": "run",
  "input": "input.toml",
  "site": "gpu-site",
  "compute": {
    "gpus": 4,
    "walltime": "04:00:00",
    "precision": "double"
  }
}
```

A `run` Goal plans only after the simulation parameters are confirmed: the
pgen skill's `pgen_preflight.py confirm <input> --by <actor>` writes
`<input>.decisions.json`, and planning fails with `needs_decision` when the
record is missing or the TOML changed afterwards. Show the parameter card to
the user before confirming.

```json
{"schema_version": 1, "kind": "build", "site": "gpu-site",
 "checkpoint": "/abs/entity-deps.local.json", "executable": "entity.xc"}
```

A `build` Goal registers a verified env-build checkpoint into the identity
chain; the checkpoint must have `compatibility: pass` and a confirmed
`decisions.parameters` record. Once registered, later `run` Goals may omit
`executable`.

```json
{"schema_version": 1, "kind": "data", "run": "current"}
```

A `data` Goal inventories a run's outputs into a hashed manifest and advances
the data identity. `analysis` is not a Goal yet; it stays with entity-nt2py.

`executable` is optional when the Case has a verified current build identity.
Site policy supplies safe defaults such as nodes, tasks, CPUs per GPU,
partition, and QoS. Ask the user only when physics, resource commitment,
deletion, or genuine ambiguity remains. Never put ID, hash, Locator, binding,
owner/domain, lease, shell, command, or generated script fields in GoalSpec.

## Operating loop

1. Run `plan`. It is read-only apart from writing the requested plan artifact.
2. If it returns `needs_decision`, ask only the listed semantic questions and
   regenerate the Plan.
3. Show the compact Plan summary when resource commitment matters.
4. Run `apply` once. It internally claims the Operation, stages exact payloads,
   executes allowlisted Steps, verifies owner-site receipts, and commits facts
   transactionally.
5. If Apply is interrupted or reports a retryable anomaly, run `apply` again on
   the same Plan. There is no separate recover command.
6. Use `status` for cached controller facts. Add `--live` only when a current
   scheduler observation is needed; it makes at most one remote call.

Do not create a second Plan merely because Apply was interrupted. Create a new
Plan only when the Goal, source content, Site profile, input, executable, or
resource decision changed.

## Authority and verification

- `router.db` is the sole structured controller authority.
- Source, build, run, raw data, and analysis artifacts remain authoritative at
  their owner Sites; the controller stores identities and evidence references.
- One Case has one editable source authority.
- The identity chain `source → build → run → data → analysis` must remain intact.
- Site and absolute path jointly identify a resource.
- Local and SSH execution use the same immutable StepSpec and the same
  content-addressed executor.
- The executor accepts structured allowlisted requests, never caller shell text.
- External effects are preceded by an intent receipt and are never blindly
  replayed. Controller state advances only after an independent receipt/output
  verification.
- Worker prose cannot advance state.
- Default status is controller-local and never writes state.

## Owner skills

For PGen and scientific analysis use **自由探索，严格收束**: give the owner skill
the semantic goal, exact input identities, workspace/root envelope, protected
paths, and acceptance criteria. Let it choose its internal method. Accept only
structured changed/output Locators, then let Router re-probe and commit the
evidence.

`entity-pgen` owns PGen/TOML/design work, `entity-env-build` owns dependency and
build work, and `entity-nt2py` owns data access/inspection. Router owns lifecycle
ordering and authority transitions, not their domain reasoning.

## Destructive work

Raw-data deletion always requires explicit user authorization, an exact
manifest, protected source/build/dependency roots, and an out-of-target receipt.
Never infer deletion authority from a broad request and never use a run or
analysis Operation as a deletion envelope.

## Reporting

Report the Goal outcome, Operation status, exact source/build/run identities,
execution Site, verified outputs/effects, unresolved decision or anomaly, and
whether status is cached or live. Internal claims, Step mechanics, and legacy
Case fields are diagnostic details, not normal user-facing work.
