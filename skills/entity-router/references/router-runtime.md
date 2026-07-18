# Router v3 Runtime Reference

Use the bundled tools. Put `--router-home` before the subcommand when using a
non-default controller root.

## Public controller entry

Prefer the compact provider-neutral façade for ordinary orientation and status:

```bash
python3 scripts/entityctl.py doctor
python3 scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  bundle install --source-root <entity-skills-repo>/skills
python3 scripts/entityctl.py project bind \
  --project-root /absolute/project --case <case_uid>
python3 scripts/entityctl.py inspect --project-root /absolute/project/subdir
python3 scripts/entityctl.py run-status --project-root /absolute/project \
  --job-id <job_id>
```

Bindings are stored at `~/.entity-router/project-bindings.json`. `inspect`
never contacts a remote site and normally returns at most 4 KiB. `run-status`
derives site/run root from the Case and makes at most one remote call.

`bundle install` is the supported multi-client publication path. It stores a
content-addressed bundle under `~/.entity-skills/bundles/`, atomically moves
`current`, projects client skill entries as symlinks, and retains replaced entries
under `~/.entity-skills/backups/`.

For attributable mutations, set `ENTITY_AGENT_RUN_ID` and optionally
`ENTITY_AGENT_PROVIDER`, `ENTITY_AGENT_CLIENT`, `ENTITY_AGENT_SESSION_ID`,
`ENTITY_AGENT_MODEL`, and `ENTITY_SKILLS_BUNDLE_HASH`. Set
`ENTITY_ROUTER_REQUIRE_ACTOR=1` to reject unattributed mutations. These fields
are audit provenance and never contain hidden reasoning.

## Coordinate multiple Agent writers

```bash
python3 scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  writer acquire --case <uid> --expected-revision <n> \
  --lease-id <lease-id> --ttl-seconds 900

python3 scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  --writer-lease-id <lease-id> writer handoff --case <uid> \
  --expected-revision <n> --new-lease-id <new-id> \
  --to-run-id <next-run-id> --to-provider <next-provider>
```

An active lease makes actor run ID plus lease ID mandatory for every Case
mutation. TTL is 60–3600 seconds. A mutating `flow execute/watch` requires a
lease; `inspect/check/run-status/writer status` remain lock-free read paths.
Acquire the lease before freezing a flow request or recording its base
revision: lease acquisition is itself a Case mutation, so a request created
from the preceding revision is intentionally rejected as stale.

## Register sites

```bash
python3 scripts/entity_router_site.py --router-home <control-root> add \
  --site-id laptop --transport local \
  --source-root /src --build-root /build --run-root /runs \
  --deps-root /deps --staging-root /stage --analysis-root /analysis

python3 scripts/entity_router_site.py --router-home <control-root> add \
  --site-id cluster --transport ssh --ssh-alias cluster-login \
  --scheduler slurm --source-root /shared/src --build-root /scratch/build \
  --run-root /scratch/run --deps-root /shared/deps --staging-root /shared/stage

python3 scripts/entity_router_site.py --router-home <control-root> verify --site-id cluster
```

## Create and recover a Case

```bash
python3 scripts/entity_router_state.py --router-home <control-root> create \
  --case-id <label> --controller-site laptop \
  --source-authority laptop:/src/entity \
  --pgen-locator laptop:/src/entity/src/pgen.hpp \
  --toml-locator laptop:/src/entity/input.toml \
  --design-locator laptop:/src/entity/docs/design.md \
  --build-root cluster:/scratch/build/<case_uid> \
  --run-root cluster:/scratch/run/<case_uid> \
  --data-root cluster:/scratch/run/<case_uid> \
  --analysis-root cluster:/scratch/analysis/<case_uid> \
  --transfer-policy git-ref --goal <goal>

python3 scripts/entity_router_state.py --router-home <control-root> list
python3 scripts/entity_router_state.py --router-home <control-root> rebuild-registry \
  --scan-root <control-root>/cases
python3 scripts/entity_router_state.py --router-home <control-root> show --case <uid-or-label>
python3 scripts/entity_router_state.py --router-home <control-root> refresh \
  --case <uid> --expected-revision <revision>
```

`case_uid` is immutable; `case_id` is only a label. All mutations use the last
read revision. A conflict requires rereading state.

## Source materialization

```bash
python3 scripts/entity_router_site.py --router-home <control-root> materialize \
  --mode git-ref --target cluster:/shared/stage/<case_uid>/<commit> \
  --repository <reachable-git-url> --commit <exact-commit>

python3 scripts/entity_router_site.py --router-home <control-root> materialize \
  --mode snapshot --source laptop:/src/entity \
  --target cluster:/shared/stage/<case_uid>
```

`shared` and `external` take both `--source` and `--target` and accept them only
when the observed revision fingerprints match. Remote authority snapshot work
executes as a Worker on the authority site; it does not make a local replica
editable.

## Start and finish an Action

Every path argument is a Locator:

```bash
python3 scripts/entity_router_state.py --router-home <control-root> start-action \
  --case <uid> --expected-revision <revision> \
  --action-id <id> --action-type <allowed-action> \
  --owner <owner> --execution-domain <domain> \
  --execution-site <site_id> --goal <goal> \
  --input <site:/path> --read-root <site:/path> --write-root <site:/path> \
  --expected-output <site:/path> --acceptance-check <check>

python3 scripts/entity_router_state.py --router-home <control-root> finish-action \
  --case <uid> --expected-revision <revision> --action-id <id> \
  --status completed --output <site:/path> \
  --verification <performed-check> --readiness <dimension=status>
```

The controller stages an immutable remote request, then probes outputs again
before completion. An unreachable site yields no current evidence; suspend or
block the Action until the site is reachable and probe again.

Authority transfer uses `source.transfer-authority` and completes with
`--new-authority <replica-locator>`.

## Read run status without an Action

For a bound Case, prefer `entityctl.py run-status`. For an exact unbound or
legacy run, use the one-shot read-only probe below. It does not
mutate Case state and makes at most one SSH call:

```bash
python3 scripts/entity_router_status.py --router-home <control-root> \
  --site-id cluster --run-root /scratch/run/<case_uid>/<run_id> \
  --scheduler slurm --job-id <job_id> \
  --progress-log logs/stdout.log --stderr-log logs/stderr.log \
  --fields-root data/fields --checkpoint-root data/checkpoints
```

For an unregistered legacy site, replace `--site-id cluster` with
`--ssh-alias <ssh-config-alias>`. Use `--pid <pid>` for a non-scheduler run and
add `--pid-start-ticks <ticks>` when `/proc` identity protection is available.
The default quick inventory is shallow; `--profile full` recursively totals
only matching field/checkpoint entries.

## Purge explicitly authorized data

Use `data.purge` only after `data.inspect` has established `data=partial` or
`data=ready`. The Action requires non-empty `--authorization` text. Declare
each deletion target as a write root, protect source/build/dependency and any
retained run paths, and put the expected purge receipt outside every deletion
target, normally under the registered staging root. A completed purge must set
`--readiness data=absent` or `data=partial`.

## Migrate v2

```bash
python3 scripts/entity_router_state.py --router-home <control-root> migrate-case \
  --legacy-case /old/problem --dry-run
python3 scripts/entity_router_state.py --router-home <control-root> migrate-case \
  --legacy-case /old/problem \
  --build-root <site:path> --run-root <site:path> \
  --data-root <site:path> --analysis-root <site:path> \
  --active-run <site:path> --active-run-id <run-id> --commit
```

Migration copies old control records into v3 evidence and suspends v2 only
after v3 validates. It does not move or delete source, build, run, or raw data.
If remote scope is discovered after migration, repair it with
`reconcile --resource-root DIMENSION=LOCATOR`. After the v3 Case verifies,
remove the suspended v2 controller and preserved full copy only through the
explicit cleanup gate:

```bash
python3 scripts/entity_router_state.py --router-home <control-root> finalize-migration \
  --case <uid> --expected-revision <n> \
  --authorization '<explicit user authorization>' --purge-control-copy
```

Finalization retains a manifest-hashed receipt under v3 `evidence/` and never
targets run or data resources.

## Default deterministic flow

Use the public façade for managed transactions:

```bash
python3 scripts/entityctl.py flow inspect --case <uid> --live --phase build
python3 scripts/entityctl.py flow execute --request <flow-request.json>
python3 scripts/entityctl.py flow execute --request <flow-request.json> \
  --prepare --step <n>
python3 scripts/entityctl.py flow execute --request <flow-request.json> \
  --resume --step <n> --worker-result <site:/absolute/result.json>
python3 scripts/entityctl.py flow watch --case <uid> --action <action-id> \
  --flow-request-hash <sha256:...> --interval-seconds 60 --timeout-seconds 86400
```

`execute` derives progress only from Case revision, immutable Action records,
and dispatch receipts. It refuses target drift, Action ID collisions, revision
drift, arbitrary shell fields, non-contiguous history, and blind scheduler
resubmission. Set `ENTITY_ROUTER_LEGACY_LOOP=1` only to recover a legacy Action
whose immutable request predates flow orchestration fields.
