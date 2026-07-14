# nt2py: Particles, Spectra, Stats & Raw Readers (Archived)

## Working with Particles

Particles use a special lazy container. Access like xarray, then call `.load()`.

### Selection

```python
# Select specific species
data.particles.sel(sp=[1, 2])

# Select by time
data.particles.sel(t=1.0, method="nearest")

# Chain then load into pandas DataFrame
df = data.particles.sel(sp=[1, 2, 4]).isel(t=-1).load()
```

### Particle Variables

| Variable | Description |
|----------|-------------|
| `X` | Spatial coordinates (x1, x2, x3) |
| `U` | Four-velocities (ux1, ux2, ux3) |
| `W` | Particle weights |
| `PLDR` | Real-valued payloads |
| `PLDI` | Integer-valued payloads |
| `RNK` | MPI rank |
| `IDX` | Particle index |

### Phase-Space Plots

```python
data.particles.sel(sp=1).sel(t=1.0, method="nearest").phase_plot(
    x_quantity=lambda f: f.x,
    y_quantity=lambda f: f.ux,
    xy_bins=(
        np.linspace(0, 60, 100),    # X bins
        np.linspace(-2, 2, 100),    # U bins
    ),
)
```

### Spectrum Plots

```python
# Energy spectrum for selected species
data.particles.sel(sp=[1, 2]).sel(t=1.0, method="nearest").spectrum_plot()
```

## Working with Pre-computed Spectra

```python
spectrum = data.spectra.sel(t=10.0, method="nearest")
spec_sp1 = spectrum.sel(sp=1)
spec_sp1.plot()
```

## Particle Tracking (v1.3.0+)

When `tracking = true` for a species, each particle gets a unique `(IDX, RNK)` pair. nt2py auto-combines them:

```python
particles = data.particles.sel(sp=1).load()
unique_ids = particles["id"]  # Combined unique identifier
```

Note: GPU simulations are **not bitwise reproducible** — particle IDs differ between runs.

## Diagnostics & CSV Stats

```python
# Diagnostics table
diag = data.diagnostics  # pandas DataFrame
print(diag.columns)

# CSV stats (box-averaged scalars per timestep)
import pandas as pd
stats = pd.read_csv("simulation_name.csv")
stats.plot(x="time", y="B^2")
stats.plot(x="time", y=["E^2", "B^2", "T00"])
```

## Raw Readers (Bypassing xarray)

For direct file access without lazy loading overhead:

```python
import nt2.readers.adios2 as nt2a

reader = nt2a.Reader()

# Get valid output steps
valid_steps = reader.GetValidSteps("path/to/sim", "particles")

# Get variable names at a step
variables = reader.ReadCategoryNamesAtTimestep(
    "path/to/sim", "particles", "p", valid_steps[0]
)

# Read a specific array
arr = reader.ReadArrayAtTimestep(
    "path/to/sim", "particles", variable_name, valid_steps[0]
)
```

For HDF5, use `nt2.readers.hdf5.Reader` — same interface.

## Custom Analysis Script Template

```python
import nt2
import numpy as np
import matplotlib.pyplot as plt

data = nt2.Data("path/to/simulation_output")

# --- Time-averaged field ---
data.fields.Bz.mean("t").plot()
plt.savefig("Bz_mean.png")
plt.close()

# --- Energy spectrum at last timestep ---
spec = data.spectra.isel(t=-1)
for sp in spec.sp.values:
    spec.sel(sp=sp).plot(label=f"Species {sp}")
plt.legend()
plt.savefig("energy_spectrum.png")
plt.close()

# --- Phase space at last timestep ---
data.particles.sel(sp=1).isel(t=-1).phase_plot(
    x_quantity=lambda f: f.x,
    y_quantity=lambda f: f.ux,
    xy_bins=(np.linspace(0, 60, 100), np.linspace(-2, 2, 100)),
)
plt.savefig("phase_space.png")
plt.close()

# --- Field movie ---
data.fields.sel(x=slice(-0.2, 0.2)).inspect.plot(
    name="field_evolution",
    only_fields=["E", "B", "N"]
)
```

## Tips

- Use **BP5 format** over HDF5 for better performance
- Always `.sel()` before `.load()` to avoid loading the entire dataset
- For large datasets, use `downsampling` in TOML output config to reduce file size
- Spherical coordinate plots use the `.polar` accessor
- Filter particles by species with `.sel(sp=[...])` before loading
- CSV stats are fully in memory — good for quick time-evolution checks
