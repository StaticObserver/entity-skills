# Workspace and Computation Site Layout Contract

A resource's identity is always the pair `(site_id, absolute path)` plus
its fingerprint. A Computation Site can be a local machine or an SSH
access boundary covering an HPC login node, scheduler, compute nodes, and
shared filesystem.

## Workspace (development environment, the single working directory)

```text
entity-workspace/                    # location chosen by the user; entityctl workspace init/adopt
├── workspace.yaml                   # workspace_id, schema version, creation/migration history
├── projects/
│   └── <project>/                   # human-readable tree, where the user works day to day
│       ├── project.yaml             # project_uid, slug, source authority registration
│       ├── source/                  # source authority (name registered in project.yaml)
│       ├── analysis/
│       │   └── scripts/             # shared analysis script library (authoritative; hardcoded legacy scripts go into legacy/)
│       └── cases/
│           └── <case>/              # intent boundary: intent.md, decisions.json
│               └── analysis/<analysis_id>/  # fetched-back copies of analysis artifacts (lightweight)
├── sites/
│   └── <site>.yaml                  # site profile (authoritative): see below
└── .ledger/                         # controller state (machine read/write)
    ├── ledger.db                    # controller authority
    └── snapshots/                   # source snapshot tars (content-addressed)
```

`ledger.db` contains only compact facts and evidence references. It is
never placed inside a source checkout (`.ledger/` sits at the workspace
root, not inside any source authority), and never copied into
provider-private roots such as `.codex`, `.claude`, or `.kimi-code`. A
new workspace's `.ledger/` contains only `ledger.db` and `snapshots/`;
pre-v3 files such as `registry.json`, `sites/`, and `cases/` can only
exist in a legacy `~/.entity-ledger` that has not been absorbed yet —
they are handled by `workspace import`, and the runtime never reads them.

Resolution order for the controller home: explicit parameters
(`--ledger-home`, and the `ENTITY_LEDGER_HOME`/`ENTITY_ROUTER_HOME`
environment variables) > the `ENTITY_WORKSPACE` environment variable >
the `~/.entity-ledger/active-workspace` pointer > the legacy
`~/.entity-ledger` (compatibility fallback, with a deprecation warning).
Snapshots resolve to the same home as the db.

## Site profile (sites/<site>.yaml, authoritative)

```yaml
site_id: m87
schema_version: 1
transport: {"kind": "ssh", "alias": "m87"}    # or {"kind": "local"}
scheduler: {"kind": "slurm"}
machine: {"os": "...", "arch": "...", "gpus": [...]}   # written by site discover
site_root: /home/staticobserver/entity-compute
projects: ["bh-reconnection"]                 # project subtrees on this site
deps: [{"stack_id": "...", "status": "verified", "packages": [...]}]
notes: |                                      # free text, preserving human experience
  ...
```

The profile is authoritative; the `sites` table of ledger.db is refreshed
from the profiles by `entityctl site sync` (during the mapping
`transport.alias` is rewritten to the db profile's `transport.ssh_alias`
— `templates/site-profile.schema.json` uses the latter). Sites that only
exist in the db (registered by the old `site add`) are flagged db-only in
`site list`, stay usable, and are never auto-deleted. Credentials and SSH
private keys never enter a profile; the profile only records the SSH
alias name. Passwords, tokens, mutable session memory, and full copies of
skills must never enter project or controller state.

### Profile file format (flat-YAML + JSON flow)

The profile is **not** general-purpose YAML: the parser is a
standard-library implementation of a flat+flow subset
(`entity_ledger_workspace.parse_flat_yaml_text`). Rules:

- one top-level `key: value` per line — top-level keys must not be
  indented, and nested block mappings are unsupported (write nested
  structures as JSON flow on a single line);
- scalars: bare (containing no spaces and none of the special characters
  `:#"'&*!|>%@`[]{}`) or JSON double-quoted strings; collections are
  always JSON flow: `{"kind": "ssh", "ssh_alias": "astro"}`,
  `["intelhigh", "amdlow"]`;
- multi-line text (e.g. `notes`) uses the block scalar `key: |` plus
  subsequent lines indented by two spaces;
- comment lines (starting with `#`) and blank lines are skipped;
  `schema_version: 1` must be an integer.

A complete production example (astro-streaming, in live use since the
2026-08 pilot):

```yaml
site_id: astro-streaming
schema_version: 1
transport: {"kind": "ssh", "ssh_alias": "astro"}   # ssh alias, the only way to address it
scheduler: {"kind": "slurm"}                        # none/slurm/pbs/custom
# the machine section is written by entityctl site discover; do not write it by hand
site_root: /home/yangyangcai/entity-compute         # absolute path; without it, legacy roots apply
policy: {"default_partition": "fat", "default_qos": "qos512", "default_submit_user": "yangyangcai", "default_gres": "gpu:V100:1", "default_cpus_per_gpu": 32, "max_cpu_per_gpu": 48, "analysis_partitions": ["intelhigh", "amdlow"], "login_node_no_heavy_work": true}
notes: |
  Free-text site notes: partition policy, known pitfalls, toolchain paths, etc.
  Multi-line content is indented two spaces per the block-scalar rule.
```

The known policy keys are listed in `templates/site-profile.schema.json`;
`default_gres` has the format `gpu[:type]:count` (validation rejects bad
values). `deps`/`projects` are maintained by `site deps-add` / run
records; when registering deps by hand, follow the output shape of
`site deps <site> --json`.

## Computation Site file tree

```text
<site_root>/                          # skeleton created by entityctl site init
├── entity-site.yaml                  # site marker: site_id, schema version, roots inventory
├── deps/                             # shared dependency stacks (site level, reused across projects)
├── checkouts/                        # materialized source (immutable, content-addressed)
└── projects/
    └── <project>/                    # one independent subtree per project
        ├── builds/<case>/<build_id>/ #   immutable
        ├── runs/<case>/<run_id>/     #   immutable; authoritative location of raw data
        ├── staging/<case>/<op_id>/   #   staging + receipts
        └── analysis/<case>/<analysis_id>/  # analysis artifacts + analysis-manifest.json
```

When the profile carries `site_root`, path derivation for new resources
uses this tree (layout `site-tree`, path segments use the readable
project/case slugs); legacy profiles without `site_root` keep the old
independent-roots derivation (layout `legacy-roots`, path segments use
case_uid) and are flagged legacy. Old Locators remain readable under both
layouts; the two coexist until the migration (phase 5). Builds and runs
are immutable once their identities are committed. Raw data remains
authoritative on the execution/data Site; only inventory manifests, logs,
plots, reports, or explicitly selected subsets are fetched back.

## Source authority

Each Project has exactly one editable source authority (registered in
project.yaml, default `source/`). A clean Git working tree or a
content-addressed manifest identifies its exact contents. Dirty and
untracked files are also included in the manifest; `dirty=true` alone
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
