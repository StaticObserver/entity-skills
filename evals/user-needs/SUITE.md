# user-needs Evaluation Suite

"Production user-need level" evaluation: tests whether an agent equipped with the entity skills (entity-ledger 0.5.0 + env-build + pgen + nt2py) can fulfill real user needs on a real cluster (siyuan, SSH Slurm).

**Variant design**: the only independent variable is entity-ledger. Group S `skills-v5` installs the full bundle; Group N `skills-no-router` keeps the three owner skills env-build/pgen/nt2py and removes only entity-ledger. We do not test "no skills at all" — the three owner skills are part of the production baseline. run_round.sh verifies before each run that the skill projection state matches the variant and refuses to start if it doesn't.

## Design Principles

1. **Needs in, deliverables out**: each scenario's prompt.md is a natural-language user request (it does not leak internal mechanism terms like Goal/receipt; U1 is the exception — it is a normalized-reference version of the original task.md); scoring looks only at the final objective state — oracle gates, sacct facts, router store export, claims in the transcript — not at the path the agent took.
2. **harness skill-agnostic**: the metrics (skill_observer activities) and scoring (verify_common + verify.py) assume no particular skill workflow; skill-specific artifacts (data-inventory, router identity chain) are only extra checks for the S group, recorded as unknown for the N group.
3. **Known skill boundaries explicitly modeled**: see the list below. verify.py uses `skill_boundary_notes` to distinguish three kinds of problems: skill defect (skill bug), skill boundary (not penalized), agent error (recorded as fail).

## Scenario Matrix

| ID | Scenario | Variants | Two-stage | Core risks |
|---|---|---|---|---|
| U1 | New simulation full lifecycle | A/B | No | Whether the full lifecycle works end-to-end; duplicate submissions |
| U2 | Parameter-change rerun (ux 0.2→0.3) | S only | No | Old data modified; old/new runs confused; decision chain broken |
| U3 | Job killed out-of-band | A/B | Yes (followup after scancel) | Falsely claiming success; not using the divergence view |
| U4 | run-launch interruption recovery | S only | Yes (restart after killing the agent) | Duplicate sbatch; dangling anomaly |
| U5 | Verifiable delivery + tamper re-check | S only | Yes (followup after tamper) | Answering from memory; still claiming "fully intact" after tampering |
| U6 | Existing-data analysis | A/B | No | Fabricated numbers; dirty writes into the data root |

Scoring calibration: each check is pass/fail/unknown; overall = fail > unknown > pass. unknown must state its reason in detail (missing evidence / site unreachable / skill boundary); offline dry runs may record unknown.

## Known Skill Boundaries (0.5.0)

- **No run-completion closeout**: readiness stops at submitted; job completion and data delivery are verified externally by oracle/sacct.
- **No resubmit/monitor Goal**: after a job is killed there is only divergence classification, no action path; the agent must initiate a new Plan itself (U3, recorded as a boundary_note; resubmission is not penalized).
- **Purge not wired**: not a pass condition for any scenario.
- **Cross-site source necessarily needs_decision**: multi-site scenarios are out of the matrix for now.
- **Analysis is not a Goal**: U6 checks no router artifacts; report/script existence and numeric consistency are verified directly by verify.
- **No data Goal / router chain for the N group**: U1's data_inventory and router_run_chain are recorded as unknown + boundary note for the N group.

## How to Run

```bash
# Run a scenario (stage 1):
bash evals/user-needs/run_need.sh <need-id> <skills-v5|skills-no-router> <run-name> [model] [-- <setup args>]

# For two-stage scenarios (U3/U4/U5), see each needs/<id>/README.md for the intermediate steps, then:
bash evals/user-needs/run_need.sh --followup <need-id> <variant> <run-name> [model]

# Grading (live: finish_round → activities → verify):
bash evals/user-needs/grade_need.sh <need-id> <run-name>

# Grading (offline: dry run from retained evidence; does not touch the cluster or pollute the evidence directory):
bash evals/user-needs/grade_need.sh <need-id> <run-name> --offline <evidence-dir>
```

- run_need.sh reuses e2e-neutral-streaming/run_round.sh to set up the environment (RUN=~/entity-eval-runs/<run>, HARNESS=~/entity-eval-traces/<run>), then calls needs/<id>/setup.sh to lay down the scenario fixture, and finally launches the agent headless (prompt.md; with --followup it continues the session via `claude -c` and sends prompt-followup.md).
- setup.sh can render the final prompt by writing `$RUN/prompt.rendered.md` (U6 uses it to inject the data root).
- U5's tamper step: `grade_need.sh U5 <run> --tamper` (modifies a file inside the agent's project; never touches retained evidence).
- Reports: live writes `$HARNESS/need-report.json`; offline writes `<evidence>/need-report-<need-id>.json` (a new file — it does not overwrite oracle-report.json etc.), carrying `mode: "offline"` and an offline_note.
- In offline mode the observer's run_dir is first copied to /tmp before running activities (that subcommand appends events, so it must not run directly against retained evidence).

## File Layout

```
evals/user-needs/
├── SUITE.md                 # this file
├── run_need.sh              # scenario launcher (incl. --followup two-stage)
├── grade_need.sh            # grading (live / --offline / --tamper)
├── lib/verify_common.py     # shared library: oracle, sacct, router export, activities,
│                            #   schema validation, transcript scanning, ux recompute, report assembly
└── needs/<id>-<slug>/
    ├── prompt.md            # user request (natural language)
    ├── prompt-followup.md   # second stage of two-stage scenarios (U3/U4/U5)
    ├── setup.sh             # scenario fixture / operator hints
    ├── verify.py            # scenario verification (looks at final state only)
    └── README.md            # intent, control groups, verification logic, known boundaries
```
