# Multi-Site Workspace Contract

A resource's identity is always the pair `(site_id, absolute path)` plus
its fingerprint. A Site can be a local machine or an SSH access boundary
covering an HPC login node, scheduler, compute nodes, and shared
filesystem.

## Controller layout

```text
~/.entity-ledger/
└── ledger.db                         # controller authority
```

`ledger.db` contains only compact facts and evidence references. It is
never placed inside a source checkout, and never copied into
provider-private roots such as `.codex`, `.claude`, or `.kimi-code`. A
controller imported from v3 may still carry files retained from before the
migration (`registry.json`, `sites/`, `cases/`); they are read-only
historical evidence, and the current runtime never reads or writes them.

## Owner-site layout

The roots are independent of each other and do not need a shared parent
directory:

```text
<build_root>/<case_uid>/<build_id>
<run_root>/<case_uid>/<run_id>
<staging_root>/<case_uid>/<operation_id>/
<analysis_root>/<case_uid>/<analysis_id>
```

Builds and runs are immutable once their identities are committed. Raw
data remains authoritative on the execution/data Site; only inventory
manifests, logs, plots, reports, or explicitly selected subsets are
fetched back.

## Source authority

Each Case has exactly one editable source authority. A clean Git working
tree or a content-addressed manifest identifies its exact contents. Dirty
and untracked files are also included in the manifest; `dirty=true` alone
does not constitute an identity. Other checkouts are mere copies until
proven exactly equal. Edits to the PGen, TOML, and design happen only at
the source authority.

## Execution boundary

The controller derives the allowed roots and the immutable execution
requests. A Site executor may only write beneath those roots, and never
writes `ledger.db`. Receipts are kept under the operation's staging root
so that, when a record primitive is rerun after the controller process is
lost, it can adopt the existing effect instead of resubmitting.

Site-local module configuration or policy belongs in a trusted Site
adapter, not in record primitive parameters or the generic Ledger core.
Passwords, tokens, private keys, mutable session memory, and full copies
of skills must never enter project or controller state.
