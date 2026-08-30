# Data Layout and Loading

Use this reference whenever you open Entity output with nt2py. It describes the filesystem contract and the state you can inspect before loading any arrays.

This reference targets **nt2py v1.5.3** (`403437a`). Before relying on version-specific behavior, check the installed version:

```python
import nt2

print(nt2.__version__)
```

## Contents

- Installation
- Data-root contract
- Inspect before analyzing
- Runtime diagnostics
- Initialization checks and failures
- Source references

## Installation

nt2py v1.5.3 requires Python 3.8 or newer. BP5 support is installed by default; HDF5 support needs the optional `h5py` dependency.

```bash
python3 -m pip install "nt2py==1.5.3"
python3 -m pip install "nt2py[hdf5]==1.5.3"  # when reading HDF5 output
```

Making movies additionally requires an external `ffmpeg` executable. It is not needed for loading data or plotting static figures.

## Data-root contract

Pass the directory that directly contains the category directories, not the run directory above it:

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

Category files must match `<category>.<8-digit-step>.bp|h5`. A category may be missing, but at least one readable `fields`, `particles`, or `spectra` category is required to determine the format.

```python
from pathlib import Path
import nt2

data_root = Path("/path/to/run/data")
data = nt2.Data(str(data_root))
```

`nt2.Data` auto-detects BP5 versus HDF5 and reads the `Coordinates` attribute. `cart` maps to Cartesian; `sph` and `qsph` map to Spherical. Other coordinate systems are rejected.

## Inspect before analyzing

Use the metadata and container state before selecting quantities:

```python
print(data.coordinate_system.value)
print(data.attrs)

print(data.fields_defined)
print(data.particles_defined)
print(data.spectra_defined)
```

`print(data)` or `data.to_str()` provides a useful full inventory, but it is not a free metadata operation: reporting particle sizes calls `.nbytes`, which computes the Dask particle index across all valid particle outputs. On large runs, check the explicit attributes above first and print the full object only when that scan is acceptable. In v1.5.3, `to_str()` also assumes at least two field or spectra outputs when computing `dt`; for a defined fields/spectra container with only one step it raises `IndexError`. Use the explicit attributes for such runs.

Container state:

- `data.fields`: an `xarray.Dataset`; empty when no fields are defined.
- `data.particles`: a `ParticleDataset`; `None` when no particles are defined.
- `data.spectra`: an `xarray.Dataset`; empty when no spectra are defined.
- `data.diagnostics`: a `pandas.DataFrame` parsed from the `.out` file, or `None`.

Use the container-specific discovery APIs instead of guessing variable names:

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

There is no `data.particles.sp` coordinate. Use `data.particles.species` to list species, and `.sel(sp=...)` to select them.

Avoid treating `data.particles.nbytes` as a cheap discovery call: it computes Dask memory usage for the particle index.

## Runtime diagnostics

`data.diagnostics` does **not** read Entity CSV statistics files. It scans the data root for `.out` files and parses the first file the filesystem returns. The parser extracts step counts, physical time, substep timings, species counts, and optional species min/max values.

Treat it as optional runtime information:

```python
diag = data.diagnostics
if diag is not None:
    print(diag.columns)
    print(diag[["Step", "Time"]].head())
```

Do not use this attribute as proof of energy conservation or other physics statistics. When an analysis explicitly needs them, read the separately generated CSV files with pandas on their own.

## Initialization checks and failures

Initialization does more than open a directory. For fields, nt2py verifies that all readable timesteps have the same variable names, shapes, and memory layout. It also reads coordinates, edge coordinates, times, steps, and attributes.

Troubleshoot these common failures directly:

- `Could not determine file format`: the data root is wrong or the file names do not follow the convention.
- HDF5 `ImportError`: install `nt2py[hdf5]` in the current Python environment.
- Missing `Coordinates`: the output metadata is incomplete or incompatible.
- `No valid steps found`: the category exists but contains no readable output.
- Inconsistent names/shapes/layouts: output from incompatible runs was mixed together.
- Warnings about unreadable files: confirm whether partial output is acceptable.

## Source references

- Release: <https://github.com/entity-toolkit/nt2py/releases/tag/v1.5.3>
- Package metadata: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/pyproject.toml>
- Data container: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/data.py>
- Format detection: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/utils.py>
- Diagnostics parser: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/containers/diagnostics.py>
