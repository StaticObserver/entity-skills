# Entity Workspace vNext

File-first tools built around four objects:

```text
Source + PGen → Build → Run
```

Project, Workspace, Site, deps, TOML, Data, Attempt, and Analysis are containers, attributes, or derived records. State is stored in JSON and ordinary files; there is no database and no content hashing.

## Run

```bash
vnext/bin/entity --help
vnext/bin/entity workspace init /absolute/workspace
export ENTITY_WORKSPACE=/absolute/workspace
vnext/bin/entity project init --project demo
```

Register a Site before initializing its directory tree:

```bash
vnext/bin/entity site add --config /absolute/site.json
vnext/bin/entity site init --site <site-id>
```

Legacy migration accepts the old Ledger export shape shown in
`vnext/schemas/examples/legacy-export.json`. Source records with a repository
and Git commit are imported automatically. Old PGen, Build, Run, Data, and
Case facts that cannot satisfy the four-object model are retained in
`migration-report.json` for manual mapping.

Use `vnext/schemas/examples/` as the field contract. The complete architecture and development plan are under `design/`.

## Skills

`vnext/skills/` is the matching Agent interface:

- `entity-workspace`: four-object facts, cross-session work, Site and Run operations;
- `entity-env-build`: deps and Build work at one explicit Site;
- `entity-pgen`: PGen implementation and TOML-facing physics contract;
- `entity-nt2py`: read-only Data access and analysis artifacts.

`entity-ledger` is intentionally absent. The workspace skill exposes the
file-first runtime through `entity-workspace/scripts/entity`; specialist skills
do not introduce separate state or mandatory workflows.

## Test

```bash
PYTHONPATH=vnext python3 -m unittest discover -s vnext/tests -t vnext -v
```
