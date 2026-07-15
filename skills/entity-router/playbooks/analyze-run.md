# Analyze Run

Use for an existing run or output directory.

## `data.inspect`

- Owner/domain: `entity-nt2py`.
- Execute at the data site by default. Read the run manifest, immutable input,
  PGen design, logs, and raw-data Locator.
- Confirm whether data is absent, partial, ready, corrupt, or unknown.
- Load `../entity-nt2py/SKILL.md` for API, inventory, selection, plotting,
  movie, or export support.
- Keep raw data read-only. Save inventory and reproducible access code at the
  Action-authorized analysis/staging Locator. Fetch only inventory, logs,
  figures, reports, or a user-selected data subset to the controller.

## `analysis.run`

- Owner/domain: `playbook-analysis`.
- State the scientific question and acceptance criteria before computation.
- Use nt2py as data-access support; do not delegate physical interpretation to
  the nt2py skill.
- Put code, figures, notebooks, and reports under the registered analysis root;
  do not assume it is inside the run or source tree.
- Separate observations, calculations, assumptions, and interpretation.

Corrupted output or unexplained runtime failure is not an nt2py API problem.
Close the current Action with evidence and return ownership to the Router.
