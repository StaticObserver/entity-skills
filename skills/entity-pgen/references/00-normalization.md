# 00 — Normalization Conventions (Fiducial Units)

> Based on Entity v1.4.4

## When to Use

**Required reading**. Entity uses a fiducial unit system, and all physical quantities are expressed in normalized form in the code. Not mastering the normalization conventions will lead to numerical order-of-magnitude errors in InitFields (field initialization) and ext_current (external current) -- the most common and most subtle bugs in PGen development.

Trigger scenarios: any time you need to write InitFields, ext_current, or understand the engine's internal numerical behavior.

---

## Fiducial Units Overview

Entity's kernels (Ampere solver, pusher, deposition) use a fiducial unit system for normalization. In most cases, users only need to work with "physical units" -- parameters in the TOML such as `larmor0`, `extent`, etc. are specified in physical units.

### PIC Equations (CGS units, orthonormal basis)

```
∂B/(c∂t) = -∇×E
∂E/(c∂t) = ∇×B - (4π/c) J

d(βᵢγᵢ)/(c dt) = (qᵢ/(mᵢ c²)) (E + βᵢ×B)
dxᵢ/(c dt) = βᵢ

J = (1/V) Σ_{i∈V} qᵢ wᵢ βᵢ c
```

### Fiducial Quantities Definition

Introduce a **fiducial particle**: charge q₀ > 0, mass m₀. In a uniform magnetic field B₀, the Larmor radius of this particle moving in the perpendicular plane with βγ = 1 is:

```
ρ₀ = m₀ c² / (q₀ B₀)
```

In Gaussian units, we freely choose **q₀/m₀ ≡ 1** and **c ≡ 1**, hence **B₀ ≡ 1/ρ₀**.

For a plasma composed of static ions of charge -q₀ and fiducial particles of charge q₀, both with number density n₀, the oscillation frequency and skin depth are:

```
ω₀² = 4π n₀ q₀² / m₀
d₀ ≡ 1/ω₀
```

Fiducial current density and number density:

```
J₀ ≡ 4π q₀ n₀
n₀ ≡ PPC₀ / V₀
```

### Complete Fiducial Quantities Table

| Symbol | Description | Definition | Code Implementation |
|------|------|------|---------|
| c | Speed of light | ≡ 1 | — |
| PPC₀ | Fiducial particles per cell | Base quantity | `Simulation::params().ppc0()` |
| d₀ | Fiducial skin depth | Base quantity | `Simulation::params().skindepth0()` |
| ρ₀ | Fiducial Larmor radius | Base quantity | `Simulation::params().larmor0()` |
| V₀ | Fiducial cell volume | See V₀ definition below | `Simulation::params().V0()` |
| n₀ | Fiducial number density | ≡ PPC₀ / V₀ | `Simulation::params().n0()` |
| 4πq₀ | Fiducial particle charge | ≡ (n₀ d₀²)⁻¹ | `Simulation::params().q0()` |
| m₀ | Fiducial particle mass | ≡ q₀ | — (no independent variable) |
| σ₀ | Fiducial magnetization parameter | ≡ (d₀/ρ₀)² | `Simulation::params().sigma0()` |
| B₀ | Fiducial magnetic field strength | ≡ ρ₀⁻¹ | `Simulation::params().B0()` |
| J₀ | Fiducial current density | ≡ 4πq₀ n₀ | — |

**Critical note**: `q0()` in the code returns **4πq₀**, not q₀ itself. m₀ has no independent variable in the code because we can choose m₀ ≡ q₀ in Gaussian units. In the TOML, a species' `charge` = qᵢ/q₀ and `mass` = mᵢ/m₀, both dimensionless.

### Normalized Equations

Define q̃ᵢ ≡ qᵢ/q₀, m̃ᵢ ≡ mᵢ/m₀, **e** ≡ **E**/B₀, **b** ≡ **B**/B₀, **j** ≡ 4π**J**/J₀:

```
∂b/∂t = -∇×e
∂e/∂t = ∇×b - (J₀/B₀) j

d(βᵢγᵢ)/dt = (q̃ᵢ/m̃ᵢ) B₀ (e + βᵢ×b)
dxᵢ/dt = βᵢ

j = (V₀/V)·(1/PPC₀)·Σ_{i∈V} q̃ᵢ wᵢ βᵢ
```

All field quantities in the output data are ratios relative to fiducial values, and these quantities are insensitive to resolution and particle sampling.

### Definition of Fiducial Volume V₀

```
V₀ ≡ (Δx)^D                            (Cartesian coordinates)
V₀ ≡ √(det h)|_{r=Δr/2, θ=Δθ/2}       (spherical coordinates, first cell near the pole)
```

where D is the simulation dimension. End users do not need to know the specific value of V₀ -- all factors like V₀ and n₀ cancel out after normalization.

### Physical Quantity Conversion

Physical quantities in any formula are converted to dimensionless quantities through the following substitutions:

```
n → ñ n₀,   m → m̃ m₀,   q → q̃ q₀
B → b B₀,   E → e B₀,   4πJ → j J₀,   ct → t
```

After substituting the equivalence relations, all fiducial unknowns ultimately reduce to ρ₀ and d₀, with no residual extra factors.

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

### Constraints on External Current

Because the Ampere kernel has a `-larmor0/skindepth0²` scaling factor in front, the current values you return in ext_current are **automatically multiplied** by this factor when they enter the engine.

**This means ext_current return values must be pre-compensated**:

```
text_current_return_value = physical_current × (skindepth0² / larmor0)
```

### Constraints on InitFields

Field values defined by InitFields are written directly into EM arrays and **do NOT go through the Ampere kernel**. Therefore:

- **Field values returned by InitFields are in code normalized units** -- just return them directly, no extra normalization coefficients needed
- The engine internally handles all unit conversions through relations like B0 = 1/larmor0

---

## Unit Domain Boundaries

Different code regions in Entity use different unit conventions:

| Code Region | Units Used | Meaning |
|----------|---------|------|
| InitPrtls | **Physical units** | Position = global physical coordinates, velocity = local tetrad basis |
| CustomPostStep | **Code units** | Values in fields.em are already normalized code units |
| InitFields | **Code normalized units** | Returned ex/bx written directly to EM arrays, no extra coefficients |
| ext_current | **Code units (pre-compensated)** | Returned jx must include skindepth0²/larmor0 compensation |
| Ampere Kernel | **Code units** | Internally auto-applies larmor0/(ppc0·skindepth0²) factor |
| CustomFieldOutput | **Code units** | Directly reads domain.fields.em |

---

## Full Derivation Chain

Using the axion-PIC project as an example, demonstrating why the `skindepth0²/larmor0` compensation is needed:

### Physical Equation
```
dE/dt = -J_a - J_plasma
J_a = ε · ω · B · sin(kx - ωt)   (axion contribution to current)
```

### Numerical Discretization
```
E_new = E_old - Δt · (larmor0/skindepth0²) · J_total
```

### To make the E-field change match the traveling wave solution dE/dt = -ε·ω·B·sin(kx-ωt)
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

1. **Extra multiplication/division by normalization coefficients in InitFields** -- the most subtle bug. Field values returned by InitFields are in code normalized units; just write them directly. Extra operations will cause the field value magnitudes to be completely wrong. Symptom: B-field is N times weaker, all physical results are wrong
2. **Forgetting to multiply ext_current by skindepth0²/larmor0** -- current strength is wrong, causing incorrect dE/dt magnitude
3. **Confusing physical units with code units** -- using code unit values in InitPrtls, or directly comparing physical values in CustomPostStep
4. **Unreasonable choices of larmor0 and skindepth0** -- e.g., larmor0 too large causing B0 too small, or skindepth0 too small causing n0 to blow up

### Real Lessons from axion-PIC

During axion-PIC development, InitFields initially had the incorrect `return -epsilon * B0 * cos(k*x) / larmor0`. This bug was discovered because DivE was non-zero in vacuum tests. After correcting to directly return code normalized values, DivE returned to zero. Meanwhile, ext_current correctly kept the `skindepth0²/larmor0` compensation.
