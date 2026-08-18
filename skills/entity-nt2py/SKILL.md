---
name: entity-nt2py
description: Use nt2py to read, inspect, visualize, and export Entity simulation output. Applies to nt2py API questions and to work involving Entity fields, particles, spectra, runtime diagnostics, plotting, movies, the nt2 CLI, or raw BP5/HDF5 readers. This skill provides data-access knowledge and a read-only inventory probe; it does not prescribe physics diagnostic methods, nor does it judge whether a simulation is physically correct.
---

# Entity nt2py

Use nt2py as a flexible interface to Entity output. Scientific analysis stays
open-ended; only data discovery, memory usage, and raw-data safety are
constrained.

The accompanying references target nt2py v1.5.3. When the installed package
and the actual output disagree with the references, the installed package and
actual output take precedence.

## Boundaries

In scope:

- nt2py installation and data-root location;
- access to fields, particles, spectra, and runtime diagnostics;
- xarray/Dask selection, plotting, movies, and export;
- the `nt2` CLI and bounded raw-reader usage;
- derivation or visualization code for quantities chosen by the user.

Do not define the physical meaning, normalization, or validity of a quantity
from its variable name alone. When the interpretation is not established,
read the relevant TOML/PGen contract or ask the user. Diagnosing corrupted
output or failed runs is out of scope for this skill and should be handed off
elsewhere.

## Minimal rules

1. Before writing analysis against concrete data, inspect the actual
   variables, dimensions, species, and nt2py version. Do not infer them from
   the PGen name.
2. Select fields and spectra before `.values`, `.load()`, `.compute()`, or
   plotting. Select particle times/species and the needed columns before
   `ParticleDataset.load()`.
3. Treat the Entity data root as read-only. Always write plots, frames,
   notebooks, scripts, and exports elsewhere. The authoritative location of
   the data is the run directory itself: new layout
   `<site_root>/projects/<project>/runs/<case>/<run_id>` (old layout
   `<run_root>/<case_uid>/<run_id>`); the `record data` inventory manifest
   references paths inside the run directory, and fetched subsets go into the
   project area of the workspace.
4. Keep API facts separate from physical interpretation. Without the
   necessary simulation context, do not promote a visual pattern or variable
   name into a scientific conclusion.
5. When creating artifacts, run the relevant code and confirm the requested
   output actually exists. Do not impose reports, notebooks, scripts, or
   directory layouts the user did not ask for.
6. You organize the analysis execution freely; **registration** belongs to
   the Ledger: after the analysis is done, record it with
   `entityctl record analysis` (scripts come from the project's
   `analysis/scripts/` library, and the artifacts directory holds an
   `analysis-manifest.json`). This skill does not handle registration, nor
   does it judge whether a simulation is physically correct.

## Probing the actual output

For conceptual nt2py questions, read the relevant reference directly. When an
actual data root is available, run the read-only probe before choosing
concrete variables or selections:

```bash
python3 scripts/inspect_nt2_data.py /path/to/data-root
python3 scripts/inspect_nt2_data.py /path/to/data-root \
  --output /path/to/analysis/nt2-inventory.json
```

The probe prints JSON and optionally mirrors it to `--output`. It does not
call `print(data)`, particle `.nbytes`, particle `.load()`, or Dask
computation. It does initialize `nt2.Data`; the library's initialization
reads coordinate/binning information and, in v1.5.3, also reads the first
stored spectrum to determine shapes. The probe rejects output paths located
inside the data root. Treat its JSON as current evidence, not as a persistent
analysis state machine.

If the probe reports a version mismatch, use the inventory it discovered, and
check the installed nt2py source or documentation before relying on
version-specific examples.

## Reference routing

Read only the references the current task needs:

| Task | Reference |
|---|---|
| Install nt2py, locate the data root, initialize `nt2.Data`, inspect diagnostics | `references/data-layout-and-loading.md` |
| Select fields, build derived arrays, or use precomputed spectra | `references/fields-and-spectra.md` |
| Select, load, plot, or export particles | `references/particles.md` |
| Create xarray, inspect, polar, phase-space, or movie output | `references/plotting-and-movies.md` |
| Use the CLI or read exact BP5/HDF5 arrays | `references/cli-and-raw-readers.md` |

Prefer the high-level containers by default. Load the raw-reader reference
only when exact storage names/arrays are needed, or when a high-level
construction fails.
