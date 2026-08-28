---
name: entity-workspace
description: Manage long-lived Entity simulation work with the file-first Source, PGen, Build, and Run model. Use for workspace or site setup, cross-session state, build/run creation, submission, status, migration, or work spanning multiple Entity domains. Focused PGen, dependency-build, and nt2py tasks can use their specialist skills directly.
---

# Entity Workspace

Keep only the facts needed to resume Entity work across agents, projects, and
sites. Do not turn those facts into a mandatory workflow.

## Core model

`Source + PGen -> Build -> Run` is the complete first-class object model.

| Object | Fixed facts |
|---|---|
| Source | repository, Git commit, checkout location |
| PGen | independent ID, entry file, actual user-code files |
| Build | one Source, one PGen, one Site, one deps environment, compile options, runtime capabilities |
| Run | one Build and one exact TOML; default resources and environment do not define identity |

Everything else is subordinate:

- Workspace and Project organize objects.
- Site describes paths, environment, scheduler, and MPI launcher.
- deps belongs to a Site and is referenced by a Build.
- Attempt, Data, and single-run Analysis belong to a Run.
- joint Analysis combines one or more Runs.

There is no Case, database, content hash, seal, release, current pointer, or
lifecycle state machine. Source Git commit is the only required hash-like
identity. Report contradictions with exact files and fields; leave repair to
the user unless they explicitly request it.

## Working boundary

- For a read-only question, inspect JSON, TOML, scheduler state, logs, and
  actual files without creating records or procedural artifacts.
- For a requested change, use the narrowest relevant object command. Do not
  require unrelated checks, confirmations, or stage transitions.
- Treat recorded paths and IDs as facts, but verify volatile execution state
  from the Site when it matters.
- Never edit registered Build artifacts, Run input, or raw Data in place to
  represent a different object. Create a new object when Source, PGen, Build,
  or TOML identity changes.
- A scheduler/resource/environment change or resubmission creates a new
  Attempt under the same Run when Build and TOML are unchanged. Attempt JSON
  records the resources actually used. Never interpret "adjust resources with
  the same TOML" as a TOML change.
- Create a new Run only when the selected Build or the actual TOML content
  changes. Resource values are not part of Run identity even if `run.json`
  carries defaults for new Attempts.
- Before retrying an uncertain submission, query the scheduler or process
  state so the same Run is not launched twice.
- External submission or remote mutation still requires the user's requested
  target and scope; the records do not grant additional authority.

## CLI

Resolve the CLI from this skill and run it as:

```bash
<entity-workspace-skill>/scripts/entity --help
<entity-workspace-skill>/scripts/entity --workspace /absolute/workspace <command>
```

Use subcommand `--help` instead of guessing arguments. The command groups are:

```text
workspace  project  site  source  pgen  deps
build      run      analysis  check  migrate
```

Structured writes go through this CLI. Direct file edits are appropriate for
user-owned Source/PGen code, TOML before Run creation, analysis scripts, and
manual conflict repair requested by the user.

`entity check` is a read-only diagnostic, not a prerequisite for ordinary
work and not an automatic repair command.

## Specialist routing

- PGen physics, implementation, and PGen-TOML consistency: `entity-pgen`.
- Site deps and Entity compilation: `entity-env-build`.
- Entity output access, plotting, and export: `entity-nt2py`.

The workspace skill remains responsible when a task creates or changes object
relationships, submits or tracks a Run, spans domains, or must remain
resumable across sessions.
