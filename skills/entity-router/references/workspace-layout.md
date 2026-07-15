# Multi-site Workspace Contract

Router v3 models a Case as locators and immutable identities, not as one
directory. A `Locator` is always `{site_id, path}` in JSON and
`site_id:/absolute/path` on the CLI.

## Controller state

The controller is the single writer. The default root is
`$ENTITY_ROUTER_HOME` or `~/.entity-router`:

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

`registry.json` is a rebuildable index. `case.json` is the control snapshot.
Workers never write this tree. A remote Worker receives an immutable request
under that site's staging root and returns owner artifacts/evidence.

## Site profile

A logical execution site represents one access boundary, including an HPC
login node, its scheduler, compute nodes, and a shared filesystem. It records:

- `site_id`, local or SSH transport, SSH alias, and scheduler kind;
- independent `source_root`, `build_root`, `run_root`, `deps_root`,
  `staging_root`, and `analysis_root` values;
- no password, private key, token, or site-specific repair in the core skill.

Roots may be absent until a phase needs them and never need a common parent.
Recommended immutable paths are:

```text
<build_root>/<case_uid>/<build_id>
<run_root>/<case_uid>/<run_id>
<staging_root>/<case_uid>/<snapshot_id>
```

Existing compatible paths may be registered directly.

## Source authority and replicas

Each Case has exactly one editable source authority. PGen, TOML, and design
locators must be inside that authority root. Other checkouts are replicas and
are never silently treated as current.

Materialization modes are explicit:

- `git-ref`: checkout an exact commit; default for formal build/run.
- `snapshot`: package dirty/untracked files into an immutable manifest-hashed
  directory and verify every file after transfer.
- `shared`: accept a shared-filesystem mapping only after revision/hash proof.
- `external`: accept a user-managed copy only after revision/hash proof.

Mutable rsync/tar directories are transport mechanisms, not source identity.
Authority transfer is a separate `source.transfer-authority` Action and
requires matching clean Git commit/tree evidence.

## Build, run, data, and analysis

These are independent resources. A build records an immutable `build_id` and
source revision. A run records a new immutable `run_id` and the referenced
`build_id`. Raw data remains authoritative at its data site; inventory, logs,
figures, reports, or an explicitly selected subset may be fetched. Analysis
defaults to the data site.

No source checkout may contain Router control state merely to make discovery
work. Managed-path detection queries the controller registry and Locator
envelope.
