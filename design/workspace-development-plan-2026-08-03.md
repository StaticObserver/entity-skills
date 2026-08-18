# Workspace Development Plan

Date: 2026-08-03. Companion design: `design/workspace-and-computation-site-2026-08-03.md`.

The implementation order follows the dependencies: first the Workspace
container, then the Project/Case split, then the site profiles and file tree,
and finally env-build integration and migration. Each phase is independently
usable and testable.

## Phase 1: Workspace Container

Goal: `entityctl` understands workspaces, and the controller state location is
resolvable.

- `workspace.yaml` schema (workspace_id, schema_version, created_at,
  migrated_from).
- `entityctl workspace init <path>`: create the directory tree skeleton
  (workspace.yaml, projects/, sites/, .ledger/).
- `entityctl workspace adopt <path>`: write the
  `~/.entity-ledger/active-workspace` pointer; `workspace where` shows the
  currently active workspace.
- store resolution order: explicit argument > `ENTITY_WORKSPACE` environment
  variable > active-workspace pointer > legacy `~/.entity-ledger/ledger.db`
  (compatibility period, with a warning).
- Touches: `entity_ledger_store.py` (path resolution for opening the db),
  `entityctl.py` (new subcommands), `entity_ledger_common.py`.

## Phase 2: Project / Case Split

Goal: project 1:N cases, and cases have physical directories.

- store schema v3: the `projects` table becomes project entities
  (project_uid, slug, workspace-relative path); the `cases` table gains a
  `project_uid` foreign key. Write `store migrate` (upgrade the old root→case
  1:1 data to one default case per project).
- `entityctl project init <name>`: create `projects/<p>/` (project.yaml +
  source/ + cases/); `entityctl case init <project> <name>`: create
  `cases/<c>/` (intent.md, decisions.json) and record it in the ledger.
- `record intent` two-way sync: the db is primary, and writes are synced to
  `cases/<c>/intent.md`.
- status/show/dashboard output grouped by project → case; the semantics of the
  readiness board and run ledger are unchanged.
- Touches: `entity_ledger_store.py`, `entity_ledger_record.py`,
  `entity_ledger_facts.py`, `entity_ledger_dashboard.py`, `entityctl.py`,
  `tests/test_ledger_migrate.py`, plus new tests.

## Phase 3: Computation Site Profiles and File Tree

Goal: site profiles become structured and authoritative, and the on-site file
tree has conventions.

- Upgrade `templates/site-profile.schema.json`: `site_root`, the `deps[]`
  registry, the `projects[]` list; roots change from 5 independent roots to
  derived conventions (deps/checkouts/projects).
- `workspace/sites/<site>.yaml` is authoritative; `entityctl site sync`
  (profile → db) and `site list/show` (merged view of db + profile).
- `entityctl site init <site>`: create the `<site_root>` tree skeleton + the
  `entity-site.yaml` marker file on the target machine; extend `site
  discover`: probe and persist the machine profile (the machine section), and
  discover existing `entity-site.yaml` files (claim old trees).
- Path derivation switches to the new tree: Locator derivation for render-run
  and record build/run/data becomes
  `<site_root>/projects/<p>/{builds,runs,staging}/<case>/<id>`; old Locators
  remain referenceable until the full migration in phase 5.
- `site-notes/*.md` converter: prose goes into the notes section, with
  `astro-axion-site-profile.json` as a structured reference.
- Touches: `entity_ledger_common.py` (Locator derivation),
  `entity_ledger_remote.py`, `entityctl.py`, `references/workspace-layout.md`
  (rewrite), new `references/site-record.md`.

## Phase 4: deps registry and env-build Integration

Goal: solve problem 1 — "what environments have been used on this machine
before" becomes a single query.

- env-build's lookup order when resolving `requirements.json`: site profile
  deps registry → `entity-site.yaml` marker → on-the-spot probing to fill
  gaps; a hit stack directly reuses `deps/<stack_id>/env.sh`.
- After a new dependency stack is confirmed (`entity_checkpoint.py confirm` +
  compatibility pass), write it back to the site profile registry +
  `deps/<stack_id>/stack.yaml`.
- `entityctl site deps <site>`: list the registry (human-readable + `--json`).
- The checkpoint payload of `record build` gains a `stack_id` reference.
- Touches: `skills/entity-env-build/scripts/` (checkpoint/generate),
  `skills/entity-env-build/SKILL.md` and `references/`,
  `entity_ledger_record.py`.

## Phase 5: Migration Primitives and the Migration Skill

Goal: fully migrate the old layout into the new model. The approach is to
build the migration capability into the skill and the primitives, and after
rollout let the agent tidy things up in production following the skill —
rather than writing one big one-shot migration script.

- **Local absorption script** `entityctl workspace import` (one-shot, local
  only): move the whole directories `~/Documents/{axion-pic,bh-reconnection,polar_cap}`
  → `projects/`; move `~/.entity-ledger/ledger.db` + `snapshots/` →
  `.ledger/`; convert site-notes → `sites/*.yaml`; project-bindings → the
  per-project project.yaml. Dry-run by default; `--apply` actually acts; the
  old locations keep read-only copies, cleaned up manually by the user after
  doctor verification passes.
- **Migration primitives** (supporting the agent's remote tidying):
  - `entityctl site plan-migration <site>`: inventory the resources on the old
    tree (scan old roots, cross-check against ledger records) and output an
    "old path → new path" migration plan (JSON), without executing it;
  - `entityctl record relocate`: after a resource is moved, re-probe the
    evidence (hash/path) and update the Locator in the ledger; zero writes if
    the evidence does not match;
  - the move itself (ssh/rsync/mv) is orchestrated by the agent and is not
    wrapped into a primitive.
- **Migration guide**: `skills/entity-ledger/references/migration-guide.md` —
  target layout, movement rules, ordering and taboos (runs in flight are not
  touched — migrate them after `record run-exit` reaches a terminal state;
  inventory hashes before moving; verify with `doctor` after each step), plus
  a per-site checklist template.
- Migration completion criteria: the Locators of all current identities point
  at the new tree; old paths are no longer referenced; old directories are
  verified empty and deleted.

## Phase 6: Documentation and Wrap-up

- Sync the four SKILL.md files to the new model (ledger: workspace/case
  semantics; env-build: registry lookup; pgen: preflight target resolution;
  nt2py: data root comes from the run directory convention).
- Rewrite `references/workspace-layout.md`; update README and CHANGELOG.
- All tests green; add workspace/site-record/migrate tests.

## Explicitly Out of Scope for This Plan

Analysis management design (slots already reserved in phases 3/2); multiple
workspaces; git-ifying the workspace.

## Acceptance Criteria

- In a fresh agent session on any registered site: `site deps <site>` lists
  reusable environments, with no on-the-spot probing needed.
- `rsync` the workspace to another local path → `workspace adopt` → `status`
  output identical to the original location (except remote live state).
- Newly created projects/cases/builds/runs all land in the new file tree.
- Migration wrap-up: the old trees on all sites have been tidied per the
  migration guide, the Locators of all current identities point at the new
  paths, and the old directories have been emptied and deleted.
