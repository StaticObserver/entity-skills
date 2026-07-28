# Ledger Runtime Reference

This is an internal/debugging reference. For normal work use the
`entityctl status`, `record` primitives, and `show` documented in
`SKILL.md`.

## Controller

`$ENTITY_LEDGER_HOME/ledger.db` (default `~/.entity-ledger/ledger.db`) is
the single structured authority. Schema v2 stores Sites, Cases, project
bindings, identities, compact evidence, and events in SQLite (events are
passive audit). Large artifacts and logs remain on their owner Site.
Concurrency control is a `BEGIN IMMEDIATE` file lock; the Operation/Step
records of the old plan/apply protocol were archived to
`<ledger_home>/archive/` during the v1→v2 migration.

Export without changing controller state:

```bash
python3 scripts/entityctl.py export --output /absolute/ledger-export.json
```

## record writes and receipts

Each record primitive first derives the identity locally in the controller
(content-addressed hash), then hands a structured envelope via
`ExecutorClient` to the executor on the execution Site. Writing primitives
carry their own evidence probes: the executor re-reads and verifies the
receipt/output fingerprints, and only when everything passes does the
primitive record the identity, the current projection, and the audit event
in a single SQLite transaction. Any failed step means zero writes; fix the
cause and rerun the same primitive.

Submitting a job (`record run-launch`) is an external effect that must not
be blindly replayed; internally the executor advances the receipt through
`intent_written → effect_observed → outputs_verified`: repeated execution
short-circuits on an already-verified receipt; when the process is
interrupted after submission but before verification, it finds the uniquely
matching submitted effect by launch comment in the scheduler/process table
and adopts it — it never submits twice. Multiple matches are an anomaly —
adopting any one of them is unsafe.

## Rename and storage migration boundaries

The entity-router → entity-ledger rename introduces three compatibility
boundaries:

- **Storage directory and database**: the first time the Ledger home is
  resolved, `~/.entity-router` is automatically migrated to
  `~/.entity-ledger` (the `router.db` inside the home is renamed to
  `ledger.db` along with it). Migration is lazy — it only happens when a
  command actually resolves the home, and is not triggered during parser
  construction phases such as `--help`. The `ENTITY_ROUTER_HOME`
  environment variable is still honored (when `ENTITY_LEDGER_HOME` is not
  set).
- **Receipt identity**: for runs that were prepared/inventoried before the
  rename, the receipts in their staging receipts record the old
  `plan_hash` (which embeds the old kind string). Rerunning prepare/data
  for the same run hits "existing receipt belongs to another Step". Fix:
  delete the run's old receipts under
  `<staging_root>/<case_uid>/<operation_id>/receipts/` and rerun the
  primitive.
- **In-flight job recovery**: in-flight jobs submitted before the rename
  carry a launch comment with the `entity-router:` prefix. Recovery
  matching (the squeue/sacct scan for Slurm and the pgrep scan for direct)
  accepts both the `entity-ledger:` and `entity-router:` prefixes, so old
  jobs are adopted rather than resubmitted; new submissions always use the
  `entity-ledger:` prefix.

## Executor transport

Local and SSH run the same `entity_ledger_executor.py` validate/execute/verify
logic and the same request envelope protocol, but the invocation differs: on a
local Site the `ExecutorClient` calls it in-process (receipt persistence and
allowed_roots checks are identical, skipping the script copy, the request
file, and the subprocess); on an SSH Site a content-addressed executor copy
is deployed to the remote and invoked as a subprocess. The remote copy lives
at:

```text
<staging_root>/.entity-ledger-executor/<sha256>/entity_ledger_executor.py
```

The SSH transport only stages the exact payload/request JSON, invokes actions
on the whitelist, and returns structured results. Run submission accepts a
validated `run_spec`; the executor renders the submission script selected
by the Site profile's `scheduler.kind` — `slurm` corresponds to an sbatch
script, `direct` to a self-contained `run.sh`. Caller-provided shell,
commands, pre-commands, or script text are all rejected.

The launch effect identity varies by backend. Slurm records
`{"scheduler": "slurm", "job_id": ..., "comment": ...}`; the direct backend
(Sites without a scheduler) records a detached process:

```json
{"scheduler": "direct", "pid": 418795, "pgid": 418795,
 "run_root": "...", "log": "<run_root>/run.log",
 "exit_file": "<run_root>/.entity-exit-code", "comment": "entity-ledger:..."}
```

The launched process is a session leader (`pid == pgid`); the walltime is
enforced by `timeout` inside `run.sh` (or an inline bash equivalent), and
the exit code — including 124 on timeout — is written to the exit file.
Recovery claims an interrupted launch by scanning for the launch comment
with `pgrep -f` and matching the process working directory, and only
adopts a unique match.

## Site profile

Sites are registered directly into the store:

```bash
python3 scripts/entityctl.py site add --profile /absolute/site-profile.json
python3 scripts/entityctl.py site list
```

The required runtime roots are `build_root`, `run_root`, and
`staging_root`; a run Site must also declare a transport and a scheduler
(`slurm`, or `none` for Sites without a scheduler). A policy may provide
`default_cpus_per_gpu`, `default_partition`, `default_qos`,
`default_submit_user`, and `max_cpu_per_gpu`. The direct backend ignores
`default_partition` and `default_qos` (they normalize to empty strings)
and defaults the submit user to the current user. Secrets and cluster
repair commands must never appear in a profile.

## Live status probing

The default status is controller-local and never writes state; only
`--live` touches the execution Site, and it makes at most three bounded
backend queries. On a Slurm Site: job status, an `sacct` fallback query
after the job leaves the queue, and an untracked-job scan of the Case run
root. On a Site without a scheduler: the exit file, a `kill -0` liveness
probe, and a foreign-process scan — when the Site refuses that scan, the
result degrades to `unknown` (never treated as a failure). `--live` also
reports `divergences`, classifying out-of-band changes: `job_gone` (the
backend has no record of a recorded job or process), `state_mismatch` (the
job reached a terminal state the Ledger never observed), and
`untracked_job` (a foreign scheduler job or process is running in the Case
run root — evidence that the record primitives were bypassed).
