# U4 — Interrupted-Launch Recovery (S group only)

## Scenario Intent

The agent is killed midway through an `entityctl record run-launch` execution (simulating a terminal crash/disconnect), and after restart the user only says "keep going". Tests: no duplicate sbatch, no dangling anomaly state in the router store, and data delivered as usual in the end.

## Control Groups

`skills-v5` only (the scenario premise is exactly the router's record/recovery semantics).

## Procedure (two-stage)

1. `bash run_need.sh U4 skills-v5 <run-name> [model]`
2. Watch the transcript (`tail -f ~/entity-eval-traces/<run-name>/transcript.jsonl`); once an `entityctl ... record run-launch` call appears, kill the agent process (Ctrl-C or `kill <pid>`).
3. `bash run_need.sh --followup U4 skills-v5 <run-name> [model]` ("please continue").
4. `bash grade_need.sh U4 <run-name>`.

## Verification Logic (verify.py checks)

| check | Meaning |
|---|---|
| `no_duplicate_sbatch` | each job-name is submitted exactly once in activities job_lifecycle (>1 is a fail; detail prompts a human check of whether the first one FAILED) |
| `no_anomaly_operations` | no anomaly Operation in the router export; the record primitive no longer writes to the operations table, and an anomaly left over from old plan/apply counts as resolved only if superseded by a later completed Operation on the same case |
| `data_delivered` | oracle Gate D passes |

## Known Boundaries

- The exemption "resubmission is allowed after the first one FAILED" requires human sacct confirmation; verify only gives a hint (fail + detail), to avoid an automatic exemption masking a real duplicate.
