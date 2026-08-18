# Entity Skills Run Logging System

Date: 2026-07-15  
Status: v1 implemented

## 1. Goals

This system answers three questions:

1. Which skills and references were exposed to the Agent during a task;
2. Which key decisions the Agent made, which tools it actually invoked, and which
   artifacts it produced;
3. Which results were merely claimed as successful by the Agent, and which have
   been verified by external evidence.

The logs provide machine-readable evidence for later controlled experiments,
component ablations, and error attribution, but the logs themselves do not prove
that a skill caused an improvement in outcomes.

## 2. Boundaries

### Recorded

- Task, model, tool set, and skill version identities;
- Key decision events such as routing, gating, stopping, and recovery;
- Tool call chains, state transitions, artifact references, and validation
  results;
- Failure locations, terminal states, and execution costs.

### Not recorded

- The model's hidden chain of thought or long self-narrated reasoning;
- Passwords, tokens, SSH private keys, complete environment variables, or other
  credentials;
- Bulk copies of large raw data, complete build logs, or complete tool outputs
  by default;
- A second authoritative state for Cases, builds, or runs.

The model may submit short structured decision records, but those are only
"claims" — not a read of its true internal reasoning, and not independent
evidence.

## 3. Three Log Layers

```text
Domain fact layer       Router events / Action / build logs / probe output
       ^                each owner remains responsible for its own state and artifacts
       |
Execution observability  this design: a unified trace for each Agent run
layer                    records only the call chain and references to domain evidence
       |
Evaluation summary layer  future baseline/full/ablation comparisons and metric aggregation
```

These three layers cannot substitute for one another. The Router's
`events.jsonl` remains the Case control fact; env-build's `run.log` and build
logs remain the build facts; the observability log only stores their Locators,
hashes, and related IDs, and never writes back into those authoritative states.

## 4. Evidence Levels

Every event must declare an `evidence_level`:

| Level | Meaning | Example |
|---|---|---|
| `declared` | A claim by the Agent or Worker | "This is a managed write and should go through the Router" |
| `observed` | Behavior directly observed by the collector | `pgen_preflight.py` was invoked and returned exit code 0 |
| `verified` | Confirmed by a validator or an authoritative fact source | The Action exists and the site/path/revision envelope matches |

`declared` must never be automatically promoted to `observed` or `verified`.
For example, the Agent claiming "build succeeded" is only `declared`; the actual
command returning zero is `observed`; the expected executable existing and
referencing the correct build ID is `verified`.

## 5. Run Directory

The default log root is `~/.entity-skills/observability`, overridable via
`ENTITY_SKILL_TRACE_HOME`. The evaluator should pass a dedicated temporary
directory for each experiment.

```text
<trace-home>/runs/<yyyy-mm-dd>/<run_id>/
├── manifest.json
├── events.jsonl
├── artifacts.jsonl
└── result.json
```

- `manifest.json`: immutable run identity and capture policy;
- `events.jsonl`: single-writer, append-only call chain;
- `artifacts.jsonl`: Locator/hash index of artifacts and external evidence;
- `result.json`: reconstructable terminal summary, not a new domain fact source.

Run logs are never written into the Entity source checkout, the Router Case
root, or the raw data root.

## 6. Run Manifest

`manifest.json` contains at least:

```json
{
  "schema_version": 1,
  "run_id": "run-uuid",
  "task": {
    "case_id": "eval-routing-001",
    "input_ref": "evals/cases/routing/managed-pgen-write.json",
    "input_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "variant": "full",
  "agent": {
    "provider": "...",
    "model": "...",
    "configuration": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "tools": {
    "profile": "tool-profile-name",
    "configuration": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "skills": [
    {
      "name": "entity-router",
      "source": "/absolute/path/to/skill",
      "package_revision": "git-commit-or-null",
      "content_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "dirty": false,
      "exposure": "injected"
    }
  ],
  "capture": {
    "raw_input": false,
    "raw_tool_output": false,
    "decision_records": true,
    "protected_roots": [
      "/absolute/entity-source",
      "/absolute/router-case",
      "/absolute/raw-data"
    ]
  },
  "started_at": "2026-07-15T00:00:00Z"
}
```

`exposure: injected` only proves the skill was placed into the Agent's available
context; it does not prove the model used it in any causal sense. If the
platform does not expose a precise context-load event, the log must not guess
that the skill was "read".

## 7. Event Protocol

### Common envelope

```json
{
  "schema_version": 1,
  "event_id": "event-uuid",
  "run_id": "run-uuid",
  "seq": 12,
  "time": "2026-07-15T00:00:03.420Z",
  "type": "tool.finished",
  "source": {
    "kind": "collector",
    "id": "local-runner"
  },
  "evidence_level": "observed",
  "phase": "execute",
  "span_id": "span-uuid",
  "parent_span_id": "parent-span-uuid",
  "payload": {}
}
```

`span_id/parent_span_id` connect Router, Worker, owner skills, and tool calls.
`seq` is allocated monotonically by the collector within a single run; the clock
is for display only and must not replace ordering. `phase` uses
`orient/decide/execute/verify/finish`; finer-grained internal owner phases go
into the payload instead of expanding the common enum.

### Event types

| Category | Types | Purpose |
|---|---|---|
| lifecycle | `run.started`, `run.finished`, `run.failed` | run boundaries |
| skill | `skill.exposed`, `skill.resource_observed` | available skills and observable reference reads |
| decision | `decision.recorded` | routing, gating, recovery, or stop decisions |
| tool | `tool.started`, `tool.finished` | command or API calls |
| state | `state.transition_observed` | observations of external state changes |
| artifact | `artifact.observed` | artifact, log, and evidence references |
| validation | `validation.finished` | deterministic check or rubric results |
| error | `error.observed` | tool, collector, or protocol failures |

v1 does not record every token, ordinary conversation sentences, or every
incidental file read. It records only events that can change the execution path,
the artifacts, or the validation conclusions.

## 8. Decision Records

The Agent records at most one key decision per phase, so that continuous
self-narration does not alter the execution behavior it was supposed to have.

```json
{
  "type": "decision.recorded",
  "evidence_level": "declared",
  "payload": {
    "kind": "route",
    "choice": "entity-router",
    "observed_facts": [
      "request spans pgen and build",
      "target belongs to a registered Case"
    ],
    "contract_ref": "entity-router.entry.cross-domain"
  }
}
```

Requirements:

- `observed_facts` contains only task facts available at that moment;
- `choice` is a decision that can be cross-checked against later tool calls;
- `contract_ref` points to a stable behavior contract, not to SKILL.md line
  numbers;
- Candidate options, detailed reasoning, and after-the-fact explanations are not
  required.

The evaluation definitions for `contract_ref` should in the future live in
`evals/contracts/` at the repository root; no evaluation-specific text is added
to SKILL.md.

## 9. Tools and Artifacts

`tool.started/tool.finished` record:

- A stable tool name, argument hash, and a safe summary;
- exit/status, start and end times;
- Hash, byte count, and a redacted tail summary of stdout/stderr;
- Correlation IDs with Action, Worker, Case, build, or run;
- The artifact event ID.

Each line of `artifacts.jsonl` records:

```json
{
  "artifact_id": "artifact-uuid",
  "run_id": "run-uuid",
  "role": "verification-evidence",
  "locator": {"site_id": "controller", "path": "/absolute/path"},
  "media_type": "application/json",
  "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "size_bytes": 1234,
  "produced_by": "event-uuid",
  "authority": "entity-router-action-result"
}
```

Large artifacts stay on the owner site; the log keeps only the Locator and the
fingerprint. If an artifact may be overwritten, its fingerprint at the time must
be recorded before the run ends, otherwise it cannot serve as reproducible
evidence.

`result.json` is rebuilt by the collector from the events and contains at least:

```json
{
  "schema_version": 1,
  "run_id": "run-uuid",
  "terminal_status": "completed",
  "last_seq": 42,
  "decisions": 3,
  "tool_calls": {"total": 8, "failed": 1},
  "artifacts": 4,
  "validations": {"pass": 5, "fail": 0, "unknown": 1},
  "usage": {
    "input_tokens": null,
    "output_tokens": null,
    "wall_time_ms": 120000
  },
  "terminal_event_id": "event-uuid"
}
```

Usage values the platform does not expose stay `null`; tokens are not guessed
from character counts.

## 10. Integration with the Current Four Skills

### entity-router

- Does not change the authority of Case `events.jsonl`, Action request/result,
  or evidence;
- The observability log records `case_uid/action_id/revision/execution_domain`
  and the authoritative file hashes;
- The Router remains the controller single writer; the collector must not write
  Case state.

### entity-pgen

- Captures preflight commands, results, and the target envelope;
- Indexes the before/after hashes of `docs/design.md` / `pgen.hpp` / TOML;
- A validator decides whether a managed write has a matching Action; the Agent's
  self-report is not trusted.

### entity-env-build

- References the existing `~/.entity-env-build/run.log`, build results, and build
  logs;
- Records the hash relationships of requirements/checkpoint/env/build scripts;
- Verifies success via the expected executable, build ID, and source revision.

### entity-nt2py

- Captures read-only probe commands and inventory JSON fingerprints;
- Records the output artifacts selected after the fact; raw data is not copied;
- Verifies that output Locators are not inside the Entity data root.

## 11. Collector

v1 allows only one collector to write a run's `events.jsonl`. The Router,
Worker, tool adapters, and validators submit events to the collector; they do
not append to the same file concurrently.

The collector is responsible for:

1. Generating `run_id/event_id/seq/time`;
2. Validating schema and `evidence_level`;
3. Redacting arguments, outputs, and paths;
4. Appending line by line and flushing immediately;
5. Indexing artifacts and atomically writing `result.json` on normal
   termination.

If the process crashes, the completed JSONL lines remain readable; a run missing
`run.finished/run.failed` is uniformly treated as `incomplete` — success is
never inferred from the last line.

## 12. Redaction and Retention

Default policy:

- Raw user input, raw tool output, and file contents do not enter the log; only
  hashes/refs are recorded;
- Fields matching `token/password/secret/credential/private_key/cookie/authorization`
  are replaced wholesale with `[REDACTED]`;
- The full `env` is not recorded; only allow-listed values related to the
  execution identity, or their hashes, are recorded;
- Evaluation runs retain manifest/events/result and small validation artifacts
  by default;
- Retention for real tasks is configured by the runner; the collector never
  automatically deletes owner artifacts.

v1 keeps raw capture fixed off. If that capability is added later, it must be an
explicit run-level option and leave a trace in the manifest.

## 13. v1 Implementation Scope

v1 implements only the minimal closed loop:

1. JSON Schemas: `manifest` / `event` / `artifact` / `result`;
2. One local collector CLI: `start` / `emit` / `import-events` / `import-codex` / `tool` /
   `artifact` / `evidence` / `finish` / `validate`;
3. Safe redaction and content hashing;
4. Event ingestion for tool calls, decisions, artifacts, and validators;
5. References to five kinds of existing evidence: historical Router Actions,
   Router v5 Operations, PGen preflight, env-build results, and nt2py
   inventories;
6. Tests for schema, ordering, crash recovery, redaction, and single-writer
   behavior.

v1 does not implement a dashboard, hidden chain-of-thought capture, automatic
scoring, A/B scheduling, a cross-machine log service, or full transcript
archival. These enter later designs only after the basic trace proves stable.

## 14. Acceptance Criteria

When v1 is complete it must satisfy:

1. A run's routing, tools, artifacts, and validation chain can be reconstructed
   from the manifest and JSONL alone;
2. It can distinguish a skill being exposed, the Agent claiming to use it, the
   actual behavior being observed, and the result being verified;
3. Each run precisely identifies skill content hash, package revision, model,
   and tool profile;
4. The collector does not write Router Case state, the Entity source checkout,
   or the raw data root;
5. After a mid-run crash the JSONL remains validatable, and the run is correctly
   marked `incomplete`;
6. Tests prove that common secret fields do not enter the log;
7. Removing decision self-reports does not affect the completeness of tool and
   validation events;
8. With logging disabled, the four skills' existing execution paths and
   artifacts are unchanged.

## 15. v1 Default Decisions

- The core collector stays platform-agnostic and accepts standard events; Codex,
  Claude, and Kimi transcript imports are independent adapters and do not enter
  the core schema;
- The local command wrapper covers deterministic tool calls first; transcript
  adapters fill in the routing and Agent/Worker call chain;
- Real tasks by default store only user input hashes and external references;
  the original text of frozen evaluation items is kept in a separate test set;
- The Agent may optionally submit a `contract_ref`, but the authoritative result
  is the validator's judgment based on behavior and domain facts;
- When the platform provides no skill/context load event, only `injected` is
  recorded, explicitly without claiming "read" or "used".

## 16. Implementation Location

```text
tools/skill_observability/
├── skill_observer.py
├── cli.py
├── core.py
├── contracts.py
├── evidence.py
├── adapters/
│   ├── codex_rollout.py
│   ├── claude_transcript.py
│   ├── kimi_wire.py
│   └── tool_trace.py
└── schemas/
    ├── manifest.schema.json
    ├── event.schema.json
    ├── artifact.schema.json
    └── result.schema.json
```

`tests/test_skill_observability.py` and `tests/test_e2e_evaluation.py` cover the
complete owner evidence chain, Router v5 Plan/Operation/receipt/scheduler
evidence, secret redaction, multi-process write serialization, post-crash
incomplete determination, artifact fingerprint drift, incremental import for the
three providers, and the zero-intrusion runtime boundary. All adapters import
only observable tool call/output fingerprints; the Kimi adapter traverses the
main and sub-agent wires and reads the platform-native usage, but does not
retain `think` content.

## 17. Production Invocation Logging (passive invocation logging)

Status: implemented (2026-08-09).

This is a different layer from the evaluation trace described earlier in this
document (skill_observability, the complete evidence chain for controlled
evaluation rounds): production invocation logging is **passive** — every time a
CLI of the four entity skills is actually invoked, one JSONL record is
appended, with the goal of accumulating real usage data during everyday use.

- **What is recorded**: schema_version, timestamp (UTC Z), duration_ms, skill,
  script, argv (after redaction), cwd, exit_code, error_type (optional),
  skill_version (when a VERSION file exists), pid, ppid_comm (best-effort), and
  host. Each CLI entry point (`entityctl`, the ledger's executor/remote
  standalone CLIs, the four env-build CLIs, pgen_preflight, inspect_nt2_data)
  is wrapped in its `__main__` block with a thin context manager, without
  intruding into library code.
- **Where it is written**: by default
  `~/.entity-skills/observability/invocations/<yyyy-mm>.jsonl` (UTC monthly
  rotation, append-only, O_APPEND, mkdir -p as needed); the environment
  variable `ENTITY_SKILL_INVOCATION_LOG` can override with a full file path
  (for tests and one-off collection).
- **Privacy boundary**: in argv, the values of flags matching
  token/secret/password/passwd/api[-_]?key/credential (case-insensitive) are
  always recorded as `<redacted>` (both `--flag value` and `--flag=value`
  forms are handled), while the flag names themselves are preserved; no
  secrets are recorded; the log is observational data and **never becomes a
  second authoritative state** — the Ledger's ledger.db remains the sole
  authority, and invocation logs never participate in any state derivation.
- **Never-fail principle**: all exceptions on the logging path (unwritable
  directory, full disk, ps failure, etc.) are swallowed; the return value,
  exit code, and exception semantics of the wrapped main flow are completely
  unchanged. Each of the four skills keeps a byte-identical copy of
  `_invocation_log.py` under its scripts/ directory (installed skill
  directories are self-contained and cannot import across skills; entity-ledger
  may be absent in the skills-no-router variant), protected from drift by the
  byte-identity test in `tests/test_invocation_log.py`.
