# Router Runtime Reference

Use the Router-bundled state tool rather than editing `_case/` files directly:

Run these commands from the `skills/entity-router/` directory. If another
working directory is active, prefix script paths with the Router skill path.

```bash
python3 scripts/entity_router_state.py --help
```

All mutating commands require the revision most recently read from disk. A
revision conflict means another writer advanced the Case; re-read and decide
again instead of retrying blindly.

## Create and recover

```bash
python3 scripts/entity_router_state.py list --workdir "$ENTITY_WORKDIR"

python3 scripts/entity_router_state.py create \
  --workdir "$ENTITY_WORKDIR" \
  --case-id <case_id> \
  --entity-checkout <checkout> \
  --pgen <pgen> \
  --goal <goal> \
  --done-when <condition>

python3 scripts/entity_router_state.py show --case <case_dir>
python3 scripts/entity_router_state.py refresh \
  --case <case_dir> --expected-revision <revision>
python3 scripts/entity_router_state.py verify --case <case_dir>
```

Run `refresh` before choosing work after a resume, Case switch, checkout change,
or suspected external edit.

When adopting an existing workspace, inspect owner artifacts first and record
only proven readiness:

```bash
python3 scripts/entity_router_state.py reconcile \
  --case <case_dir> --expected-revision <revision> \
  --readiness pgen=verified --evidence pgen=<pgen_path> \
  --readiness build=pass --evidence build=<build_result>
```

Use `--observation run=<process_or_scheduler_evidence>` for dynamic evidence.
Use `update-memory` to record only compact decisions, open questions,
constraints, and handoff summaries; keep detailed design and logs in owner
files.

## Start an Action

```bash
python3 scripts/entity_router_state.py start-action \
  --case <case_dir> \
  --expected-revision <revision> \
  --action-id <unique_id> \
  --action-type <allowed_action> \
  --owner <owner> \
  --execution-domain <domain> \
  --goal <goal> \
  --input <path> \
  --read-root <path> \
  --write-root <path> \
  --expected-output <description> \
  --acceptance-check <check>
```

The command returns the immutable `request.json` path. Send a new Worker only:

```text
Use <owner skill or playbook> to execute <request.json>.
Read the request before acting. Do not write _case/. Return changed paths and
verification evidence.
```

Reuse an existing Worker only when its Case and execution domain both match.

## Close an Action

First inspect the Worker outputs yourself. Then record only verified paths:

```bash
python3 scripts/entity_router_state.py finish-action \
  --case <case_dir> \
  --expected-revision <revision> \
  --action-id <action_id> \
  --status completed \
  --output <verified_path> \
  --verification <performed_check> \
  --readiness pgen=verified \
  --next-action build.compile
```

Terminal statuses are `completed`, `failed`, `blocked`, and `cancelled`.
Outputs must exist within the Action write roots. Use readiness updates only
for dimensions actually proven by the Action.

## Suspend, resume, and complete

```bash
python3 scripts/entity_router_state.py suspend \
  --case <case_dir> --expected-revision <revision> --summary <handoff>

python3 scripts/entity_router_state.py resume \
  --case <case_dir> --expected-revision <revision>

python3 scripts/entity_router_state.py complete-workflow \
  --case <case_dir> --expected-revision <revision> \
  --summary <summary> \
  --verification <one_per_done_when> \
  --evidence <path>
```

After completing a Workflow, retain Case artifacts and start a new goal with
`new-workflow`. `suspend` and `complete-workflow` save history snapshots.
