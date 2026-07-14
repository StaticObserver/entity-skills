# Entity TOML Input Configuration Reference (Archived)

The input file uses TOML format. Reference file in repo: `input.example.toml`.

---

## `[simulation]` — Simulation Control

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `name` | string | Simulation name (used for output files) | **Required** |
| `engine` | string | `"SRPIC"` or `"GRPIC"` | **Required** |
| `runtime` | float (>0) | Max runtime in code units | **Required** |
| `number` | int | Number of domains (MPI) | `1` (no MPI); `MPI_SIZE` (MPI) |
| `decomposition` | array<int> (1-3) | MPI domain decomposition; `-1` = auto | `[-1, -1, -1]` |

---

## `[grid]` — Spatial Grid

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `resolution` | array<uint> (1-3) | Grid resolution per dimension | **Required** |
| `extent` | array<[float,float]> (1-3) | Physical extent `[min, max]` per dim | **Required** |
| `dim` | short (1,2,3) | Dimensionality | Inferred from resolution size |

---

## `[metric]` — Metric & Coordinates

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `metric` | string | `"Minkowski"`, `"Spherical"`, `"QSpherical"`, `"Kerr_Schild"`, `"QKerr_Schild"`, `"Kerr_Schild_0"` | — |
| `coord` | string | `"cartesian"`, `"spherical"`, `"qspherical"` | — |
| `qsph_r0` | float | r0 for QSpherical (negative → near-uniform grid) | `0.0` |
| `qsph_h` | float (-1→1) | Angular coordinate mapping parameter | `0.0` |
| `ks_a` | float (0→1) | Kerr-Schild spin parameter | `0.0` |
| `ks_rh` | float | Horizon radius for GR Kerr-Schild | Inferred |

---

## `[boundaries]` — Boundary Conditions

### Top-level
| Parameter | Type | Description |
|-----------|------|-------------|
| `fields` | array<string> (1-3) | Field BC per direction: `"PERIODIC"`, `"MATCH"`, `"FIXED"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"HORIZON"`, `"CONDUCTOR"` |
| `particles` | array<string> (1-3) | Particle BC per direction: `"PERIODIC"`, `"ABSORB"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"REFLECT"`, `"HORIZON"` |
| `match_ds` | float or array (1-3) | Matching layer width per direction | 1% of domain |
| `absorb_ds` | float | Absorption layer width for particles | 1% of domain |

Notes:
- Periodic in all directions: `["PERIODIC"]` (single value applies to all)
- In spherical coordinates: theta/phi boundaries are auto-set; only specify `[rmin, rmax]`
- In GR: horizon boundary is auto-set; only specify outer boundary

### `[boundaries.atmosphere]`
| Parameter | Type | Description |
|-----------|------|-------------|
| `temperature` | float | Atmosphere temperature in m0 c^2 |
| `density` | float | Peak number density at base in n0 |
| `height` | float | Pressure scale-height in physical units |
| `species` | array<int> (2) | Species indices for atmosphere |
| `ds` | float | Distance from edge for gravity imposition |
| `g` | float | Gravitational acceleration |

---

## `[scales]` — Fiducial Units

Fundamental normalization scales for the simulation:

| Parameter | Description |
|-----------|-------------|
| `larmor0` | Fiducial Larmor radius |
| `skindepth0` | Fiducial plasma skin depth |
| `dx0` | Fiducial minimum cell size |
| `V0` | Fiducial elementary volume |
| `n0` | Fiducial number density |
| `q0` | Fiducial elementary charge |
| `sigma0` | Fiducial magnetization |
| `B0` | Fiducial magnetic field |
| `omegaB0` | Fiducial cyclotron frequency |

---

## `[algorithms]` — Numerical Methods

### `[algorithms.timestep]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `CFL` | float (0→1) | CFL number | `0.95` |
| `correction` | float | Speed-of-light correction factor | `1.0` |
| `dt` | float | Fixed timestep (inferred) | From CFL |

### `[algorithms.deposit]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | Enable current deposition | `true` |
| `order` | ushort (0→10) | Particle shape function order | — |

### `[algorithms.fieldsolver]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | Enable field solver | `true` |
| `delta_x/y/z` | float | Higher-order stencil coefficients (2nd order) | `0.0` |
| `beta_xy/yx/xz/zx/yz/zy` | float | Off-diagonal correction coefficients | `0.0` |

### `[algorithms.gr]` (GRPIC only)
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `pusher_eps` | float (>0) | Numerical differentiation step | `1e-6` |
| `pusher_niter` | ushort (>0) | Newton-Raphson iterations | `10` |

### `[algorithms.gca]` (Guiding Center)
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `e_ovr_b_max` | float (0→1) | Max E/B for GCA validity | `0.9` |
| `larmor_max` | float | Max Larmor radius for GCA | `0.0` |

### Top-level
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `current_filters` | ushort | Current smoothing passes | `0` |

---

## `[particles]` — Particle Configuration

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `ppc0` | float (>0) | Fiducial particles per cell | **Required** |
| `nspec` | uint | Number of particle species | **Required** |
| `use_weights` | bool | Use particle weights | `false` |
| `clear_interval` | uint | Steps between dead particle removal | `100` |
| `spatial_sorting_interval` | uint | Steps between spatial sorting | `0` |

### `[[particles.species]]` (array of tables — one per species)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `label` | string | Species label | `"s<INDEX>"` |
| `mass` | float (>=0) | Mass in fiducial units | **Required** |
| `charge` | float | Charge in fiducial units | **Required** |
| `maxnpart` | uint (>0) | Max particles per MPI task | **Required** |
| `pusher` | string | `"Boris"`, `"Vay"`, `"Boris,GCA"`, `"Vay,GCA"`, `"Photon"`, `"None"` | `"Boris"` (massive) / `"Photon"` (massless) |
| `n_payloads_real` | ushort | Extra real-valued payloads | `0` |
| `n_payloads_int` | ushort | Extra integer payloads | `0` |
| `tracking` | bool | Enable particle tracking via indices | `false` |
| `radiative_drag` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |
| `emission` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |
| `spatial_sorting_interval` | uint | Per-species override | `0` |
| `clear_interval` | uint | Per-species override | `100` |

---

## `[output]` — Data Output

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `format` | string | `"disabled"`, `"hdf5"`, `"BPFile"` | `"hdf5"` |
| `interval` | uint (>0) | Steps between outputs | `1` |
| `interval_time` | float | Physical time between outputs | `-1.0` (use interval) |
| `separate_files` | bool | One file per timestep | `true` |

### `[output.fields]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | Enable field output | `true` |
| `quantities` | array<string> | `"E"`, `"B"`, `"J"`, `"divE"`, `"Rho"`, `"Charge"`, `"N"`, `"Nppc"`, `"T0i"`, `"Tij"`, `"Vi"`, `"D"`, `"H"`, `"divD"`, `"A"` | `[]` |
| `custom` | array<string> | Custom field quantities | `[]` |
| `mom_smooth` | ushort | Smoothing window for moments | `0` |
| `interval` | uint | Override output interval | `0` (use parent) |
| `interval_time` | float | Override time interval | `-1.0` |
| `downsampling` | uint array (1-3) | Downsampling per direction | `[1,1,1]` |

### `[output.particles]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | Enable particle output | `true` |
| `species` | array<int> | Species to output (empty=all) | `[]` |
| `stride` | uint (>1) | Output every Nth particle | `100` |
| `interval` | uint | Override output interval | `0` |
| `interval_time` | float | Override time interval | `-1.0` |

### `[output.spectra]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | Enable spectra output | `true` |
| `e_min` | float | Minimum energy | `1e-3` |
| `e_max` | float | Maximum energy | `1e3` |
| `log_bins` | bool | Logarithmic binning | `true` |
| `n_bins` | uint (>0) | Number of energy bins | `200` |
| `interval` / `interval_time` | | Overrides | |

### `[output.stats]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | Enable statistics output | `true` |
| `interval` | uint (>0) | Steps between stat outputs | `100` |
| `interval_time` | float | Time between stat outputs | `-1.0` |
| `quantities` | array<string> | `"B^2"`, `"E^2"`, `"ExB"`, `"N"`, `"Npart"`, `"Charge"`, `"Rho"`, `"T00"`, `"T0i"`, `"Tij"` | `["B^2","E^2","ExB","Rho","T00"]` |
| `custom` | array<string> | Custom scalar stats | `[]` |

### `[output.checkpoint]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `interval` | uint (>0) | Steps between checkpoints | `1000` |
| `interval_time` | float | Time between checkpoints | `-1.0` |
| `keep` | int | Checkpoints to keep (0=off, -1=all) | `2` |
| `walltime` | string | Checkpoint after `"HH:MM:SS"` | `"00:00:00"` |
| `write_path` | string | Checkpoint output directory | `<simname>.ckpt` |
| `read_path` | string | Resume from checkpoint dir | Inherits write_path |
| `is_resuming` | bool | Resume from checkpoint | Inferred |
| `start_step` | uint | Resume timestep | Inferred |
| `start_time` | float | Resume time | Inferred |

### `[output.debug]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `as_is` | bool | Output raw fields without conversion | `false` |
| `ghosts` | bool | Include ghost cells in output | `false` |

---

## `[radiation]` — Radiative Physics

### `[radiation.drag.synchrotron]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `gamma_rad` | float (>0) | Radiation reaction limit gamma | `1.0` |

### `[radiation.drag.compton]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `gamma_rad` | float (>0) | Radiation reaction limit gamma | `1.0` |

### `[radiation.emission.synchrotron]` / `[radiation.emission.compton]`
| Parameter | Type | Description |
|-----------|------|-------------|
| `gamma_qed` | float (>1) | Gamma-factor for photon emission in B0 |
| `photon_energy_min` | float (>0) | Minimum photon energy in m0 c^2 |
| `photon_weight` | float (>0) | Weights for emitted photons |
| `photon_species` | ushort (>0) | Species index for emitted photons |
| `nominal_probability` | float | Nominal emission probability |
| `nominal_photon_energy` | float | Nominal photon energy |

---

## `[diagnostics]` — Logging

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `interval` | int (>0) | Steps between diagnostic logs | `1` |
| `blocking_timers` | bool | Blocking timers between algorithms | `false` |
| `colored_stdout` | bool | Colored terminal output | `true` |
| `log_level` | string | `"VERBOSE"`, `"WARNING"`, `"ERROR"` | `"VERBOSE"` |

---

## Minimum Required Parameters

For any simulation, at minimum specify:
- `simulation.name`, `simulation.engine`, `simulation.runtime`
- `grid.resolution`, `grid.extent`
- `particles.ppc0`, `particles.nspec`
- At least one `[[particles.species]]` with `mass`, `charge`, `maxnpart`
- `metric.metric` (especially for GR: `"Kerr_Schild"` etc.)

---

## Typical Configuration Skeleton

```toml
[simulation]
name = "my_run"
engine = "SRPIC"
runtime = 100.0

[grid]
resolution = [256, 256]
extent = [[0.0, 10.0], [0.0, 10.0]]

[metric]
metric = "Minkowski"
coord = "cartesian"

[boundaries]
fields = ["PERIODIC"]
particles = ["PERIODIC"]

[scales]
larmor0 = 1.0
skindepth0 = 1.0
n0 = 1.0
B0 = 1.0

[algorithms.timestep]
CFL = 0.45

[particles]
ppc0 = 100
nspec = 2

[[particles.species]]
label = "electrons"
mass = 1.0
charge = -1.0
maxnpart = 5000000
pusher = "Boris"

[[particles.species]]
label = "positrons"
mass = 1.0
charge = 1.0
maxnpart = 5000000
pusher = "Boris"

[output]
format = "BPFile"
interval = 100

[output.fields]
quantities = ["E", "B", "Rho", "N"]

[output.particles]
species = [0, 1]
stride = 10

[output.spectra]
enable = true

[output.stats]
quantities = ["B^2", "E^2", "T00"]
```
