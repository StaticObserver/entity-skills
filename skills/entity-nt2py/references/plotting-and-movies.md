# Plotting and Movies

Use this reference for nt2py plotting accessors and animation export. First
select a bounded data subset using the container-specific reference.

## Contents

- Standard xarray plots
- Field overview with `inspect`
- Spherical and qspherical plots
- Single-quantity movie
- Custom movie
- Low-level export
- Source basis

## Standard xarray plots

Fields and spectra use xarray plotting. Select one time and reduce spatial data
to one or two dimensions before plotting:

```python
import matplotlib.pyplot as plt

q = data.fields["Bz"].isel(t=-1)
if "z" in q.dims:
    q = q.isel(z=0)
q.plot()
plt.savefig("Bz-last.png", dpi=150, bbox_inches="tight")
plt.close()
```

Plotting triggers Dask computation. Set output paths, close figures, and check
that the expected file was created.

## Field overview with `inspect`

Importing `nt2` registers the `Dataset.inspect` accessor. It accepts data with
one or two remaining dimensions after time selection:

```python
snapshot = data.fields.isel(t=-1)
if "z" in snapshot.dims:
    snapshot = snapshot.isel(z=0)

fig = snapshot.inspect.plot(only_fields=["E.*", "B.*"])
fig.savefig("field-overview.png", dpi=150, bbox_inches="tight")
plt.close(fig)
```

`only_fields` and `skip_fields` are lists of regular expressions matched from
the start of each variable name. `only_fields` takes precedence. `plot_kwargs`
maps field-name regexes to xarray plot arguments.

If `t` is still a dimension, `inspect.plot()` enters movie mode and requires a
`name`:

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

Still-image mode returns a Matplotlib `Figure`; movie mode returns `True` or
`False`. More than two dimensions after removing `t` is an error.

## Spherical and qspherical plots

The `DataArray.polar` accessor requires exactly two dimensions, `r` and `th`,
and no time dimension:

```python
q = data.fields["Br"].isel(t=-1)
im = q.polar.pcolor(cmap="RdBu_r")
plt.savefig("Br-polar.png", dpi=150, bbox_inches="tight")
plt.close()
```

The accessor draws on rectilinear Cartesian axes. Useful options include
`invert_x`, `invert_y`, `cbar_position`, `cbar_size`, `title`, and `label`.
`polar.contour()` has the same dimensionality requirements.

For field lines, operate on a time-selected spherical dataset:

```python
snapshot = data.fields.isel(t=-1)
snapshot.polar.fieldplot(
    "Br",
    "Bth",
    sample={"template": "dipole", "radius": 2.0, "nth": 24},
)
```

Supported sampling templates are `dipole` and `monopole`. Field-line integration
is a plotting utility, not an accuracy-certified physics integrator.

## Single-quantity movie

A time-dependent `DataArray` has a `.movie` accessor:

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

It requires a `t` dimension. Frames are indexed by time position, not passed as
physical time values to the xarray plot call.

## Custom movie

`Data.makeMovie` passes both the physical time value and the `Data` object to
the callback:

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

In v1.5.3, when `data.attrs["simulation.name"]` exists, `Data.makeMovie` uses
that attribute as the output name. When the attribute is absent, it consumes
`name=` or defaults to `movie`. Do not pass `name=` without first checking the
attribute: in the attribute-present branch v1.5.3 leaves that keyword in
`movie_kwargs`, causing a duplicate `name` argument. Use the lower-level export
functions when the filename must be controlled independently.

## Low-level export

```python
from nt2.plotters.export import makeFrames, makeMovie, makeFramesAndMovie
```

- `makeFrames(plot, times, fpath, data=None, num_cpus=None)` writes numbered PNGs.
- `makeMovie(input=..., output=..., ...)` invokes external `ffmpeg`.
- `makeFramesAndMovie(name=..., plot=..., times=..., ...)` performs both stages.

The default worker count is all detected CPUs. Set `num_cpus` explicitly on a
login node or shared machine. Combined export writes frames under
`<name>/frames/` and defaults to `<name>.mp4`. Inspect the boolean result and
output file; a successful frame stage does not guarantee ffmpeg success.

## Source basis

- Inspect accessor: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/inspect.py>
- Polar accessor: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/polar.py>
- Movie accessor: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/movie.py>
- Export functions: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/plotters/export.py>
