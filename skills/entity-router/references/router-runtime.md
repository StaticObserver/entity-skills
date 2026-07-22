# Router Runtime Reference

This is an internal/debugging reference. Normal work uses `entityctl plan`,
`apply`, and `status` as documented in `SKILL.md`.

## Controller

`$ENTITY_ROUTER_HOME/router.db` (default `~/.entity-router/router.db`) is the
single structured authority. It stores Sites, Cases, project bindings,
identities, Operations, Steps, compact evidence, and events in SQLite. Large
artifacts and logs remain at their owner Sites.

Export without changing controller state:

```bash
python3 scripts/entityctl.py export --output /absolute/router-export.json
```

## Operation journal

Each Operation has an immutable Goal and Plan hash. Internal Steps advance:

```text
pending → intent_written → effect_observed → verified → committed
```

The execution Site owns a receipt for every Step. Apply records controller
intent, invokes the content-addressed executor, asks the executor to re-read and
verify the receipt/output fingerprints, then commits the Step plus identity and
current projection in one SQLite transaction.

A lost process, network interruption, or transient controller error leaves the
receipt/journal recoverable. Re-run Apply with the same Plan. Multiple scheduler
jobs matching one launch intent is terminal `anomaly` because adopting either
job would be unsafe.

## Executor transport

Local and SSH use the same `entity_router_executor.py` content and StepSpec. A
remote copy lives at:

```text
<staging_root>/.entity-router-executor/<sha256>/entity_router_executor.py
```

Transport only stages exact payloads/request JSON, invokes an allowlisted Step,
and returns structured results. Run submission accepts a validated `run_spec`;
the executor renders the scheduler script. Caller-provided shell, command,
pre-command, or script text is rejected.

## Site profiles

Sites are registered directly into the store:

```bash
python3 scripts/entityctl.py site add --profile /absolute/site-profile.json
python3 scripts/entityctl.py site list
```

Required run roots are `build_root`, `run_root`, and `staging_root`; a Slurm
run Site also declares transport and scheduler. Policy may supply
`default_cpus_per_gpu`, `default_partition`, `default_qos`,
`default_submit_user`, and `max_cpu_per_gpu`. Secrets and cluster
repair commands never belong in the profile.
