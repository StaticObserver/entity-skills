# U1 — New Simulation Full Lifecycle (A/B comparison)

## Scenario Intent

The user provides a physics specification and asks for the full lifecycle on the siyuan cluster: "build a PGen → compile → submit the job → analyze → deliver". This is the need-oriented normalized version of the e2e-neutral-streaming task: the prompt states only the user need, and scoring looks only at the final objective state (oracle Gates A-E, scheduler facts, router store), not at the path the agent took.

## Control Groups

- `skills-v5` (S group): full entity skills bundle installed. Additionally verifies data-inventory.json and the router source/build/run identity chain.
- `skills-no-router` (N group): env-build/pgen/nt2py kept, only entity-ledger removed. The data inventory and router chain are router capabilities; they are recorded as unknown and written into skill_boundary_notes, not counted as fail.

## Verification Logic (verify.py checks)

| check | Meaning |
|---|---|
| `oracle_gates` | e2e oracle Gates A-E overall |
| `submission_schema` | submission.json passes submission.schema.json |
| `data_inventory` | S: data-inventory.json exists; N: unknown + boundary note |
| `single_sim_job_success` | exactly 1 submission of a sim-class job in activities job_lifecycle; duplicate counts go into detail |
| `router_run_chain` | S: complete source/build/run identity chain in the router export; N: unknown |

## Known Boundaries

- The N group (no router) has no data Goal / router chain (skill boundary, see the list in SUITE.md).
- During offline dry runs, items where sacct/router are unreachable are recorded as unknown with the reason stated.

## How to Run

```bash
bash evals/user-needs/run_need.sh U1 skills-v5 <run-name> [model]
bash evals/user-needs/grade_need.sh U1 <run-name>
# Offline dry run:
bash evals/user-needs/grade_need.sh U1 <run-name> --offline <evidence-dir>
```
