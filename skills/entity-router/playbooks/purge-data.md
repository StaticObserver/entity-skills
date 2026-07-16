# Purge Data

Use only when the user explicitly requests irreversible deletion of inventoried
simulation data.

## `data.purge`

- Owner/domain: `router`.
- Require prior `data.inspect` evidence with readiness `partial` or `ready`.
- Record the user's authorization in the Action Contract.
- Build an exact manifest of deletion targets, byte counts, and retained paths.
- Refuse broad parent deletion when source, build, dependencies, controller
  state, or retained files share that parent.
- Declare every deletion target as an Action write root and every retained path
  as protected where practical.
- Write the purge receipt outside all deletion targets, normally under staging.
- Before deletion, verify no relevant run is active. After deletion, verify each
  target is missing, each retained path still exists, and record reclaimed
  filesystem space.
- Finish with `data=absent` only when all registered Case data was removed;
  otherwise use `data=partial`. Mark dependent analysis stale or absent as
  appropriate.

Never reinterpret `data.inspect`, `analysis.run`, or `run.resume` as permission
to delete data.
