# Plotting and Movies

Use this reference when working with the nt2py plotting accessors and animation export. First select a bounded data subset following the container-specific references.

## Contents

- Standard xarray plotting
- Field overview with `inspect`
- Spherical and quasi-spherical plotting
- Single-quantity movies
- Custom movies
- Low-level export
- Source references

## Standard xarray plotting

Fields and spectra use xarray plotting. Select a time and reduce the spatial data to one or two dimensions before plotting:

```python
import matplotlib.pyplot as plt

q = data.fields["Bz"].isel(t=-1)
if "z" in q.dims:
    q = q.isel(z=0)
q.plot()
plt.savefig("Bz-last.png", dpi=150, bbox_inches="tight")
plt.close()
```

Plotting triggers Dask computation. Set the output path, close the figure, and confirm the expected file was actually created.

## Field overview with `inspect`

Importing `nt2` registers the `Dataset.inspect` accessor. It accepts data that has one or two dimensions remaining after time selection:

```python
snapshot = data.fields.isel(t=-1)
if "z" in snapshot.dims:
    snapshot = snapshot.isel(z=0)

fig = snapshot.inspect.plot(only_fields=["E.*", "B.*"])
fig.savefig("field-overview.png", dpi=150, bbox_inches="tight")
plt.close(fig)
```

`only_fields` and `skip_fields` are lists of regular expressions matched from the start of each variable name. `only_fields` takes precedence. `plot_kwargs` maps field-name regexes to xarray plotting arguments.

If `t` is still a dimension, `inspect.plot()` enters movie mode and requires `name`:

```python
movie_data = data.fields[["Ex", "Bx"]]
if "z" in movie_data.dims:
    movie_data = movie_data.isel(z=0)
ok = movie_data.inspect.plot(
    name="field-overview",
    only_fields=["E.*", "B.*"],
    movie_kwargs={"num_cpus": 4},
)
```

Static-plot mode returns a Matplotlib `Figure`; movie mode returns `True` or `False`. More than two dimensions after removing `t` raises an error.

## Spherical and quasi-spherical plotting

The `DataArray.polar` accessor requires exactly the two dimensions `r` and `th`, with no time dimension:

```python
q = data.fields["Br"].isel(t=-1)
im = q.polar.pcolor(cmap="RdBu_r")
plt.savefig("Br-polar.png", dpi=150, bbox_inches="tight")
plt.close()
```

The accessor plots on rectilinear Cartesian axes. Common options include `invert_x`, `invert_y`, `cbar_position`, `cbar_size`, `title`, and `label`. `polar.contour()` has the same dimension requirements.

For field lines, operate on a spherical dataset after time selection:

```python
snapshot = data.fields.isel(t=-1)
snapshot.polar.fieldplot(
    "Br",
    "Bth",
    sample={"template": "dipole", "radius": 2.0, "nth": 24},
)
```

Supported sampling templates are `dipole` and `monopole`. Field-line integration is a plotting tool, not an accuracy-certified physics integrator.

## Single-quantity movies

A time-varying `DataArray` has a `.movie` accessor:

```python
q = data.fields["Bz"]
if "z" in q.dims:
    q = q.isel(z=0)
ok = q.movie.plot(
    name="Bz-evolution",
    movie_kwargs={"num_cpus": 4, "framerate": 20},
    cmap="RdBu_r",
)
```

It requires a `t` dimension to exist. Frames are indexed by time position rather than passed as physical time values to the xarray plotting call.

## Custom movies

`Data.makeMovie` passes both the physical time value and the `Data` object to the callback:

```python
def plot_frame(t, data):
    data.fields["Ex"].sel(t=t, method="nearest").plot()

ok = data.makeMovie(
    plot_frame,
    time=list(data.fields.t.values),
    num_cpus=4,
    framerate=20,
)
```

In v1.5.3, `Data.makeMovie` uses `data.attrs["simulation.name"]` as the output name when that attribute exists. When the attribute is missing, it consumes `name=`, otherwise defaulting to `movie`. Do not pass `name=` without checking the attribute first: in the attribute-present branch, v1.5.3 leaves the keyword inside `movie_kwargs`, causing a duplicate `name` argument. Use the low-level export functions when you need independent control of the file name.

## Low-level export

```python
from nt2.plotters.export import makeFrames, makeMovie, makeFramesAndMovie
```

- `makeFrames(plot, times, fpath, data=None, num_cpus=None)` writes numbered PNGs.
- `makeMovie(input=..., output=..., ...)` invokes the external `ffmpeg`.
- `makeFramesAndMovie(name=..., plot=..., times=..., ...)` runs both stages.

The default worker count is all detected CPUs. Set `num_cpus` explicitly on login nodes or shared machines. The combined export writes frames under `<name>/frames/` and outputs `<name>.mp4` by default. Check the boolean return value and the output files; success of the frame stage does not guarantee ffmpeg succeeded.

## Source references

- Inspect accessor: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/inspect.py>
- Polar accessor: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/polar.py>
- Movie accessor: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/movie.py>
- Export functions: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/export.py>
