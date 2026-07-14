# Runtime Workspace Contract

Use this layout unless the user provides an established compatible workspace.

```text
$ENTITY_WORKDIR/
├── entity-<version-or-label>/
├── deps/
└── problems/
    └── <pgen>/
        ├── pgen.hpp
        ├── <matching>.toml
        ├── docs/design.md
        ├── build/
        ├── _build/
        ├── _case/
        │   ├── case.json
        │   ├── events.jsonl
        │   ├── actions/
        │   └── history/
        ├── scripts/
        └── run-<label>/
            ├── input.toml
            ├── run-manifest.yaml
            ├── data/
            ├── logs/
            └── analysis/
```

## Reserved Paths

- `build/`: current CMake build tree; disposable.
- `_build/`: build requirements, dependency checkpoint, generated scripts,
  logs, and session state; persistent.
- `_case/`: Router-owned Case, Workflow, Action Contract, and event state.
- `scripts/`: analysis code shared by runs of the same PGen.
- `run-<label>/`: one immutable run identity.
- `run-<label>/data/`: raw Entity output and checkpoints; read-only to analysis.
- `run-<label>/analysis/`: run-specific scripts, figures, notebooks, and reports.

## State Sources

| Scope | Read |
|---|---|
| Router | `_case/case.json`, Action requests/results, `events.jsonl` |
| PGen design | `pgen.hpp`, matching TOML, `docs/design.md` |
| Build | `_build/requirements.json`, `entity-deps.local.json`, `.entity-session.json` |
| Run | `run-manifest.yaml`, logs, process/scheduler state, output |
| Analysis | run-specific analysis artifacts; no separate state file |

Do not create a workspace-wide state database. Only the Router state tool may
write `_case/`. If existing paths differ, preserve them and record exact paths
in Case, build, and run artifacts.
