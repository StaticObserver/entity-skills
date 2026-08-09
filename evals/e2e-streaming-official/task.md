# End-to-end Entity simulation task (official streaming PGen)

Run the controlled Entity simulation described by the supplied
`physics-spec.json` on the astro cluster (reachable via `ssh astro`), using
the **official `streaming` PGen** from the Entity source tree — you must NOT
write or modify any PGen source. `compile.pgen` is `streaming`.

## Architecture red lines (read first)

- The entity-ledger controller (`entityctl`) runs ONLY on the machine where
  you run. astro is a remote execution endpoint reached through the site's
  ssh transport. **Never copy entityctl, the workspace, or any skill
  tooling onto astro and never execute them there** — the Ledger drives the
  site over ssh; remote work happens through Slurm jobs and plain file
  operations.
- Before creating the workspace, confirm the location with the user
  (suggested default: under the project directory on this machine). Only
  run `workspace init` after the user confirms.

## Lifecycle

Complete the full lifecycle through the entity-ledger 0.7.0 workflow (every
step is required; the ledger records are part of the deliverables):

1. create a workspace (`entityctl workspace init` + `workspace adopt`) at
   the confirmed location, and inside it a project and a case
   (`project init` / `case init`);
2. register the astro site yourself: write a site archive
   (`sites/<site>.yaml`; format is documented in the entity-ledger
   `references/workspace-layout.md`), `site init` the Computation Site
   tree, `site discover` it, and `site sync` it into the store; then
   resolve the dependency stack with the full env-build flow
   (requirements.json → discovery of existing installs → checkpoint
   confirm → compatibility pass → env.sh) and register the verified stack
   (`site deps-add`); register the analysis Python environment the same
   way (`--kind analysis`);
3. write the input TOML for the official streaming PGen implementing the
   frozen `physics-spec.json`, and `docs/design.md` recording the rationale
   for every parameter choice (the PGen is official, so the design document
   justifies parameters, not code);
4. build Entity cleanly (CUDA, single GPU, no MPI) against the verified
   stack and register it (`record build`) — the login node forbids heavy
   work, so the build itself must run as a Slurm CPU-only job;
5. run the simulation exactly once within the stated resource budget via
   `render-run` → `record run-prepare` → `record run-launch` (a Slurm batch
   submission), and follow it to its terminal state with `record run-exit`;
6. inventory the outputs (`record data`), then inspect the data with nt2py
   and perform the requested analysis; book it with `record analysis`
   (script from the project `analysis/scripts/` library, output directory
   carrying an `analysis-manifest.json`);
7. write all required artifacts and a final `submission.json` that conforms
   to the supplied `submission.schema.json` (provided in this directory
   alongside `task.md` and `physics-spec.json`).

Site rules:

- All computation happens on the astro cluster. Do not use any other
  compute site.
- astro is a **Slurm cluster**: all heavy work — compilation, the
  simulation, and data analysis — goes through the scheduler. The login
  node is for light file operations only. Discover the partitions, GPU,
  QoS, toolchain, and writable roots yourself.
- **Do NOT set `--time` on any Slurm job. The walltime figure in
  `physics-spec.json` is the evaluation budget the oracle checks against,
  not a scheduler directive — leave the time limit to the partition/QoS
  defaults.**
- Run the simulation on a GPU, within the resource budget:
  1 GPU, 10 minutes walltime.
- Use CPU resources for data analysis; do not occupy a GPU for analysis.

Analysis deliverables (both required):

- `analysis/report.md`: analysis conclusions with supporting evidence;
- a rerunnable analysis script in the project `analysis/scripts/` library
  that reproduces the analysis from the raw run root (data paths must be
  CLI-parameterized; only genuinely legacy hard-coded scripts go to
  `analysis/scripts/legacy/` and are then registered with
  `--hardcoded-paths`).

Particle output stride must not exceed `output.particle_stride_max` in
`physics-spec.json`.

Resource locations are intentionally not specified. Discover the available
Entity source checkout, the dependency stack, and writable roots yourself.
Do not use the public network. Do not modify shared read-only content —
and in particular do not modify the official PGen source. Do not expose
credentials in source files, logs, or results. Keep analysis artifacts
outside the raw-data root.

If a required scientific or resource decision is genuinely missing, report
it precisely and stop before creating external effects. Do not silently
change the physics specification or resource ceiling.
