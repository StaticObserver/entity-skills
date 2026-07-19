# Multi-site Workspace Contract

A resource identity is always the pair `(site_id, absolute path)` plus its
fingerprint. A Site may be a local machine or one SSH access boundary covering
an HPC login node, scheduler, compute nodes, and shared filesystem.

## Controller layout

```text
~/.entity-router/
├── router.db                         # v5 authority
├── registry.json                    # preserved v3 evidence after migration
├── project-bindings.json            # preserved v3 evidence after migration
├── sites/*.json                     # preserved v3 evidence after migration
└── cases/*/                          # preserved v3 evidence after migration
```

`router.db` contains compact facts and evidence references only. It never lives
inside a source checkout and is never copied into provider-private roots such
as `.codex`, `.claude`, or `.kimi-code`.

## Owner-site layout

Roots are independent and need not share a parent:

```text
<build_root>/<case_uid>/<build_id>
<run_root>/<case_uid>/<run_id>
<staging_root>/<case_uid>/<operation_id>/
<analysis_root>/<case_uid>/<analysis_id>
```

Builds and runs are immutable once their identities are committed. Raw data
remains authoritative at the execution/data Site; fetch only inventory, logs,
figures, reports, or an explicitly selected subset.

## Source authority

Each Case has one editable source authority. A clean Git tree or a
content-addressed manifest identifies its exact content. Dirty and untracked
files are included in the manifest; `dirty=true` alone is not an identity.
Other checkouts are replicas until exact equality is proven. PGen, TOML, and
design edits occur only at the source authority.

## Execution envelope

The controller derives allowed roots and immutable Step requests. The Site
executor may write only beneath those roots and never writes `router.db`.
Receipts remain under the Operation staging root so Apply can recover after a
lost controller process.

Site-local module setup or policy belongs in a trusted Site adapter, not in the
GoalSpec or generic Router core. Passwords, tokens, private keys, mutable session
memory, and full skill copies do not belong in project or controller state.
