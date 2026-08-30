---
name: entity-env-build
description: Prepare one explicit Entity Site dependency environment and compile a Build from one recorded Source plus one recorded PGen. Use for deps setup, compiler or library remediation, build script inspection, compilation, and build-result diagnosis. Run submission and cross-object lifecycle work belong to entity-workspace.
---

# Entity Environment Build

Build work is one part of the four-object model:

```text
Source + PGen + Site + deps + options -> Build
```

The Build record must name all of these inputs. The same PGen may be compiled
with different Source commits, producing different Builds.

## Fixed facts

- Site root, transport, environment script, scheduler, and MPI launcher come
  from the Site JSON.
- deps lives at `<site_root>/deps/<deps-id>/` with `deps.json`, `env.sh`,
  `install/`, `sources/`, `scripts/`, and `logs/`.
- Build preparation copies the selected PGen into the Build directory and
  creates `scripts/build.sh`, `work/`, `bin/`, and `logs/`.
- `build-result.json` records the actual command result and executable path.
- Environment order is `site-env.sh`, then `deps/<deps-id>/env.sh`, then the
  generated Build script variables or Run Attempt environment.

Do not reintroduce `requirements.json`, `entity-deps.local.json`, Case records,
content hashes, mandatory compatibility gates, or a separate build state
machine. Inspect and remediate the actual compiler/library failure. A check is
useful when evidence calls for it, not as a universal prerequisite.

Treat Site configuration and registered object directories as cooperative
project inputs. Add a validation only when it prevents a concrete build error;
do not turn ordinary compilation into a general security audit.

## Working method

1. Resolve the exact Workspace, Project, Site, Source, PGen, and deps IDs.
2. Inspect the recorded JSON and the actual Site environment relevant to the
   request.
3. Use `entity deps`, `entity build create`, `entity build prepare`, and
   `entity build run` as needed; inspect each subcommand's `--help` first.
4. Diagnose from the generated script, logs, executable, and
   `build-result.json`.
5. Report what was configured, compiled, verified, or still unresolved.

Resolve `entity` through the sibling workspace skill:

```bash
<entity-workspace-skill>/scripts/entity --workspace /absolute/workspace build --help
```

Source or PGen edits are normal development work, but once an input has been
used by a Build, represent changed content with a new Source commit or PGen ID
and create a new Build. Do not overwrite an existing Build to hide changed
inputs.
