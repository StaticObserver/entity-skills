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

Use `vnext/schemas/examples/` as the field contract. The complete architecture and development plan are under `design/`.

## Test

```bash
PYTHONPATH=vnext python3 -m unittest discover -s vnext/tests -t vnext -v
```
