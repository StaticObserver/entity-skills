# 04 — External Current Source (ext_current)

> Based on Entity v1.4.4

## When to Use

When you need to add an external source current to Ampere's law. Trigger keywords: external current, antenna drive, axion current, Wald current, J_ext, current source term.

**Only applies to Minkowski metric (SRPIC). GRPIC does not support ext_current.**

---

## API Signature

### Official API (coordinate-only access)

```cpp
struct ExtCurrent {
    // All three components must be defined
    Inline auto jx1(const coord_t<D>& x) const -> real_t;
    Inline auto jx2(const coord_t<D>& x) const -> real_t;
    Inline auto jx3(const coord_t<D>& x) const -> real_t;

    // Internal parameters
    real_t coeff, k, omega, B0;
};
```

**Instance name `ext_current` is mandatory** — the engine detects it via C++20 concept.

### Engine-Modified API (access to EM fields and time)

```cpp
// Requires modifying Entity engine source (ampere_mink.hpp) to extend Context
struct ExtCurrent {
    template <class Context>
    Inline auto jx1(const Context& ctx) const -> real_t {
        // ctx.x_Ph  — physical coordinates
        // ctx.em(i1, i2, em::bx1)  — read current EM field (available after engine modification)
        // ctx.time  — current simulation time
        // ctx.dx    — grid spacing
    }
};
```

**Important**: Context extension requires modifying `src/engines/srpic/ampere_mink.hpp`. This is an **engine modification** — route to entity-core-dev.

---

## Parameter Description

| Parameter | Meaning | Units |
|-----------|---------|-------|
| `coord_t<D> x` | Physical coordinates of the current grid point | code units |
| `real_t` return value | External current density component | j0 = n0 * q0 * c (requires normalization compensation) |
| `coeff = skindepth0^2 / larmor0` | Ampere normalization compensation coefficient | — |

---

## Normalization Compensation (Critical!)

**See `00-normalization.md` for the full derivation.**

Ampere discretization formula:
```
dE/dt = - (larmor0 / (ppc0 * skindepth0^2)) x (J_deposited + J_external)
```

**Every current component returned in ext_current must be pre-multiplied by `skindepth0^2 / larmor0`**:

```cpp
struct ExtCurrent {
    real_t larmor0, skindepth0;
    real_t coeff;  // = skindepth0^2 / larmor0 (computed in constructor)

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        // Physical current x normalization compensation
        return coeff * epsilon * omega * B0 * math::sin(k * x[0] - omega * time);
    }
};
```

---

## Required Includes

```cpp
#include "utils/numeric.h"  // ZERO, ONE, SQR, math::
```

No additional archetype needed — ext_current is called directly by the engine kernel.

---

## Code Examples

### Example 1: Static Current Source (Wald vacuum proof of concept)

```cpp
struct ExtCurrent {
    real_t coeff, amp;

    ExtCurrent(real_t l0, real_t s0, real_t a)
      : coeff(SQR(s0) / l0), amp(a) {}

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        return coeff * amp * math::sin(x[0]);
    }
    Inline auto jx2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto jx3(const coord_t<D>&) const -> real_t { return ZERO; }
};

// In PGen
ExtCurrent ext_current;

PGen(...) : ext_current { larmor0, skindepth0, amplitude } {}
```

### Example 2: Traveling Wave Current Source (axion-PIC mode)

```cpp
struct ExtCurrent {
    real_t coeff, epsilon, omega, k, B0;
    real_t time;  // Must be updated in CustomPostStep or externally

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        return coeff * epsilon * omega * B0
             * math::sin(k * x[0] - omega * time);
    }
    Inline auto jx2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto jx3(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

**Issue**: The official ext_current can only access coordinates, not `time`. Time-dependent current sources require:
1. Updating the ext_current's time member in `CustomPostStep` (if ext_current is not const)
2. Or modifying the engine so Context includes time → entity-core-dev

---

## Constraints and Incompatibilities

| Constraint | Description |
|------------|-------------|
| **Minkowski only** | ext_current is only valid in the SRPIC engine. GRPIC does not support it |
| **All three components must be defined** | Even unused ones must return ZERO. Undefined components = undefined behavior |
| **Cannot access real-time EM fields (official API)** | Only coordinates are readable. Use Context extension for field access (engine modification) |
| **Cannot directly read time** | Must pass time through ext_current's member variable in CustomPostStep (if not const) |

---

## Common Pitfalls

1. **Forgetting to multiply by skindepth0^2/larmor0** — values returned by ext_current go directly into the Ampere kernel and are scaled by larmor0/skindepth0^2. No compensation → wrong order-of-magnitude current strength. **This is the most common ext_current bug**
2. **Attempting to use ext_current in GRPIC** — compilation failure or undefined behavior at runtime. The Ampere solver must be modified for GR
3. **Time-dependent current source without time access** — the official API has no time parameter. Must pass via member variable and update in CustomPostStep
4. **EM field access limitations** — EM field access in Context is an engine modification, not part of the standard API. If PGen needs to read real-time B/E to compute current → mark as engine modification
5. **All three components defined** — missing one undetected jx method may cause anomalous behavior for that component (depends on trait detection logic)
