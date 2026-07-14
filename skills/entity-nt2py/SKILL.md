---
name: entity-nt2py
description: Read, inspect, visualize, and export Entity simulation output with nt2py. Use for nt2py API questions and for work with Entity fields, particles, spectra, runtime diagnostics, plots, movies, the nt2 CLI, or raw BP5/HDF5 readers. This skill supplies data-access knowledge and a read-only inventory probe; it does not prescribe physics diagnostics or judge whether a simulation is physically correct.
---

# Entity nt2py

Use nt2py as a flexible interface to Entity output. Keep the scientific analysis
open-ended; constrain only data discovery, memory use, and raw-data safety.

The bundled references target nt2py v1.5.3. Treat the installed package and the
actual output as authoritative when they differ from the references.

## Boundaries

Handle:

- nt2py installation and data-root discovery;
- fields, particles, spectra, and runtime diagnostics access;
- xarray/Dask selection, plotting, movies, and export;
- the `nt2` CLI and bounded raw-reader use;
- code that derives or visualizes quantities chosen by the user.

Do not define the physical meaning, normalization, or validity of a quantity
from its name alone. Read the relevant TOML/PGen contract or ask the user when
the interpretation is not already established. Route corrupted-output or run
failure diagnosis outside this skill.

## Minimal Rules

1. Inspect actual variables, dimensions, species, and nt2py version before
   writing data-specific analysis. Do not infer them from a PGen name.
2. Select fields and spectra before `.values`, `.load()`, `.compute()`, or
   plotting. Select particle time/species and requested columns before
   `ParticleDataset.load()`.
3. Treat the Entity data root as read-only. Write plots, frames, notebooks,
   scripts, and exports elsewhere.
4. Separate API facts from physics interpretation. Do not promote a visual
   pattern or a variable name into a scientific conclusion without the needed
   simulation context.
5. When creating an artifact, run the relevant code and check that the requested
   output exists. Do not impose a report, notebook, script, or directory format
   when the user did not ask for one.

## Probe Actual Output

For a conceptual nt2py question, read the relevant reference directly. When an
actual data root is available, run the read-only probe before choosing concrete
variables or selections:

```bash
python3 scripts/inspect_nt2_data.py /path/to/data-root
python3 scripts/inspect_nt2_data.py /path/to/data-root \
  --output /path/to/analysis/nt2-inventory.json
```

The probe prints JSON and optionally mirrors it to `--output`. It does not call
`print(data)`, particle `.nbytes`, particle `.load()`, or Dask computation. It
does initialize `nt2.Data`; that library initialization reads coordinates/bin
information and, in v1.5.3, the first stored spectrum while determining its
shape. The probe rejects an output path inside the data root. Treat its JSON as
current evidence, not as a persistent analysis state machine.

If the probe reports a version mismatch, use its discovered inventory and check
the installed nt2py source or documentation before relying on version-specific
examples.

## Reference Routing

Read only the references needed for the current task:

| Task | Reference |
|---|---|
| Install nt2py, locate the data root, initialize `nt2.Data`, inspect diagnostics | `references/data-layout-and-loading.md` |
| Select fields, build derived arrays, or use precomputed spectra | `references/fields-and-spectra.md` |
| Select, load, plot, or export particles | `references/particles.md` |
| Create xarray, inspect, polar, phase-space, or movie output | `references/plotting-and-movies.md` |
| Use the CLI or read exact BP5/HDF5 arrays | `references/cli-and-raw-readers.md` |

Use the high-level containers by default. Load the raw-reader reference only
when exact stored names/arrays are required or high-level construction fails.
