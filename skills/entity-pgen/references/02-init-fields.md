# 02 — Field Initialization (InitFields)

> Based on Entity v1.4.4

## When to Use

When you need to set up the initial electromagnetic field configuration for a simulation. Trigger keywords: initial B-field, initial E-field, magnetic field configuration, electric field distribution, Wald, dipole, Harris sheet.

**If the simulation does not require an initial field (e.g., pure particle electrostatic), skip this reference.**

---

## InitFields Signature

```cpp
template <Dimension D>
struct InitFields {
    // Constructor: read parameters from TOML [setup]
    InitFields(real_t b0, real_t theta, ...);

    // ===== SRPIC: tetrad (orthonormal) basis =====
    Inline auto bx1(const coord_t<D>& x) const -> real_t;
    Inline auto bx2(const coord_t<D>& x) const -> real_t;
    Inline auto bx3(const coord_t<D>& x) const -> real_t;

    Inline auto ex1(const coord_t<D>& x) const -> real_t;
    Inline auto ex2(const coord_t<D>& x) const -> real_t;
    Inline auto ex3(const coord_t<D>& x) const -> real_t;

    // ===== GRPIC additional: D field + potential =====
    Inline auto dx1(const coord_t<D>& x) const -> real_t;
    Inline auto dx2(const coord_t<D>& x) const -> real_t;
    Inline auto dx3(const coord_t<D>& x) const -> real_t;

    // Or use the potential method (code computes B and D via finite differences)
    Inline auto A_1(const coord_t<D>& x) const -> real_t;
    Inline auto A_0(const coord_t<D>& x) const -> real_t;
    Inline auto A_3(const coord_t<D>& x) const -> real_t;

private:
    real_t param1, param2, ...;
};
```

### Instantiation

```cpp
// Declare in PGen
InitFields<D> init_flds;

// Initialize in PGen constructor
PGen(...) : init_flds { B0, theta, ... } {}
```

**The init_flds instance name is mandatory** (detected by the engine via C++20 concepts).

---

## Parameter Descriptions

### Coord Parameter
- `coord_t<D>` — D-dimensional physical coordinate array. `x[0]` = x1 coordinate, `x[1]` = x2 coordinate, `x[2]` = x3 coordinate
- In Cartesian: x1=x, x2=y, x3=z
- In Spherical: x1=r, x2=θ, x3=φ

### SRPIC: Tetrad (Orthonormal) Basis

Field values are returned in the **local tetrad (orthonormal) basis**. The code automatically handles coordinate transformations and staggered grid placement.

| Cartesian Component | Physical Meaning | Spherical Component | Physical Meaning |
|---------------|---------|---------------|---------|
| ex1 | Ex | ex1 | Er |
| ex2 | Ey | ex2 | Eθ |
| ex3 | Ez | ex3 | Eφ |
| bx1 | Bx | bx1 | Br |
| bx2 | By | bx2 | Bθ |
| bx3 | Bz | bx3 | Bφ |

### GRPIC: Coordinate Basis

Field values are returned in the **coordinate basis**. An additional D field (electric displacement vector) is required.

**Two ways to define GR fields:**

**Method 1: Set B and D directly**
```cpp
Inline auto bx1(const coord_t<D>& x) const -> real_t { return ...; }
Inline auto dx1(const coord_t<D>& x) const -> real_t { return ...; }
```

**Method 2: Set magnetic potential A (code computes B = ∇×A via finite differences)**
```cpp
Inline auto A_1(const coord_t<D>& x) const -> real_t { return ...; }
Inline auto A_0(const coord_t<D>& x) const -> real_t { return ...; }
Inline auto A_3(const coord_t<D>& x) const -> real_t { return ...; }
```

Metric API in GRPIC (accessible from InitFields):
- `metric.sqrt_det_h()` — √det(h) = √|g|
- `metric.alpha()` — lapse function
- `metric.beta1()` — shift vector β¹
- `metric.spin()` — black hole spin parameter a
- `metric.template h_<i,j>()` — spatial metric components hij

---

## Required Includes

```cpp
// Math utilities
#include "utils/numeric.h"     // ZERO, ONE, math::cos, math::sin, SQR

// Coordinates and types
#include "global.h"
#include "enums.h"
```

No additional archetype includes are needed -- InitFields directly returns scalar values.

---

## Code Examples

### Example 1: Uniform B-field (SRPIC, 2D Cartesian)

```cpp
template <Dimension D>
struct InitFields {
    real_t Bmag, Btheta, Bphi;

    InitFields(real_t b, real_t theta, real_t phi)
      : Bmag(b)
      , Btheta(theta * static_cast<real_t>(constant::deg2rad))
      , Bphi(phi * static_cast<real_t>(constant::deg2rad)) {}

    Inline auto bx1(const coord_t<D>&) const -> real_t {
        return Bmag * math::cos(Btheta);
    }
    Inline auto bx2(const coord_t<D>&) const -> real_t {
        return Bmag * math::sin(Btheta) * math::sin(Bphi);
    }
    Inline auto bx3(const coord_t<D>&) const -> real_t {
        return Bmag * math::sin(Btheta) * math::cos(Bphi);
    }

    // E-field satisfies E = -v×B (static plasma → E=0)
    Inline auto ex1(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex3(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

### Example 2: Harris Current Sheet (SRPIC, 2D Reconnection)

```cpp
template <Dimension D>
struct InitFields {
    real_t bg_B, bg_Bguide, cs_width;

    InitFields(real_t B, real_t Bg, real_t w)
      : bg_B(B), bg_Bguide(Bg), cs_width(w) {}

    // Reversing Bx1 field
    Inline auto bx1(const coord_t<D>& x) const -> real_t {
        return bg_B * math::tanh(x[1] / cs_width);
    }
    // Guide field
    Inline auto bx3(const coord_t<D>&) const -> real_t {
        return bg_Bguide;
    }
    Inline auto bx2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex1(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex2(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto ex3(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

### Example 3: Wald Vacuum Solution (GRPIC, Kerr-Schild)

```cpp
template <class M, Dimension D>
struct InitFields {
    const M& metric;

    InitFields(const M& m) : metric(m) {}

    Inline auto A_3(const coord_t<D>& x) const -> real_t {
        // Wald: A_φ = (B0/2) * Σ * sin²θ
        real_t r = x[0];
        real_t th = x[1];
        real_t a = metric.spin();
        real_t sigma = SQR(r) + SQR(a * math::cos(th));
        return 0.5 * B0 * sigma * SQR(math::sin(th));
    }

    Inline auto A_1(const coord_t<D>&) const -> real_t { return ZERO; }
    Inline auto A_0(const coord_t<D>&) const -> real_t { return ZERO; }
};
```

The code automatically computes B and D fields from A_3 via finite differences.

### Example 4: Field Setter Inheritance (Time-Dependent Fields)

```cpp
// Base static field
template <Dimension D>
struct InitFields {
    real_t B0;
    InitFields(real_t b) : B0(b) {}
    Inline auto bx1(const coord_t<D>&) const -> real_t { return B0; }
};

// Extension: add rotating E-field (pulsar magnetosphere)
template <Dimension D>
struct DriveFields : public InitFields<D> {
    real_t omega, time;
    DriveFields(real_t b, real_t om, real_t t)
      : InitFields<D>(b), omega(om), time(t) {}

    Inline auto ex2(const coord_t<D>& x) const -> real_t {
        return -omega * x[0] * this->bx1(x) * math::sin(x[1]);
    }
    Inline auto ex3(const coord_t<D>& x) const -> real_t {
        return omega * x[0] * this->bx1(x) * math::cos(x[1]);
    }
};
```

In the PGen, replace `InitFields` with `DriveFields`, and pass time parameters through `AtmFields` or `MatchFields`.

---

## Constraints and Incompatibilities

| Constraint | Description |
|------|------|
| init_flds instance name is mandatory | Cannot be renamed; the engine detects it by name |
| SR does not need dx | Only define ex + bx; undefined components default to 0 |
| GR must set both B and D (or A) | Setting only bx without dx → D field is 0 → electric field solver anomalies |
| Poles in spherical coordinates | Use `cmp::AlmostZero(math::sin(x[1]))` to detect and handle specially |
| E×B = 0 constraint | For pure magnetic field initialization, E×B=0 must hold, otherwise there will be artificial Poynting flux |

---

## Common Pitfalls

1. **Extra multiplication/division by normalization coefficients in InitFields** — Field values returned by InitFields are in code normalized units; just return physical values directly. No need to consider extra normalization coefficients such as larmor0. See `00-normalization.md` for details
2. **Confusion with spherical coordinates** — In Spherical coordinates, ex2 = Eθ, not Ey; the physical meaning is completely different
3. **Mixing SR vs GR basis** — SR returns orthonormal basis, GR returns coordinate basis. If you mistakenly use SR's tetrad convention in GR, field values will be distorted in regions with non-trivial metric
4. **Forgetting the D field** — In GR, setting only bx without dx; the code does not error but the electric field solution is wrong
5. **Inheritance-based Field Setter** — Derived classes need `this->` to access base class members (because it is a template class)
6. **Performance note** — These methods are called for every grid point. Avoid repeated calculations within the method; pre-compute constants in the constructor whenever possible
