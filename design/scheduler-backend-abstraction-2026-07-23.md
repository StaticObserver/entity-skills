# Scheduler Backend Abstraction Design (2026-07-23)

Status: design pending review. Motivating evidence: `evals/e2e-neutral-streaming/findings-2026-07-23.md`
(round m87: on a scheduler=none site the router main path was never entered; the agent ran bare, bypassing the control plane).

## 1. Problem Statement

The Router's abstract skeleton (GoalSpec semantic layer, the `scheduler.kind`
enum in the Site profile, Locator, Step whitelist, intent receipts/recovery) is
system-agnostic; but **the run lifecycle has only a single Slurm implementation,
and it has not been consolidated behind a backend interface**. Slurm calls are
scattered across four files:

| Location | Coupling point |
|---|---|
| `entity_router_planner.py:434` | `run Goal currently requires a Slurm Site`, plan hard-rejects |
| `entity_router_planner.py:284-295` | policy enforces `default_partition`/`default_submit_user` |
| `entity_router_executor.py:178-216` | `render_sbatch`: the submit script for `run.prepare.v2` is an sbatch script |
| `entity_router_executor.py:219-253` | preflight = `sbatch --test-only` |
| `entity_router_executor.py:337-439` | launch = `sbatch --parsable`; recovery matches comment via `squeue`/`sacct` |
| `entity_router_operation.py:615-731` | `--live` and all three divergence classes rely on `squeue`/`sacct` |
| `entityctl.py:394-427` | `site discover` = `sacctmgr list qos` |

The essence: **"the identity of a run" is equated with the Slurm job_id**, and
the unified interface for the backend operations
`validate_policy / render / preflight / submit / probe / history /
scan_foreign / recover_match` is missing.

## 2. Design Principles

1. **GoalSpec is untouched.** `compute` (gpus/walltime/precision) is user
   semantics; partition/qos were never Goal fields — the abstraction gap is not
   at this layer.
2. **Receipt and recovery semantics are untouched.** `pending → intent_written →
   effect_observed → verified → committed`, replay-based recovery of the same
   Plan, intent-first — all preserved.
3. **Backend selection is baked into the Plan; the executor does not read the
   Site profile.** The envelope currently does not contain the profile (the
   executor may be pushed to a remote host for standalone execution); the
   planner generates a backend-specific request from `profile.scheduler.kind`,
   and the executor dispatches on the `scheduler` field in the request —
   preserving the executor's one-way dependency.
4. **Byte-for-byte identical Slurm behavior** is the acceptance criterion for
   phase one; existing receipts/plans need no migration.
5. Do not write implementations for `pbs`/`custom` (the enum values are kept,
   with a `PlanError` giving guidance); this phase only adds `direct`.

## 3. Backend Interface Surface

Logical interface (dispatched on `scheduler.kind`; not a public API — implement
it first as one dispatch table per file plus a set of functions per backend, to
avoid over-engineering):

```text
validate_policy(profile)          → needs_decision question list when policy is missing
render_launch(run_spec, context)  → submit payload text (sbatch script | run.sh)
preflight(request)                → pre-submit acceptance (sbatch --test-only | executability check)
submit(request)                   → effect_identity (see below)
probe(identity)                   → RUNNING | PENDING | <terminal> | NOT_FOUND
history(identity, comment)        → terminal-state fallback query (sacct | exit-code file)
scan_foreign(run_root, identity)  → out-of-band job scan (squeue %Z | /proc cwd scan)
recover_match(request, comment)   → claim an existing effect after interruption (adopt only on unique match)
```

**effect_identity is already an open structure** (existing receipts already carry
`{"scheduler": "slurm", "job_id": ..., "comment": ...}`); the direct backend
extends it to:

```json
{"scheduler": "direct", "pid": 418795, "pgid": 418795,
 "run_root": "...", "log": "<run_root>/run.log",
 "exit_file": "<run_root>/.entity-exit-code", "comment": "entity-router:..."}
```

Old receipts lack these keys; the read path already accesses by key name, so no
migration is needed.

## 4. direct Backend Semantics (scheduler.kind == "none")

- **prepare**: render `run.sh` (`set -eu`; `timeout <walltime> exec <executable>
  -input input.toml`; exit code written to `.entity-exit-code`). The run-manifest
  is exactly the same as on the Slurm path.
- **preflight**: the executable exists and is executable, run_root is writable,
  and (when GPUs are required) `nvidia-smi` is available. No resource-availability
  guarantee — scheduler-less sites have no such concept.
- **launch**: `setsid nohup bash run.sh >> run.log 2>&1 &`, record pid/pgid.
  On recovery, scan `/proc/*/cmdline`+cwd by comment and claim a unique match;
  multiple matches likewise report a terminal anomaly (same semantics as Slurm).
- **probe**: `kill -0 <pgid>` + exit_file existence → RUNNING / terminal state /
  NOT_FOUND.
- **degraded divergence semantics**: `job_gone`/`state_mismatch` are fully
  supported; `untracked_job` relies on a /proc scan of entity process cwd,
  **unknown is allowed** (scans are unreliable across permission/container
  boundaries), and unknown does not count as fail — consistent with how the
  evaluation suite treats known boundaries.
- **walltime is enforced by `timeout`**; on timeout it sends SIGTERM, and exit
  code 124 is written to exit_file.

## 5. Affected Files and Change Size (estimate)

| File | Change | Size |
|---|---|---|
| `entity_router_common.py` | profile validation dispatched by kind (slurm keeps existing requirements) | small |
| `entity_router_planner.py` | remove the :434 hard reject; `_site_policy` requires fields per backend; for direct, switch step requests to backend fields | medium |
| `entity_router_executor.py` | `render_sbatch`/`_preflight`/`_launch` dispatched on request.scheduler; add direct render/submit/claim | medium-large |
| `entity_router_operation.py` | `status --live`/`_reconcile_job` dispatched per backend; direct probe/exit_file determination | medium |
| `entityctl.py` | `site discover`: for none sites probe GPU/execution environment (nvidia-smi, writable root) instead of sacctmgr | small-medium |
| `tests/test_router_v5.py` etc. | add local + scheduler=none end-to-end: plan→apply→status full path testable on a single machine (the direct backend's biggest testing dividend) | medium |
| SKILL.md / router-runtime.md | run Goal no longer says "requires a Slurm Site"; one paragraph per backend semantics | small |

`entity_router_remote.py` and the store layer have not been read in detail, so
sizes are estimates; remote only moves envelopes and is expected to be
unaffected.

## 6. One Explicit Design Decision: Step kind Is Not Bumped

The kind names `run.prepare.v2`/`run.launch.v2` stay unchanged; the request's
internal fields differ per backend (the planner side already binds immutable
content via plan_hash). Rationale: kind expresses the "lifecycle phase", not the
"submission mechanism"; bumping the version would pollute the whitelist and old
plans could not be cross-read. The cost is that the executor validation logic
branches on `request.scheduler` — acceptable, since the dispatch table has to
land in the executor anyway.

## 7. Phasing

- **Phase A (pure refactor)**: consolidate the four Slurm call sites behind the
  dispatch table; Slurm behavior byte-for-byte identical; all existing tests
  green. Independently releasable.
- **Phase B (direct backend)**: planner/executor/operation wire up direct;
  local scheduler=none end-to-end tests; re-run the m87 scenario to verify the
  router main path can be entered.
- **Phase C (discovery and observation)**: the none branch of `site discover`,
  the unknown semantics of direct divergence, SKILL.md updates.

Each phase is independently releasable (0.6.0 / 0.7.0 / 0.7.x), not bundled.

## 8. Explicitly Out of Scope

- No pbs/custom implementation; no execution-mechanism fields added to GoalSpec;
  no major-version change to the receipt/identity-chain schema; no resource
  mutual exclusion for the direct backend (GPU contention on a single machine is
  beyond the control plane's remit — divergence reporting is the boundary).
