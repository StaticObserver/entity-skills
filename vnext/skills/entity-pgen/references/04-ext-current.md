# 04 — External Current Source (ext_current)

> Based on Entity v1.4.4

## When to Use

Use this when you need to add an external source current to Ampere's law. Trigger keywords: external current, antenna drive, axion current, Wald current, J_ext, current source term.

**Only applicable to the Minkowski metric (SRPIC). GRPIC does not support ext_current.**

---

## API Signatures

### Official API (Coordinate Access Only)

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

**The instance name `ext_current` is mandatory** — the engine detects it via a C++20 concept.

### Engine-Modified API (Access to EM Fields and Time)

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

**Important**: extending Context requires modifying `src/engines/srpic/ampere_mink.hpp`. This counts as an **engine modification** — hand it off to entity-core-dev.

---

## Parameter Reference

| Parameter | Meaning | Units |
|-----------|---------|-------|
| `coord_t<D> x` | physical coordinates of the current grid point | code units |
| `real_t` return value | external current density component | j0 = n0 * q0 * c (requires normalization compensation) |
| `coeff = skindepth0^2 / larmor0` | Ampere normalization compensation coefficient | — |

---

## Normalization Compensation (Critical!)

**For the full derivation, see `00-normalization.md`.**

Ampere discretization formula:
```
dE/dt = - (larmor0 / (ppc0 * skindepth0^2)) x (J_deposited + J_external)
```

**Every current component returned by ext_current must be pre-multiplied by `skindepth0^2 / larmor0`**:

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

## Required Headers

```cpp
#include "utils/numeric.h"  // ZERO, ONE, SQR, math::
```

No additional archetypes needed — ext_current is called directly by the engine kernel.

---

## Code Examples

### Example 1: Static Current Source (Wald Vacuum Proof of Concept)

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

### Example 2: Traveling-Wave Current Source (axion-PIC Pattern)

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

**Problem**: the official ext_current can only access coordinates, not `time`. Time-dependent current sources require:
1. Updating ext_current's time member in `CustomPostStep` (provided ext_current is not const)
2. Or modifying the engine so that Context includes time → entity-core-dev

---

## Constraints and Incompatibilities

| Constraint | Explanation |
|------------|-------------|
| **Minkowski only** | ext_current is only valid in the SRPIC engine. GRPIC does not support it |
| **All components must be defined** | even unused components must return ZERO. Undefined components = undefined behavior |
| **No access to live EM fields (official API)** | only coordinates can be read. For EM field access, use the Context extension (engine modification) |
| **No direct access to time** | time must be passed through a member variable of ext_current and updated in CustomPostStep (provided it is not const) |

---

## Common Pitfalls

1. **Forgetting to multiply by skindepth0^2/larmor0** — the value returned by ext_current goes directly into the Ampere kernel and is scaled by larmor0/skindepth0^2. Without compensation → current strength magnitude is wrong. **This is the most common ext_current bug**
2. **Trying to use ext_current in GRPIC** — causes compilation failure or runtime undefined behavior. The Ampere solver under GR must be modified
3. **Time-dependent current source with no access to time** — the official API has no time parameter. Time must be passed via a member variable and updated in CustomPostStep
4. **EM field access limitations** — accessing EM fields in Context is an engine modification, not part of the standard API. If the PGen needs to read live B/E to compute the current → flag it as an engine modification
5. **All three components must be defined** — omitting a jx method that goes undetected can cause abnormal behavior in that component (depends on the trait detection logic)
