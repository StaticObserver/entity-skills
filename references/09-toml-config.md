# 09 — TOML Configuration Reference

> Based on Entity v1.4.4

## When to Use

**Required reading**. Every PGen needs a matching TOML file. This reference covers all TOML sections and parameters supported by Entity.

Use for: creating a new TOML, validating existing TOML correctness, understanding how TOML parameters map to C++ code.

---

## TOML Syntax Conventions

Entity uses standard TOML v1.0 format with the following conventions:

| Convention | Description |
|------------|-------------|
| String values **PascalCase** | `"SRPIC"` not `"srpic"`, `"Minkowski"`, `"PERIODIC"`, `"Boris"` |
| bool values **lowercase** | `true` / `false` (TOML standard) |
| Arrays | Square brackets: `resolution = [256, 256]` |
| Arrays of arrays | `extent = [[0.0, 10.0], [0.0, 10.0]]` (2D requires 2 inner bracket pairs) |
| Nested tables | `[grid.metric]` or flattened `[grid]` + indented `metric = "..."` — both styles work |
| Array of Tables | `[[particles.species]]` (double square brackets) for repeating sections |

---

## Required Sections

### `[simulation]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `name` | string | Output filename prefix | **Required** |
| `engine` | string | `"SRPIC"` or `"GRPIC"` | **Required** |
| `runtime` | float (>0) | Maximum runtime (code units) | **Required** |
| `number` | int | Number of MPI domains | `1` (no MPI); `MPI_SIZE` (MPI) |
| `decomposition` | array<int> (1-3) | MPI decomposition; `-1` = auto | `[-1, -1, -1]` |

### `[grid]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `resolution` | array<uint> (1-3) | Grid resolution per dimension | **Required** |
| `extent` | array<[float,float]> (1-3) | Physical extent per dimension [min, max] | **Required** |
| `dim` | short (1,2,3) | Number of dimensions | Inferred from resolution |

### `[grid.metric]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `metric` | string | See Metrics enum table | — |
| `coord` | string | `"cartesian"`, `"spherical"`, `"qspherical"` | — |

#### Spherical Coordinate Specific
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `qsph_r0` | float | r0 for QSpherical (negative → nearly uniform grid) | `0.0` |
| `qsph_h` | float (-1→1) | Angular coordinate mapping parameter | `0.0` |

#### Kerr-Schild Specific (GRPIC)
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `ks_a` | float (0→1) | Black hole spin parameter | `0.0` |
| `ks_rh` | float | Horizon radius | Inferred |

### `[particles]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `ppc0` | float (>0) | Fiducial particles per cell | **Required** |
| `nspec` | uint | Number of species | **Required** |
| `use_weights` | bool | Use particle weights (must be true when PGen has injection) | `false` |
| `clear_interval` | uint | Dead particle cleanup interval (steps) | `100` |
| `spatial_sorting_interval` | uint | Spatial sorting interval | `0` (disabled) |

### `[[particles.species]]` (Array of Tables — one per species)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `label` | string | Species label | `"s<INDEX>"` |
| `mass` | float (>=0) | Mass (fiducial units, m0) | **Required** |
| `charge` | float | Charge (fiducial units, q0) | **Required** |
| `maxnpart` | uint (>0) | Maximum particles per MPI task | **Required** |
| `pusher` | string | `"Boris"`, `"Vay"`, `"Boris,GCA"`, `"Vay,GCA"`, `"Photon"`, `"None"` | Massive: Boris, Massless: Photon |
| `n_payloads_real` | ushort | Extra real-valued payload slots | `0` |
| `n_payloads_int` | ushort | Extra integer-valued payload slots | `0` |
| `tracking` | bool | Enable particle tracking (requires compile-time TRACKING=ON) | `false` |
| `radiative_drag` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |
| `emission` | string | `"None"`, `"Synchrotron"`, `"Compton"` | `"None"` |

---

## Common Optional Sections

### `[scales]`

**See `00-normalization.md`**.

| Parameter | Type | Description |
|-----------|------|-------------|
| `larmor0` | float | Fiducial Larmor radius (B0 = 1/larmor0) |
| `skindepth0` | float | Fiducial skin depth (n0 = 1/(larmor0·skindepth0²)) |
| `n0` | float | Fiducial number density |
| `B0` | float | Fiducial magnetic field (engine built-in = 1/larmor0) |
| `sigma0` | float | Fiducial magnetization parameter |
| `omegaB0` | float | Fiducial cyclotron frequency |

### `[boundaries]`

| Parameter | Type | Description |
|-----------|------|-------------|
| `fields` | array<string> (1-3) | Field BC per dimension: `"PERIODIC"`, `"MATCH"`, `"FIXED"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"HORIZON"`, `"CONDUCTOR"` |
| `particles` | array<string> (1-3) | Particle BC per dimension: `"PERIODIC"`, `"ABSORB"`, `"ATMOSPHERE"`, `"CUSTOM"`, `"REFLECT"`, `"HORIZON"` |

**Shorthand syntax**:
```toml
# Same BC for all dimensions
boundaries = { fields = ["PERIODIC"], particles = ["PERIODIC"] }

# 2D per-dimension specification
[boundaries]
  fields = [["PERIODIC"], ["PERIODIC"]]
  particles = [["PERIODIC"], ["PERIODIC"]]
```

**Pairing constraint**: `CONDUCTOR` field BC must pair with `REFLECT` particle BC. `HORIZON` is only valid in GR.

#### `[boundaries.match]` / `[boundaries.absorb]` / `[boundaries.atmosphere]`
See `06-boundary.md`.

### `[algorithms]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `current_filters` | ushort | Current smoothing passes (set to 0 when charge conservation is needed) | `0` |

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
| `enable` | bool | Enable electric field solver | `true` |
| `delta_x/y/z` | float | Higher-order stencil coefficients (second-order) | `0.0` |
| `beta_xy/yx/xz/zx/yz/zy` | float | Off-diagonal correction coefficients | `0.0` |

#### `[algorithms.gr]` (GRPIC only)
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `pusher_eps` | float (>0) | Numerical differentiation step size | `1e-6` |
| `pusher_niter` | ushort (>0) | Newton-Raphson iteration count | `10` |

#### `[algorithms.gca]` (Guiding Center)
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `e_ovr_b_max` | float (0→1) | Maximum E/B for GCA validity | `0.9` |
| `larmor_max` | float | Maximum Larmor radius for GCA | `0.0` |

### `[setup]` — PGen-Specific Parameters

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
| `interval_time` | float | Output interval (time), -1 disables | `-1.0` |
| `separate_files` | bool | Separate file per timestep | `true` |

#### `[output.fields]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `enable` | bool | | `true` |
| `quantities` | array<string> | `"E"`, `"B"`, `"J"`, `"divE"`, `"Rho"`, `"Charge"`, `"N"`, `"Nppc"`, `"T0i"`, `"Tij"`, `"Vi"`, `"D"`, `"H"`, `"divD"`, `"A"` | `[]` |
| `custom` | array<string> | Custom field quantities (see 07-custom-output.md) | `[]` |
| `mom_smooth` | ushort | Moment smoothing window | `0` |
| `interval` / `interval_time` | | Override global | |
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
| `interval` | uint | Stats output interval | `100` |
| `quantities` | array<string> | `"B^2"`, `"E^2"`, `"T00"`, etc. | `["B^2","E^2","T00"]` |
| `custom` | array<string> | Custom statistics quantities (see 07-custom-output.md) | `[]` |

#### `[output.checkpoint]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `interval` | uint | Checkpoint interval | `1000` |
| `keep` | int | How many to keep (0=off, -1=unlimited) | `2` |
| `walltime` | string | Force checkpoint before timeout (`"HH:MM:SS"`) | `"00:00:00"` |
| `write_path` / `read_path` | string | Checkpoint path | |
| `is_resuming` | bool | Resume from checkpoint | Inferred |

#### `[output.debug]`
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `as_is` | bool | Output raw fields without conversion | `false` |
| `ghosts` | bool | Include ghost cells | `false` |

### `[diagnostics]`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `interval` | int (>0) | Logging interval | `1` |
| `blocking_timers` | bool | Per-phase blocking timers | `false` |
| `colored_stdout` | bool | Colored output | `true` |
| `log_level` | string | `"VERBOSE"`, `"WARNING"`, `"ERROR"` | `"VERBOSE"` |

### `[radiation]` (if needed)

See `input.example.toml` for complete radiation parameters (drag and emission).

---

## Minimal Working TOML Skeleton

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

## Common Pitfalls

1. **Incorrect array-of-arrays nesting** — 2D boundary requires `[["PERIODIC"], ["PERIODIC"]]`, not `["PERIODIC", "PERIODIC"]`
2. **Capitalized boolean** — `True` / `False` are not valid TOML
3. **PascalCase written as lowercase** — `engine = "srpic"` is not recognized
4. **Species label mismatch with PGen code** — PGen injects using 1-based indices but TOML ordering differs
5. **Forgot to set use_weights = true** — PGens with particle injection must set this, otherwise weight logic is broken
6. **Typo in [setup] parameter names** — Keys in TOML and `params.get()` must match character-for-character
