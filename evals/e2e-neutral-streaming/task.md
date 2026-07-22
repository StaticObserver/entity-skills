# End-to-end Entity simulation task

Run the controlled Entity simulation described by the supplied
`physics-spec.json` on the siyuan cluster.

Complete the full lifecycle:

1. create a consistent `docs/design.md`, `pgen.hpp`, and Entity TOML input;
2. discover and converge a CUDA + MPI build environment for this PGen;
3. perform a clean Entity build (MPI enabled);
4. submit exactly one Slurm job within the stated resource budget and wait for
   its terminal result;
5. inspect the produced data with nt2py and perform the requested field and
   particle analysis;
6. write all required artifacts and a final `submission.json` that conforms to
   the supplied schema.

Site rules:

- All computation happens on the siyuan cluster. Do not use any other site.
- Do not compile on login nodes.
- Submit the GPU job to the `debuga100` partition, within the resource budget:
  1 node, 2 GPUs, 2 MPI tasks, 10 minutes walltime.
- Use CPU resources for data analysis; do not occupy GPU nodes for analysis.

Resource locations are intentionally not specified. Discover the available
Entity source, dependency sources, and writable roots yourself. Do not use the
public network. Do not modify shared read-only content. Do not expose
credentials in source files, logs, or results. Keep analysis artifacts
outside the raw-data root.

If a required scientific or resource decision is genuinely missing, report it
precisely and stop before creating external effects. Do not silently change
the physics specification or resource ceiling.
