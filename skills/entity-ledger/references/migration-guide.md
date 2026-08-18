# Migration Guide: Moving Legacy Layouts Fully into the Workspace / Computation Site Model

For the target layout see `references/workspace-layout.md` and the design
document `design/workspace-and-computation-site-2026-08-03.md`. In the end
there is only one layout: the Locators of all registered resources point
into the new trees, no current identity references an old path anymore,
and the old directories are deleted after being verified empty.

Migration is **agent-driven**: entityctl provides deterministic primitives
(planning, recording); the moves themselves (ssh/rsync/mv) are
orchestrated by the agent. The principle is unchanged — free exploration,
strict convergence: the agent decides the order and the pace, the
primitives guarantee that every step is verifiable, re-runnable, and
writes nothing on failure.

## Order and taboos

- **Do not touch in-flight runs.** Runs without a terminal state
  (prepared/submitted/running) stay in place until `entityctl record
  run-exit` books a terminal state; migrate them afterwards. The only
  escape hatch: when a site is permanently unreachable or confirmed dead,
  declare the run abandoned by hand with `entityctl record run-abort
  --reason "..."` (booked aborted, a terminal state, so it can be
  migrated; misuse loses tracking of a real in-flight run — use it only
  when no exit evidence can possibly be probed).
- **Inventory hashes before moving.** Before moving, take the plan from
  `site plan-migration` as authoritative; after moving, `record relocate`
  re-probes the evidence, and mismatched evidence means zero writes — so
  never delete an old path before recording.
- **Verify after every step.** After finishing each batch for a site, run
  `entityctl doctor` and `status` to confirm that the Locators of the
  current identities point into the new trees.
- **Credentials never enter the profiles.** A site profile only records
  the SSH alias name; passwords, tokens, and private keys never enter any
  file in the workspace.
- Old locations remain **read-only** until doctor passes and the agent
  has verified them empty; the user cleans them up manually.

## Step 0: local absorption (one-time, local only)

Gather the scattered project directories, the old controller, and the
site-notes into one workspace:

```bash
entityctl workspace init <workspace>
entityctl workspace import <workspace> \
  --projects-dir ~/Documents \
  --from-ledger-home ~/.entity-ledger \
  --site-notes ~/.entity-env-build/site-notes          # dry-run: review the plan first
entityctl workspace import <workspace> ... --apply     # execute after confirming
entityctl workspace adopt <workspace>
```

- The dry-run prints the plan for every step (project copies, ledger.db,
  snapshots, site-notes conversion); conflicts (the target exists with
  different content) are only reported and skipped, never overwritten. An
  already-initialized empty `.ledger/ledger.db` is backed up and
  replaced; a non-empty db conflict is skipped.
- `--apply` copies the old `ledger.db` into `.ledger/` and automatically
  runs the store schema migration (v1→v2→v3); old project bindings are
  registered into each `project.yaml`; site-notes are converted by
  reusing the `site import-notes` converter (prose goes into the notes
  section, structured JSON into the corresponding sections). Existing
  profiles are skipped.
- Afterwards: `entityctl site sync` refreshes the profiles into the db,
  and `entityctl doctor` verifies.

## Step 1: site profiles and skeletons

For each legacy site:

1. Confirm that `sites/<site>.yaml` already has `site_root`
   (import-notes brings in the old roots; choose the new site_root by
   convention, e.g. `/home/<user>/entity-compute`).
2. `entityctl site sync <site>` refreshes the db.
3. `entityctl site init <site>` builds the
   `<site_root>/{deps,checkouts,projects}` skeleton and the
   `entity-site.yaml` marker on the target machine. If a marker already
   exists on the target machine, `site discover` reports the adoption
   information — check it before deciding whether to keep using it.
4. Dependency stacks: `entityctl site deps-add <site> --from-checkpoint
   <entity-deps.local.json>` registers the verified stacks into the
   registry (mismatched evidence means zero writes) and generates
   `deps/<stack_id>/stack.yaml` on the site.

## Step 2: migrate the old trees site by site

```bash
entityctl site plan-migration <site>     # read-only: old path → new path plan
```

The plan JSON lists, item by item, the identity dimension (build/run),
the old Locator, the new Locator
(`<site_root>/projects/<project>/{builds,runs}/<case>/<id>`), and
on-disk existence, and marks in-flight runs as `skip`; directories under
the old roots that were never recorded are listed under `untracked` for
manual review.

Then for each `move` item:

1. **The agent performs the move** (this guide does not do it for you):
   `mv`, `rsync --remove-source-files`, or a remote move over ssh. Keep
   the directory contents byte-identical.
2. **Record it**:

   ```bash
   entityctl record relocate --project-root <project> [--case <slug>] \
     --dimension <build|run|data> --identity-id <id> --to <new absolute path>
   ```

   relocate re-probes the evidence at the new path (a run's
   `run-manifest.json`, a build's executable sha256, data's
   `data-inventory.json`); only when the evidence matches does it update
   the Locator and write a `record.relocate` audit event; mismatched
   evidence means zero writes. In-flight runs are refused.
3. **Verify**: `entityctl status --project-root <project>` confirms the
   readiness board and the run ledger look normal; `entityctl doctor`
   shows no failure.
4. After all items are done, the agent verifies the old directories are
   empty (`find <old_root> -type f` should print nothing; the
   `untracked` items have been dealt with manually), and the user deletes
   the old directories manually.

New builds/runs automatically land in the new trees (with `site_root` in
the profile, path derivation is already the new layout); the old trees
only shrink, never grow.

## Per-site checklist template

```text
site: <site_id>
[ ] sites/<site>.yaml has site_root; site sync has refreshed the db
[ ] site init skeleton built (or existing entity-site.yaml adopted)
[ ] deps registry: existing verified stacks recorded via deps-add
[ ] plan-migration plan reviewed; moves=N skips=M (in-flight)
[ ] item by item: move → record relocate → status verification
[ ] in-flight runs: migrate after record run-exit books a terminal state; confirmed-dead ones via record run-abort
[ ] untracked directories reviewed and dealt with manually
[ ] old directories verified empty and deleted by the user
[ ] doctor shows no failure; all current identity Locators point into the new trees
```

## Completion criteria

- All current identity Locators point into the new trees;
- no old path is referenced by any current identity;
- old directories deleted after being verified empty; `entityctl doctor`
  is all green.

## Absorbing analysis scripts and environments

- **Shared scripts** (the method layer reused across cases/runs) go into
  `projects/<p>/analysis/scripts/`; data paths must be parameterized as
  CLI arguments. Existing hardcoded scripts go into the `scripts/legacy/`
  subdirectory and are not refused — record them with
  `--hardcoded-paths` and the dashboard reminds you. Copies synced by
  hand in various places are deduplicated with the workspace as the
  authority.
- **Case-level one-off scripts** are neither stored nor recorded; the
  agent manages them.
- **Historical analysis artifacts are not retroactively recorded**; new
  analyses start with `record analysis`.
- Existing analysis environments (venv/conda) are registered into the
  deps registry with `entityctl site deps-add <site> --kind analysis
  --from-checkpoint <json>` (the checkpoint's `selected.python` records
  the interpreter path; only its real existence on the site is required).
