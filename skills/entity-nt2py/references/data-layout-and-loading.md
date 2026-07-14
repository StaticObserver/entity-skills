# Data Layout and Loading

Use this reference whenever opening Entity output with nt2py. It describes the
filesystem contract and the state that can be inspected before loading arrays.

This reference targets **nt2py v1.5.3** (`403437a`). Check the installed version
before relying on version-specific behavior:

```python
import nt2

print(nt2.__version__)
```

## Contents

- Install
- Data-root contract
- Inspect before analysis
- Runtime diagnostics
- Initialization checks and failures
- Source basis

## Install

nt2py v1.5.3 requires Python 3.8 or newer. BP5 support is installed by default;
HDF5 support requires the optional `h5py` dependency.

```bash
python3 -m pip install "nt2py==1.5.3"
python3 -m pip install "nt2py[hdf5]==1.5.3"  # when reading HDF5 output
```

Movie creation additionally requires an external `ffmpeg` executable. It is not
needed for loading or still plots.

## Data-root contract

Pass the directory that directly contains the category directories, not the run
directory above it:

```text
<data-root>/
├── fields/
│   └── fields.00000001.bp  # or .h5
├── particles/
│   └── particles.00000001.bp
├── spectra/
│   └── spectra.00000001.bp
└── simulation.out          # optional runtime diagnostics
```

Category files must match `<category>.<8-digit-step>.bp|h5`. A category may be
absent, but at least one readable `fields`, `particles`, or `spectra` category is
needed to determine the format.

```python
from pathlib import Path
import nt2

data_root = Path("/path/to/run/data")
data = nt2.Data(str(data_root))
```

`nt2.Data` auto-detects BP5 versus HDF5 and reads the `Coordinates` attribute.
`cart` becomes Cartesian; `sph` and `qsph` become Spherical. Other coordinate
systems are rejected.

## Inspect before analysis

Use metadata and container state before selecting quantities:

```python
print(data.coordinate_system.value)
print(data.attrs)

print(data.fields_defined)
print(data.particles_defined)
print(data.spectra_defined)
```

`print(data)` or `data.to_str()` provides a useful full inventory, but it is not
a free metadata operation: reporting particle size calls `.nbytes`, which
computes the Dask particle index across valid particle outputs. On a large run,
inspect the explicit properties above first and print the full object only when
that scan is acceptable. In v1.5.3, `to_str()` also assumes at least two field
or spectrum outputs when calculating `dt`; it raises `IndexError` for a defined
single-step fields/spectra container. Use explicit properties for such runs.

Container states are:

- `data.fields`: an `xarray.Dataset`; empty when fields are not defined.
- `data.particles`: a `ParticleDataset`; `None` when particles are not defined.
- `data.spectra`: an `xarray.Dataset`; empty when spectra are not defined.
- `data.diagnostics`: a `pandas.DataFrame` parsed from `.out`, or `None`.

Use the container-specific discovery APIs rather than assuming variable names:

```python
if data.fields_defined:
    print(dict(data.fields.sizes))
    print(list(data.fields.data_vars))
    print(data.fields.coords)

if data.particles_defined and data.particles is not None:
    print(data.particles.species)
    print(data.particles.times)
    print(data.particles.columns)

if data.spectra_defined:
    print(dict(data.spectra.sizes))
    print(list(data.spectra.data_vars))
```

There is no `data.particles.sp` coordinate. Use `data.particles.species` to list
species and `.sel(sp=...)` to select them.

Avoid using `data.particles.nbytes` as a cheap discovery call: it computes Dask
memory usage for the particle index.

## Runtime diagnostics

`data.diagnostics` does **not** read Entity CSV statistics. It scans the data root
for `.out` files and parses the first one returned by the filesystem. The parser
extracts step, physical time, substep timings, species counts, and optional
species minima/maxima.

Treat it as optional runtime information:

```python
diag = data.diagnostics
if diag is not None:
    print(diag.columns)
    print(diag[["Step", "Time"]].head())
```

Do not use this property as proof of energy conservation or other physics
statistics. Read separately produced CSV files with pandas when the analysis
explicitly needs them.

## Initialization checks and failures

Initialization is more than a directory open. For fields, nt2py verifies that
all readable timesteps have the same variable names, shapes, and memory layout.
It also reads coordinates, edge coordinates, time, step, and attributes.

Investigate these common failures directly:

- `Could not determine file format`: wrong data root or nonconforming filenames.
- HDF5 `ImportError`: install `nt2py[hdf5]` in the active Python environment.
- missing `Coordinates`: output metadata is incomplete or incompatible.
- `No valid steps found`: category exists but contains no readable outputs.
- different names/shapes/layouts: outputs from incompatible runs were mixed.
- warning about unreadable files: confirm whether partial output is acceptable.

## Source basis

- Release: <https://github.com/entity-toolkit/nt2py/releases/tag/v1.5.3>
- Package metadata: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/pyproject.toml>
- Data container: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/data.py>
- Format detection: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/utils.py>
- Diagnostics parser: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/diagnostics.py>
