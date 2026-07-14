# nt2py: Installation & Data Loading (Archived)

## Installation

```bash
pip install nt2py
# or with HDF5 support:
pip install "nt2py[hdf5]"
```

## Output File Types

Entity produces these files in the simulation output directory:

| File/Folder | Format | Contents |
|-------------|--------|----------|
| `<name>.info` | Text | Simulation metadata, parameters, compiler info |
| `<name>.log` | Text | Timestamped log of each substep |
| `<name>.err` | Text | Errors and warnings (only if issues occurred) |
| `<name>.csv` | CSV | Box-averaged stats per output step |
| `<name>/fields/` | BP5/HDF5 | Field data (E, B, J, Rho, etc.) |
| `<name>/particles/` | BP5/HDF5 | Particle data (X, U, W, payloads) |
| `<name>/spectra/` | BP5/HDF5 | Energy spectra per species |
| `<name>.ckpt/` | BP5/HDF5 | Checkpoint files |

## Loading Data

```python
import nt2

# Load a simulation directory
data = nt2.Data("path/to/simulation_output")
```

## Data Containers

Four lazy containers — **data is NOT loaded into memory until explicitly accessed**:

```python
data.fields       # xarray Dataset — field quantities (E, B, J, Rho, N, Tij...)
data.particles    # Special lazy container — call .load() to get pandas DataFrame
data.spectra      # xarray Dataset — pre-computed energy spectra
data.diagnostics  # pandas DataFrame — per-step diagnostic info
```

Lazy loading allows working with datasets much larger than RAM. Always `.sel()`/`.isel()` to narrow down before calling `.load()` or `.values`.
