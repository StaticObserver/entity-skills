# 09 — TOML Configuration Reference

> Based on Entity v1.4.4

## When to use

**Required reading**. Every PGen needs a companion TOML file. This reference covers all TOML sections and parameters supported by Entity.

Use it for: creating a new TOML, validating an existing TOML, understanding how TOML parameters map to C++ code.

---

## TOML syntax conventions

Entity uses the standard TOML v1.0 format, with the following conventions:

| Convention | Description |
|------------|-------------|
| String values use **PascalCase** | `"SRPIC"` not `"srpic"`; `"Minkowski"`, `"PERIODIC"`, `"Boris"` |
| Bool values are **lowercase** | `true` / `false` (TOML standard) |
| Arrays | Square brackets: `resolution = [256, 256]` |
| Arrays of arrays | `extent = [[0.0, 10.0], [0.0, 10.0]]` (2D requires 2 pairs of inner brackets) |
| Nested tables | `[grid.metric]` or flattened `[grid]` + indented `metric = "..."` — both forms work |
| Arrays of tables | `[[particles.species]]` (double brackets), for repeatable sections |

---

## Required sections

### `[simulation]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `name` | string | Output filename prefix | **required** |
| `engine` | string | `"SRPIC"` or `"GRPIC"` | **required** |
| `runtime` | float (>0) | Maximum runtime (code units) | **required** |
| `number` | int | Number of MPI domains | `1` (no MPI); `MPI_SIZE` (MPI) |
| `decomposition` | array<int> (1-3) | MPI decomposition; `-1` = automatic | `[-1, -1, -1]` |

### `[grid]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `resolution` | array<uint> (1-3) | Grid resolution per dimension | **required** |
| `extent` | array<[float,float]> (1-3) | Physical extent [min, max] per dimension | **required** |
| `dim` | short (1,2,3) | Number of dimensions | Inferred from resolution |

### `[grid.metric]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `metric` | string | See Metrics enum table | — |
| `coord` | string | `"cartesian"`, `"spherical"`, `"qspherical"` | — |

#### Spherical coordinates only
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `qsph_r0` | float | r0 for QSpherical (negative → nearly uniform grid) | `0.0` |
| `qsph_h` | float (-1→1) | Angular coordinate mapping parameter | `0.0` |

#### Kerr-Schild only (GRPIC)
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `ks_a` | float (0→1) | Black hole spin parameter | `0.0` |
| `ks_rh` | float | Horizon radius | Automatically inferred |

### `[particles]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `ppc0` | float (>0) | Base particles per cell | **required** |
| `nspec` | uint | Number of particle species | **required** |
| `use_weights` | bool | Use particle weights (must be true when the PGen includes injection) | `false` |
| `clear_interval` | uint | Dead particle cleanup interval (steps) | `100` |
| `spatial_sorting_interval` | uint | Spatial sorting interval | `0` (disabled) |

### `[[particles.species]]` (array of tables — one per species)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `label` | string | Species label | `"s<INDEX>"` |
| `mass` | float (>=0) | Mass (base unit m0) | **required** |
| `charge` | float | Charge (base unit q0) | **required** |
| `maxnpart` | uint (>0) | Maximum particles per MPI task | **required** |
| `pusher` | string | `"Boris"`, `"Vay"`, `"Boris,GCA"`, `"Vay,GCA"`, `"Photon"`, `"None"` | Massive: Boris; massless: Photon |
| `n_payloads_real` | ushort | Extra real-valued payload slots | `0` |
| `n_payloads_int` | ushort | Extra integer-valued payload slots | `0` |
| `tracking` | bool | Enable particle tracking (requires compile-time TRACKING=ON) | `false` |
| `radiative_drag` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |
| `emission` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |

---

## Common optional sections

### `[scales]`

**See `00-normalization.md`**.

| Parameter | Type | Description |
|-----------|------|-------------|
| `larmor0` | float | Base Larmor radius (B0 = 1/larmor0) |
| `skindepth0` | float | Base skin depth (n0 = 1/(larmor0·skindepth0²)) |
| `n0` | float | Base number density |
| `B0` | float | Base magnetic field (engine built-in = 1/larmor0) |
| `sigma0` | float | Base magnetization |
| `omegaB0` | float | Base cyclotron frequency |

### `[boundaries]`

| Parameter | Type | Description |
|-----------|------|-------------|
| `fields` | array<string> (1-3) | Field boundary conditions per dimension: `"PERIODIC"`, `"MATCH"`, `"FIXED"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"HORIZON"`, `"CONDUCTOR"` |
| `particles` | array<string> (1-3) | Particle boundary conditions per dimension: `"PERIODIC"`, `"ABSORB"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"REFLECT"`, `"HORIZON"` |

**Shorthand syntax**:
```toml
# Same BC for all dimensions
boundaries = { fields = ["PERIODIC"], particles = ["PERIODIC"] }

# 2D per-dimension specification
[boundaries]
  fields = [["PERIODIC"], ["PERIODIC"]]
  particles = [["PERIODIC"], ["PERIODIC"]]
```

**Pairing constraints**: `CONDUCTOR` field boundary conditions must be paired with `REFLECT` particle boundary conditions. `HORIZON` is valid only in GR.

#### `[boundaries.match]` / `[boundaries.absorb]` / `[boundaries.atmosphere]`
See `06-boundary.md`.

### `[algorithms]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `current_filters` | ushort | Number of current smoothing passes (set to 0 when charge conservation is required) | `0` |

#### `[algorithms.timestep]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `CFL` | float (0→1) | CFL number | `0.95` |
| `correction` | float | Speed-of-light correction factor | `1.0` |
| `dt` | float | Fixed timestep | Inferred from CFL |

#### `[algorithms.deposit]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | Enable current deposition | `true` |
| `order` | ushort (0→10) | Particle shape function order | — |

#### `[algorithms.fieldsolver]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | Enable field solver | `true` |
| `delta_x/y/z` | float | High-order stencil coefficients (second order) | `0.0` |
| `beta_xy/yx/xz/zx/yz/zy` | float | Off-diagonal correction coefficients | `0.0` |

#### `[algorithms.gr]` (GRPIC only)
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `pusher_eps` | float (>0) | Numerical differentiation step | `1e-6` |
| `pusher_niter` | ushort (>0) | Newton-Raphson iteration count | `10` |

#### `[algorithms.gca]` (Guiding Center)
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `e_ovr_b_max` | float (0→1) | Maximum E/B for GCA validity | `0.9` |
| `larmor_max` | float | Maximum Larmor radius for GCA | `0.0` |

### `[setup]` — PGen-specific parameters

**This is the core section for PGen development**. All custom parameters are defined here:

```toml
[setup]
  temperature = 0.01
  drift_ux = 0.1
  Bmag = 1.0
  Btheta = 0.0
  filling_fraction = 0.5
  injection_frequency = 100
```

Read in pgen.hpp via `params.template get<T>("setup.key")`. Parameter types can be `real_t`, `int`, `std::string`, `std::vector<real_t>`.

### `[output]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `format` | string | `"disabled"`, `"hdf5"`, `"BPFile"` | `"hdf5"` |
| `interval` | uint (>0) | Output interval (steps) | `1` |
| `interval_time` | float | Output interval (time); -1 disables | `-1.0` |
| `separate_files` | bool | One file per timestep | `true` |

#### `[output.fields]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | | `true` |
| `quantities` | array<string> | `"E"`, `"B"`, `"J"`, `"divE"`, `"Rho"`, `"Charge"`, `"N"`, `"Nppc"`, `"T0i"`, `"Tij"`, `"Vi"`, `"D"`, `"H"`, `"divD"`, `"A"` | `[]` |
| `custom` | array<string> | Custom field quantities (see 07-custom-output.md) | `[]` |
| `mom_smooth` | ushort | Moment smoothing window | `0` |
| `interval` / `interval_time` | | Override global settings | |
| `downsampling` | array<uint> (1-3) | Downsampling | `[1,1,1]` |

#### `[output.particles]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | | `true` |
| `species` | array<int> | Species to output (empty = all) | `[]` |
| `stride` | uint (>1) | Output 1 out of every N particles | `100` |

#### `[output.spectra]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | | `true` |
| `e_min` / `e_max` | float | Energy range | `1e-3` / `1e3` |
| `log_bins` | bool | Logarithmic binning | `true` |
| `n_bins` | uint | Number of bins | `200` |

#### `[output.stats]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | | `true` |
| `interval` | uint | Statistics output interval | `100` |
| `quantities` | array<string> | `"B^2"`, `"E^2"`, `"T00"`, etc. | `["B^2","E^2","T00"]` |
| `custom` | array<string> | Custom statistics (see 07-custom-output.md) | `[]` |

#### `[output.checkpoint]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `interval` | uint | Checkpoint interval | `1000` |
| `keep` | int | Number to keep (0=off, -1=unlimited) | `2` |
| `walltime` | string | Force checkpoint write before timeout (`"HH:MM:SS"`) | `"00:00:00"` |
| `write_path` / `read_path` | string | Checkpoint path | |
| `is_resuming` | bool | Resume from checkpoint | Automatically inferred |

#### `[output.debug]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `as_is` | bool | Output raw fields without conversion | `false` |
| `ghosts` | bool | Include ghost cells | `false` |

### `[diagnostics]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `interval` | int (>0) | Logging interval | `1` |
| `blocking_timers` | bool | Staged blocking timers | `false` |
| `colored_stdout` | bool | Colored output | `true` |
| `log_level` | string | `"VERBOSE"`, `"WARNING"`, `"ERROR"` | `"VERBOSE"` |

### `[radiation]` (if needed)

For the full set of radiation parameters (drag and emission), see `input.example.toml`.

---

## Minimal working TOML skeleton

```toml
[simulation]
  name     = "my_run"
  engine   = "SRPIC"
  runtime  = 100.0

[grid]
  resolution = [256, 256]
  extent     = [[-10.0, 10.0], [-10.0, 10.0]]

  [grid.metric]
    metric = "Minkowski"
    coord  = "cartesian"

[boundaries]
  fields     = [["PERIODIC"], ["PERIODIC"]]
  particles  = [["PERIODIC"], ["PERIODIC"]]

[scales]
  larmor0     = 1.0
  skindepth0  = 1.0

[algorithms]
  current_filters = 0

  [algorithms.timestep]
    CFL = 0.45

[particles]
  ppc0  = 32.0
  nspec = 2

  [[particles.species]]
    label    = "electrons"
    mass     = 1.0
    charge   = -1.0
    maxnpart = 5e6

  [[particles.species]]
    label    = "positrons"
    mass     = 1.0
    charge   = 1.0
    maxnpart = 5e6

[output]
  format        = "BPFile"
  interval_time = 10.0

  [output.fields]
    quantities = ["E", "B", "Rho"]

[diagnostics]
  log_level = "VERBOSE"
```

---

## Common pitfalls

1. **Wrong nesting of arrays of arrays** — 2D boundary conditions require `[["PERIODIC"], ["PERIODIC"]]`, not `["PERIODIC", "PERIODIC"]`
2. **Capitalized booleans** — `True` / `False` are not valid TOML
3. **PascalCase written as lowercase** — `engine = "srpic"` is not recognized
4. **Species labels not matching the PGen code** — the PGen uses 1-based indices for injection, but the TOML ordering differs
5. **Forgetting use_weights = true** — PGens that include particle injection must set this, otherwise the weight logic breaks
6. **Typo in [setup] parameter names** — keys in TOML and `params.get()` must match character for character
