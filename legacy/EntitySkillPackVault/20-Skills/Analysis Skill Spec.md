# Analysis Skill Spec

## Mission

Turn Entity output into evidence-backed diagnostics and reusable analysis artifacts.

## Core Tools

Use nt2py when available:

- `nt2.Data(...)`;
- `data.fields`;
- `data.particles`;
- `data.spectra`;
- `data.diagnostics`;
- use raw readers when lazy xarray access is not appropriate.

## Required Inputs

Collect:

- output path;
- simulation name;
- Entity commit, when known;
- TOML and pgen paths, when available;
- analysis question;
- target quantities;
- species;
- time range or output steps.

## Workflow

1. Locate the output directory and metadata files.
2. If a `.err` file exists, check it first.
3. Check `.info`, `.log`, and stats CSV.
4. Lazy-load the data.
5. Narrow the scope by time, space, and species before loading into memory.
6. Produce diagnostics and plots.
7. State the evidence strength and caveats.
8. Save the analysis script or notebook when valuable.
9. Write the analysis report.

## Evidence Strength

| Label | Meaning |
| --- | --- |
| visual | Images suggest a pattern, but no quantitative check has been done yet. |
| numerical | Computed diagnostics support the claim. |
| regression | Compared against an old run, a benchmark, or an analytic expectation. |
| unresolved | Data is insufficient or diagnostics contradict each other. |

## Common Diagnostics

- particle counts per species;
- field energy and particle energy;
- `E.B` and `B^2`;
- charge density and divergence consistency;
- spectra and phase-space plots;
- whether an output quantity exists and its units;
- continuity after a checkpoint restart.
