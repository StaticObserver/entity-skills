# Particles

Use this reference whenever you read, select, plot, or export particle output. In nt2py v1.5.3, particles are not an xarray dataset; they use a custom Dask-backed `ParticleDataset` whose `.load()` returns a pandas DataFrame.

## Contents

- Discovering the container
- Select before loading
- Load only the columns you need
- Particle IDs
- Built-in particle plots
- Missing quantities
- Source references

## Discovering the container

```python
particles = data.particles
if particles is None:
    raise ValueError("This output has no readable particles")

print(particles.species)
print(particles.steps)
print(particles.times)
print(particles.columns)
print(particles.selection)
```

`particles.nbytes` is not a cheap metadata property. It computes Dask memory usage for the particle index and may touch every selected particle output.

Do not use `data.particles.sp`; that attribute does not exist. Species are listed via `.species` and selected via `.sel(sp=...)`.

Default coordinate and momentum names:

| Coordinate system | Positions | Momenta/four-velocities | Other |
|---|---|---|---|
| Cartesian | `x`, `y`, `z` | `ux`, `uy`, `uz` | `w`, `id`, `sp` |
| Spherical | `r`, `th`, `ph` | `ur`, `uth`, `uph` | `w`, `id`, `sp` |

Only quantities actually present in the output appear in `.columns`.

## Select before loading

`.sel()` supports only physical time `t`, simulation step `st`, species `sp`, and particle ID `id`:

```python
selected = (
    particles
    .sel(t=10.0, method="nearest")
    .sel(sp=[1, 2])
)
```

Selectors can be scalars, lists, slices, or two-tuples. `method="nearest"` is useful for physical time; `st`, `sp`, and `id` are always exact selections.

`.isel()` supports only the time/step axis:

```python
last = particles.isel(t=-1)
some_outputs = particles.isel(t=[0, 5, -1])
```

Chained selections intersect. An empty intersection yields an empty selection rather than silently restoring all particles.

## Load only the columns you need

Call `.load(cols=...)` only after reducing time and species:

```python
df = (
    particles
    .isel(t=-1)
    .sel(sp=1)
    .load(cols=["x", "ux", "w"])
)

print(df.columns)
```

The returned DataFrame also keeps the index columns `id`, `sp`, `st`, and `t`. Passing `cols` reduces the particle arrays read from disk; omitting it requests all available columns.

### Spatial filtering limitation

Particle `.sel()` does not accept `x`, `y`, `z`, `r`, `th`, or `ph`. Reduce timesteps, species, and columns first, then filter the loaded DataFrame:

```python
df = particles.isel(t=-1).sel(sp=1).load(cols=["x", "y", "ux"])
region = df[df["x"].between(-1.0, 1.0) & df["y"].between(-2.0, 2.0)]
```

This still reads the requested columns for every selected particle. For very large dumps, narrow the output timesteps/species first, or use the raw-reader workflow; do not claim that nt2py pushes predicates down onto spatial coordinates.

## Particle IDs

nt2py constructs `id` as follows:

- If a species has `pIDX` and `pRNK`, combine them with Cantor pairing;
- if it has `pIDX` but no rank, use the index directly;
- if there is no tracked index, use `-100` as a placeholder.

Therefore `id` is a unique tracking key only when the Entity output contains the required tracking quantities. Check the output configuration before comparing IDs across times or across runs.

## Built-in particle plots

Select first, because both methods call `.load()` internally.

```python
import numpy as np
import matplotlib.pyplot as plt

p = data.particles.isel(t=-1).sel(sp=1)
p.phase_plot(
    x_quantity=lambda df: df["x"].to_numpy(),
    y_quantity=lambda df: df["ux"].to_numpy(),
    xy_bins=(np.linspace(-5, 5, 101), np.linspace(-10, 10, 101)),
)
plt.savefig("phase-space.png", dpi=150, bbox_inches="tight")
plt.close()
```

`phase_plot()` defaults to `x/ux` for Cartesian data and `r/ur` for spherical data. It returns the `pcolormesh` collection.

```python
p = data.particles.isel(t=-1).sel(sp=[1, 2])
p.spectrum_plot(bins=np.logspace(0, 4, 101))
```

The default quantity of `spectrum_plot()` is an internal function of the three momentum components. Do not label it as a specific physical energy definition before checking the analysis conventions. Prefer `data.spectra` when Entity has already written the expected spectra, or pass an explicit `quantity` function.

## Missing quantities

Different species or timesteps may not contain every quantity. nt2py builds the column list across valid outputs and conditionally concatenates the quantities present per species and per step. Do not assume a column is complete just because it appears in `.columns`; before quantitative use, load a bounded selection and verify row counts, null values, and the expected species.

## Source references

- Particles container: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/particles.py>
- Reader particle naming: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/readers/base.py>
