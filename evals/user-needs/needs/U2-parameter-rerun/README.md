# U2 — Parameter-Change Rerun (S group only)

## Scenario Intent

On top of a completed U1 run, the user asks to "change ux from 0.2 to 0.3 and run it again, keeping the old data". Tests: whether the change went through the proper confirmation chain (the new TOML has a new preflight decision record), whether old/new run identities are distinguishable, whether the old data is completely untouched, and whether the new data physically drifts at 0.3.

## Control Groups

`skills-v5` only: decision records and run identity chains are both router capabilities, so a no-router group would be meaningless.

## Prerequisites

First complete a U1 run (live), or provide its retained evidence:

```bash
bash evals/user-needs/run_need.sh U2 skills-v5 <run-name> [model] -- --prior <u1-run-name|evidence-dir>
```

setup.sh lays U1's input.toml/pgen.hpp/docs into the new project as "existing work", records the old data_root, and takes a remote file snapshot of it (skipped when the site is unreachable; the corresponding check is recorded as unknown).

## Verification Logic (verify.py checks)

| check | Meaning |
|---|---|
| `new_decisions_digest` | a .decisions.json exists whose input_sha256 matches the new TOML containing 0.3 |
| `distinct_run_ids` | ≥2 distinct run identities in the router export |
| `old_run_root_preserved` | the old data_root matches the setup-time snapshot file by file (mtime+size) |
| `gate_d_ux_new_target` | independently recompute ux drift on the new data with expected value 0.3 (gate_d logic parameterized) |

## Known Boundaries

- The ux recompute requires nt2py to be able to read the data root; offline mode uses the evidence's oracle-data, live mode rsyncs the data root of the latest run identity.
- The snapshot comparison's mtime precision relies on remote `find -printf` (GNU); recorded as unknown when the site is unreachable.
