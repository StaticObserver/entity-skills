---
name: entity-analysis
description: Analyze Entity simulation output with nt2py. Use when the user needs to load simulation data, generate diagnostic plots (fields, particles, spectra, phase-space), create movies/animations, write analysis scripts, or produce analysis reports. Covers the full analysis lifecycle from data loading through visualization to evidence-backed reporting.
---

# Entity-Analysis

> Archived: replaced by the narrower live `entity-nt2py` support skill. This
> file is historical and must not be loaded by the current Router.

## Mission

Help the Agent turn Entity simulation output into evidence-backed diagnostics, reusable analysis scripts, and clear reports. The agent uses **nt2py** as the primary data interface and learns to progressively narrow data, generate standard diagnostic plots, create movies, and structure findings into reports.

Core workflow:

```
Locate Data → Check Health → Lazy Load → Narrow → Diagnose → Visualize → Report
```

## Boundaries

**Handle**: Simulation output discovery, health checks (.err/.log/.info), nt2py data loading, lazy slicing, field/particle/spectra/diagnostics access, standard plots, movies/animations, diagnostic calculations, analysis script generation, report writing.

**Route to other skills**:
- Compilation, build environment, running simulations → `entity-env-build`
- PGen development, TOML configuration → `entity-pgen`
- Entity engine source modifications → `entity-core-dev`

## Hard Rules

1. **Always lazy-load first**: Use `nt2.Data()` which creates lazy containers. NEVER load everything into memory — always `.sel()`/`.isel()` before `.values`/`.load()`/`.compute()`
2. **Check health before analysis**: Read `.err` first if it exists, then `.info` for metadata, then `.csv` for quick stats overview
3. **Narrow before loading**: Filter by time, space, species BEFORE calling `.load()` or `.values`. This is critical for performance with large datasets
4. **Evidence strength is mandatory**: Every diagnostic finding must be labeled with evidence strength: `visual` / `numerical` / `regression` / `unresolved`
5. **Save scripts, not just images**: Every analysis session should produce a runnable Python script or notebook that reproduces the results
6. **Species index is 1-based** in Entity's output (sp=1, sp=2, ...)

## Reference Index

> All nt2py references are written based on Entity v1.4.x output format.

### Background Knowledge (Loaded in Step 1)

| Reference | Summary |
|-----------|---------|
| `knowledge/nt2py/01-data-loading.md` | nt2py installation, output file types, Data containers (fields/particles/spectra/diagnostics), lazy loading semantics |
| `knowledge/nt2py/02-fields.md` | Field data access, xarray slicing, basic plots, inspect accessor, movies/animations, spherical coordinates |
| `knowledge/nt2py/03-particles-stats.md` | Particle loading and filtering, phase-space plots, spectra plots, diagnostics/CSV, raw readers, tracking |

### Load by Task (Matched to Analysis Goals)

| Reference | When Needed | Trigger Keywords |
|-----------|-------------|------------------|
| `references/01-diagnostic-recipes.md` | Standard physics diagnostics needed | energy check, conservation, particle count, field energy, E·B, divergence, spectrum slope, growth rate |
| `references/02-report-generation.md` | Writing or structuring an analysis report | analysis report, writeup, findings summary, present results |
| `references/03-advanced-visualization.md` | Complex or custom visualizations | custom plot, multi-panel, animation, movie, publication figure, comparison plot |

## Analysis Workflow (7 Steps)

### Step 1: Locate Data & Check Health

**Always start here.** Ask the user or discover:

| Information | How to Obtain |
|-------------|---------------|
| Output directory | User provides, or `ls` the working directory |
| Simulation name | From TOML or directory listing |
| Entity commit | From `.info` file |
| TOML config | User provides path |
| PGen source | User provides path |

**Health checks** (in order):

1. **`.err` file**: Read first if it exists. Any content here means the simulation had errors/warnings
2. **`.info` file**: Confirm simulation parameters, compile flags, commit hash
3. **`.log` file**: Check for any abnormal termination messages at the end
4. **`.csv` stats**: Quick overview — plot `time` vs key columns (`E^2`, `B^2`, `T00`) to spot anomalies

Load background knowledge: `knowledge/nt2py/01-data-loading.md`

### Step 2: Clarify Analysis Goals

Ask the user what they want to learn. Common categories:

| Category | Example Questions | References Needed |
|----------|-------------------|-------------------|
| Field evolution | How do E/B fields evolve over time? | 02-fields |
| Particle dynamics | What is the particle energy distribution? | 03-particles-stats |
| Energy budget | Is total energy conserved? | 01-diagnostic-recipes |
| Spectra | What is the power-law index? | 03-particles-stats |
| Phase space | Are there instabilities or features? | 03-particles-stats |
| Custom diagnostic | User-defined quantity check | 01-diagnostic-recipes |
| Comprehensive report | Full simulation analysis | All references |

Record the analysis goals in a brief `analysis_plan.md`:

```markdown
# Analysis Plan — <simulation_name>

## Data
- Output path: <path>
- Entity commit: <from .info>
- Time range: <start> – <end>
- Output steps: <N>

## Questions
1. <question_1>
2. <question_2>

## Planned Diagnostics
| Diagnostic | Quantity | Reference |
|------------|----------|-----------|
| Field energy over time | B^2, E^2 from CSV | 01-diagnostic-recipes |
| Phase space at t=final | sp=1, x-ux | 03-particles-stats |
```

Present the plan to the user for confirmation before proceeding.

### Step 3: Load Data (Lazy)

```python
import nt2
import numpy as np
import matplotlib.pyplot as plt

data = nt2.Data("path/to/simulation_output")
```

Verify what's available:

```python
# Fields
print(list(data.fields.data_vars))
print(data.fields.coords)

# Species in particles
print(data.particles.sp)

# Time steps available
print(data.fields.t.values[:5])  # first 5
print(data.fields.t.values[-5:]) # last 5
```

Load `knowledge/nt2py/02-fields.md` and `knowledge/nt2py/03-particles-stats.md` as needed by the analysis plan.

### Step 4: Narrow & Compute Diagnostics

For each diagnostic in the plan, follow this pattern:

1. **Narrow** the lazy container to the specific subset needed
2. **Compute** the diagnostic (numerical value or reduced array)
3. **Document** the result

Example patterns:

```python
# Field energy trend (from CSV — already in memory)
stats = data.diagnostics  # or pd.read_csv for .csv
stats.plot(x="time", y=["E^2", "B^2"])

# Field slice at specific time
bz_slice = data.fields.Bz.sel(t=10.0, method="nearest").isel(y=128)

# Particle count per species over time
# (use diagnostics or compute from particle data)

# Energy spectrum at last step
spec = data.spectra.isel(t=-1)
```

Load `references/01-diagnostic-recipes.md` for standard diagnostic formulas.

### Step 5: Generate Visualizations

For each diagnostic, produce the appropriate plot:

| Data Type | Plot Method | Reference |
|-----------|-------------|-----------|
| 2D field slice | `.plot()` or `inspect.plot()` | 02-fields |
| 1D field profile | `.plot()` after spatial reduction | 02-fields |
| Phase space | `.phase_plot()` | 03-particles-stats |
| Energy spectrum | `.spectrum_plot()` or `.plot()` | 03-particles-stats |
| Time evolution | `.plot(x="time", y=...)` on CSV stats | 03-particles-stats |
| Multi-panel overview | `.inspect.plot()` | 02-fields |
| Spherical coordinates | `.polar.pcolor()` | 02-fields |

For movies, see `references/03-advanced-visualization.md`.

Save every figure with a descriptive name:
```python
plt.savefig("diagnostic_name.png", dpi=150, bbox_inches="tight")
```

### Step 6: Assess Evidence Strength

For each finding, assign one label:

| Label | Criteria |
|-------|----------|
| **visual** | Pattern visible in a plot but no quantitative check performed |
| **numerical** | Diagnostic calculated and compared to threshold/expectation |
| **regression** | Result compared against a previous run, benchmark, or analytic solution |
| **unresolved** | Data insufficient or diagnostics contradictory |

Upgrade labels when possible — a visual finding can be strengthened to numerical by computing the relevant diagnostic.

### Step 7: Write Report & Save Script

Load `references/02-report-generation.md` for report structure.

**Deliverables:**

```
analysis/<simulation_name>/
├── analysis_plan.md        # Analysis goals and planned diagnostics
├── analysis_report.md      # Findings with evidence strength
├── analyze.py              # Runnable analysis script
├── figures/                # Generated plots
│   ├── field_energy.png
│   ├── bz_slice_t100.png
│   ├── phase_space_sp1.png
│   └── energy_spectrum.png
└── movies/                 # Generated animations (if any)
    └── field_evolution.mp4
```

**Report to user:**
- Summary of key findings with evidence strength
- Path to deliverables
- "Script saved at `analyze.py`. Run with: `python analyze.py`"

## Quick Reference: Common Diagnostics

### Field Diagnostics
```python
# Field energy over time
data.fields.sel(x=slice(...), y=slice(...)).inspect.plot(
    name="fields_overview", only_fields=["E", "B", "N"]
)

# Check ∇·E vs ρ (charge conservation)
# Compare div(E) with Rho in the diagnostics

# E·B (alignment diagnostic)
edotb = sum(data.fields[f"E{i}"] * data.fields[f"B{i}"] for i in range(1,4))
edotb.mean("t").plot()
```

### Particle Diagnostics
```python
# Particle count per species
for sp in data.particles.sp.values:
    df = data.particles.sel(sp=sp).isel(t=-1).load()
    print(f"Species {sp}: {len(df)} particles")

# Phase space
data.particles.sel(sp=1).isel(t=-1).phase_plot(
    x_quantity=lambda f: f.x,
    y_quantity=lambda f: f.ux,
    xy_bins=(np.linspace(x_min, x_max, 100), np.linspace(u_min, u_max, 100)),
)

# Energy spectrum comparison
for sp in data.particles.sp.values:
    data.particles.sel(sp=sp).isel(t=-1).spectrum_plot()
```

### Energy Budget
```python
# From CSV stats
stats = data.diagnostics
stats["E_total"] = stats["E^2"] + stats["B^2"]
stats.plot(x="time", y="E_total")
```

## Agent Operations

### Handling "analyze my simulation" without specifics

1. Run Step 1 (locate data, health check)
2. Present what's available: field quantities, species count, time range
3. Ask the user which category of analysis they want (field evolution, particles, energy, comprehensive)
4. Proceed to Step 2

### Handling comparison between runs

When the user wants to compare two simulations:
1. Load both datasets: `data1 = nt2.Data("path1")`, `data2 = nt2.Data("path2")`
2. Normalize to common time/spatial coordinates if needed
3. Compute diagnostics on both, then difference/ratio
4. Label evidence strength as **regression**

### Handling "make a movie of X"

1. Load `references/03-advanced-visualization.md`
2. Use `data.fields.inspect.plot(name="movie_name", ...)` for standard quantities
3. Use `data.makeMovie(custom_func, name="movie_name")` for custom plots
4. Check output file exists and report path to user

### Handling custom diagnostic quantities

When the user asks for a derived quantity (e.g., vorticity, helicity):
1. Access the raw field components from `data.fields`
2. Compute the derived quantity using xarray operations (lazy)
3. Narrow to the specific time/space region
4. Plot and save
