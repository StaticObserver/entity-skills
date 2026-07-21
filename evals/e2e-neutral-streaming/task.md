# End-to-end Entity simulation task

Build and run the controlled `neutral_streaming` Entity simulation described by
the supplied `physics-spec.json` on the supplied evaluation Site.

Complete the full lifecycle:

1. create a consistent `docs/design.md`, `pgen.hpp`, and Entity TOML input;
2. inspect and converge the requested CUDA environment;
3. perform a clean Entity build for this PGen;
4. submit exactly one Slurm job within the stated resource budget and wait for
   its terminal result;
5. inspect the produced data with nt2py and perform the requested field and
   particle analysis;
6. write all required artifacts and a final `submission.json` that conforms to
   the supplied schema.

Use the frozen Entity source and local dependency/source caches supplied by the
evaluation runtime. Do not use the public network. Do not modify protected
inputs or shared dependencies. Keep analysis artifacts outside the raw-data
root. Do not expose credentials in source files, logs, or results.

If a required scientific or resource decision is genuinely missing, report it
precisely and stop before creating external effects. Do not silently change the
physics specification or resource ceiling.
