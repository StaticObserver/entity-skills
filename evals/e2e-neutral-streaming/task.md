# End-to-end Entity simulation task

Run the controlled Entity simulation described by the supplied
`physics-spec.json` on the m87 host (reachable via `ssh m87`).

Complete the full lifecycle:

1. create a consistent `docs/design.md`, `pgen.hpp`, and Entity TOML input;
2. discover and converge a CUDA build environment for this PGen (no MPI);
3. perform a clean Entity build (MPI disabled);
4. run the simulation exactly once within the stated resource budget and wait
   for its completion;
5. inspect the produced data with nt2py and perform the requested field and
   particle analysis;
6. write all required artifacts and a final `submission.json` that conforms to
   the supplied `submission.schema.json` (provided in this directory alongside
   `task.md` and `physics-spec.json`).

Site rules:

- All computation happens on the m87 host. Do not use any other site.
- m87 is a personal single-GPU machine with no job scheduler (no Slurm) and
  no MPI. Discover the GPU, toolchain, and writable roots yourself.
- Run the simulation on the GPU, within the resource budget:
  1 GPU, 10 minutes walltime.
- Use CPU resources for data analysis; do not occupy the GPU for analysis.

Analysis deliverables (both required):

- `analysis/report.md`: analysis conclusions with supporting evidence;
- `analysis/analyze.py`: a rerunnable script that reproduces the analysis
  from the raw data root.

Particle output stride must not exceed `output.particle_stride_max` in
`physics-spec.json`.

Resource locations are intentionally not specified. Discover the available
Entity source, dependency sources, and writable roots yourself. Do not use the
public network. Do not modify shared read-only content. Do not expose
credentials in source files, logs, or results. Keep analysis artifacts
outside the raw-data root.

If a required scientific or resource decision is genuinely missing, report it
precisely and stop before creating external effects. Do not silently change
the physics specification or resource ceiling.
