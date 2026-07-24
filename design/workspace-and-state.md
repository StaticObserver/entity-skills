# Entity Multi-Endpoint Workspace and Case v3

Date: 2026-07-14
Status: current implementation baseline

## 1. Principles

A Case is a logical resource graph, not one big directory containing source
code, dependencies, builds, runs, and data. The control endpoint where the Agent
runs and the endpoint where code executes may differ; each resource is
identified by `Locator = {site_id, path}`. JSON stores only structured Locators;
the CLI uses `site_id:/absolute/path`.

Router state is written solely by the control endpoint. Source code, builds,
runs, raw data, and analysis may each live on a different site; directories are
not required to share a common parent.

## 2. Control Endpoint

Default `ENTITY_ROUTER_HOME=~/.entity-router`:

```text
~/.entity-router/
├── registry.json
├── sites/<site_id>.json
└── cases/<case_uid>-<label>/
    ├── case.json
    ├── events.jsonl
    ├── actions/<action_id>/{request.json,result.json}
    ├── history/
    └── evidence/
```

`registry.json` is a rebuildable index; `case.json` is the control snapshot;
owner files remain the fact sources for their respective domains. Custom control
roots can be registered. Control state must not be placed inside a source
checkout, and remote Workers must not modify control state.

## 3. Site

A Site profile records a stable `site_id`, local/SSH transport, SSH alias,
scheduler kind, and independent roots: `source_root/build_root/run_root/deps_root/staging_root/
analysis_root`. Credentials never enter the profile. An HPC login node,
scheduler, compute nodes, and a shared filesystem together form one logical
site.

Recommended but not required:

```text
<build_root>/<case_uid>/<build_id>
<run_root>/<case_uid>/<run_id>
<staging_root>/<case_uid>/<snapshot_id>
```

A root becomes a gate only when the current phase needs it; orient does not
block because a root for a future phase is not yet configured.

## 4. Source

Each Case has exactly one editable authority, local on the control endpoint by
default, though it may be remote. PGen/TOML/design must be located inside the
authority root; replicas are not editable by default.

Supported modes:

- `git-ref`: exact commit checkout, the default for formal builds/runs;
- `snapshot`: dirty/untracked files enter the manifest, are named by content
  hash, and are reviewed file by file;
- `shared`: after declaring a shared mapping, verify the Git tree/file hashes;
- `external`: a user-managed copy, accepted only when revision/hash match.

A plain mutable rsync/tar is only a transport implementation, not a source
identity. Snapshot directories must not be overwritten. Switching the authority
is a `source.transfer-authority` Action: first prove both ends have identical
clean commits/trees, then atomically switch the authority and the PGen locators;
both ends being editable simultaneously is forbidden.

## 5. Build, Run, Data, Analysis

Build request schema v2 explicitly records `site_id/source_checkout/build_root/
deps_root/artifacts_root`, replacing the ambiguous `entity.workdir`. Each build
ID references one SourceRevision; each run ID references one build ID. A change
in parameters or checkpoint creates a new run identity; historical paths are not
overwritten.

Raw data is held authoritatively on the data site. `data.inspect`/`analysis.run`
execute close to the data by default, pulling back only the inventory, logs,
images, reports, or a data subset explicitly selected by the user.

## 6. Evidence and Recovery

Evidence contains at least a Locator, kind, fingerprint, observed time, and
observer site. A remote request is an immutable copy in the staging root; a
Worker result is only a claim — before completing an Action, the Router must
re-probe the files, Git, scheduler, or data.

When a remote endpoint is unreachable, old observations do not count as current
facts; the Action enters blocked/suspended and is re-probed after recovery. A
Source change makes builds/runs stale; a build change makes unstarted runs
stale; a data change makes the related analyses stale.

## 7. Migration

`migrate-case --dry-run` only shows the v2-to-Locator mapping; `--commit`
creates a new v3 control Case, maps old paths onto the `legacy-local` site, and
copies the old control records. It does not move or delete source code, builds,
runs, or raw data. The old control plane is suspended only after the new state
is validated, and a migration backup is kept to prevent dual control.

PGen preflight determines managed status via the registry + Locator; it no
longer walks ancestor directories looking for `_case/case.json`.
