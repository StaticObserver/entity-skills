# Resume Simulation

Use for checkpoint continuation. Execute in the `playbook-run` domain.

1. Read the parent manifest, immutable input, logs, and checkpoint evidence.
2. Verify parent checkout, executable, PGen, compile options, and checkpoint
   format against the intended continuation.
3. Create a new run identity. Never overwrite the parent run.
4. Copy or derive a new `input.toml`; record every changed parameter.
5. Create a new manifest with `parent_run` and `parent_checkpoint` provenance.
6. Follow `run-simulation.md` from `run.launch` onward.
7. Preserve both manifests and checkpoint fingerprints.

Stop before launch when compatibility is uncertain. Route an established PGen
or build cause to its owner through a new Action; otherwise preserve evidence
for `failure.triage`.
