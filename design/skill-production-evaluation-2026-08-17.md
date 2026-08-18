# Entity Skills 0.7.0 Production Usage Evaluation (First Week)

Date: 2026-08-17
Status: evaluation complete; fix proposals pending review
Data sources: `~/.entity-skills/observability/invocations/2026-08.jsonl`
(production invocation log, online since 2026-08-09), kimi session wire logs
(`~/.kimi-code/sessions/`), codex rollout logs (`~/.codex/sessions/`), and
line-by-line source-code verification.

## 0. Summary

The 0.7.0 Workspace/Site abstraction **held up** in production: the migration
week's real work (multi-project directory migration, run reconciliation, remote
compile submission) all went through the new model, and `record relocate`
succeeded 50 out of 51 invocations. The observability instrumentation proved
its value in its first week — every piece of problem evidence in this report
comes from it.

At the same time it exposed **3 real bugs (P0)** and a batch of
contract/usability issues (P1/P2). The most severe one (a remote executor
crash reported as "invalid JSON") cost the kimi agent 28 minutes of wasted
troubleshooting on the night of 08-10; another is ledger distortion: a Slurm
CANCELLED run was recorded as `completed` and could not be corrected.

## 1. Data Overview

- 2258 total invocations, of which **2030 (90%) are repository pytest noise**
  (see P1-I1); 228 genuine production invocations.
- Production time distribution: 08-09 (142, migration day) → 08-10 (69, the
  polar_cap incident night) → 08-11 (11) → sporadic afterwards. Projects used:
  polar_cap, bh-reconnection, axion-pic, axion-grpic.
- Clients: all kimi (codex had no entity sessions this week, see §5; claude
  had no usage). kimi proactively passed `--actor-provider kimi
  --actor-run-id kimi-ledger`, so attribution works.
- Key command success rates (production, excluding tests):

| Command | Success | Failure | Notes |
|---|---|---|---|
| `record relocate` | 50 | 1 | migration workhorse, healthy |
| `record run-prepare` | 2 | 9 | incident epicenter, see P0-B1 |
| `record run-launch` | 6 | 5 | cascading failures, see P0-B2 |
| `record run-exit` | 2 | 5 | see P0-B2/B3 |
| `status` / `show` / `doctor` | 5 | 2 | see P1-I5 |
| `pgen_preflight` | 3 | 1 | the one failure was a **good failure** (see §3) |

## 2. What Works Well (do not touch)

1. **The observability layer itself**: the passive JSONL log + never-fail
   design ran for a week without faults, captured all key events, and had no
   visible impact on the host tools.
2. **The migration flow**: `workspace import` + `record relocate` (51
   invocations) completed the directory migration of four projects with a 98%
   success rate.
3. **Good error messages pay off immediately**: when `pgen_preflight` rejected
   a relative path with `"locator must use SITE_ID:/absolute/path [target:
   ...]"`, the agent switched to an absolute path and succeeded within 10
   seconds. Contrast with P0-B1's 28 minutes — error message quality directly
   determines recovery cost.
4. **Legacy schema guard**: after the 08-09 fix, in the scenario of a missing
   pointer plus an old v2 db, doctor correctly gives migration guidance, with
   no recurrence of crashes.
5. **The agent's ledger discipline**: when batch run-exit failed on 08-09, the
   agent did not unilaterally batch-abort runs that require a human
   declaration, but listed them as items for the user to decide; after the
   incident it proactively reported the ledger distortion to the user. The
   Ledger's "human declaration" gate served its design intent.

## 3. P0: Real Bugs (fix immediately)

### B1. Remote executor crash swallowed into "Site executor returned invalid JSON"

- **Symptom**: on 08-10 13:10–13:20, `record run-prepare` failed 8 times in a
  row with exit 2; the only error was `"Site executor returned invalid JSON"`,
  status=anomaly. The agent was forced to read three skill source files and
  ssh to astro to manually replay the executor before seeing the real root
  cause: the default python3 on the astro login node is 3.6.8, and the
  executor used `contextlib.nullcontext` (3.7+), which raised AttributeError
  directly; the traceback went to stderr and stdout was empty.
- **Root cause** (verified): `skills/entity-ledger/scripts/entity_ledger_operation.py`
  `ExecutorClient.invoke()` (around line 201) calls
  `_json_from_stdout(stdout, "Site executor")` **before** checking
  `code != 0`. When the remote exits non-zero with no JSON on stdout,
  `_json_from_stdout` throws first, and the stderr carrying the traceback
  never reaches the error message. Ironically, the error branch does have a
  `stderr.strip()` fallback, but it is unreachable.
- **Fix proposal**: in invoke, check `code != 0` first: on non-zero, build
  OperationError("Site executor exited <code>: <stderr tail>") from the stderr
  tail (last ~500 characters); only parse JSON when code is 0, and report
  "invalid JSON" with the head of stdout when parsing fails. Side benefit: the
  executor's minimum python version (3.7+) should be written into the site
  profile's probing/documentation.
- **Effort**: small (~15 lines + 2 tests: remote non-zero exit with stderr;
  zero exit with bad JSON).
- **Session evidence**: `wd_polar_cap_f4cd27212882/session_21329893`,
  turns 112–114.

### B2. Slurm CANCELLED/TIMEOUT runs recorded as `completed`, with no way to correct

- **Symptom**: in the early hours of 08-10, polar_cap's run-23dbefcc8d2d9b64
  actually died of OOM; the agent first manually `scancel`ed the idling
  process, sacct reported `CANCELLED 0:0`; `record run-exit` recorded it as
  **completed** based on exit_code=0. The ledger was distorted, and a
  subsequent `record run-launch` was rejected ("only a prepared run can be
  launched"); `--reclassify` only opens for failed, so completed is a dead
  end. The agent could only report to the user that "this record is
  inaccurate" without being able to fix it.
- **Root cause** (verified): `entity_ledger_record.py` `record_run_exit()`
  (around line 1475): `final = "completed" if exit_code == 0 else "failed"` —
  **scheduler_state plays no part in classification at all**.
  CANCELLED/TIMEOUT/PREEMPTED/NODE_FAIL/OUT_OF_MEMORY are all recorded as
  completed as long as the exit code is 0:0. `_slurm_exit_probe` had already
  retrieved scheduler_state.
- **Fix proposal**:
  1. Look at scheduler_state first during classification: only `COMPLETED`
     may be recorded as completed based on exit_code;
     `CANCELLED`/`TIMEOUT`/`PREEMPTED`/`NODE_FAIL`/`OUT_OF_MEMORY` etc. are
     recorded as failed (or add a new terminal state `cancelled`;
     `TERMINAL_RUN_STATES` already has the "exited"/"aborted" precedent, so
     adding one is compatible), and write scheduler_state into the event
     payload (currently it is only written into identity.scheduler.state).
  2. Extend `--reclassify`'s scope from failed to completed (the reverse
     correction scenario), or add a new `record run-correct --status
     cancelled` human-correction primitive. The latter is preferred:
     reclassify means "re-judge based on log evidence", and a human correction
     should not masquerade as an evidence-based judgment.
  3. The existing distorted record (run-23dbefcc8d2d9b64) is to be manually
     corrected by the user after the new primitive lands.
- **Effort**: medium (classification logic + new primitive + ~5 tests).
- **Note**: this changes terminal-state semantics; before making the change,
  confirm that no test pins "CANCELLED 0:0 → completed".

### B3. `_require_case` error message is misleading: it calls "project not registered" a "missing Case" and points to the wrong command

- **Symptom**: on 08-10 12:57–13:00, the agent called `record run-exit` with
  the pre-migration old path `--project-root ~/Documents/polar_cap` and got
  `"no Case covers the project; create it first"`, with the decision
  suggesting "run entityctl record run-prepare to create the Case" — **run-
  prepare does not create a Case**. The Case existed; it was just bound to the
  new post-migration path. The agent did not blindly follow (commendable) and
  spent 5 minutes relying on its own memory of the migration context to switch
  to the right new path.
- **Root cause** (verified): in `entity_ledger_record.py:108`
  `_require_case()`, `CaseResolutionError(no_project)` and `StoreError` share
  the same message; the message neither distinguishes "this project path is
  not registered" from "the project has no Case", nor gives the correct
  Case-creation command.
- **Fix proposal**:
  1. Split the wording of the two error kinds: project not registered → "no
     project is registered at <path>; if it moved, use the new path or
     `entityctl workspace import`"; project has no Case → give the real
     Case-creation command (check the correct spelling in the code).
  2. Bonus: when a project is not registered, fuzzy-match same-named
     directories in the workspace registry (e.g. `projects/polar_cap`) and
     list candidates in the message — agents learn from error messages, which
     works better than documentation (the 08-10 site deps-add astro →
     astro-axion case is the same kind of problem: when the site name does not
     match, the registered site candidates should be listed).
- **Effort**: small (message layer + 2–3 tests).

## 4. P1: Contracts and Usability (proposed for 0.7.1)

### I1. Test traffic pollutes the production log (90% noise)

- 2030 of 2258 records come from repository pytest (cwd/argv contain
  `/var/folders/` temporary directories). If unaddressed, every long-term
  statistic (success rate, command distribution) will need a filter written
  first.
- **Proposal**: add a kill switch to `_invocation_log.py`: fully silent when
  `ENTITY_SKILL_INVOCATION_LOG=off`; an autouse fixture in the repository's
  `tests/conftest.py` sets it to off (or points it at tmp). The four copies
  stay in sync; the consistency test already exists. Effort: small.

### I2. The retry semantics of the `status` field are not communicated to the agent

- Having developed a habit from intermittent astro SSH disconnects, kimi wraps
  **all** ledger calls in a `for i in 1..5; sleep` retry loop. Retrying
  deterministic errors like `invalid_request`/`needs_decision` is never
  effective — the ×5/×5/×8 retries on the night of 08-10 were all wasted
  (up to 150 seconds of sleep wasted each time).
- **Proposal**: ① state in the contract section of SKILL.md: only `anomaly`
  is retryable; every other status requires changing the input or escalating
  to a human; ② add a `"retryable": false` field to the error payload
  (machine-readable, so the agent does not have to guess). Effort: small.

### I3. run-launch has no resubmission primitive

- After job 357460 died instantly due to a missing executable, a further
  `record run-launch` returned `ok:true, state_mutated:false, "run already has
  a recorded scheduler identity"` (exactly-once receipt, by design). The agent
  could only bypass the ledger, manually sbatch, and then `--adopt-job`.
  "Resubmit after a ledger-submitted job fails" is a common scenario and
  deserves a primitive.
- **Proposal**: `record run-relaunch` (or `run-launch --resubmit`): only when
  the run's recorded job is in a terminal and failed state, generate a new
  submission receipt and resubmit. The design needs a pass (receipt semantics,
  event chain). Effort: medium.

### I4. run-exit is ambiguous for a still-running run

- Calling run-exit on a running run returns `ok:true, state_mutated:false,
  state:"running"` (verified in code: the state field is indeed present), but
  not a single plain sentence says "nothing was written". The agent has to
  confirm by reasoning. Proposal: add `detail: "run is still running; no state
  written"` to the return. Effort: one line + test.

### I5. `doctor` does not support `--project-root`

- The agent guessed `doctor --project-root` by symmetry intuition
  (status/show/record all accept it) and hit an argparse error. Proposal:
  either doctor accepts the flag for project-level filtering, or the argparse
  error text states "doctor is workspace-scoped; use status --project-root".
  Effort: small.

### I6. Invocation attribution depends on agent conscientiousness

- The migration batches (without actor flags) cannot be attributed to a
  client. Proposal: `_invocation_log.py` best-effort sniffs environment
  variables (`KIMI_*`/`CLAUDE*`/`CODEX_*` etc.) to fill an `agent_hint` field,
  omitted when nothing is sniffed. Effort: small.

## 5. Environment State Corrections and Leftover Items

- **codex is already on 0.7.0**: at 08-09 21:42 (local) an `entityctl install`
  without `--provider` rebuilt the codex links to also go through `current` →
  bundle `7215fc5a`. The previous state of "codex pinned to 0.6.1" no longer
  exists. codex had no entity sessions this week (gold/literature projects),
  so no conflict instances. This once again exposes the inherent behavior of
  the shared `current` selector: any bare install switches all three clients
  together — the 0.7.x design topic (per-provider independent selectors) is
  still on the table.
- **The deps registry is empty**: in the 08-17 axion-grpic session, `site deps
  pi2-v100` returned `"stacks": []`, and the agent could only get dependency
  information from a handwritten handoff document. Registering the astro/pi2
  dependency stacks is an operational to-do (`site deps-add`), not a code
  problem; but `site deps` could add a hint when its output is empty ("no
  stacks registered; see site deps-add").
- **0.7.x design topics** (out of scope for this fix round): a source
  authority re-registration primitive, batch historical run import, and
  cross-session knowledge (e.g. "astro needs a companion sbatch", "python3.6
  fixed") are currently carried by handwritten handoff documents in project
  directories; the Ledger does not store this kind of site operations fact.
- **The astro python3.6 root cause has been temporarily fixed** (the agent
  prepended a py39 path in astro's ~/.bashrc), but this is a site-level
  environment patch and should be registered in the site profile
  (sites/<site>.yaml) instead of staying only in the handoff document.

## 6. Proposed Fix Roadmap

1. **Immediately (one commit batch)**: B1, B3, I1, I2, I4, I5, I6 — all small
   changes, mutually non-conflicting, under a day in total. B1 has the highest
   priority (largest diagnostic cost).
2. **0.7.1 (needs a small design pass)**: B2 (terminal-state semantics change
   + human-correction primitive), I3 (resubmission primitive). B2 involves
   correcting existing records; handle run-23dbefcc8d2d9b64 after it lands.
3. **0.7.x design discussions**: shared current selector, source authority
   re-registration, batch import, and where site operations facts live.
4. **Operational to-dos (non-code)**: register the astro/pi2 deps stacks;
   write the astro python fix into the site profile.

## Appendix: Evidence Index

- Invocation log: `~/.entity-skills/observability/invocations/2026-08.jsonl`
- Key kimi sessions: `wd_polar_cap_f4cd27212882/session_21329893` (incident
  night), `wd_documents_3746f1f7c2c5/session_5f71f7c7` (migration wrap-up
  batch reconciliation), `wd_axion-grpic_9df4b4432942/session_a8d28d5b`
  (healthy sample)
- Code verification points: `entity_ledger_operation.py:201`,
  `entity_ledger_record.py:108` (`_require_case`),
  `entity_ledger_record.py:1475` (terminal classification),
  `entity_ledger_record.py:1296` (`_slurm_exit_probe`)
