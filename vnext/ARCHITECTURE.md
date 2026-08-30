# Entity Workspace 0.8.0 Release Candidate Architecture

## Core objects

The only first-class objects are:

```text
Source + PGen -> Build -> Run
```

- Source records one repository and one fixed Git commit.
- PGen is an independent, self-contained user-code package.
- Build records one Source, one PGen, one Site, one deps environment, compile
  options, and runtime capabilities. Its Site directory contains the PGen
  snapshot actually compiled.
- Run records one Build and one exact TOML.

Workspace and Project are containers. Site and deps are Build attributes.
Attempt and Data belong to Run. Analysis records one or more exact
`{build, run}` inputs.

There is no Case, database, content hash, seal/release process, current pointer,
or lifecycle state machine. Source Git commit is the only hash-like identity.

The workspace assumes cooperative users and agents. Object directories are
authoritative records, not protected storage: callers use new IDs instead of
editing registered inputs in place. `entity check` detects structural conflicts
that are cheap to observe; it does not add content hashing, locks, or a security
policy layer.

## Stable relations

1. Changed Source content requires a new Git commit and Source ID.
2. Changed PGen content requires a new PGen ID once used by a Build.
3. Changed Source, PGen, Site, deps, or compile options requires a new Build.
4. Changed Build or TOML requires a new Run.
5. Resource, environment, or submission changes create a new Attempt when
   Build and TOML are unchanged.
6. Data stays under its Run and is read-only to analysis tools.
7. Contradictions are reported with paths and fields; commands do not silently
   merge or overwrite conflicting records.

## Workspace layout

```text
<workspace>/
├── workspace.json
├── sites/<site>.json
└── projects/<project>/
    ├── project.json
    ├── sources/<source>/source.json
    ├── pgens/<pgen>/pgen.json
    ├── builds/<build>/
    │   ├── build.json
    │   └── runs/<run>/
    │       ├── run.json
    │       ├── input.toml
    │       └── analysis/
    ├── scripts/
    └── analysis/
```

## Site layout

```text
<site-root>/
├── site.json
├── site-env.sh
├── checkouts/<source>/
├── deps/<deps>/
│   ├── deps.json
│   ├── env.sh
│   ├── install/
│   ├── sources/
│   ├── scripts/
│   └── logs/
└── projects/<project>/builds/<build>/
    ├── build-prepared.json
    ├── build-result.json
    ├── pgen/
    ├── scripts/build.sh
    ├── work/
    ├── bin/entity
    ├── logs/
    └── runs/<run>/
        ├── input.toml
        ├── attempts/<attempt>/
        ├── data/
        └── analysis/
```

An Attempt contains `attempt.json`, `run.sh`, optional `job.slurm`, an atomic
`submit-intent.lock`, a pre-effect `submit-intent.json`, and
`submit-result.json` when the submission outcome is known. An unresolved
intent prevents automatic resubmission.

## Execution

Environment order is Site `site-env.sh`, deps `env.sh`, then Attempt variables.
Entity is invoked as `entity -input input.toml`; `runtime.arguments` are
appended. MPI is used only when the Build declares MPI and always follows the
Site's explicit launcher template. Slurm does not imply `srun`.

Generated Slurm directives support `nodes`, `tasks`, `tasks_per_node`,
`cpus_per_task`, `gpus_per_node`, `gres`, `walltime`, `partition`, `account`,
and `qos`. Other resource fields remain Attempt metadata or MPI-template
values; inspect `job.slurm` before submission when using custom fields.

JSON and directories are authoritative. `entity check` is read-only and is not
a prerequisite for unrelated work.
