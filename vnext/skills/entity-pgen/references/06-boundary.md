# 06 — Boundary Conditions (MatchFields / FixFieldsConst / AtmFields)

> Based on Entity v1.4.4

## When to use

Use this when non-PERIODIC boundary conditions are needed. Trigger keywords: open boundary, matching boundary, fixed boundary, atmosphere boundary, absorbing boundary, horizon boundary, conductor boundary, MatchFields, FixFields, AtmFields.

**If all directions are PERIODIC, skip this reference.**

---

## Overview of boundary condition types

### Field boundary conditions

| TOML value | Meaning | Corresponding PGen method |
|------------|---------|------------------------------|
| `"PERIODIC"` | Periodic boundary | Not needed |
| `"MATCH"` | Matching boundary | `MatchFields(time)` or `MatchFieldsInX1/X2/X3(time)` |
| `"FIXED"` | Fixed-value boundary | `FixFieldsConst(time, bc_in, em)` |
| `"ATMOSPHERE"` | Atmosphere boundary | `AtmFields(time)` |
| `"CUSTOM"` | Custom | Engine extension |
| `"HORIZON"` | Horizon boundary (GR only) | Not needed (handled automatically) |
| `"CONDUCTOR"` | Conductor boundary | `FixFieldsConst` |

### Particle boundary conditions

| TOML value | Meaning | Pairing requirement |
|------------|---------|---------------------|
| `"PERIODIC"` | Periodic boundary | — |
| `"ABSORB"` | Absorbing boundary | — |
| `"ATMOSPHERE"` | Atmosphere boundary | Must pair with field ATMOSPHERE |
| `"CUSTOM"` | Custom | — |
| `"REFLECT"` | Reflecting boundary | Must pair with field CONDUCTOR |
| `"HORIZON"` | Horizon boundary | — |

---

## MatchFields (MATCH boundary)

### Function signature

```cpp
// Generic MATCH (same for all directions)
auto MatchFields(simtime_t time) const -> FieldSetterType;

// Direction-specific MATCH
auto MatchFieldsInX1(simtime_t time) const -> FieldSetterType;
auto MatchFieldsInX2(simtime_t time) const -> FieldSetterType;
auto MatchFieldsInX3(simtime_t time) const -> FieldSetterType;
```

### Parameter description

| Parameter | Meaning |
|-----------|---------|
| `time` | Current simulation time (for time-varying boundary fields) |
| Return value | A field setter struct (same interface as InitFields) |

### Code example

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

**Difference between MatchFields and MatchFieldsInX1/X2/X3**:
- `MatchFields` applies generically to all MATCH directions
- `MatchFieldsInX1` is used only for the MATCH boundary in the X1 direction; X2/X3 can use different implementations

### TOML configuration

```toml
[boundaries]
  fields    = [["MATCH"], ["PERIODIC"]]     # X1=MATCH, X2=PERIODIC
  particles = [["ABSORB"], ["PERIODIC"]]
  match_ds  = 0.5                           # Matching layer width
```

---

## FixFieldsConst (FIXED boundary)

### Function signature

```cpp
auto FixFieldsConst(simtime_t time, const bc_in& bc, const em& comp) const
    -> std::pair<real_t, bool>;
```

### Parameter description

| Parameter | Meaning |
|-----------|---------|
| `time` | Current time |
| `bc` | Which boundary: `bc_in::Mx1` (left), `bc_in::Px1` (right), `bc_in::Mx2`, `bc_in::Px2`, ... |
| `comp` | Which component: `em::ex1`, `em::bx2`, `em::dx3`, ... |
| Return value `pair<real_t, bool>` | Value + whether to apply |

### Code example

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

### TOML configuration

```toml
[boundaries]
  fields    = [["FIXED"], ["PERIODIC"]]
  particles = [["REFLECT"], ["PERIODIC"]]   # FIXED field + REFLECT particles = CONDUCTOR
```

---

## AtmFields (ATMOSPHERE boundary)

### Function signature

```cpp
auto AtmFields(simtime_t time) const -> FieldSetterType;
```

The return value is a field setter (same interface as InitFields) used to set the field values in the atmosphere layer.

### Code example

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

### TOML configuration

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

## Dynamically switching boundary conditions (in CustomPostStep)

Switch boundary types at runtime:

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

**Note**: A PGen that uses `setFldsBC`/`setPrtlBC` must take a non-const `Metadomain<S, M>&` (see `01-skeleton.md`).

---

## Special cases: spherical coordinates and GR

| Case | Boundary condition setup |
|------|--------------------------|
| Spherical theta boundary | Set automatically (no need to specify in TOML) |
| Spherical phi boundary | Automatically PERIODIC (due to 2-pi periodicity) |
| GR HORIZON boundary | Set automatically (no need to specify in TOML, and no pgen method required) |

In these cases, the TOML only needs boundary conditions for dimensions **not handled automatically**. For example, a 2D Spherical setup only needs a boundary condition for the rmin boundary.

---

## Required headers

```cpp
#include "enums.h"     // bc_in, em, FldsBC, PrtlBC
```

---

## Constraints and incompatibilities

| Constraint | Description |
|------------|-------------|
| CONDUCTOR fields + REFLECT particles | Must be paired |
| ATMOSPHERE fields + ATMOSPHERE particles | Must be paired |
| HORIZON is GR only | No horizon boundary exists in SRPIC |
| Priority of MatchFields vs MatchFieldsInX1 | When both are defined, the direction-specific version takes precedence |
| FixFieldsConst bc_in parameter | Must use `bc_in::Mx1`, not the `"x1"` string |

---

## Common pitfalls

1. **match_ds too small** — matching layer too thin → fields oscillate at the boundary → increase match_ds (5-10% of the simulation domain)
2. **Forgetting particle boundary conditions** — only field boundary conditions set, not particle ones → particles pile up or leak
3. **Wrong dimension setup for spherical coordinates** — 2D Spherical boundary condition arrays need only 1 element (r direction); theta and phi are handled automatically
4. **Incomplete AtmFields** — the atmosphere boundary requires `[boundaries.atmosphere]` configured in TOML to work properly
5. **Forgetting to restore after dynamic boundary switch** — if setFldsBC is a permanent change, all subsequent steps are affected. Use a flag to ensure the switch happens only once
