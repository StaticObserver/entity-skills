# Entity Workspace 0.8.0 Release Candidate

File-first tools built around four objects:

```text
Source + PGen → Build → Run
```

Project, Workspace, Site, deps, TOML, Data, Attempt, and Analysis are containers, attributes, or derived records. State is stored in JSON and ordinary files; there is no database and no content hashing.

This is the active implementation on branch `0.8.0rc`, targeting release 0.8.0. It is intentionally a cooperative
scientific workspace rather than a hostile-input security boundary: registered
files are managed by convention, and checks report contradictions without
adding permission layers, content seals, or mandatory gates.

## Run

```bash
bin/entity --help
bin/entity workspace init /absolute/workspace
export ENTITY_WORKSPACE=/absolute/workspace
bin/entity project init --project demo
```

Register a Site before initializing its directory tree:

```bash
bin/entity site add --config /absolute/site.json
bin/entity site init --site <site-id>
```

Legacy migration accepts the old Ledger export shape shown in
`schemas/examples/legacy-export.json`. Source records with a repository
and Git commit are imported automatically. Old PGen, Build, Run, Data, and
Case facts that cannot satisfy the four-object model are retained in
`migration-report.json` for manual mapping.

Use `schemas/examples/` as the field contract and `ARCHITECTURE.md` as the
complete architecture. This directory is self-contained and has no runtime,
skill, reference, or test dependency on the legacy implementation outside it.

## Install

From this directory:

```bash
python3 -m pip install .
entity --help
```

The direct `bin/entity` entry point remains available without installation and
reports version `0.8.0`.

## Skills

`skills/` is the matching Agent interface:

- `entity-workspace`: four-object facts, cross-session work, Site and Run operations;
- `entity-env-build`: deps and Build work at one explicit Site;
- `entity-pgen`: PGen implementation and TOML-facing physics contract;
- `entity-nt2py`: read-only Data access and analysis artifacts.

`entity-ledger` is intentionally absent. The workspace skill exposes the
file-first runtime through `entity-workspace/scripts/entity`; specialist skills
do not introduce separate state or mandatory workflows.

## Test

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -t . -v
```
