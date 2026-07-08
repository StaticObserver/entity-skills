# Official PGen Reference Index

> Based on Entity v1.4.4 source (`pgens/` directory), 7 PGens total.
> Source: https://github.com/entity-toolkit/entity/tree/v1.4.4/pgens

Use these official implementations as references when writing a PGen. Each PGen demonstrates a different combination of features and code patterns.

---

## Overview

| PGen | Engine | Metric | Dim | Core Features |
|------|--------|--------|-----|---------------|
| [streaming](#streaming) | SRPIC | Minkowski | 1D/2D/3D | Uniform neutral plasma + drift velocity + oblique B-field |
| [shock](#shock) | SRPIC | Minkowski | 1D/2D/3D | Partially filled plasma + moving injector replenish |
| [reconnection](#reconnection) | SRPIC | Minkowski | 2D/3D | Harris current sheet + guide field + open BC + replenish |
| [turbulence](#turbulence) | SRPIC | Minkowski | 2D/3D | Antenna-driven turbulence + Fourier modes + random driving |
| [magnetosphere](#magnetosphere) | SRPIC | Spherical/QSpherical | 2D | Rotating magnetized star + dipole/monopole field + spherical coordinates |
| [wald](#wald) | GRPIC | Kerr-Schild family | 2D | Black hole magnetosphere Wald solution + uniform vertical B-field |
| [accretion](#accretion) | GRPIC | Kerr-Schild family | 2D | Black hole magnetosphere + pair cascade injection + GJ density |

---

## streaming

**The simplest starter PGen**. Uniform plasma + constant oblique magnetic field. Ideal as a starting point for new PGens.

**Feature Checklist**:
- `InitFields` — Uniform oblique B-field (Bmag, Btheta, Bphi), E = 0
- `InitPrtls` — Pair-injected Maxwellian-distributed particles (nspec must be even), supports per-species independent temperature and drift velocity

**Reference Patterns**: traits declaration, parameter reading, InjectUniformMaxwellians usage, multi-species looping

---

## shock

**Classic implementation of partial filling + moving injector**. Plasma initially occupies only a fraction of the domain, with the injection window advancing over time continuously replenishing fresh plasma.

**Feature Checklist**:
- `InitFields` — Uniform oblique B-field, E = -v x B
- `InitPrtls` — Partially filled Maxwellian distribution (filling_fraction controls fill ratio), two species with different temperatures
- `CustomPostStep` — Moving injector: clear old particles in window → reset EM fields → inject new Maxwellian distribution

**Reference Patterns**: partial domain filling, CustomPostStep particle replenish, field reset

---

## reconnection

**Complete implementation of magnetic reconnection**. Harris-type current sheet + guide field + open boundaries + boundary replenish.

**Feature Checklist**:
- `InitFields` — Harris current sheet B-field (tanh profile) + guide field
- `InitPrtls` — Uniform background Maxwellian + current sheet non-uniform density layer, CurrentLayer spatial distribution, drift velocity within current sheet
- `CustomPostStep` — After open boundaries are activated, replenish background density particles at top/bottom boundaries
- `MatchFields` — x1-direction MATCH boundary field values

**Reference Patterns**: non-uniform field (tanh), non-uniform particle distribution (CurrentLayer), Open BC + replenish, MatchFields, drift velocity computation

---

## turbulence

**Antenna-driven turbulence**. Simulates a turbulent spectrum via Fourier mode superposition + random driving.

**Feature Checklist**:
- `InitFields` — Transverse magnetic field perturbation from multiple Fourier mode superposition + guide field bx3 = 1.0
- `ExternalCurrent` — Driving current computed from vector potential curl (jx1/jx2/jx3)
- `InitPrtls` — Single-temperature Maxwellian injection
- `CustomPostStep` — Random driving (Langevin-type noise + damping), particle escape/reset loop

**Reference Patterns**: ext_current (antenna driving), Fourier mode superposition, CustomPostStep random driving, escape particle handling

---

## magnetosphere

**Spherical coordinates + rotating stellar magnetosphere**. The only official PGen using Spherical/QSpherical coordinates under SRPIC.

**Feature Checklist**:
- `InitFields` — Dipole field (r⁻³ decay, cosθ angular distribution) or monopole field (r⁻² decay)
- `DriveFields` (derives from InitFields) — Superimpose rigid-rotation induced electric field (E = -v×B, v = Ω×r)
- `MatchFields` — Inner boundary matching field values (passing time parameter to DriveFields)

**Reference Patterns**: Spherical coordinates, inherited Field Setter (InitFields → DriveFields), MatchFields passing time-varying parameters, field components in spherical coordinates

---

## wald

**GRPIC black hole magnetosphere initialization**. Sets up initial fields only; no particles.

**Feature Checklist**:
- `InitFields` — Wald vacuum solution (magnetic potential A₃ → finite-difference computation of B and D) or uniform vertical B-field
- Supports three metrics: `Kerr_Schild` / `QKerr_Schild` / `Kerr_Schild_0`

**Reference Patterns**: GRPIC traits, potential method (A₃/A₀/A₁), GR metric API (spin, h_ij, alpha)

---

## accretion

**GRPIC black hole magnetosphere + pair cascade**. The most complex of the 7 PGens.

**Feature Checklist**:
- `InitFields` — Wald solution + uniform vertical B-field (similar to wald)
- `InitPrtls` — Inject e⁻/e⁺ pairs in regions where magnetization exceeds threshold and density is below threshold (Goldreich-Julian density scaling)
- `CustomPostStep` — Periodic pair injection loop

**Reference Patterns**: GRPIC + particle injection, conditional injection (sigma > threshold, density < threshold), GJ density computation, particle initialization in Kerr-Schild coordinates

---

## Feature Matrix

Arranged from top to bottom for quick lookup of PGens containing a specific feature:

| Feature | streaming | shock | reconnection | turbulence | magnetosphere | wald | accretion |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| InitFields (uniform B) | ✓ | ✓ | | | | | |
| InitFields (non-uniform B) | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| InitFields (spherical) | | | | | ✓ | | |
| InitFields (potential method A) | | | | | | ✓ | |
| InitPrtls (Uniform Maxwellian) | ✓ | ✓ | ✓ | ✓ | | | |
| InitPrtls (NonUniform) | | | ✓ | | | | |
| InitPrtls (GR particles) | | | | | | | ✓ |
| ext_current | | | | ✓ | | | |
| MatchFields | | | ✓ | | ✓ | | |
| CustomPostStep | | ✓ | ✓ | ✓ | | | ✓ |
| Spherical coordinates | | | | | ✓ | | |
| GRPIC / Kerr-Schild | | | | | | ✓ | ✓ |
