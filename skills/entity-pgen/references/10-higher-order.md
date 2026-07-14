# 10 — Higher-Order Methods (Field Stencil & Particle Shape)

> Based on Entity v1.4.4

## When to Use

Load this reference when the user needs:

- Custom field solver stencils to suppress Cherenkov instability or numerical dispersion
- Particle shape functions above 1st order to improve numerical accuracy
- Reduced numerical heating to allow running at lower resolution
- Configuration of `[algorithms.fieldsolver]` off-diagonal terms (`beta_xy`, etc.)

**Prerequisites**: Parameter tables for `[algorithms.fieldsolver]` and `[algorithms.deposit]` in `09-toml-config.md`.

---

## 1. Generalized Field Stencil

### Background

Based on Blinne et al. (2018), Entity supports customizing the Maxwell solver's finite-difference stencil through `delta` and `beta` parameters in `[algorithms.fieldsolver]`. This can significantly reduce numerical dispersion and suppress Cherenkov instability.

Key header: `kernels/faraday_mink.hpp`

### Parameters

All parameters are configured under `[algorithms.fieldsolver]` (listed in `09-toml-config.md`):

| Parameter | Description |
|-----------|-------------|
| `delta_x`, `delta_y`, `delta_z` | Diagonal direction second-order offset correction coefficients |
| `beta_xy`, `beta_yx` | x-y plane cross-term stencil coefficients |
| `beta_xz`, `beta_zx` | x-z plane cross-term stencil coefficients |
| `beta_yz`, `beta_zy` | y-z plane cross-term stencil coefficients |

### Key Constraint

> **Stencils are optimized for a given CFL; you must use the CFL matching the stencil.**

The CFL in the paper uses standard convention. To convert to Entity, multiply by √(N_dim):
- **2D**: Entity CFL = paper CFL / √2
- **3D**: Entity CFL = paper CFL / √3

### Predefined Stencils

#### 2D Stencils

| Solver | Optimized For | Paper CFL | Entity CFL | delta_x/y | beta_xy/yx |
|--------|--------------|-----------|------------|-----------|------------|
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

**TOML Example (2D Cowan min3)**:

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

#### 3D Stencils

| Solver | Optimized For | Paper CFL | Entity CFL | delta_x/y/z | beta_(all 6) |
|--------|--------------|-----------|------------|-------------|--------------|
| Yee | — | 1.0 | 1/√3 ≈ 0.577 | 0.0 | 0.0 |
| — | min1 | 0.5 | 0.5/√3 | -0.00867 | -0.00867 |
| — | min2 | 0.5 | 0.5/√3 | -0.00733 | -0.00867 |
| — | min3 | 0.5 | 0.5/√3 | -0.006 | -0.00667 |
| — | min4 | 0.1 | 0.1/√3 | -0.048434 | -0.048434 |

> For 3D stencils, delta_x = delta_y = delta_z, and all 6 beta parameters are identical.

### Yee (Default) Stencil

Not setting any delta/beta parameters yields the standard Yee mesh. `delta_x/y/z = 0`, `beta_* = 0`.

---

## 2. Higher-Order Particle Shape Functions

### Background

Before Entity v1.3.0, only 1st-order particle shape functions were supported. Now orders **1 through 11** are supported via the Esirkepov (2001) current deposition scheme.

Key headers:
- `kernels/particle_shapes.hpp`
- `kernels/current_deposit.hpp`
- `kernels/particle_pusher_sr.hpp`

### Build Configuration

Higher-order shape functions are a **compile-time option**, enabled via CMake parameters:

```bash
cmake -B build \
  -D deposit=esirkepov \
  -D shape_order=<N>
```

- `<N>` = integer from 1 to 11
- `deposit=esirkepov` is required (Esirkepov scheme, guarantees charge conservation)

### Effects

- **Numerical heating significantly reduced**: In drifting plasma tests with periodic boundary conditions, higher-order shape functions allow running at resolutions far below the Debye length without uncontrolled numerical heating
- **Accuracy improvement**: Numerical accuracy of current deposition and particle push is enhanced

### Performance Cost

| Dimension | Computational Cost |
|-----------|-------------------|
| 1D | **Negligible** |
| 2D | Moderate |
| 3D | **Can be significant** |

### Important Note

> **Strongly recommended to perform convergence tests before lowering resolution.**

Higher-order shape functions are not a substitute for proper physical resolution but an improvement to the numerical method.

### Corresponding TOML Parameters

`[algorithms.deposit]` section (defined in `09-toml-config.md`):

```toml
[algorithms.deposit]
  enable = true
  order  = 4   # Must match cmake -D shape_order=N
```

---

## Common Pitfalls

1. **CFL mismatch** — Using paper stencil values without converting CFL (forgetting to multiply by √(N_dim)), resulting in CFL condition mismatch
2. **shape_order vs TOML order inconsistency** — CMake `-D shape_order=N` and TOML `algorithms.deposit.order` must match
3. **Forgot to enable esirkepov** — Higher-order shape functions require `-D deposit=esirkepov`; the default deposit scheme cannot be used
4. **Blindly using high-order shape** — In 3D, 11th-order shape functions can have very large computational cost; run convergence tests first
5. **Stencil only applicable to Minkowski** — The generalized field stencil is currently only available under the Minkowski metric (see `faraday_mink.hpp`)

---

## Relationship to PGen Development

Higher-order methods are **primarily set at the TOML configuration level** and do not directly affect PGen code. However, the following scenarios require attention:

| Scenario | PGen Consideration |
|----------|-------------------|
| Non-zero stencil parameters | Does not affect PGen code; TOML configuration only |
| Higher-order shape functions | Does not affect PGen code; build option + TOML only |
| CFL adjustment | TOML `algorithms.timestep.CFL` must match the stencil |
| Lowering resolution | Physical fields/particles in PGen may need re-normalization |
