# Entity Router Restructuring Migration Plan: plan/apply → Deterministic Primitives

Date: 2026-07-23
Status: P1–P4 completed (2f333ef, b7330e6, and follow-up commits); P5 field validation
pending
Basis: `design/router-case-centric-restructure-2026-07-23.md` (target architecture)
Prerequisite: P1 (status dashboard-ification) completed

This document expands P2–P5 from §6 of the design draft into an executable migration
plan, based on a full inventory of the current implementation (executor 823 lines,
operation 871 lines, planner 840 lines, entityctl 859 lines, plus tests and docs).

## 1. Inventory Conclusions

### 1.1 Parts Reusable Wholesale (untouched or thin-wrapped)

| Part | Location | Serves which primitive |
|---|---|---|
| `render_sbatch` / `render_direct` / `_validate_run_spec` / `_walltime_seconds` | executor.py:178-277, pure functions | generate run script |
| `source_manifest` | common.py:237 | generate source snapshot manifest |
| `make_manifest` / `snapshot_archive` / `snapshot_install` / `verify` (written but **never wired in**) | remote.py, whole file | generate source snapshot |
| Data inventory walk+hash+manifest core | executor.py:709-725 | record data |
| `file_evidence` / `sha256_file` | executor.py:116-126 / common.py:112 | probe hashes |
| `_slurm_live_status` / `_direct_live_status` / `_direct_foreign_scan` | operation.py:717-868, input only (profile, scheduler, result), no store dependency | probe live run |
| `validate_site_profile` / `run_on_site` / `parse_locator` etc. | common.py | all primitives |
| Site policy defaults (`_slurm_site_policy` / `_direct_site_policy`) | planner.py:269-340 | generate run script |
| decisions confirmation gate (`_simulation_confirmation`), checkpoint gate (`require_verified_checkpoint`) | planner.py:407-434, 608-627 | preconditions of record primitives |
| `ExecutorClient` (content-addressed deployment + local/SSH dispatch) | operation.py:71-192 | primitives executed remotely |
| Receipt three-state mechanism (intent→effect→verified + recovery matching) | executor.py:152-175, 461-519, 592-615 | internal to submit/delete-class side effects |

### 1.2 Bound to plan, Needing Disassembly (only 4 places)

1. The Popen section of `_direct_launch` (executor.py:649-660): the comment is derived
   from `operation_id+plan_hash`. Disassembly: extract
   `launch_detached(run_root, script, log, comment)`, with the comment now derived from
   case_uid+run_id.
2. `receipt_base` / `matching_receipt` (executor.py:152-175): identity fields bound to
   operation/plan_hash/step. Disassembly: switch the identity key to `(case_uid,
   run_id, action)`.
3. The `_prepare` assembly section (executor.py:418-438): payload comes from the plan.
   Disassembly: parameterize as `(run_root, input_path, manifest, script)`.
4. `_identity_projection` and the apply write-back section (operation.py:449-606): the
   projection rules themselves are simple; copy the per-kind mapping and rewrite it as
   each record primitive's own ledger-posting logic.

### 1.3 Deleted Wholesale with the Protocol

- planner.py's GoalSpec validation (:25-146), plan derivation/hash/schema (:459-472,
  774-839) — planner.py ends up with only the helper functions kept in 1.1; recommended
  to move them into a new module `entity_router_facts.py` and then delete the whole
  file;
- operation.py's `apply_plan` engine and claim heartbeat;
- templates/goal.schema.json, templates/operation-plan.schema.json;
- entityctl's `plan` / `apply` / `operation cancel` subcommands.

## 2. Primitive Command Surface (P2 Target Form)

```text
read      entityctl status [--live] [--json]          # done (P1)
          entityctl show --project-root X             # Case fact details (JSON)
generate  entityctl render-run --project-root X --toml input.toml --site m87 \
            [--gpus 4 --walltime 04:00:00]            # render run script + derive run_root
          entityctl snapshot-source --project-root X  # wire in remote.py
record    entityctl record build --project-root X --site m87 \
            --checkpoint deps.local.json --executable /abs/entity.xc
          entityctl record run-prepare --project-root X --toml input.toml --site m87
          entityctl record run-launch --run-id R [--adopt-job 42 | --adopt-pid N]
          entityctl record run-exit  --run-id R       # probe exit file/sacct, post terminal state
          entityctl record data --run-id R            # inventory → manifest + identity
probe     status --live (existing) / probing built into record run-exit
```

Key points:

- **All write gates are embedded in the record primitives**: `record build` first
  verifies the checkpoint's `compatibility: pass` and the decisions record, then probes
  the executable's existence and hash; `record run-prepare` first runs
  `_simulation_confirmation` (parameter card confirmation); `record run-launch` goes
  through receipts to prevent duplicate submission; `--adopt-*` adopts jobs the agent
  submitted itself (posted to the ledger only after probing squeue/`kill -0` to
  verify). The agent has no entry point that "bypasses verification and writes state
  directly".
- run_id derivation (content-addressed), run_root paths, and site policy defaults move
  from planner into `entity_router_facts.py`, shared by render/record.
- Build script generation is not in the router: that is the job of entity-env-build's
  `entity-build.sh`; the router only does `record build`. The "generate build script"
  item in §3.3 of the design draft is corrected accordingly.

## 3. Phase Plan

### P2a: Extract the Fact-Derivation Layer (pure refactor, low risk)

- Create `scripts/entity_router_facts.py`: move in from planner.py `_resolve_case`,
  `_simulation_confirmation`, `require_verified_checkpoint`, site policy defaults,
  run_root/run_id derivation, `_source_identity`, `_git_revision`, `_resolve_input`,
  `_current_build_executable`.
- planner/operation/dashboard switch to importing from facts; behavior unchanged.
- Completion gate: full test suite green, no behavior change.

### P2b: Primitive Commands Go Live (coexist with plan/apply, purely additive)

- Implement `show`, `render-run`, `snapshot-source`, `record build/run-prepare/
  run-launch/run-exit/data` one by one; reuse the 1.1 parts, disassemble the 4 places
  in 1.2.
- Record ledger posting writes identities/current directly (following the mapping of
  `_identity_projection`), bypassing the operations/steps tables.
- Each primitive gets new tests (reusing the fake slurm/direct fixtures); the plan/apply
  legacy tests are untouched in this phase.
- The dashboard deriver's wording switches to primitive names ("apply the same plan" →
  "re-execute the failed record"; "inventory with a data Goal" → "record data").
- Completion gate: the same scenario produces identical results via the primitive path
  and via the plan/apply path; full test suite green.

### P2c: Retire plan/apply (deletion change, done in one concentrated pass)

- Delete: entityctl's plan/apply/operation cancel commands, planner.py's protocol part
  (helper functions already moved out in P2a, delete the whole file), operation.py's
  apply engine, the goal/plan schemas.
- Must change in sync (hard dependencies found by exploration):
  - `tools/skill_observability/adapters/claude_phases.py:56` (the run-phase regex
    contains `entityctl\b.*\b(plan|apply)\b`) and `claude_activities.py:66` (job-submit
    regex likewise) — rewrite to match record/run-launch;
  - `tools/skill_observability/evidence.py:254-310`
    `validate_router_operation` binds to the plan envelope — change to validate the
    Case facts after record ledger posting (or retire that validation; decision point
    in §5);
  - the plan fixtures in `tests/test_skill_observability.py:279,968-1004` and
    `test_skill_observability_phases.py:88,279`;
  - `evals/user-needs/needs/U4-interrupted-apply/` (the whole case revolves around
    interrupting apply) — rewrite to interrupt record run-launch, or keep the verify
    logic per receipt semantics;
  - wording such as "plan gate" at `skills/entity-pgen/SKILL.md:82` and elsewhere, and
    the "Router plan gate" phrasing in the `pgen_preflight.py` docstring.
- Test matrix (test_router_v5.py, 68 methods): about 35 deleted with the protocol
  (plan hash, reapply recovery, claim, cancel, etc.), about 15 rewritten using
  primitives to build fixtures (live status series, site policy, confirmation gates,
  direct backend end-to-end), about 18 untouched (site add/discover, doctor,
  submission, executor allowlist). test_router_contracts.py updates the entry-point
  list and goal/plan schema assertions; purge and dashboard tests untouched.
- Completion gate: full test suite green; `entityctl plan/apply` returns unknown
  command; grep the whole repo for no residual GoalSpec references (except the
  design/legacy archives).

### P3: Store Slimming and Gate Deletion

- The operations/steps tables lose their writers with P2c; bump `STORE_SCHEMA_VERSION`
  to 2, and provide a migration via `store migrate`: keep
  sites/cases/projects/identities/events, archive-export then delete operations/steps
  (the landing spot of open question 2: old-data readability is guaranteed by the
  export file).
- Delete the claim/lease mechanism (claim_operation/renew/release/heartbeat):
  concurrency degrades to a `BEGIN IMMEDIATE` file lock (already in transaction).
- actor is kept as a passive audit field on events.
- Completion gate: dashboard/status work normally after migrating an old router.db;
  tests green.

### P4: SKILL.md Rewrite and Playbooks

- Per design draft §3.6: thin SKILL + six playbooks; rewrite the Step/Apply paragraphs
  of references/router-runtime.md into primitive internal mechanisms;
  workspace-layout.md is kept.
- Sync the router-related phrasing in entity-pgen (:3, :23-24, :40, :65, :69, :82) and
  entity-env-build (:9, :154); entity-nt2py needs no changes.
- Completion gate: contracts tests green after update; quick validation of all four
  skills passes.

### P5: Field Validation

- Rerun the S1/S2 same scenarios on m87; comparison metrics: record primitive adoption
  rate, status first-read rate, total token consumption; the adoption measurement rules
  were synced in P2c, so no false positives.

## 4. Risks and Ordering Notes

- **Hard ordering dependencies**: P2a → P2b → P2c → P3; P4 can run in parallel with
  P3, P5 last. P2b keeps coexistence so that deletion is concentrated in P2c in a
  single pass, keeping the repo usable at every intermediate point.
- **The largest change surface is P2c**: about 35 test deletions + the
  observability/evidence tools + evals U4. Recommended to make P2c its own commit for
  easy rollback.
- **SSH path**: record-class primitives reuse ExecutorClient's content-addressed
  deployment when executing remotely; m87 (ssh + direct) is currently the only real
  validation environment, and P2b's run-launch must be smoke-tested once on m87 before
  entering P2c.
- **remote.py wired in for the first time**: the snapshot tools were written but never
  called by production; when P2b wires in `snapshot-source`, treat it as new code (add
  tests).

## 5. Decision Points to Settle Before Migration

1. `evidence.py validate_router_operation`: change to validate record-posted facts, or
   retire it with the plan protocol (observability no longer does operation-level
   validation)? Leaning toward the latter — the validation responsibility already lives
   inside the record primitives.
2. `--adopt-*` adoption of external jobs: do it in P2b, or wait until a real scenario
   needs it? Leaning toward P2b — in S1/S2 the agents all ran things bypassing the
   router, and adoption is the only way to bring such faits accomplis into the ledger.
3. The U4-interrupted-apply case: rewrite as interrupting `record run-launch` (receipt
   recovery semantics unchanged), or retire it outright?
4. In the store schema v2 migration, are operations/steps exported for archiving or
   dropped directly?
