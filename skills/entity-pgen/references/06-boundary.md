# 06 — Boundary Conditions (MatchFields / FixFieldsConst / AtmFields)

> Based on Entity v1.4.4

## When to Use

When non-PERIODIC boundary conditions are needed. Trigger keywords: open boundary, matching boundary, fixed boundary, atmosphere boundary, absorbing boundary, horizon boundary, conducting boundary, MatchFields, FixFields, AtmFields.

**If all directions are PERIODIC, skip this reference.**

---

## BC Type Overview

### Field BC

| TOML Value | Meaning | Corresponding Method in PGen |
|------------|---------|------------------------------|
| `"PERIODIC"` | Periodic | Not needed |
| `"MATCH"` | Matching boundary | `MatchFields(time)` or `MatchFieldsInX1/X2/X3(time)` |
| `"FIXED"` | Fixed value boundary | `FixFieldsConst(time, bc_in, em)` |
| `"ATMOSPHERE"` | Atmosphere boundary | `AtmFields(time)` |
| `"CUSTOM"` | Custom | Engine extension |
| `"HORIZON"` | Horizon boundary (GR only) | Not needed (automatic) |
| `"CONDUCTOR"` | Conducting boundary | `FixFieldsConst` |

### Particle BC

| TOML Value | Meaning | Pairing Requirement |
|------------|---------|---------------------|
| `"PERIODIC"` | Periodic | — |
| `"ABSORB"` | Absorbing | — |
| `"ATMOSPHERE"` | Atmosphere | Pair with field ATMOSPHERE |
| `"CUSTOM"` | Custom | — |
| `"REFLECT"` | Reflecting | Pair with field CONDUCTOR |
| `"HORIZON"` | Horizon | — |

---

## MatchFields (MATCH Boundary)

### Signature

```cpp
// Generic MATCH (same for all directions)
auto MatchFields(simtime_t time) const -> FieldSetterType;

// Direction-specific MATCH
auto MatchFieldsInX1(simtime_t time) const -> FieldSetterType;
auto MatchFieldsInX2(simtime_t time) const -> FieldSetterType;
auto MatchFieldsInX3(simtime_t time) const -> FieldSetterType;
```

### Parameter Description

| Parameter | Meaning |
|-----------|---------|
| `time` | Current simulation time (for time-dependent boundary fields) |
| Return value | A field setter struct (same interface as InitFields) |

### Code Example

```cpp
// Simple constant matching field
template <Dimension D>
struct MatchData {
    Inline auto bx1(const coord_t<D>&) const -> real_t { return 1.0; }
    Inline auto ex2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex3(const coord_t<D>&) const -> real_t { return ZERO; }
};

auto MatchFields(simtime_t time) const {
    return MatchData<D>{};
}
```

**MatchFields vs MatchFieldsInX1/X2/X3**:
- `MatchFields` is generic for all directions with MATCH
- `MatchFieldsInX1` is only used on MATCH boundaries in the X1 direction; X2/X3 can use different ones

### TOML Configuration

```toml
[boundaries]
  fields    = [["MATCH"], ["PERIODIC"]]     # X1=MATCH, X2=PERIODIC
  particles = [["ABSORB"], ["PERIODIC"]]
  match_ds  = 0.5                           # Matching layer width
```

---

## FixFieldsConst (FIXED Boundary)

### Signature

```cpp
auto FixFieldsConst(simtime_t time, const bc_in& bc, const em& comp) const
    -> std::pair<real_t, bool>;
```

### Parameter Description

| Parameter | Meaning |
|-----------|---------|
| `time` | Current time |
| `bc` | Which boundary: `bc_in::Mx1`(left), `bc_in::Px1`(right), `bc_in::Mx2`, `bc_in::Px2`, ... |
| `comp` | Which component: `em::ex1`, `em::bx2`, `em::dx3`, ... |
| Return value `pair<real_t, bool>` | Value + whether to apply |

### Code Example

```cpp
auto FixFieldsConst(simtime_t time, const bc_in& bc, const em& comp) const
    -> std::pair<real_t, bool> {

    // X1 left boundary → time-dependent drive
    if (bc == bc_in::Mx1) {
        real_t ramp = time < t_transition
            ? time / t_transition
            : (time > t_transition + t_duration
                ? (t_transition + t_duration - time) / t_duration + 1.0
                : 1.0);

        if (comp == em::ex3) {
            return { amplitude * ramp * math::cos(omega * time), true };
        }
    }

    // Unhandled components → not applied
    return { ZERO, false };
}
```

### TOML Configuration

```toml
[boundaries]
  fields    = [["FIXED"], ["PERIODIC"]]
  particles = [["REFLECT"], ["PERIODIC"]]   # FIXED field + REFLECT particles = CONDUCTOR
```

---

## AtmFields (ATMOSPHERE Boundary)

### Signature

```cpp
auto AtmFields(simtime_t time) const -> FieldSetterType;
```

The return value is a field setter (same interface as InitFields), which sets field values in the atmosphere layer.

### Code Example

```cpp
template <Dimension D>
struct AtmData {
    real_t Bsurf, Rstar, omega, time;

    Inline auto bx1(const coord_t<D>& x) const -> real_t {
        return Bsurf * SQR(Rstar) / SQR(x[0]);
    }
    Inline auto ex2(const coord_t<D>& x) const -> real_t {
        return -omega * x[0] * this->bx1(x) * math::sin(x[1]);
    }
};

auto AtmFields(simtime_t time) const {
    return AtmData<D>{ Bsurf, Rstar, omega, time };
}
```

### TOML Configuration

```toml
[boundaries]
  fields    = [["ATMOSPHERE"]]
  particles = [["ATMOSPHERE"]]

  [boundaries.atmosphere]
    temperature = 0.01
    density     = 1.0
    height      = 1.0
    species     = [1, 2]    # Which species participate in the atmosphere
    ds          = 0.5
    g           = 1.0       # Gravitational acceleration
```

---

## Dynamic BC Switching (in CustomPostStep)

Dynamically switch boundary types at runtime:

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    if (time >= t_open) {
        metadomain.setFldsBC(bc_in::Mx1, FldsBC::MATCH);
        metadomain.setFldsBC(bc_in::Px1, FldsBC::MATCH);
        metadomain.setPrtlBC(bc_in::Mx1, PrtlBC::ABSORB);
        metadomain.setPrtlBC(bc_in::Px1, PrtlBC::ABSORB);
    }
}
```

**Note**: PGen using `setFldsBC`/`setPrtlBC` must use a non-const `Metadomain<S, M>&` (see `01-skeleton.md`).

---

## Spherical Coordinates and GR Special Cases

| Case | BC Settings |
|------|-------------|
| Spherical theta boundary | Automatically set (no need to specify in TOML) |
| Spherical phi boundary | Automatically PERIODIC (due to 2-pi periodicity) |
| GR HORIZON boundary | Automatically set (no need to specify in TOML, no pgen method needed) |

In these cases, TOML only sets BC for dimensions that are **not automatically handled**. For example, 2D Spherical only needs BC settings for the rmin boundary.

---

## Required Includes

```cpp
#include "enums.h"     // bc_in, em, FldsBC, PrtlBC
```

---

## Constraints and Incompatibilities

| Constraint | Description |
|------------|-------------|
| CONDUCTOR field + REFLECT particles | Must be paired |
| ATMOSPHERE field + ATMOSPHERE particles | Must be paired |
| HORIZON GR only | Horizon boundaries do not exist in SRPIC |
| MatchFields and MatchFieldsInX1 priority | When both are defined, the direction-specific version takes priority |
| FixFieldsConst bc_in parameter | Must use `bc_in::Mx1`, not `"x1"` string |

---

## Common Pitfalls

1. **match_ds too small** — matching layer too thin → fields oscillate at boundary → increase match_ds (5-10% of domain)
2. **Forgot particle BC** — only setting fields BC without particles BC → particle accumulation or leakage
3. **Wrong dimensions set for spherical coordinates** — 2D Spherical BC array only needs 1 element (r direction); theta and phi are handled automatically
4. **Incomplete AtmFields** — atmosphere boundaries need `[boundaries.atmosphere]` configuration in TOML to work properly
5. **Forgot to revert after Dynamic BC** — if setFldsBC is a permanent change, all subsequent steps are affected. Use a flag to ensure it switches only once
