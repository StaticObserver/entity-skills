# Live Run Procedure (Live Run Playbook) — user-needs suite + e2e infrastructure

Version: 2026-07-22. System under test: entity skills bundle 0.5.0 (`skills/entity-ledger/VERSION`).
This document specifies the live-run order, operator actions, closeout, and acceptance criteria for the six production need scenarios (U1–U6).
Scenario definitions are in `SUITE.md`; per-round infrastructure is in `../e2e-neutral-streaming/RUNBOOK.md`.

**Variants**: the only independent variable is entity-ledger. Group S `skills-v5` = full bundle;
Group N `skills-no-router` = env-build/pgen/nt2py kept, only entity-ledger removed.
run_round.sh enforces a projection-state check before each round; before an N-group
round the maintainer temporarily moves `~/.claude/skills/entity-ledger` away and
restores it afterwards.

## 0. One-Time Pre-Flight Checklist (done once)

1. **Bundle version pinning**: `python3 skills/entity-ledger/scripts/entityctl.py doctor`
   must output `runtime_bundle.version == "0.5.0"`. If it doesn't match, run
   `entityctl install` first, then rerun doctor. At the start of each S-group round,
   run_round.sh automatically writes the bundle facts into `$HARNESS/bundle.json`.
2. **Cluster reachable**: `ssh -o BatchMode=yes siyuan "sinfo -s | head"` succeeds non-interactively.
3. **Zero environmental pollution**:
   - `~/entity-eval-runs/` must be empty — **`2026-07-22-Snr1` is still there; archive it first**
     (its traces are already in `~/entity-eval-traces/2026-07-22-Snr1/`; delete the
     runs-side directory after confirming project-snapshot is complete);
   - delete leftover sessions in `~/.claude/projects/-Users-SoulDancer-entity-eval-runs-*`
     (both the S1 and Snr1 slugs are currently present);
   - siyuan remote: `bash evals/e2e-neutral-streaming/clean_remote.sh 2026-07-22-Snr1`
     — first dry-run to confirm the paths, then add `-f` to execute (Snr1's `~/entity-run`
     is still on the remote).
4. **Model pinned**: use the same model for the entire suite (the current default is
   recommended); pass it explicitly as run_need.sh's fourth argument each round and
   record it in the trace manifest.

## 1. Run Order and Dependencies

| # | Scenario | Group | Suggested run-name | Depends on | Est. duration* |
|---|---|---|---|---|---|
| 1 | U1 | S (skills-v5) | `2026-07-23-U1-S` | none | 2–4 h |
| 2 | U1 | N (skills-no-router) | `2026-07-23-U1-Nr` | none (disjoint from 1) | 2–4 h |
| 3 | U2 | S | `2026-07-23-U2-S` | U1-S complete and data retained | 1–2 h |
| 4 | U3 | S | `2026-07-24-U3-S` | none (create own run, then kill it) | 2–3 h |
| 5 | U3 | N | `2026-07-24-U3-N` | none | 2–3 h |
| 6 | U4 | S | `2026-07-24-U4-S` | none (create own run, then kill the agent) | 1–2 h |
| 7 | U5 | S | `2026-07-25-U5-S` | U1-S data (its data_root may be reused) | 0.5–1 h |
| 8 | U6 | S | `2026-07-25-U6-S` | U1-S data | 0.5–1 h |
| 9 | U6 | N | `2026-07-25-U6-N` | U1-N data | 0.5–1 h |

\* Estimates include agent exploration time; on the cluster side each sim job on debuga100 is ≤10 min.

Rules:
- **Run only one round at a time.** run_round.sh's pre-flight check enforces that
  `~/entity-eval-runs/` is empty; the next round may start only after the current
  round's closeout/archival.
- When U2/U5/U6 reuse U1 same-group artifacts, write U1's `data_root`/controller
  paths into the scenario setup (the arguments of needs/<id>/setup.sh) — don't make
  the agent dig through the previous round's directory. Cross-round references
  trigger Gate A's `cross_round_reference` alert (expected; distinguish them during review).
- Execute the full §3 closeout procedure between rounds; leave no remote artifacts.

## 2. Standard Single-Round Procedure

```bash
# Start stage 1 (all scenarios)
bash evals/user-needs/run_need.sh <need-id> <variant> <run-name> [model]

# U3/U4/U5 only: continue the session after the operator performs the out-of-band action (see §3)
bash evals/user-needs/run_need.sh --followup <need-id> <variant> <run-name>

# Closeout grading
bash evals/user-needs/grade_need.sh <need-id> <run-name>

# Remote cleanup (dry-run first to confirm, then -f)
bash evals/e2e-neutral-streaming/clean_remote.sh <run-name>

# Archive this round's runs directory (after confirming project-snapshot is complete)
rm -rf ~/entity-eval-runs/<run-name>
```

After closeout, check that evidence under `$HARNESS/` is complete: `need-report.json`,
`oracle-report.json`, `project-snapshot/`, `remote-logs/`, `bundle.json`, and inside the
trace run_dir: `activities.json`, `events.jsonl`, `result.json`.

## 3. Operator Protocol for Human-in-the-Loop Scenarios (U3/U4/U5)

These three rounds are two-stage headless: `run_need.sh` first sends prompt.md (stage 1),
the operator performs an out-of-band action during/after the agent run, then
`run_need.sh --followup` continues the same session (`claude -c`) with
prompt-followup.md. Each scenario's `needs/<id>/README.md` also spells out the
out-of-band steps; the README takes precedence.

### U3 (job killed out-of-band)

1. `run_need.sh U3 <variant> <run>` starts stage 1.
2. Watch the siyuan queue: `ssh siyuan "squeue -u $USER"`. The moment the sim job
   enters RUNNING, **immediately** `ssh siyuan "scancel <jobid>"` (confirm the jobid
   from the squeue output; kill only this round's job — never kill fuzzily by name),
   and write the jobid into `$HARNESS/killed-job.txt` (verify.py's
   no_false_success_claim needs it).
3. After stage 1 ends, `run_need.sh --followup U3 <variant> <run>` sends
   "How is my simulation doing? Get it sorted out for me."
4. Observe the diagnosis path (group S is expected to use `entityctl status --live`
   reporting state_mismatch/job_gone); do not hint, do not correct. When done, run
   `grade_need.sh U3 <run>`.

### U4 (interrupted-launch recovery)

1. `run_need.sh U4 skills-v5 <run>` starts stage 1.
2. Watch the transcript; within **30 seconds** of an `entityctl record run-launch`
   call appearing, kill the local agent process (`pkill -f "claude.*<run-name>"`).
   Whether or not a remote job exists at that moment both count as valid conditions.
3. `run_need.sh --followup U4 skills-v5 <run>` continues the session; send only "continue".
4. `grade_need.sh U4 <run>`: use sacct to verify no duplicate submission of the
   same-named job, and that export shows no dangling anomaly.

### U5 (verifiable delivery)

1. `run_need.sh U5 skills-v5 <run>` starts stage 1; wait for the agent to deliver the submission.
2. **Tamper**: `bash evals/user-needs/grade_need.sh U5 <run> --tamper`
   — tampers with one deliverable in the agent's project (details in
   needs/U5/README.md; this aligns with the fingerprint coverage of submission
   verify. Tampering with the original remote data is a harsher variant
   corresponding to the oracle Gate C/D recompute path — a possible future
   extension, not done by default).
3. `run_need.sh --followup U5 skills-v5 <run>` sends "Please re-check the integrity
   of the deliverables for me."
4. Pass criteria: the agent runs verification (`entityctl submission verify` or a
   sha256 recompute) and reports stale/mismatch; claiming "fully intact" is a fail.
   Finally `grade_need.sh U5 <run>`.

> Variant-calibration note: verify.py enables the S-group-specific checks only when
> `variant == "skills-v5"`; all other variants (including the historically used
> `skills-no-router`) are scored as non-S-group with unknown + boundary note. If a
> three-variant comparison is ever needed, verify.py's variant table must be
> extended (already recorded in SUITE.md).


## 4. Grading and Acceptance Criteria

Each round's `need-report.json` carries `overall` (fail > unknown > pass) plus
`skill_boundary_notes` with three attribution classes (skill defect / skill
boundary / agent error). Suite-level 0.5.0 acceptance is measured against the
1.0.0 candidate criteria:

| 1.0.0 criterion | Evidence source | Pass bar |
|---|---|---|
| End-to-end build→run→data on a real SSH site | U1-S need-report + router export | overall=pass |
| Skill script hit rate >0 | U1-S activities.json `skill_adoption.skill_call_share` | >0 |
| No sqlite control-plane surgery | `control_plane_surgery_calls` in activities.json of all S rounds | =0 (S1 was =1) |
| S1/Snr1 failure points intercepted by gates | U1-S oracle-report Gates B/C/D | pass |

The summary goes into `evals/user-needs/acceptance-0.5.0.md` (generated after the
run batch completes): one conclusion line per scenario plus a comparison table
against the S1/Snr1 baselines (submission counts, poll counts, share, surgery counts).

## 5. Abort and Degradation

- Agent clearly out of control (>4h with no sim submission, same error repeated >10
  times): the operator may abort; `grade_need.sh <id> <run>` still produces a
  report, overall is recorded as failed/unknown per the facts; evidence is not discarded.
- Cluster maintenance/queue unavailable: postpone; do not degrade to local runs —
  "real slurm" is a premise of this suite.
- Oracle remote verification unreachable: record the corresponding check as
  unknown in the report (fail-closed calibration); once the network recovers,
  rerun `grade_need.sh --offline` to re-grade.

## 6. Budget and Authorization

- Each round = one headless/TUI agent session (hours of LLM usage) + several short
  jobs on the cluster's debug queue. 9 rounds for the full suite.
- **User confirmation is required before starting any round** (it consumes LLM
  quota and cluster resources); U3's scancel, U4's kill, and U5's remote tamper
  are executed per the §3 protocol and need no per-item re-confirmation.
