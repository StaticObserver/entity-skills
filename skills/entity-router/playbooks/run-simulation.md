# Run Simulation

Use when verified PGen/TOML and a matching executable exist. Execute run work
in the `playbook-run` domain; this is Router-owned behavior, not a run skill.

## `run.prepare`

Preconditions:

- exact source revision/snapshot, TOML, executable, build ID, and their site
  Locators are known;
- `pgen=verified`, `source=ready`, and `build=pass` evidence is current;
- run label and compute resources are explicit;
- the immutable run ID is new and its target Locator does not exist.

Procedure:

1. Allocate `<run_root>/<case_uid>/<run_id>` (or a registered compatible
   existing convention) at the run site; never reuse it.
2. Create only the run-site subpaths required by the launch contract.
3. Materialize the verified TOML as immutable `input.toml`.
4. Instantiate `templates/run-manifest.yaml` with structured Locators, source
   revision, build ID, input/build hashes, and execution site.
5. Verify the launch command without submitting it.
6. Close the Action with `run=prepared` and manifest evidence.

## `run.launch`

1. Re-read the prepared manifest and compare all fingerprints.
2. Execute at the manifest's run site; write stdout, stderr, submission script,
   and scheduler ID under the immutable run root.
3. Record `submitted` or `running` only after process/scheduler evidence.
4. Never mutate `input.toml` after launch.

## `run.monitor`

1. Query the actual process or scheduler through a fresh site probe; do not
   trust manifest or cached observation state alone.
2. Inspect exit status and latest logs.
3. Record `completed`, `failed`, or `stopped` with timestamps and evidence.
4. Set data readiness from actual output inventory, not run completion alone.

Never reuse a run directory for changed parameters. Never claim completion
without exit or equivalent scheduler evidence.
