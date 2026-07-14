# Run Simulation

Use when verified PGen/TOML and a matching executable exist. Execute run work
in the `playbook-run` domain; this is Router-owned behavior, not a run skill.

## `run.prepare`

Preconditions:

- exact checkout, PGen, TOML, executable, and compile identity are known;
- `pgen=verified` and `build=pass` evidence is current;
- run label and compute resources are explicit;
- the target run directory does not already contain a launched identity.

Procedure:

1. Create a new `problems/<case_id>/run-<label>/`.
2. Create `data/`, `logs/`, and `analysis/`.
3. Copy the verified TOML to immutable `input.toml`.
4. Instantiate `templates/run-manifest.yaml` with absolute provenance and
   input/build hashes; set state `prepared`.
5. Verify the launch command without submitting it.
6. Close the Action with `run=prepared` and manifest evidence.

## `run.launch`

1. Re-read the prepared manifest and compare all fingerprints.
2. Execute from `data/`; write stdout, stderr, submission script, and scheduler
   ID under the run directory.
3. Record `submitted` or `running` only after process/scheduler evidence.
4. Never mutate `input.toml` after launch.

## `run.monitor`

1. Query the actual process or scheduler; do not trust manifest state alone.
2. Inspect exit status and latest logs.
3. Record `completed`, `failed`, or `stopped` with timestamps and evidence.
4. Set data readiness from actual output inventory, not run completion alone.

Never reuse a run directory for changed parameters. Never claim completion
without exit or equivalent scheduler evidence.
