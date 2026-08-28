---
name: entity-nt2py
description: Read, inspect, visualize, and export Entity simulation output with nt2py. Use for fields, particles, spectra, runtime diagnostics, plotting, movies, nt2 CLI, and bounded raw BP5/HDF5 access. This skill reads Run Data; it does not submit simulations or decide physical validity from names alone.
---

# Entity nt2py

Use nt2py as a flexible read-only interface to a Run's Data. Scientific
analysis stays open-ended; only actual data discovery, bounded loading, and
raw-data safety are fixed.

## Run/Data boundary

- Data is inseparable from its Run and lives under
  `<site_root>/projects/<project>/builds/<build-id>/runs/<run-id>/data/`.
- Inspect the Run JSON and exact TOML before assigning physical meaning to
  variables or normalization.
- Treat raw Data as read-only. Write scripts to the Project `scripts/`
  directory and results to the Run or Project analysis directory.
- A single-Run analysis belongs under that Run. A joint analysis records all
  input Run IDs under the Project analysis directory.
- Record an `analysis.json` when durable cross-session provenance is useful;
  do not force a report, notebook, registration step, or directory beyond the
  user's requested deliverable.

## Minimal rules

1. Inspect actual variables, dimensions, species, stored times, and installed
   nt2py version before writing concrete selections.
2. Select fields/spectra before `.values`, `.load()`, `.compute()`, or plotting.
   Select particle times/species and columns before `ParticleDataset.load()`.
3. Keep API facts, measured data, and physical interpretation distinct.
4. When creating an artifact, run the relevant code and verify the output.

For a concrete data root, use the bundled read-only probe when helpful:

```bash
python3 <entity-nt2py-skill>/scripts/inspect_nt2_data.py /path/to/data
```

## Reference routing

Read only the relevant file under `references/`:

| Task | Reference |
|---|---|
| install nt2py, locate/load data, diagnostics | `data-layout-and-loading.md` |
| fields, derived arrays, spectra | `fields-and-spectra.md` |
| particles | `particles.md` |
| plots, phase space, movies | `plotting-and-movies.md` |
| nt2 CLI or raw readers | `cli-and-raw-readers.md` |

The installed package and actual output take precedence over version-specific
examples in the references.
