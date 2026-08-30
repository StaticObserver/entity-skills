# Fields and Spectra

Use this reference for work involving lazy field operations, derived field quantities, and precomputed spectra. In nt2py v1.5.3, both containers are `xarray.Dataset` objects backed by Dask arrays.

## Contents

- Field data model and remapping
- Lazy selection
- Derived quantities
- Spectra data model
- Safe plotting example
- Source references

## Field data model

`data.fields` uses physical time as the dimension `t`; the spatial dimensions depend on the coordinate system, and the simulation step `s` is a coordinate along `t`.

```python
fields = data.fields
print(dict(fields.sizes))
print(list(fields.data_vars))
print(fields.coords)
print(fields.attrs)
```

Typical dimensions:

```text
Cartesian: (t, x), (t, y, x), or (t, z, y, x)
Spherical: (t, r), (t, th, r), or (t, ph, th, r)
```

Use the actual `fields.dims` and `fields.data_vars`; do not infer dimensions or available quantities from the PGen name.

### Name remapping

The default remapping strips the leading `f` and converts component indices:

| Raw Entity name | Cartesian | Spherical/qspherical |
|---|---|---|
| `fE1`, `fE2`, `fE3` | `Ex`, `Ey`, `Ez` | `Er`, `Eth`, `Eph` |
| `fB1`, `fB2`, `fB3` | `Bx`, `By`, `Bz` | `Br`, `Bth`, `Bph` |
| `fT01_2` | `Ttx_2` | `Ttr_2` |

Coordinate names map from `X1/X2/X3` to `x/y/z` or `r/th/ph`. Cell-edge coordinates are exposed as `<coord>_min` and `<coord>_max`.

## Lazy selection

Constructing and selecting the fields dataset does not load field arrays. Plotting, `.values`, `.load()`, and `.compute()` trigger the reads.

```python
# Select physical time, then reduce space before computing.
snapshot = data.fields.sel(t=10.0, method="nearest")
plane = snapshot["Bz"].isel(z=0) if "z" in snapshot.dims else snapshot["Bz"]
subset = plane.sel(x=slice(-5.0, 5.0)) if "x" in plane.dims else plane
array = subset.values
```

Use `.isel(t=-1)` for the last output index. Use `.sel(t=..., method="nearest")` to select by physical time. The step is the coordinate `s`, not a separate dimension; when mapping simulation steps, select by time index or inspect `data.fields.s`.

Avoid these patterns on large runs:

```python
data.fields.values          # Dataset has no single safe bulk array
data.fields.compute()       # reads every field and timestep
data.fields.Bz.mean("t")    # still lazy, but plotting it reads all timesteps
```

The last expression is only reasonable when you intend a full time-domain reduction.

## Derived quantities

Keep arithmetic inside xarray so selections stay composable and Dask-backed:

```python
f = data.fields
if {"Ex", "Ey", "Ez", "Bx", "By", "Bz"} <= set(f.data_vars):
    e_dot_b = f.Ex * f.Bx + f.Ey * f.By + f.Ez * f.Bz
    view = e_dot_b.isel(t=-1)
```

For spherical output, use `Er/Eth/Eph` and `Br/Bth/Bph`. Select a time and reduce to one or two spatial dimensions before plotting.

## Spectra data model

`data.spectra` is likewise lazy, but species are represented by data variable names rather than an `sp` dimension. Typical structure:

```text
dimensions: t, E
coordinates: t, E, s
data variables: N_1, N_2, N_3, ...
```

Inspect the variables first, then select one explicitly:

```python
if data.spectra_defined:
    print(list(data.spectra.data_vars))
    spectrum = data.spectra["N_1"].isel(t=-1)
    spectrum.sel(E=slice(1.0, 100.0)).plot()
```

Do not write `data.spectra.sel(sp=1)`: v1.5.3 has no `sp` coordinate. Raw variables starting with `sN` are included with the leading `s` stripped; for example `sN_1` becomes `N_1`.

The energy coordinate is built from the raw `sEbn` bin edges. nt2py uses arithmetic bin centers when the spacing looks linear, and geometric centers otherwise. Treat `E` as a coordinate provided by the output; apply physical interpretation or normalization only when the simulation contract specifies it.

## Safe plotting example

```python
from pathlib import Path
import matplotlib.pyplot as plt

out = Path("analysis/figures")
out.mkdir(parents=True, exist_ok=True)

quantity = data.fields["Bz"].isel(t=-1)
while quantity.ndim > 2:
    quantity = quantity.isel({quantity.dims[0]: 0})

quantity.plot()
plt.savefig(out / "Bz-last.png", dpi=150, bbox_inches="tight")
plt.close()
```

In real analysis, prefer selecting dimensions explicitly over this generic `while` reduction; the loop is just a defensive example for writing inventory tools.

## Source references

- Fields container: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/fields.py>
- Spectra container: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/spectra.py>
- Default remapping: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/data.py>
