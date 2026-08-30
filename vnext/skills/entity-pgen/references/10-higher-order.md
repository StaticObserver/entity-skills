# 10 — Higher-Order Methods (Field Stencils and Particle Shape Functions)

> Based on Entity v1.4.4

## When to use

Load this reference when the user needs any of the following:

- Custom field solver stencils to suppress Cherenkov instability or numerical dispersion
- Particle shape functions higher than first order to improve numerical accuracy
- Reduced numerical heating, allowing runs at lower resolution
- Configuring the off-diagonal terms of `[algorithms.fieldsolver]` (`beta_xy`, etc.)

**Prerequisite**: the parameter tables for `[algorithms.fieldsolver]` and `[algorithms.deposit]` in `09-toml-config.md`.

---

## 1. Generalized field stencils

### Background

Based on the work of Blinne et al. (2018), Entity supports customizing the finite-difference stencils of the Maxwell solver through the `delta` and `beta` parameters in `[algorithms.fieldsolver]`. This can significantly reduce numerical dispersion and suppress the Cherenkov instability.

Key header: `kernels/faraday_mink.hpp`

### Parameters

All parameters are configured under `[algorithms.fieldsolver]` (see the table in `09-toml-config.md`):

| Parameter | Description |
|-----------|-------------|
| `delta_x`, `delta_y`, `delta_z` | Second-order offset correction coefficients along the diagonal directions |
| `beta_xy`, `beta_yx` | Cross-term stencil coefficients in the x-y plane |
| `beta_xz`, `beta_zx` | Cross-term stencil coefficients in the x-z plane |
| `beta_yz`, `beta_zy` | Cross-term stencil coefficients in the y-z plane |

### Key constraint

> **Stencils are optimized for a specific CFL; you must use the CFL that matches the stencil.**

The paper (Blinne et al. 2018) uses a normalized CFL convention (Yee limit = 1). Entity's
CFL uses the standard convention — `dt = CFL * dx0`, where `dx0 = metric.dxMin()` (see
`src/framework/parameters/algorithms.cpp`) — so the conversion requires dividing by √(N_dim):
- **2D**: Entity CFL = paper CFL / √2
- **3D**: Entity CFL = paper CFL / √3

### Predefined stencils

#### 2D stencils

| Solver | Optimization target | Paper CFL | Entity CFL | delta_x/y | beta_xy/yx |
|--------|---------------------|-----------|------------|-----------|------------|
| Yee | — | 1.0 | 1/√2 ≈ 0.707 | 0.0 | 0.0 |
| Cowan | min1 | 0.99 | 0.99/√2 | -0.122 | 0.108 |
| Cowan | min2 | 0.985 | 0.985/√2 | -0.120 | 0.106 |
| Cowan | min3 | 0.97 | 0.97/√2 | -0.125 | 0.11 |
| Cowan | min4 | 0.975 | 0.975/√2 | -0.1252 | 0.110 |
| Cowan | min5 | 0.98 | 0.98/√2 | -0.1255 | 0.111 |
| Cowan | min6 | 0.98 | 0.98/√2 | -0.1228 | 0.108 |
| Lehe | min1 | 0.99 | 0.99/√2 | -0.117 | 0.1 |
| Lehe | min2 | 0.97 | 0.97/√2 | -0.124 | 0.11 |
| Lehe | min3 | 0.97 | 0.97/√2 | -0.118 | 0.101 |
| Lehe | min4 | 0.975 | 0.975/√2 | -0.120 | 0.104 |
| Lehe | min5 | 0.98 | 0.98/√2 | -0.121 | 0.106 |
| Lehe | min6 | 0.975 | 0.975/√2 | -0.118 | 0.102 |

**TOML example (2D Cowan min3)**:

```toml
[algorithms.fieldsolver]
  enable   = true
  delta_x  = -0.125
  delta_y  = -0.125
  beta_xy  = 0.11
  beta_yx  = 0.11

[algorithms.timestep]
  CFL = 0.686    # ≡ 0.97 / sqrt(2)
```

#### 3D stencils

| Solver | Optimization target | Paper CFL | Entity CFL | delta_x/y/z | beta_(all 6) |
|--------|---------------------|-----------|------------|-------------|--------------|
| Yee | — | 1.0 | 1/√3 ≈ 0.577 | 0.0 | 0.0 |
| — | min1 | 0.5 | 0.5/√3 | -0.00867 | -0.00867 |
| — | min2 | 0.5 | 0.5/√3 | -0.00733 | -0.00867 |
| — | min3 | 0.5 | 0.5/√3 | -0.006 | -0.00667 |
| — | min4 | 0.1 | 0.1/√3 | -0.048434 | -0.048434 |

> For 3D stencils, delta_x = delta_y = delta_z, and all 6 beta parameters are the same.

### Yee (default) stencil

Not setting any delta/beta parameters gives the standard Yee mesh: `delta_x/y/z = 0`, `beta_* = 0`.

---

## 2. Higher-order particle shape functions

### Background

Before Entity v1.3.0, only first-order particle shape functions were supported. Orders **1 through 11** are now supported via the Esirkepov (2001) current deposition scheme.

Key headers:
- `kernels/particle_shapes.hpp`
- `kernels/current_deposit.hpp`
- `kernels/particle_pusher_sr.hpp`

### Build configuration

Higher-order shape functions are a **compile-time option**, enabled via CMake parameters:

```bash
cmake -B build \
  -D deposit=esirkepov \
  -D shape_order=<N>
```

- `<N>` = integer from 1 to 11
- `deposit=esirkepov` must be specified (the Esirkepov scheme guarantees charge conservation)

### Effects

- **Significantly reduced numerical heating**: in drifting plasma tests with periodic boundary conditions, higher-order shape functions allow running at resolutions well below the Debye length without runaway numerical heating
- **Improved accuracy**: the numerical accuracy of current deposition and particle pushing is improved

### Performance overhead

| Dimension | Computational overhead |
|-----------|------------------------|
| 1D | **Negligible** |
| 2D | Moderate |
| 3D | **Can be large** |

### Important note

> **Strongly recommended: run a convergence test before lowering resolution.**

Higher-order shape functions are no substitute for proper physical resolution; they are an improvement to the numerical method only.

### Corresponding TOML parameter

The `[algorithms.deposit]` section (defined in `09-toml-config.md`):

```toml
[algorithms.deposit]
  enable = true
  order  = 4   # Must match cmake -D shape_order=N
```

---

## Common pitfalls

1. **CFL mismatch** — using the stencil values from the paper directly without converting the CFL (forgetting to divide by √(N_dim)), causing a CFL condition mismatch
2. **shape_order inconsistent with TOML order** — CMake's `-D shape_order=N` and TOML's `algorithms.deposit.order` must match
3. **Forgetting to enable esirkepov** — higher-order shape functions require `-D deposit=esirkepov`; the default deposition scheme cannot be used
4. **Blindly using high-order shape functions** — in 3D, the computational overhead of an 11th-order shape function can be very large; run a convergence test first
5. **Stencils only work with Minkowski** — generalized field stencils are currently available only for the Minkowski metric (see `faraday_mink.hpp`)

---

## Relationship to PGen development

Higher-order methods are **mainly configured at the TOML level** and do not directly affect PGen code. Note the following scenarios:

| Scenario | PGen considerations |
|----------|---------------------|
| Non-zero stencil parameters | Does not affect PGen code; TOML configuration only |
| Higher-order shape functions | Does not affect PGen code; build option + TOML only |
| CFL adjustment | TOML's `algorithms.timestep.CFL` must match the stencil |
| Reduced resolution | Physical fields/particles in the PGen may need renormalization |
