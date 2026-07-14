# Analyze Run

Use for an existing run or output directory.

## `data.inspect`

- Owner/domain: `entity-nt2py`.
- Read the run manifest, immutable input, PGen design, logs, and data root.
- Confirm whether data is absent, partial, ready, corrupt, or unknown.
- Load `../entity-nt2py/SKILL.md` for API, inventory, selection, plotting,
  movie, or export support.
- Keep raw data read-only. Save inventory and reproducible access code under
  the Case or run analysis paths.

## `analysis.run`

- Owner/domain: `playbook-analysis`.
- State the scientific question and acceptance criteria before computation.
- Use nt2py as data-access support; do not delegate physical interpretation to
  the nt2py skill.
- Put shared code in Case-level `scripts/` and run-specific code, figures,
  notebooks, and reports under `run-*/analysis/`.
- Separate observations, calculations, assumptions, and interpretation.

Corrupted output or unexplained runtime failure is not an nt2py API problem.
Close the current Action with evidence and return ownership to the Router.
