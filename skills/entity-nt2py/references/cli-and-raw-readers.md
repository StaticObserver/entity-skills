# CLI and Raw Readers

Use this reference for quick command-line inspection or when a precise raw
array read is more appropriate than the high-level lazy containers.

## Contents

- CLI scope and selection syntax
- When to use raw readers
- Choose the reader
- Core reader workflow
- Reader constraints
- Source basis

## CLI scope in v1.5.3

The installed command is `nt2`:

```bash
nt2 version
nt2 show /path/to/data-root
nt2 plot /path/to/data-root --what fields --isel "t=0"
```

`nt2 show` constructs `nt2.Data` and prints its inventory. `nt2 plot` currently
implements only `--what fields`. Although `particles` and `spectra` are accepted
option names, both paths raise `NotImplementedError` in v1.5.3.

### Selection syntax

Separate multiple selectors with semicolons:

```bash
nt2 plot /path/to/data-root \
  --what fields \
  --fields "E.*;B.*" \
  --sel "x=slice(-5.0, 5.0);y=0.0" \
  --isel "t=0;z=0"
```

The CLI splits slice selectors from scalar selectors. It applies scalar `.sel`
with `method="nearest"`, then slice `.sel`, then `.isel`. `--fields` entries are
regular expressions used by the `inspect` accessor.

If the result has no `t` dimension, the CLI saves `<data-root-basename>.png`.
If time remains, it creates an inspect movie named from the data-root basename.

The selection parser uses Python `eval()` on each argument value. Use it only
with trusted, manually controlled command lines. Never interpolate untrusted
user, file, scheduler, or network content into `--sel` or `--isel`.

## When to use raw readers

Prefer `nt2.Data` for normal analysis because it supplies coordinate remapping,
cross-step checks, Dask-backed fields/spectra, and the particle selection layer.

Use a raw reader when you need to:

- inspect exact stored variable names or attributes;
- read one known array from one output step;
- diagnose a high-level container construction failure;
- verify file shape/layout without building the full dataset;
- implement a carefully bounded custom reader workflow.

Raw reads return NumPy arrays immediately. They do not provide lazy-loading or
automatic memory protection.

## Choose the reader

```python
from pathlib import Path
from nt2.readers.adios2 import Reader as BP5Reader
from nt2.readers.hdf5 import Reader as HDF5Reader

data_root = Path("/path/to/data-root")
reader = BP5Reader()  # choose HDF5Reader() for .h5 output
```

Importing `HDF5Reader` is allowed without `h5py`, but opening an HDF5 file raises
an `ImportError` until `nt2py[hdf5]` is installed.

## Core reader workflow

```python
steps = reader.GetValidSteps(str(data_root), "fields")
if not steps:
    raise ValueError("No readable field steps")

step = steps[-1]
names = reader.ReadCategoryNamesAtTimestep(
    str(data_root), "fields", "f", step
)
name = sorted(names)[0]

attrs = reader.ReadAttrsAtTimestep(str(data_root), "fields", step)
shape = reader.ReadArrayShapeAtTimestep(
    str(data_root), "fields", name, step
)
array = reader.ReadArrayAtTimestep(
    str(data_root), "fields", name, step
)

print(step, name, shape, array.shape, attrs.get("Coordinates"))
```

The primary common methods are:

| Method | Purpose |
|---|---|
| `GetValidSteps(path, category)` | List readable step numbers |
| `GetValidFiles(path, category)` | List readable category filenames |
| `ReadAttrsAtTimestep(...)` | Read file-level attributes |
| `ReadCategoryNamesAtTimestep(...)` | List names matching a raw prefix |
| `ReadArrayAtTimestep(...)` | Read one array immediately |
| `ReadArrayShapeAtTimestep(...)` | Read stored shape metadata |
| `ReadFieldCoordsAtTimestep(...)` | Read raw `X1/X2/X3` centers |
| `ReadEdgeCoordsAtTimestep(...)` | Read raw edge coordinates |
| `ReadFieldLayoutAtTimestep(...)` | Return `Layout.L` or `Layout.R` |
| `ReadPerTimestepVariable(...)` | Gather `Time`, `Step`, or another scalar |

Categories are literal strings: `fields`, `particles`, or `spectra`. Prefixes
and variable names are raw on-disk names such as `f`, `p`, `s`, `fB3`, or
`pX1_1`; high-level remapping is not applied.

## Reader constraints

- Validity checks open every candidate file and skip files that raise `OSError`.
- Filenames still must follow `<category>.<8-digit-step>.<format>`.
- `ReadArrayAtTimestep` reads the full stored array; inspect shape first.
- HDF5 data arrays live below `Step0`; BP5 variables are read through ADIOS2.
- Field layout may require transposition in high-level containers; raw readers
  return stored layout.
- Reader APIs use PascalCase because that is the released public interface.

## Source basis

- CLI: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/cli/main.py>
- Base reader: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/readers/base.py>
- BP5 reader: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/readers/adios2.py>
- HDF5 reader: <https://github.com/entity-toolkit/nt2py/blob/v1.5.3/nt2/readers/hdf5.py>
