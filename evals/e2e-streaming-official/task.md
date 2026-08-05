# End-to-end Entity simulation task (official streaming PGen)

Run the controlled Entity simulation described by the supplied
`physics-spec.json` on the m87 host (reachable via `ssh m87`), using the
**official `streaming` PGen** from the Entity source tree — you must NOT
write or modify any PGen source. `compile.pgen` is `streaming`.

Complete the full lifecycle through the entity-ledger 0.7.0 workflow (every
step is required; the ledger records are part of the deliverables):

1. create a workspace (`entityctl workspace init` + `workspace adopt`) and
   inside it a project and a case (`project init` / `case init`);
2. register the m87 site archive with legacy roots (no `site_root` — m87
   predates the site tree) and sync it (`site sync`); query the deps
   registry (`site deps m87`) for the already-verified build stack and
   reuse it — register a new stack with `site deps-add` only if nothing
   verified matches;
3. write the input TOML for the official streaming PGen implementing the
   frozen `physics-spec.json`, and `docs/design.md` recording the rationale
   for every parameter choice (the PGen is official, so the design document
   justifies parameters, not code);
4. build Entity cleanly (CUDA, single GPU, no MPI) against the verified
   stack and register it (`record build`);
5. run the simulation exactly once within the stated resource budget via
   `render-run` → `record run-prepare` → `record run-launch`, and follow it
   to its terminal state with `record run-exit`;
6. inventory the outputs (`record data`), then inspect the data with nt2py
   and perform the requested analysis; book it with `record analysis`
   (script from the project `analysis/scripts/` library, output directory
   carrying an `analysis-manifest.json`);
7. write all required artifacts and a final `submission.json` that conforms
   to the supplied `submission.schema.json` (provided in this directory
   alongside `task.md` and `physics-spec.json`).

Site rules:

- All computation happens on the m87 host. Do not use any other site.
- m87 is a personal single-GPU machine (RTX 4070 Ti) with **no job
  scheduler** (no Slurm — the direct backend) and no MPI. Discover the GPU,
  toolchain, and writable roots yourself.
- Run the simulation on the GPU, within the resource budget:
  1 GPU, 10 minutes walltime.
- Use CPU resources for data analysis; do not occupy the GPU for analysis.

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
Entity source checkout, the dependency stack, and writable roots yourself —
the existence of a previously verified dependency stack on m87 is
discoverable through `site deps`. Do not use the public network. Do not
modify shared read-only content — and in particular do not modify the
official PGen source. Do not expose credentials in source files, logs, or
results. Keep analysis artifacts outside the raw-data root.

If a required scientific or resource decision is genuinely missing, report
it precisely and stop before creating external effects. Do not silently
change the physics specification or resource ceiling.
