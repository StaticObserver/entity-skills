# U6 — Existing-Data Analysis (A/B comparison)

## Scenario Intent

The user already has the data root of a completed run and wants analysis only, no new simulation: whether ux drifts, the E² noise level, delivered as a report + a rerunnable script, with the data root kept read-only. Tests "analysis capability" and "data protection"; unrelated to the router (analysis is not a Goal — a skill boundary, not a defect; see SUITE.md).

## Control Groups

- `skills-v5` and `skills-no-router` share the same checks (this scenario has no router-specific artifacts).

## Prerequisites

setup.sh needs a data root source and renders it into the prompt (the `@DATA_ROOT@` placeholder):

```bash
bash evals/user-needs/run_need.sh U6 <variant> <run-name> [model] -- --data-root <remote-path>
# or take run.data_root from the submission.json in retained evidence:
bash evals/user-needs/run_need.sh U6 <variant> <run-name> [model] -- --evidence <evidence-dir>
```

## Verification Logic (verify.py checks)

| check | Meaning |
|---|---|
| `analysis_artifacts_exist` | analysis/report.md and analysis/*.py exist (Gate E style) |
| `ux_value_consistent` | the ux value in the report deviates from the nt2py-independent recompute of the last snapshot's mean ux by ≤ max(0.02, 10%) |
| `analyze_rerunnable` | analyze.py reruns successfully against the data root (both positional-argument and --data-root invocations are tried) |
| `data_root_readonly` | no analysis artifacts (report/script/plots/notebook) inside the data root |

## Known Boundaries

- Report value extraction is heuristic (the float on the ux/drift line); a miss is recorded as unknown for human review.
- analyze.py's invocation convention is not standardized; verify tries two common forms and records fail only if both fail.
- Offline mode uses the evidence's oracle-data to actually recompute and rerun.
