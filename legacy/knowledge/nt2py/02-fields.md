# nt2py: Field Analysis & Visualization (Archived)

## Accessing Field Data

Fields are xarray Datasets with dimensions like `(t, x, y, z)` or `(t, r, theta, phi)`.

```python
# List available field quantities and dimensions
data.fields.coords
list(data.fields.data_vars)

# Access specific fields (lazy — no data loaded yet)
Ex = data.fields.Ex
Bz = data.fields.Bz

# Species-specific moments
Rho1 = data.fields.Rho_1      # Charge density of species 1
Tij_1_3 = data.fields.Tij_1_3  # Energy-momentum for species 1 & 3
```

## Slicing and Selection

All operations are lazy:

```python
# Select by time value (nearest match)
fields_at_t5 = data.fields.sel(t=5.0, method="nearest")

# Select by integer index
fields_step_100 = data.fields.isel(t=100)

# Spatial slicing
fields_subset = data.fields.sel(x=slice(-5.0, 5.0), z=0.5)

# Chain selections
result = data.fields.Ex.sel(t=10.0, method="nearest").isel(x=-1)
```

### Loading Into Memory

```python
arr = data.fields.Ex.sel(t=5.0, method="nearest").values  # numpy array
all_fields = data.fields.compute()  # load everything — careful!
```

## Basic Plots

```python
# 2D Cartesian field at specific time
data.fields.Ex.sel(t=10.0, method="nearest").plot()

# 1D slice
data.fields.Bz.isel(y=128).sel(t=5.0, method="nearest").plot()

# Time-averaged field
data.fields.Bz.mean("t").plot()
```

## Spherical/Polar Coordinates

```python
# Radial slice in spherical coords
data.fields.Ex.sel(t=50.0, method="nearest").sel(r=slice(None, 10)).polar.pcolor()

# Derived quantity in spherical coords
e_dot_b = sum(data.fields[f"E{i}"] * data.fields[f"B{i}"] for i in range(1,4))
bsqr = sum(data.fields[f"B{i}"]**2 for i in range(1,4))
(e_dot_b / bsqr).sel(t=50.0, method="nearest").sel(r=slice(None, 10)).polar.pcolor()
```

## Inspect Accessor (Quick Multi-Panel)

```python
# Multi-panel at a slice
data.fields.sel(t=3.0, method="nearest").sel(
    x=slice(-0.2, 0.2)
).inspect.plot(only_fields=["E", "B"])

# With derived quantities
data.fields.sel(t=3.0, method="nearest").inspect.plot(
    only_fields=["E", "B", "N"]
)
```

## Movies / Animations

```python
# Omit time selection + provide name = movie mode
data.fields.sel(x=slice(-0.2, 0.2)).inspect.plot(
    name="inspect_movie",
    only_fields=["E", "B", "N"]
)

# Single quantity movie
(data.fields.Ex * data.fields.Bx).sel(
    x=slice(None, 0.2)
).movie.plot(name="ExBx_movie")
```

### Custom Movie with Plot Function

```python
import matplotlib.pyplot as plt

def my_plot(fields_at_timestep, ax):
    data_to_plot = fields_at_timestep.Ex - fields_at_timestep.Ex.mean()
    data_to_plot.plot(ax=ax, cmap="RdBu_r")

data.makeMovie(my_plot, name="custom_movie")
```

### Low-Level Movie Export

```python
import nt2.plotters.export as nt2e
import numpy as np

def plot_func(data, ax, step):
    fields = data.fields.isel(t=step)
    fields.Bz.plot(ax=ax)

nt2e.makeFramesAndMovie(
    name="my_animation",
    plot=plot_func,
    times=np.arange(100)
)
```
