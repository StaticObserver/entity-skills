# 0.5.0 Production Acceptance Report (user-needs suite)

System under test: entity skills bundle 0.5.0 (see each round's bundle.json for the bundle_hash).
Evaluation framework: evals/user-needs/ (scenario definitions in SUITE.md, procedure in LIVE-RUN.md).
Variants: S = skills-v5 (full bundle); N = skills-no-router (only entity-ledger removed).
Baseline comparison: S1 (2026-07-21) / Snr1 (2026-07-22) retained evidence.

> Status: 5/9 rounds complete (U1-S, U1-Nr, U6-Nr, U4-S, U6-S). U2-S/U3-S/U3-Nr/U5-S
> are blocked by the environment: the siyuan account-level GPU GRES has been
> unavailable since 2026-07-22 ~22:00 (AssocGrpGRES, GrpTRES empty; two agents
> independently diagnosed it the same way; the gold run worked the day before),
> probed every 20 minutes by gpu_probe.sh (cron 4441807b); once it recovers,
> rerun per LIVE-RUN.md; since U2-S depends on a completed S-group run, the
> recovery order is: rerun U1-S → U2-S → U3-S/Nr → U5-S.

## Results Summary

| Round | Scenario | Group | overall | Key facts | Report |
|---|---|---|---|---|---|
| 2026-07-22-U1-S | U1 new simulation full lifecycle | S | **fail** (operator aborted per §5) | Account-level AssocGrpGRES blocked the entire round (~2h); agent probed the router 7 times (doctor/site list) but stalled at onboarding, never site add, never plan (share=0.081, surgery=0); 67 submissions (26 build/41 sim, including 21 wrap probes); gcc 11.2 ICE blocked the build; agent patched Entity source (get_gpu patch) and tried running sim on a CPU partition (spec violation); submission.json not delivered | need-report.json |
| 2026-07-22-U1-Nr | U1 | N | **fail** (agent completed delivery on its own) | **Gate D physics fully passed** (sim on CPU, ux drift 2.35%, E² 4.7e-05); schema ✓; failures: input.toml/pgen/analysis not delivered to project (B/E), 4 analyses on the login node (A), 28 sim submissions; sim job ran on 64c512g (violates task.md's debuga100 requirement; oracle compared against the submission's self-reported values and didn't catch it — recorded as a gate gap); skill usage limited to env-build | need-report.json |
| U2-S | U2 parameter-change rerun | S | blocked (GPU) | Depends on the GPU run completed by U1-S; rerun after GPU recovery | |
| U3-S | U3 job killed out-of-band | S | blocked (GPU) | Requires a RUNNING sim job to scancel | |
| U3-Nr | U3 | N | blocked (GPU) | Same as above | |
| 2026-07-23-U4-S | U4 interrupted-launch recovery | S | **fail** (partial conclusion under environment blockage) | Crash recovery: agent used cancel+resubmit (run_a100.sbatch ×4, no parallel duplicates, but losing queue position each time — the router's apply/adopt is designed exactly for this, yet the agent didn't use it); router invoked 9 times and site add registration completed, but plan/apply was never executed (fell back to bare sbatch after onboarding); agent precisely diagnosed the GPU root cause twice (GrpTRES empty=0, needs admin) and stopped per task.md; data not delivered (GPU wall) | need-report.json |
| U5-S | U5 verifiable delivery | S | blocked (GPU) | Depends on one completed delivery; waiting for GPU recovery | |
| U6-S | U6 existing-data analysis | S | _pending_ | | |
| 2026-07-23-U6-Nr | U6 | N | **pass** (first pass of the suite) | Reported ux=0.1985 consistent with the independent recompute of 0.2021; analyze.py rerun exit 0; data root read-only; completed in ~8 min (vs. hours for the U1 rounds) | need-report.json |

## Comparison Against 1.0.0 Candidate Criteria

| Criterion | Evidence | Result |
|---|---|---|
| End-to-end build→run→data on a real SSH site | U1-S need-report + router export | **Not met** (GPU wall + router not adopted) |
| Skill script hit rate >0 | U1-S activities.json skill_call_share | 0.081 (router=7 calls but no plan/apply; metric after the bug-fix calibration) |
| No sqlite control-plane surgery | control_plane_surgery_calls in all S rounds | **Met** (U1-S=0, U4-S=0; S1 baseline=1) |
| S1/Snr1 failure points intercepted by gates | U1-S oracle Gates B/C/D | Partial (U1-Nr's Snr1-style layout was correctly parsed by Gate B; physics Gate D fully passed in U1-Nr) |

## Baseline Comparison vs S1/Snr1 (U1 Scenario)

| Metric | S1 | Snr1 | U1-S | U1-Nr |
|---|---|---|---|---|
| sim submission count | 4 | 8 (7 succeeded) | | |
| build-class submissions | 8 | 12 | | |
| poll count (squeue/sacct/scontrol) | 26 | 42 | | |
| skill_call_share | 0.328 | 0.057 | | |
| sqlite surgery | 1 | 0 | | |
| oracle overall | fail | fail | | |

## Headline Finding: Router Onboarding Friction

The initial report of "zero router adoption" was a **measurement bug** (skill_adoption misclassified path invocations of `python3 ~/.claude/skills/.../entityctl.py` as "reading skill docs" and skipped them; fixed and covered by regression tests). The corrected facts are more interesting:

- U1-S: 7 entityctl probes (doctor with wrong arguments → usage error → help → doctor → site list), then **gave up** — never site add, never plan;
- U4-S: 9 invocations and **site add succeeded**, but `plan --goal` / `apply` was never executed — during recovery the agent literally said "try the router's plan", then fell back to bare sbatch the next second;
- Conclusion: the problem is not "the agent doesn't know about the router" but the **friction between CLI probing and the first successful plan** — hand-written site profile, hand-written GoalSpec JSON, decisions confirmation chain, every step can fail, while bare sbatch submits in a single line. The router's value (idempotence/recovery/attribution) only appears after apply, yet the onboarding cost is front-loaded. **The top requirement for 0.6.0: lower the startup cost of the first plan** (e.g. `entityctl init` to one-shot generate a site profile + goal template, or an agent-facing quickstart playbook).

## Skill Boundaries and Defects Recorded (accumulated during the run batch)

- (Known boundaries) 0.5.0 has no run-completion closeout / no resubmit Goal / purge not wired / cross-site source necessarily needs_decision / analysis is not a Goal.
- (Environment) There is a leftover 2026-07-20 job 59839672 on siyuan (dgx2, PENDING/AssocGrpGRES), not produced by this evaluation; left alone.
