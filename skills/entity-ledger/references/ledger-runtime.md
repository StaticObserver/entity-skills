# Ledger Runtime Reference

This is an internal/debugging reference. For normal work use the
`entityctl status`, `record` primitives, and `show` documented in
`SKILL.md`.

## Controller

`ledger.db` is the single structured authority. Schema v3 stores Sites,
Projects (project_uid + slug + root, 1:N Cases), Cases (with a
project_uid foreign key), identities, compact evidence, and events in
SQLite (events are passive audit). Large artifacts and logs remain on
their owner Site. Concurrency control is a `BEGIN IMMEDIATE` file lock;
the Operation/Step records of the old plan/apply protocol were archived
to `<ledger_home>/archive/` during the v1→v2 migration.

Resolution order for the controller home (the directory holding
ledger.db): explicit parameters (`--ledger-home` or
`ENTITY_LEDGER_HOME`) > the `ENTITY_WORKSPACE` environment variable
(`<workspace>/.ledger`) > the `~/.entity-ledger/active-workspace`
pointer > the legacy `~/.entity-ledger` (compatibility fallback, with a
one-time deprecation warning on stderr). The snapshots directory resolves
to the same home as the db.

Export without changing controller state:

```bash
python3 scripts/entityctl.py export --output /absolute/ledger-export.json
```

## record writes and receipts

Each record primitive first derives the identity locally in the
controller (content-addressed hash), then hands a structured envelope via
`ExecutorClient` to the executor on the execution Site. Writing
primitives carry their own evidence probes: the executor re-reads and
verifies the receipt/output fingerprints, and only when everything passes
does the primitive record the identity, the current projection, and the
audit event in a single SQLite transaction. Any failed step means zero
writes; fix the cause and rerun the same primitive.

Submitting a job (`record run-launch`) is an external effect that must
not be blindly replayed; internally the executor advances the receipt
through `intent_written → effect_observed → outputs_verified`: repeated
execution short-circuits on an already-verified receipt; when the process
is interrupted after submission but before verification, it finds the
uniquely matching submitted effect by launch comment in the
scheduler/process table and adopts it — it never submits twice. Multiple
matches are an anomaly — adopting any one of them is unsafe.

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
- **Receipt identity**: for runs that were prepared/inventoried before
  the rename, the receipts in their staging receipts record the old
  `plan_hash` (which embeds the old kind string). Rerunning prepare/data
  for the same run hits "existing receipt belongs to another Step". Fix:
  delete the run's old receipts under
  `<staging_root>/<case_uid>/<operation_id>/receipts/` and rerun the
  primitive.
- **In-flight job recovery**: in-flight jobs submitted before the rename
  carry a launch comment with the `entity-router:` prefix. Recovery
  matching (the squeue/sacct scan for Slurm and the pgrep scan for
  direct) accepts both the `entity-ledger:` and `entity-router:`
  prefixes, so old jobs are adopted rather than resubmitted; new
  submissions always use the `entity-ledger:` prefix.

## Executor transport

Local and SSH run the same `entity_ledger_executor.py`
validate/execute/verify logic and the same request envelope protocol, but
the invocation differs: on a local Site the `ExecutorClient` calls it
in-process (receipt persistence and allowed_roots checks are identical,
skipping the script copy, the request file, and the subprocess); on an
SSH Site a content-addressed executor copy is deployed to the remote and
invoked as a subprocess:

```text
<staging_root>/.entity-ledger-executor/<sha256>/entity_ledger_executor.py
```

The SSH transport only stages the exact payload/request JSON, invokes
actions on the whitelist, and returns structured results. Run submission
accepts a validated `run_spec`; the executor renders the submission
script selected by the Site profile's `scheduler.kind` — `slurm`
corresponds to an sbatch script, `direct` to a self-contained `run.sh`.
Caller-provided shell, commands, pre-commands, or script text are all
rejected.

The executable invocation inside the script is prefixed by
`compute.launcher`, resolved by the planner from the build's deps stack:
a stack whose signature has `mpi=false` (or no recorded stack, e.g. an
explicit `--executable`) renders a bare invocation; `mpi=true` renders
the Site policy's `mpi_launcher` (default `mpirun -np <tasks>`). `srun`
is only ever rendered when the policy explicitly selects it — several
MPI stacks (OpenMPI without PMIx) cannot be launched by srun, and
wrapping a non-MPI binary in srun would spawn `--ntasks` independent
duplicate processes. Run identities recorded before the launcher field
existed keep their historical rendering at launch time (slurm: srun,
direct: bare) so in-flight runs are unaffected.

The launch effect identity varies by backend. Slurm records
`{"scheduler": "slurm", "job_id": ..., "comment": ...}`; the direct
backend (Sites without a scheduler) records a detached process:

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

The authority for site information is the workspace's
`sites/<site>.yaml` profile (transport, scheduler, machine, site_root,
projects, deps registry, notes); `entityctl site sync` refreshes the
profile into the store, and `site list/show` gives a merged view of db +
profile. Sites from the old workflow's `site add` can still be written
directly into the db (flagged db-only in the merged view).

```bash
python3 scripts/entityctl.py site sync
python3 scripts/entityctl.py site list
```

When the profile carries `site_root`, new builds/runs/staging land in
`<site_root>/projects/<project>/{builds,runs,staging}/<case>/<id>`
(layout `site-tree`); legacy profiles without `site_root` need the three
independent roots `build_root`, `run_root`, and `staging_root` (layout
`legacy-roots`), and old Locators remain resolvable. A run Site must
also declare a transport and a scheduler (`slurm`, or `none` for Sites
without a scheduler). A policy may provide `default_cpus_per_gpu`,
`default_partition`, `default_qos`, `default_submit_user`,
`default_gres` (a Slurm gres spec `gpu[:type]:count`, e.g.
`gpu:V100:1`, used to pin the GPU type when a partition has several), and
`max_cpu_per_gpu`, and `mpi_launcher` (`srun`/`mpirun`/`mpiexec`, MPI
builds only; default `mpirun`, see the launcher rule above). gres
resolution order for a run: explicit `--gres` >
policy `default_gres` > generic `gpu:<N>`; the resolved value is recorded
in the run identity's compute. The direct backend ignores
`default_partition` and `default_qos` (they normalize to empty strings),
likewise ignores gres (normalized to ""), and defaults the submit user
to the current user. Secrets and cluster repair commands must never
appear in a profile or in the archive.

## Live status probing

The default status is controller-local and never writes state; only
`--live` touches the execution Site, and it makes at most three bounded
backend queries. On a Slurm Site: job status, an `sacct` fallback query
after the job leaves the queue, and an untracked-job scan of the Case run
root. On a Site without a scheduler: the exit file, a `kill -0` liveness
probe, and a foreign-process scan — when the Site refuses that scan, the
result degrades to `unknown` (never treated as a failure). `--live` also
reports `divergences`, classifying out-of-band changes: `job_gone` (the
backend has no record of a recorded job or process), `state_mismatch`
(the job reached a terminal state the Ledger never observed), and
`untracked_job` (a foreign scheduler job or process is running in the
Case run root — evidence that the record primitives were bypassed).
