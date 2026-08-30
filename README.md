# Entity Skills 0.8.0 Release Candidate

> For the Chinese version, see [README.zh-CN.md](README.zh-CN.md).

The `0.8.0rc` branch is the release candidate for 0.8.0. The active implementation lives
under `vnext/`; the root `skills/`, `tests/`, Router/Ledger code, and older
design documents are retained only as 0.7.x migration and historical material.

## Model

```text
Source + PGen -> Build -> Run
```

- Source records a repository and one Git commit.
- PGen is an independent user-code package.
- Build records Source, PGen, Site, deps, compile options, and runtime
  capabilities.
- Run records one Build and one exact TOML.
- Resource, environment, or resubmission changes create another Attempt under
  the same Run when Build and TOML are unchanged.
- Data belongs to its Run; Analysis records one or more exact `{build, run}`
  inputs.

Workspace, Project, Site, deps, Attempt, Data, and Analysis organize or derive
facts; they do not introduce another object hierarchy or lifecycle state
machine.

## Layout

```text
vnext/
├── entity/                      # 0.8.0 runtime
├── bin/entity                   # direct CLI entry point
├── schemas/examples/            # JSON field examples
├── skills/
│   ├── entity-workspace/
│   ├── entity-env-build/
│   ├── entity-pgen/
│   └── entity-nt2py/
├── tests/
├── ARCHITECTURE.md
└── README.md
```

`entity-ledger` is not part of 0.8.0. Cross-session object relationships,
Site operations, Build/Run creation, submission, and status belong to
`entity-workspace`.

## Quick start

```bash
cd vnext
python3 -m pip install .
entity --version
entity workspace init /absolute/workspace
export ENTITY_WORKSPACE=/absolute/workspace
entity project init --project demo
```

The direct `vnext/bin/entity` entry point works without installation. Inspect
subcommand `--help` before using the following groups:

```text
workspace  project  site  source  pgen  deps
build      run      analysis  check  migrate
```

See [vnext/README.md](vnext/README.md),
[vnext/ARCHITECTURE.md](vnext/ARCHITECTURE.md), and
[vnext/schemas/examples](vnext/schemas/examples) for the maintained contract.

## Operating boundary

0.8.0 is a cooperative, file-first scientific workspace, not a hostile
multi-tenant security boundary. JSON, TOML, Git commits, and actual Site files
are authoritative. The runtime intentionally does not add a database, content
hashes, seal/release records, permission hardening, or mandatory workflow
gates.

Use new IDs instead of editing registered PGen, Build, or Run inputs in place.
`entity check` reports structural contradictions and missing facts; it is
read-only, does not enforce immutability, and is not a prerequisite for
unrelated work. Submission intents remain deliberately small and only prevent
an uncertain submit from being repeated automatically.

## Verification

```bash
PYTHONPATH=vnext python3 -W error::ResourceWarning \
  -m unittest discover -s vnext/tests -t vnext -v
python3 -m compileall -q vnext
git diff --check
```

Validate each skill with the Codex `skill-creator` `quick_validate.py` helper.
The automated suite uses local fixtures, a fake Entity executable, and fake
Slurm commands; a real SSH/HPC canary is a separate release check.

## Legacy 0.7.x

The root legacy implementation remains readable so existing workspaces can be
exported and compared during migration. It is not the 0.8.0 runtime or Agent
entry point, and its version numbers, tests, and historical design documents
remain scoped to 0.7.x.
