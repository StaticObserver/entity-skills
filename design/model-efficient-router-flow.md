# Entity Router Model-Efficient Execution Flow

Date: 2026-07-17
Status: local core path, default public entry, and multi-provider observability completed; the explicitly authorized m87 live canary remains to be executed

Implementation snapshot (2026-07-17): the local runtime, contracts, and replay tests for
WP0–WP5 are landed; the local Slurm fake transport has verified launch recovery/watch;
the Linux `/proc` PID launcher implements the "atomic PID record first, then exec"
recovery protocol, but the current macOS CI can only verify its safe rejection gate.
Real SSH runner staging and the m87 canary are not yet complete.
`entityctl flow` has become the default managed-transaction entry point; the legacy
low-level commands are reserved for recovery only. Claude/Kimi native usage is now
readable; matched-scenario token reduction stays `not_assessed` until the live canary
and cannot be replaced by character counts or sessions from different tasks.

| Work package | Current status | Remaining gate |
|---|---|---|
| WP0 contracts/identity | completed | none |
| WP1 inspect/check | completed | none |
| WP2 deterministic execute | local completed | SSH build runner staging |
| WP3 launch/watch | local Slurm + Linux PID implemented | SSH live recovery |
| WP4 data/model Worker | local completed | SSH nt2/Worker staging |
| WP5 eval/default entry | query canary + native baselines completed | m87 matched-scenario canary |

## 1. Goals and Boundaries

This proposal keeps Router v3's `Case -> Workflow -> Action -> Worker`, controller
single-writer, immutable source/build/run identity, site/path envelope, and evidence
gates, and only adds a deterministic façade that moves state compression, fixed Action
execution, recovery, and polling out of the model loop.

Goals:

- reduce model/tool roundtrips by at least 60% relative to baseline;
- the normal build/run/data path does not wake the model when intermediate Actions succeed;
- unchanged polling during a run does not enter the model context;
- the Case summary and the normal terminal result are each no more than 4 KiB;
- failure summaries are no more than 8 KiB;
- never inject full Cases, complete logs, the full evidence set, or raw data inventories into the model by default;
- no efficiency improvement may weaken revision, identity, site/path, evidence, or recovery semantics.

Out of scope for this proposal:

- no changes to the scientific/execution semantics of Entity, nt2py, or the scheduler;
- the façade must not directly edit `case.json`, Action request/result, or Case events;
- the Router must not cache or forge the host platform's permission approvals;
- free-text `goal/done_when` must not be parsed into physical facts;
- no automatic repair of unclassified anomalies, no automatic acceptance of compatibility warnings;
- no second mutable workflow state machine.

The legacy `bh-reconnection` pipeline recorded 73 command invocations, 8 waits, and 39
approval reviews. That data serves only as a historical baseline; before entering
evaluation, the raw observations, statistical methodology, and tool versions must be
frozen into `evals/router-flow/baseline.json` — this document's numbers alone are not
a sufficient citation.

## 2. Unbreakable Control Principles

1. All Case mutations are still performed by `entity_router_state.py` under the Case
   lock; the façade may only call its public subcommands.
2. `entity_router_site.py` continues to own site profiles, probing, and source
   materialization; owner runners do not interpret site configuration on their own.
3. At most one active mutating Action per Case at any time. Steps in a flow bundle are
   strictly serial; the next step may only start after the previous one has completed
   and been verified.
4. Every Action still has an independent request/result, owner, execution domain,
   site/path envelope, and controller revision; a bundle must not merge or skip Action
   boundaries.
5. A flow request is an immutable execution plan and records no runtime progress. On
   recovery, progress is derived only from the Case revision, Action request/result,
   and remote receipts.
6. Workers may only write to the Action envelope; the controller Case root is always a
   protected path.
7. `run.status` keeps its existing one-shot read-only fast path. Persistent polling
   must use the `run.monitor` Action.
8. `data.purge` does not enter ordinary flow bundles; it continues to require an
   independent Action and explicit business authorization.

## 3. Explicit Division of Labor Between Model and Program

### 3.1 Must be handled by the model

- translating the user goal into a structured `workflow.target` and success criteria;
- deciding PGen/physics parameters, build configuration, compute resources, data retention, and authority transfer;
- executing `pgen.*` and `analysis.*` Actions that require scientific judgment;
- handling first-time `needs_decision`, `anomaly`, or unknown-owner failures;
- forming the scientific interpretation and final report.

### 3.2 Must be handled by the deterministic program

- Case candidate discovery, ambiguity reporting, and compact summaries;
- schema, revision, allowed action, owner/domain, site/path, and identity chain checks;
- fully confirmed source/build/run/data Actions;
- Action start, staging, runner dispatch, reprobe, and finish;
- scheduler/PID polling, duplicate-status suppression, and terminal Action closure;
- hash, byte count, call count, and wall-time statistics for request/result/log.

### 3.3 Definition of a model wakeup

A `model_wakeup` occurs when the façade returns an event that must be handled by the
controller or owner model. The reason enumeration is fixed:

- `user_goal`: a new goal or a change of scope;
- `owner_model_required`: entering `pgen.*` or scientific `analysis.*`;
- `needs_decision`: a choice is missing that would change physics, resources, or data policy;
- `anomaly`: a first-occurrence anomaly or one whose evidence fingerprint has changed;
- `workflow_terminal`: the entire Workflow has reached complete/blocked;
- `user_requested_report`: the user explicitly requested an explanation.

A deterministic Action's `completed` is not a model wakeup event. A repeated identical
anomaly is returned only the first time; subsequent occurrences with the same
`issue_code + evidence_fingerprint` are suppressed until the evidence changes. This
lets the end-to-end pipeline preserve each Action's independence while meeting the
goal of no more than 6 model wakeups.

## 4. New Runtime Files

All runnable files remain under `skills/entity-router/`:

```text
skills/entity-router/
├── scripts/
│   ├── entity_router_flow.py
│   ├── entity_router_flow_common.py
│   └── entity_router_flow_runners.py
└── templates/
    ├── flow-request.schema.json
    ├── flow-result.schema.json
    ├── flow-check.schema.json
    ├── worker-envelope.schema.json
    └── dispatch-receipt.schema.json
```

Constraints:

- must run on Python 3.6.8 with no third-party runtime dependencies;
- runners use an explicit mapping table — no dynamic import, no `eval`, no caller-supplied shell strings;
- JSON canonicalization is fixed to UTF-8, sorted keys, compact separators, and no NaN;
- all compact outputs are measured in actual UTF-8 bytes after redaction;
- on limit overflow, the full artifact is saved and stdout returns only the Locator, sha256, size, and a tail excerpt.

## 5. Incremental State Contract for Case v3

This proposal does not bump `case.json.schema_version=3`; it only adds optional fields.
Legacy Cases can still `show/verify/status`; backfill is only required when entering
the flow façade. All backfill goes through the new state CLI mutations — the façade
never writes files directly.

### 5.1 Structured Workflow target

Added under `workflow`:

```json
{
  "target": {
    "schema_version": 1,
    "target_id": "target-512-v1",
    "source_revision_hash": "sha256:...",
    "build_id": "build-m87-cuda-v1",
    "build_spec_hash": "sha256:...",
    "run_id": "run-512-v1",
    "run_spec_hash": "sha256:...",
    "data_id": "",
    "analysis_id": "",
    "criteria": [
      {
        "id": "run-terminal-success",
        "subject": "run",
        "subject_id": "run-512-v1",
        "check": "terminal_status",
        "expected": "completed"
      },
      {
        "id": "fields-readable",
        "subject": "data",
        "subject_id": "",
        "check": "nt2_inventory_status",
        "expected": "ok"
      }
    ]
  },
  "target_hash": "sha256:..."
}
```

`check` only accepts a fixed enumeration; no expressions are evaluated:

- `identity_exists`
- `source_revision_matches`
- `spec_hash_matches`
- `terminal_status`
- `artifact_exists`
- `artifact_sha256`
- `nt2_inventory_status`
- `analysis_result_status`

`memory.goal` and `memory.done_when` remain human-readable descriptions but must not be
used to automatically advance readiness or completion. If a legacy Case has only a
free-text goal, `check` returns `needs_decision/WF_TARGET_MISSING`, and the model or
user confirms a structured target once.

`build_id/run_id/data_id/analysis_id` may be empty, but the semantics are not "any
current value":

- before a deterministic build/run bundle starts, the source revision, build ID, run
  ID, and corresponding spec hashes must already be bound; after a PGen modification,
  the model should confirm the target once for the new source revision before entering
  that bundle;
- when a new run has not yet produced data/analysis identities, empty
  `data_id/analysis_id` means late binding, and only the first verified identity whose
  parent chain exactly matches the target run may be bound;
- late-bound actual IDs are recorded in the resource current identity and completion
  evidence and are not written back into the target, so `target_hash` does not change;
- if the workflow requires reusing an existing data/analysis, the exact ID must be
  written into the target.

New state CLI:

```bash
python3 entity_router_state.py set-workflow-target \
  --case <uid> --expected-revision <n> --target <target.json>
```

Gates: no active Action; target schema is valid; when referencing existing identities
their hash/parent must match; `target_hash` is computed by the state tool rather than
trusted from input. Modifying the target does not automatically modify external
resources; it only recomputes allowed actions and marks downstream readiness that
conflicts with the new target as `stale/unknown/none`.

For a Workflow with a structured target, `complete-workflow` must execute the fixed
evaluator for each criterion one by one and record the criterion ID, subject identity,
and evidence; the original "verification count no less than done_when count" logic is
retained only for legacy Workflows that have not yet entered the façade.

### 5.2 Unified identity record

`resources.<dimension>.identities[]` uses common fields:

```json
{
  "id": "data-run-512-<12hex>",
  "kind": "data",
  "site_id": "m87",
  "root": {"site_id": "m87", "path": "/.../run-512/data"},
  "spec_hash": "sha256:...",
  "parents": {"run_id": "run-512-v1"},
  "evidence": [
    {"locator": {"site_id": "m87", "path": "/.../nt2-inventory.json"},
     "sha256": "...", "observed_at": "..."}
  ],
  "created_by_action": "data-inspect-001",
  "verified_at": "..."
}
```

Per-dimension constraints:

| Identity | Required parent/spec/evidence |
|---|---|
| source | authority/snapshot fingerprint; canonical revision hash |
| build | `source_revision_hash`, `build_spec_hash`, executable hash |
| run | `build_id`, `run_spec_hash`, run manifest hash, run root |
| data | `run_id`, data root, nt2 inventory hash; a new identity is created even as raw data grows |
| analysis | `data_id`, analysis spec/code hash, result artifact hash |

`data_id` is generated from the sha256 of the canonical JSON
`{run_id, data_root, inventory_sha256, nt2py_version}`; `analysis_id` is generated from
`{data_id, analysis_spec_hash, code_hash}`. The program must not generate identities
from directory mtime or the "latest file".

### 5.3 Atomic activation of a new run

When `run.prepare` completes, the Action request must contain:

```json
{
  "identity_id": "run-512-v1",
  "spec_hash": "sha256:...",
  "parents": {"build_id": "build-m87-cuda-v1"},
  "resource_bindings": {
    "run": {"site_id": "m87", "path": "/.../run-512-v1"},
    "data": {"site_id": "m87", "path": "/.../run-512-v1/data"},
    "analysis": {"site_id": "m87", "path": "/.../analysis/run-512-v1"}
  }
}
```

For a successful `run.prepare`, `finish-action` performs the following within the same
Case lock and revision:

1. verifies the site and registered root of the run/data/analysis bindings;
2. appends the immutable run identity and sets `resources.run.current_id/active`;
3. updates the data/analysis roots;
4. clears the data/analysis current IDs; historical identities are retained;
5. sets `data=unknown`, `analysis=none`;
6. if the workflow target's run ID/spec hash does not match, refuses to finish rather than automatically changing the target.

Using separate `reconcile` calls to perform this switch step by step is forbidden.

### 5.4 Incremental fields on Action request/result

Action request v2 adds optional fields:

```json
{
  "orchestration": {
    "flow_id": "flow-20260717-001",
    "flow_request_hash": "sha256:...",
    "step_index": 2,
    "runner": "run.prepare.v1"
  },
  "spec_hash": "sha256:...",
  "parents": {"build_id": "...", "run_id": "...", "data_id": "..."},
  "resource_bindings": {}
}
```

Action result v2 adds the same `orchestration` and an optional `identity` record.
Legacy request/result files remain readable; an active Action lacking orchestration can
only be recovered through the original Router flow — the façade must not implicitly
take it over. If takeover is genuinely needed, the user must explicitly execute a
separately designed adopt operation in the future; `--adopt` is not implemented in
this phase.

`start-action` gains:

```text
--flow-id
--flow-request-hash
--flow-step-index
--runner
--spec-hash
--parent NAME=ID
--resource-binding DIMENSION=LOCATOR
```

These fields are immutable once the Action has started.

## 6. Flow Request: an Immutable Bundle, Not a Second State Machine

`flow-request.json` schema v1:

```json
{
  "schema_version": 1,
  "flow_id": "flow-20260717-001",
  "case_uid": "case-uid",
  "base_revision": 24,
  "workflow_id": "wf-512",
  "target_hash": "sha256:...",
  "goal": "materialize, build and launch the approved 512 run",
  "steps": [
    {
      "index": 0,
      "action_id": "source-materialize-001",
      "action_type": "source.materialize",
      "owner": "router",
      "execution_domain": "playbook-sync",
      "execution_site_id": "m87",
      "runner": "source.materialize.v1",
      "identity_id": "",
      "spec_hash": "sha256:...",
      "parents": {},
      "input_from": [],
      "inputs": [],
      "read_roots": [],
      "write_roots": [],
      "protected_paths": [],
      "resource_bindings": {},
      "constraints": [],
      "expected_outputs": [],
      "acceptance_checks": [],
      "runner_args": {}
    }
  ],
  "stop_policy": {
    "on_completed": "continue",
    "on_needs_decision": "return",
    "on_blocked": "return",
    "on_anomaly": "return"
  }
}
```

Rules:

- a bundle has at most 8 steps; each step still creates an independent Action;
- `action_id`, Action type, owner/domain/site, identity, roots, acceptance, and runner
  are all fixed before execution;
- `flow_request_hash` is the sha256 of the complete canonical JSON with that hash field removed;
- `base_revision` only constrains the bundle's starting point. Each subsequent step
  rereads the current revision but must prove that every new mutation since the start
  belongs to a completed earlier step of the same flow; otherwise it returns
  `revision_conflict`;
- the façade maintains no `current_step`. It scans the flow hash and index in Action
  request/result to derive which steps are completed, active, or not yet started;
- the next step starts only when all of the following hold: the predecessor completed,
  it is in the current allowed actions, the target hash is unchanged, there are no
  pending decisions, and runner preflight passes;
- a bundle must not contain `data.purge`, `source.transfer-authority`, or dependency
  source builds; those operations require independent decisions and authorization;
- a model-required step may only use `execute --prepare/--resume`; it must not be
  faked as completed by the façade inside an ordinary bundle.

Later steps may only read predecessor outputs through the declarative `input_from`:

```json
{
  "step_index": 4,
  "role": "launch_receipt",
  "expected_locator": {"site_id": "m87", "path": "/.../launch-receipt.json"}
}
```

No string interpolation or expressions are supported. After the predecessor Action
completes, the façade resolves the input from its verified result by
`step_index + role + exact Locator`, reprobes it, and writes the actual scheduler/PID
identity into the Action request about to start. This way the flow plan does not need
to guess the job ID before launch, while the `run.monitor` Action request remains
fully immutable once started.

## 7. Façade CLI Precise Contract

Entry point:

```text
skills/entity-router/scripts/entity_router_flow.py
```

Common output fields:

```json
{
  "schema_version": 1,
  "status": "pass",
  "case_uid": "...",
  "revision": 24,
  "flow_id": "",
  "result": {},
  "issues": [],
  "artifact_refs": [],
  "metrics": {"tool_calls": 0, "remote_calls": 0, "output_bytes": 0}
}
```

Exit codes:

| Exit | Meaning |
|---:|---|
| 0 | `pass/completed/observe_only` |
| 10 | `needs_decision` |
| 20 | `blocked` |
| 30 | `anomaly` |
| 40 | invalid request/schema/envelope |
| 50 | revision/active Action/flow hash conflict |

All non-zero exits must still output schema-conformant JSON; tracebacks are only
written to a redacted local debug artifact and never enter stdout.

### 7.1 `inspect`

```bash
python3 entity_router_flow.py inspect --case <uid>
python3 entity_router_flow.py inspect --cwd <absolute-path>
python3 entity_router_flow.py inspect --case <uid> --live --phase run
```

Case selection rules:

1. `--case` accepts an exact UID or control path and takes precedence;
2. `--cwd` matches only against the authority/artifact/resource envelopes in the
   registry; it does not read control markers inside the source checkout;
3. 0 candidates returns `needs_decision/CASE_NOT_FOUND`;
4. multiple candidates returns `needs_decision/CASE_AMBIGUOUS` and compact candidates;
5. never auto-select by last-opened, mtime, tags, or "latest".

`--live` only probes the resources needed by `--phase`. Adds
`entity_router_site.py probe-batch`: at most one transport call per relevant site,
checking multiple exact Locators within that call. A multi-site Case may use one call
per site; a single global remote call cannot be promised.

The compact output contains at least:

```json
{
  "case_uid": "...",
  "revision": 24,
  "workflow": {"id": "...", "phase": "run", "status": "active",
               "target_hash": "sha256:..."},
  "active_action": {"id": "...", "type": "run.monitor", "flow_id": "..."},
  "readiness": {"pgen": "verified", "build": "pass", "run": "running",
                "data": "unknown", "analysis": "none"},
  "identities": {"source": "...", "build": "...", "run": "...",
                 "data": "", "analysis": ""},
  "allowed_actions": [],
  "issues": [],
  "decision_required": false
}
```

### 7.2 `check`

```bash
python3 entity_router_flow.py check --case <uid>
python3 entity_router_flow.py check --case <uid> --live --phase run
```

Static `check` does not touch the remote; live check reuses the batch probe. Result
precedence is `anomaly > blocked > needs_decision > pass`.

Issue schema:

```json
{
  "code": "ID_RUN_BUILD_MISMATCH",
  "class": "anomaly",
  "message": "current run references a non-current build",
  "subject": {"kind": "run", "id": "run-512-v1"},
  "evidence_fingerprint": "sha256:...",
  "artifact_ref": null
}
```

First batch of invariants:

| Code | Check | Failure class |
|---|---|---|
| `WF_TARGET_MISSING` | an active flow has a structured target | needs_decision |
| `WF_TARGET_HASH_DRIFT` | request and current target hash agree | anomaly |
| `ACTION_REQUEST_MISSING` | the active Action request exists and is schema-valid | anomaly |
| `ACTION_RESULT_ON_ACTIVE` | an active Action must not already have a terminal result | anomaly |
| `ACTION_OWNER_ENVELOPE` | owner/domain/site/read/write/protected complete | anomaly |
| `ID_BUILD_SOURCE_MISMATCH` | build parent equals the target source revision | anomaly |
| `ID_RUN_BUILD_MISMATCH` | run parent equals the target/current build ID | anomaly |
| `ID_ACTIVE_RUN_SCOPE` | the active run is located under the run root | anomaly |
| `ID_DATA_RUN_MISMATCH` | data parent equals the current run ID | anomaly |
| `ID_DATA_SCOPE` | positive data evidence is located under the current data root | anomaly |
| `ID_ANALYSIS_DATA_MISMATCH` | analysis parent equals the current data ID | anomaly |
| `MONITOR_TERMINAL_ACTIVE` | a live terminal process must not retain an active monitor | anomaly |
| `RETRY_UNCHANGED_EVIDENCE` | a retry of the same request must have changed evidence | blocked |
| `SITE_UNREACHABLE` | a live check has no current evidence | blocked |

### 7.3 `execute`

```bash
python3 entity_router_flow.py execute --request <flow-request.json>
python3 entity_router_flow.py execute --request <flow-request.json> --prepare --step <index>
python3 entity_router_flow.py execute --request <flow-request.json> --resume \
  --step <index> --worker-result <site:/path>
```

Ordinary bundle:

```text
validate flow schema/hash/base revision/target
  -> derive step state from Case Actions
  -> for each unfinished deterministic step
       validate allowed action and runner preflight
       call state.py start-action
       dispatch fixed runner
       read/verify dispatch receipt
       reprobe expected outputs
       call state.py finish-action
  -> emit one compact bundle result
```

`--prepare`:

1. validates and starts the model-required Action;
2. stages the immutable Action request;
3. returns a worker envelope of no more than 4 KiB containing only the Action request
   Locator/hash, owner skill/playbook, exact input/read/write roots, success criteria,
   and the worker-result destination;
4. does not load skills from other phases or conversation history.

The owner Worker writes its structured result to the staging Locator authorized by the
Action. `--resume`:

1. validates the worker-result's `case_uid/action_id/request_hash/owner`;
2. does not trust the Worker's success text; reprobes the changed/output Locators;
3. executes each acceptance check one by one;
4. finishes via state.py; on failure, closes as `failed/blocked` and preserves the evidence.

### 7.4 Runner allowlist

`entity_router_flow_runners.py` uses a fixed mapping:

| Runner ID | Action | Fixed entry/result |
|---|---|---|
| `source.materialize.v1` | `source.materialize` | `entity_router_site.py materialize`; revision evidence |
| `build.plan.v1` | `build.plan` | validate/create checkpoint, compat, generate env/build; requirements/checkpoint/scripts |
| `build.compile.v1` | `build.compile` | `entity_run.py build ... --quiet --json`; build_result/log/executable |
| `run.prepare.v1` | `run.prepare` | create immutable run root/input/manifest; manifest hash |
| `run.launch.v1` | `run.launch` | scheduler/PID launcher; submission receipt/process identity |
| `run.monitor.v1` | `run.monitor` | `entity_router_status.py` loop; terminal evidence |
| `data.inspect.v1` | `data.inspect` | `inspect_nt2_data.py DATA --output INVENTORY`; inventory/data identity |

`build.plan.v1` runs only when the schema-v2 `requirements.json` already contains all
user choices; `--merge` is used only when a checkpoint already exists:

```text
entity_checkpoint.py validate requirements.json
entity_checkpoint.py create requirements.json [--merge checkpoint] --output checkpoint
entity_compat.py requirements.json --checkpoint checkpoint --json
entity_generate.py env checkpoint --output env.sh
entity_generate.py build requirements.json --env env.sh --checkpoint checkpoint --output entity-build.sh
```

If validation is partial, compat is not pass, a dependency source build is needed, or
there are unaccepted warnings, the runner returns `needs_decision` and must not
automatically downgrade or install dependencies.

runner_args is an independent schema per Runner ID. Any `command`, `shell`,
`script_text`, or `pre_command` field is rejected outright; site-specific
modules/pre-commands may only come from a verified entity-env-build checkpoint, never
from free text in the flow request.

## 8. Idempotent Execution and Crash Recovery

### 8.1 Recovery determination

For each step, execute determines the following in order:

1. a result with the same action ID exists and flow hash/index match: return the cached
   terminal result without rerunning;
2. an Action with the same action ID is active and flow hash/index match: enter
   recovery without restarting;
3. the same action ID exists but hash/index differ: `revision_conflict`;
4. the Case has another active Action: `revision_conflict`;
5. the prior flow Actions and Case events do not form a continuous chain: `revision_conflict`;
6. otherwise start a new Action.

### 8.2 Dispatch receipt

Each runner writes in the Action staging/write root:

```json
{
  "schema_version": 1,
  "case_uid": "...",
  "action_id": "...",
  "flow_request_hash": "sha256:...",
  "runner": "run.launch.v1",
  "state": "effect_observed",
  "attempt": 1,
  "intent_written_at": "...",
  "effect_identity": {
    "scheduler": "slurm",
    "job_id": "12345",
    "job_name": "entity-<action-hash>"
  },
  "outputs": [],
  "stdout": {"sha256": "...", "bytes": 0, "tail": ""},
  "stderr": {"sha256": "...", "bytes": 0, "tail": ""}
}
```

`state` enumeration: `intent_written`, `effect_observed`, `outputs_verified`. The
receipt is an owner artifact, not controller workflow state; the controller only
records its hash/Locator as evidence at finish. Every state update must atomically
replace via temporary file + rename; only the hash of the final `outputs_verified`
receipt enters the Action result.

### 8.3 `run.launch` special rules

Job submission is an external side effect that must not be blindly replayed:

1. write `intent_written` before submission; the job name/comment contains the deterministic action hash;
2. immediately after a successful submission, write the job ID and scheduler identity;
3. if the process crashes between 1 and 2, recovery first queries the scheduler by
   exact job name, user, submission time window, and run root;
4. exactly one match: backfill the receipt; 0 matches: submission may be retried;
   multiple matches: return anomaly;
5. a non-scheduler launch must be wrapped so the wrapper atomically writes the PID,
   `/proc` start ticks, and run root;
6. when there is insufficient identity evidence, return blocked; never guess a process.

An ordinary automatic retry happens at most once and must satisfy one of:

- the external evidence fingerprint has changed;
- the runner explicitly declares that no external side effect has yet occurred;
- the runner's recovery protocol proves the previous side effect does not exist.

## 9. The Unique Semantics of `watch` and `run.monitor`

`watch` is not an alias for `run.status`. It only executes an already-active
`run.monitor` Action:

```bash
python3 entity_router_flow.py watch --case <uid> --action <monitor-action-id> \
  --flow-request-hash <sha256> --interval-seconds 60 --timeout-seconds 86400
```

Preconditions:

- the Action type must be `run.monitor`;
- the run ID/root and scheduler job ID or PID identity in the request are complete;
- the Action flow hash matches the CLI's;
- the current revision and active Action match.

Loop:

1. calls `entity_router_status.py`, at most one remote call per site per round;
2. writes the compact observation to the Action staging trace;
3. if the process identity is identical to the previous round and status/progress/
   evidence hash are unchanged, only increments `unchanged_polls_suppressed` and
   produces no model event;
4. while running, keeps waiting;
5. on terminal/anomaly/offline/timeout, immediately closes the Action via the state CLI and then returns.

Terminal mapping:

| Observation | Action status | readiness | façade status |
|---|---|---|---|
| exit 0 + terminal evidence + acceptance pass | completed | `run=completed`; quick inventory may only set data to `absent/partial/unknown` | completed |
| nonzero/fatal/identity mismatch | failed | `run=failed` | anomaly |
| site offline/insufficient evidence | blocked | no positive readiness advancement | blocked |
| user-authorized timeout | blocked | keeps the last proven state | blocked |

`watch` must complete `finish-action` before returning. The only exception is when the
façade itself is killed/crashes; in that case the active Action is retained and the
next `watch` with the same hash recovers per Section 8. When `check --live` finds the
process already terminal but the Action still active, it returns
`MONITOR_TERMINAL_ACTIVE`, and the recovery entry point must close it first rather
than creating a second Action.

`data=ready` can only be established by the nt2py inventory of a subsequent
`data.inspect`; shallow file counts of fields/checkpoints are insufficient to claim
the data is readable.

## 10. Data and Analysis Identity Flow

### 10.1 `data.inspect`

Fixed steps:

1. validates the current run ID/root and the Action read envelope;
2. executes `inspect_nt2_data.py` at the data site; raw data is read-only;
3. the inventory must be written to the analysis/staging root; writing into the data root is forbidden;
4. the Router reprobes the inventory and computes its sha256;
5. generates the data ID from `{run_id,data_root,inventory_sha256,nt2py_version}`;
6. `finish-action` atomically appends the data identity, sets the current ID/readiness,
   and marks the old current analysis as stale;
7. an nt2 probe error only proves data `corrupt/unknown`; it must not be interpreted as a physical failure.

### 10.2 `analysis.run`

This is a model-required Action and uses `--prepare/--resume`:

- the request must contain the exact data ID, scientific question, analysis spec hash,
  code/output roots, and acceptance checks;
- the owner model may only write code, plots, and reports under the analysis root, never the raw data root;
- resume re-executes or checks the necessary code and probes the outputs;
- on success, creates an analysis identity referencing the exact data ID;
- when the data current ID changes, analysis readiness automatically goes stale; historical artifacts are not deleted.

## 11. Approval and Remote Execution Boundaries

Approvals fall into two categories that must not be conflated:

1. **Business authorization**: the authorization inside a Router request, e.g.
   `data.purge`, dependency source builds, authority transfer; verified by the
   Case/Action contract.
2. **Host execution approval**: Codex/sandbox approvals of actual commands or
   permission boundaries; decided by the host. The Router does not save, replay, or
   self-authorize them by hash.

The value of runners is to converge many scattered SSH/SCP commands into one fixed,
auditable entry point and to reduce the number of approvals the host may need, but
"one Action, one approval" is only an observability metric, not a Router guarantee. If
a future host provides a scoped approval API, the adapter must be reviewed separately;
no approval cache is implemented in this phase.

Remote runners must:

- use the transport/alias from the site profile;
- send a fixed helper and immutable JSON request, never concatenating caller shell;
- re-verify the request hash, site ID, roots, and protected paths on the remote side;
- stop at the first failure, preserve receipt/log, and not guess at repairs;
- return structured errors `permission_denied/site_unreachable/envelope_violation/
  runner_failed`.

## 12. Context and Observability

| Content | Normal limit | On overflow |
|---|---:|---|
| Case summary | 4 KiB | keep only current identity/readiness/issues |
| Flow request summary | 4 KiB | full request stays at its Locator |
| Terminal result | 4 KiB | evidence list becomes artifact refs |
| Failure result | 8 KiB | stdout/stderr each keep at most 2 KiB of redacted tail |
| Worker envelope | 4 KiB | input files given only as Locator/hash |
| Single owner reference | one per phase | lazily loaded when entering the phase |

New observability fields:

```json
{
  "model_wakeups": {
    "total": 4,
    "by_reason": {"user_goal": 1, "owner_model_required": 2,
                  "workflow_terminal": 1}
  },
  "tool_roundtrips": 18,
  "remote_calls": 7,
  "approval_reviews": 7,
  "tool_output_bytes_injected": 12000,
  "unchanged_polls_suppressed": 42,
  "retries": {"total": 1, "without_changed_evidence": 0},
  "usage": {"input_tokens": null, "cached_input_tokens": null,
            "output_tokens": null, "wall_time_ms": 120000}
}
```

The collector only observes the façade, state/site/owner runners, and artifacts; it
does not write Case state. Token fields use only the platform's raw values; when usage
is unavailable they stay `null` and are never estimated from character counts.

## 13. Implementation Work Packages

### WP0: Contracts and Compatibility Layer

Modified:

- `templates/case-state.json`
- `templates/action-request.json`
- `templates/action-result.json`
- five new flow schemas
- `scripts/entity_router_state.py`
- `tests/test_router_state.py`
- `tests/test_router_contracts.py`

Implementation: structured target, criteria evaluator, incremental Action fields,
unified identity record, `run.prepare` atomic activation, data/analysis identity
transitions.

Completion gate: legacy Cases can still show/verify; a legacy Case without a target
gets an explicit needs_decision from flow-check; all mutations have revision conflict
and active Action tests.

### WP1: inspect/check and Batch Probe

Added:

- `entity_router_flow.py inspect/check`
- `entity_router_flow_common.py`
- `entity_router_site.py probe-batch`
- `tests/test_router_flow_inspect.py`
- `tests/test_router_flow_check.py`

Completion gate: tests cover 0/1/N Case candidates, one call per site, all invariant
codes, 4 KiB truncation, and offline-site behavior.

### WP2: Deterministic execute and Owner Adapters

Added:

- `entity_router_flow.py execute`
- `entity_router_flow_runners.py`
- `tests/test_router_flow_execute.py`
- `tests/test_router_flow_build_adapter.py`

First supports `source.materialize`, `build.plan`, `build.compile`, `run.prepare`.
Completion gate: each bundle step is an independent Action; errors stop-first; no
arbitrary shell fields; build partial/compat fail returns needs_decision; crash
recovery does not repeat side effects.

### WP3: launch/watch/monitor

Added:

- `run.launch.v1` and `run.monitor.v1`
- dispatch receipt and scheduler/PID recovery
- `tests/test_router_flow_watch.py`
- `tests/test_router_flow_launch_recovery.py`

Completion gate: simulated "crash after submission, before writing the receipt",
duplicate jobs, PID reuse, offline, timeout, terminal active Action, and unbounded
unchanged polls; no path blindly resubmits a job.

### WP4: data/analysis and the Two-Phase Model Worker

Added:

- `data.inspect.v1`
- `execute --prepare/--resume`
- `tests/test_router_flow_data_identity.py`
- `tests/test_router_flow_worker_resume.py`

Completion gate: the data ID is stable for a run/inventory; an inventory change
generates a new ID; analysis references the exact data ID; the Worker narrative alone
cannot advance state; wrong output roots are rejected.

### WP5: Observability, Evaluation, and Rollout

Added:

```text
evals/router-flow/
├── baseline.json
├── scenario.json
├── expected-invariants.json
└── replay-fixtures/
```

Local replay and the controller-local query canary run first; managed transactions go
through `entityctl flow` by default. The legacy
`list/show/verify/status/start-action/finish-action` are not deleted; they are used
only for precise recovery and diagnosis. The m87 live canary still requires the user's
separate explicit authorization for that remote compute side effect.

## 14. Test Matrix

| Category | Required scenarios |
|---|---|
| Case selection | exact UID, single cwd candidate, shared checkout with multiple candidates, stale registry |
| Revision | base drift, external mutation between steps, same Action with different hash |
| Target | missing, hash drift, 512 target against a 256 run, stale after target update |
| Envelope | wrong site, path escape, symlink escape, controller overlap |
| Identity | source-build, build-run, run-data, data-analysis parent mismatch |
| Bundle | normal serial, second step fails, model step stop, purge/authority transfer forbidden |
| Build | partial requirements, compat fail, warnings, dependency source build gate |
| Launch | failure before submission, crash after submission, 0/1/N scheduler matches, PID reuse |
| Watch | unchanged, progress, exit 0, nonzero, fatal, offline, timeout, resume |
| Data | absent, partial, ready, corrupt, inventory change, output written into data root |
| Context | 4/8 KiB boundaries, redaction, artifact refs, no full Case/log leakage |
| Compatibility | Python 3.6.8, legacy Case, legacy Action, existing fast status |

Unit tests must not access a real scheduler; they verify via a fake site transport and
fixed status fixtures. Live m87 is used only for the canary and is not a CI
requirement.

## 15. End-to-End Acceptance

Scenario:

```text
modify PGen
  -> m87 source materialize
  -> build plan/compile
  -> new run prepare/launch
  -> monitor outside the model
  -> data inspect
  -> scientific analysis
```

Hard correctness gates:

- Case, Workflow, every Action, and owner/domain/site/envelope all conform to Router v3;
- the source -> build -> run -> data -> analysis identity chain closes;
- a new run atomically switches roots and never inherits the old run's data/analysis current identity/readiness;
- scheduler/PID recovery does not resubmit;
- the terminal monitor is closed before the façade returns;
- Worker results must be reprobed by the controller before advancing state;
- if any hard gate fails, the change is not accepted even if the efficiency metrics pass.

Efficiency gates:

- `model_wakeups.total <= 6`;
- `tool_roundtrips <= 30`;
- `approval_reviews <= 10`, as an observability target only;
- total tool output injected into the model `<= 64 KiB`;
- any number of unchanged polls adds nothing to the model context;
- tool roundtrips and injected bytes both drop by at least 60% relative to the frozen baseline.

The token gate is conditional: when both baseline and canary have platform-native token
usage, model processing tokens must drop by at least 60%; when either side's usage is
`null`, record `not_assessed`, do not substitute character counts, and let the final
conclusion be decided by call counts, injected bytes, wall time, and the hard
correctness gates.

## 16. Start Order and Stop Conditions

Strict order: `WP0 -> WP1 -> WP2 -> WP3 -> WP4 -> WP5`. Do not implement watch before
WP0 is complete; do not connect a scheduler before WP2's idempotence foundation
passes; do not run a live canary before WP3 proves there is no resubmission.

At the end of each work package you must:

1. run that package's targeted tests;
2. run the full `python3 -m unittest discover -s tests -v`;
3. run `git diff --check` and the Router Python 3.6 compatibility check;
4. update the implemented/not-implemented status in this document;
5. if you find a need for a second writer, weaker evidence strength, or blind replay of
   external side effects, stop immediately and re-review.

Once WP0's schema/transition tests all pass, this plan is ready to enter the code
implementation phase; before that, do not write the façade shell first to bypass the
missing state semantics.
