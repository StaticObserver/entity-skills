# 00 — Normalization Conventions (Fiducial Units)

> Based on Entity v1.4.4

## When to Use

**Required reading**. Entity uses a fiducial unit system in which all physical quantities in the code are expressed in normalized form. Not understanding the normalization conventions leads to magnitude errors in InitFields (field initialization) and ext_current (external current) — the most common and most insidious bug in PGen development.

Trigger scenarios: whenever you need to write InitFields or ext_current, or understand the engine's internal numerical behavior.

---

## Fiducial Units Overview

The Entity kernels (Ampere solver, pusher, deposition) are normalized using a fiducial unit system. In most cases, users only need to work with "physical units" — TOML parameters such as `larmor0`, `extent`, etc. are specified in physical units.

### PIC Equations (CGS units, orthonormal basis)

```
∂B/(c∂t) = -∇×E
∂E/(c∂t) = ∇×B - (4π/c) J

d(βᵢγᵢ)/(c dt) = (qᵢ/(mᵢ c²)) (E + βᵢ×B)
dxᵢ/(c dt) = βᵢ

J = (1/V) Σ_{i∈V} qᵢ wᵢ βᵢ c
```

### Fiducial Quantity Definitions

Introduce a **fiducial particle**: charge q₀ > 0, mass m₀. In a uniform magnetic field B₀, the Larmor radius of this particle moving with βγ = 1 in the plane perpendicular to the field is:

```
ρ₀ = m₀ c² / (q₀ B₀)
```

In Gaussian units, we freely choose **q₀/m₀ ≡ 1** and **c ≡ 1**, hence **B₀ ≡ 1/ρ₀**.

For a plasma composed of stationary ions with charge -q₀ and fiducial particles with charge q₀, both with number density n₀, the oscillation frequency and skin depth are:

```
ω₀² = 4π n₀ q₀² / m₀
d₀ ≡ 1/ω₀
```

Fiducial current density and number density:

```
J₀ ≡ 4π q₀ n₀
n₀ ≡ PPC₀ / V₀
```

### Complete Fiducial Quantity Table

| Symbol | Description | Definition | Code Implementation |
|------|------|------|---------|
| c | speed of light | ≡ 1 | — |
| PPC₀ | fiducial particles per cell | fundamental quantity | `Simulation::params().ppc0()` |
| d₀ | fiducial skin depth | fundamental quantity | `Simulation::params().skindepth0()` |
| ρ₀ | fiducial Larmor radius | fundamental quantity | `Simulation::params().larmor0()` |
| V₀ | fiducial cell volume | see V₀ definition below | `Simulation::params().V0()` |
| n₀ | fiducial number density | ≡ PPC₀ / V₀ | `Simulation::params().n0()` |
| 4πq₀ | fiducial particle charge | ≡ (n₀ d₀²)⁻¹ | `Simulation::params().q0()` |
| m₀ | fiducial particle mass | ≡ q₀ | — (no independent variable) |
| σ₀ | fiducial magnetization | ≡ (d₀/ρ₀)² | `Simulation::params().sigma0()` |
| B₀ | fiducial magnetic field strength | ≡ ρ₀⁻¹ | `Simulation::params().B0()` |
| J₀ | fiducial current density | ≡ 4πq₀ n₀ | — |

**Key note**: `q0()` in the code returns **4πq₀**, not q₀ itself. m₀ has no independent variable in the code, because in Gaussian units we can choose m₀ ≡ q₀. In the TOML, a species' `charge` = qᵢ/q₀ and `mass` = mᵢ/m₀, both dimensionless quantities.

### Normalized Equations

Define q̃ᵢ ≡ qᵢ/q₀, m̃ᵢ ≡ mᵢ/m₀, **e** ≡ **E**/B₀, **b** ≡ **B**/B₀, **j** ≡ 4π**J**/J₀:

```
∂b/∂t = -∇×e
∂e/∂t = ∇×b - (J₀/B₀) j

d(βᵢγᵢ)/dt = (q̃ᵢ/m̃ᵢ) B₀ (e + βᵢ×b)
dxᵢ/dt = βᵢ

j = (V₀/V)·(1/PPC₀)·Σ_{i∈V} q̃ᵢ wᵢ βᵢ
```

All field quantities in the output data are ratios relative to fiducial values; these quantities are insensitive to resolution and particle sampling.

### Definition of the Fiducial Volume V₀

```
V₀ ≡ (Δx)^D                            (Cartesian coordinates)
V₀ ≡ √(det h)|_{r=Δr/2, θ=Δθ/2}       (spherical coordinates, first cell near the pole)
```

where D is the simulation dimension. End users do not need to know the exact numerical value of V₀ — factors like V₀ and n₀ cancel each other out after normalization.

### Physical Quantity Conversion

Any physical quantity in a formula is converted to a dimensionless quantity via the following substitutions:

```
n → ñ n₀,   m → m̃ m₀,   q → q̃ q₀
B → b B₀,   E → e B₀,   4πJ → j J₀,   ct → t
```

After substituting the equivalence relations, all unknown fiducial quantities ultimately reduce to ρ₀ and d₀, leaving no residual extra factors.

**Example**: ratio of plasma rest-mass energy density to magnetic field energy density

```
U_B / (ρ_p c²) ≡ (B²/8π) / (n_p m_p c²)
                = (b / 2 ñ_p m̃_p) · (d₀/ρ₀)²
                = (b / 2 ñ_p m̃_p) · σ₀
```

where ñ_p = n_p/n₀, m̃_p = m_p/m₀, b = B/B₀.

---

## Ampere Kernel Normalization (Critical!)

### Ampere Discretization Formula

The engine's Ampere solver uses the following discretization:

```
dE/dt = - (larmor0 / skindepth0²) × J_total
```

where `J_total = J_deposited + J_external`.

### Constraint on External Current

Because the Ampere kernel carries a `-larmor0/skindepth0²` scaling factor in front, the current value you return in ext_current is **automatically multiplied** by this factor when it enters the engine.

**This means the ext_current return value must compensate in advance**:

```
text_current_return_value = physical_current × (skindepth0² / larmor0)
```

### Constraint on InitFields

Field values defined by InitFields are written directly into the EM arrays, **bypassing the Ampere kernel**. Therefore:

- **Field values returned by InitFields are in code normalized units** — return them directly, with no extra normalization coefficient
- The engine internally handles all unit conversions through relations like B0 = 1/larmor0

---

## Unit-Domain Boundaries

Different code regions in Entity use different unit conventions:

| Code Region | Units Used | Meaning |
|----------|---------|------|
| InitPrtls | **physical units** | position = global physical coordinates, velocity = local orthonormal basis |
| CustomPostStep | **code units** | values in fields.em are already in normalized code units |
| InitFields | **code normalized units** | returned ex/bx are written directly into the EM arrays, no extra coefficient needed |
| ext_current | **code units (pre-compensated)** | returned jx must include the skindepth0²/larmor0 compensation |
| Ampere Kernel | **code units** | internally applies the larmor0/(ppc0·skindepth0²) factor automatically |
| CustomFieldOutput | **code units** | reads domain.fields.em directly |

---

## Complete Derivation Chain

Using the axion-PIC project as an example, demonstrating why the `skindepth0²/larmor0` compensation is needed:

### Physical Equations
```
dE/dt = -J_a - J_plasma
J_a = ε · ω · B · sin(kx - ωt)   (axion contribution to current)
```

### Numerical Discretization
```
E_new = E_old - Δt · (larmor0/skindepth0²) · J_total
```

### To make the electric field evolution match the traveling-wave solution dE/dt = -ε·ω·B·sin(kx-ωt)
```
J_ext = ε · ω · B · sin(kx-ωt) · (skindepth0² / larmor0)
       ^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^
       Physical current           Normalization compensation coefficient
```

### Verification Formula
```
coef = skindepth0² / larmor0
```

---

## Code Examples

### Correct Usage in InitFields

```cpp
template <Dimension D>
struct InitFields {
    real_t larmor0, skindepth0;

    InitFields(real_t l0, real_t s0) : larmor0(l0), skindepth0(s0) {}

    // Field values returned directly (code normalized units)
    Inline auto bx1(const coord_t<D>&) const -> real_t {
        return B0_physical;
    }

    // Field values returned directly (code normalized units)
    Inline auto ex1(const coord_t<D>& x) const -> real_t {
        return -epsilon * B0_physical * math::cos(k * x[0]);
    }
};
```

### Correct Usage in ext_current

```cpp
struct ExtCurrent {
    real_t larmor0, skindepth0;
    real_t coeff;  // = skindepth0² / larmor0

    ExtCurrent(real_t l0, real_t s0)
        : larmor0(l0), skindepth0(s0), coeff(SQR(s0) / l0) {}

    Inline auto jx1(const coord_t<D>& x) const -> real_t {
        // Physical current × compensation coefficient
        return coeff * epsilon * omega * B0 * math::sin(k * x[0] - omega * time);
    }
};
```

---

## Common Pitfalls

1. **Multiplying/dividing by an extra normalization coefficient in InitFields** — the most insidious bug. Field values returned by InitFields are in code normalized units; write them out directly. Extra operations make field magnitudes completely wrong. Symptom: magnetic field weaker by a factor of N, and all physics results are wrong
2. **Forgetting to multiply ext_current by skindepth0²/larmor0** — current strength is wrong, causing the magnitude of dE/dt to be incorrect
3. **Confusing physical units with code units** — using code-unit values in InitPrtls, or comparing against raw physical values in CustomPostStep
4. **Unreasonable choices of larmor0 and skindepth0** — e.g. larmor0 too large making B0 too small, or skindepth0 too small making n0 explode

### A Real Lesson from axion-PIC

During axion-PIC development, InitFields was initially written incorrectly as `return -epsilon * B0 * cos(k*x) / larmor0`. This bug was discovered when a vacuum test showed non-zero DivE. After correcting it to return the code normalized value directly, DivE returned to zero. Meanwhile, ext_current correctly retained the `skindepth0²/larmor0` compensation.
