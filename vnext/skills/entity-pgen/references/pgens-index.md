# Official PGen Reference Index

> Based on Entity v1.4.4 source code (`pgens/` directory), 7 PGens total.
> Source: https://github.com/entity-toolkit/entity/tree/v1.4.4/pgens

Refer to these official implementations when writing a PGen. Each PGen demonstrates a different combination of features and code patterns.

---

## Overview

| PGen | Engine | Metric | Dimensions | Core features |
|------|--------|--------|-----|---------------|
| [streaming](#streaming) | SRPIC | Minkowski | 1D/2D/3D | Uniform neutral plasma + drift velocity + oblique magnetic field |
| [shock](#shock) | SRPIC | Minkowski | 1D/2D/3D | Partially filled plasma + moving injector particle replenishment |
| [reconnection](#reconnection) | SRPIC | Minkowski | 2D/3D | Harris current sheet + guide field + open boundaries + particle replenishment |
| [turbulence](#turbulence) | SRPIC | Minkowski | 2D/3D | Antenna-driven turbulence + Fourier modes + random driving |
| [magnetosphere](#magnetosphere) | SRPIC | Spherical/QSpherical | 2D | Rotating magnetized star + dipole/monopole magnetic field + spherical coordinates |
| [wald](#wald) | GRPIC | Kerr-Schild family | 2D | Black hole magnetosphere Wald solution + uniform vertical magnetic field |
| [accretion](#accretion) | GRPIC | Kerr-Schild family | 2D | Black hole magnetosphere + pair-cascade injection + GJ density |

---

## streaming

**The simplest introductory PGen**. Uniform plasma + constant oblique magnetic field. An ideal starting point for writing a new PGen.

**Feature checklist**:
- `InitFields` — uniform oblique magnetic field (Bmag, Btheta, Bphi), E = 0
- `InitPrtls` — pair-injected Maxwellian particles (nspec must be even), with per-species temperature and drift velocity

**Reference patterns**: traits declaration, parameter reading, InjectUniformMaxwellians usage, multi-species loop

---

## shock

**Classic implementation of partial filling + moving injector**. The plasma initially occupies only part of the computational domain; the injection window advances over time, continuously replenishing fresh plasma.

**Feature checklist**:
- `InitFields` — uniform oblique magnetic field, E = -v x B
- `InitPrtls` — partially filled Maxwellian distribution (filling_fraction controls the fill fraction), different temperatures for the two species
- `CustomPostStep` — moving injector: clears old particles in the window → resets EM fields → injects a new Maxwellian distribution

**Reference patterns**: partial domain filling, CustomPostStep particle replenishment, field reset

---

## reconnection

**Complete magnetic reconnection implementation**. Harris-type current sheet + guide field + open boundaries + boundary particle replenishment.

**Feature checklist**:
- `InitFields` — Harris current sheet magnetic field (tanh profile) + guide field
- `InitPrtls` — uniform background Maxwellian + non-uniform density layer in the current sheet, CurrentLayer spatial distribution, drift velocity inside the current sheet
- `CustomPostStep` — after open-boundary activation, replenishes background-density particles at the upper/lower boundaries
- `MatchFields` — MATCH boundary field values in the x1 direction

**Reference patterns**: non-uniform fields (tanh), non-uniform particle distribution (CurrentLayer), open boundaries + particle replenishment, MatchFields, drift velocity computation

---

## turbulence

**Antenna-driven turbulence**. Simulates a turbulence spectrum via Fourier mode superposition + random driving.

**Feature checklist**:
- `InitFields` — transverse magnetic field perturbations from superposed Fourier modes + guide field bx3 = 1.0
- `ExternalCurrent` — driving current computed from the curl of the vector potential (jx1/jx2/jx3)
- `InitPrtls` — single-temperature Maxwellian injection
- `CustomPostStep` — random driving (Langevin-type noise + damping), particle escape/reset loop

**Reference patterns**: ext_current (antenna drive), Fourier mode superposition, CustomPostStep random driving, escaped particle handling

---

## magnetosphere

**Spherical coordinates + rotating stellar magnetosphere**. The only official PGen that uses Spherical/QSpherical coordinates under SRPIC.

**Feature checklist**:
- `InitFields` — dipole field (r⁻³ decay, cosθ angular distribution) or monopole field (r⁻² decay)
- `DriveFields` (inherits from InitFields) — superposes the rigid-rotation induced electric field (E = -v×B, v = Ω×r)
- `MatchFields` — matching field values at the inner boundary (passes the time parameter to DriveFields)

**Reference patterns**: spherical coordinates, inherited Field Setter (InitFields → DriveFields), MatchFields passing time-varying parameters, field components in spherical coordinates

---

## wald

**GRPIC black hole magnetosphere initialization**. Sets only the initial fields; contains no particles.

**Feature checklist**:
- `InitFields` — Wald vacuum solution (magnetic vector potential A₃ → B and D computed via finite differences) or uniform vertical magnetic field
- Supports three metrics: `Kerr_Schild` / `QKerr_Schild` / `Kerr_Schild_0`

**Reference patterns**: GRPIC traits, vector potential method (A₃/A₀/A₁), GR metric API (spin, h_ij, alpha)

---

## accretion

**GRPIC black hole magnetosphere + pair cascade**. The most complex of the 7 PGens.

**Feature checklist**:
- `InitFields` — Wald solution + uniform vertical magnetic field (similar to wald)
- `InitPrtls` — injects e⁻/e⁺ pairs in regions where magnetization exceeds a threshold and density is below a threshold (Goldreich-Julian density scaling)
- `CustomPostStep` — periodic pair injection loop

**Reference patterns**: GRPIC + particle injection, conditional injection (sigma > threshold, density < threshold), GJ density computation, particle initialization in Kerr-Schild coordinates

---

## Feature matrix

Arranged top to bottom for quick lookup of PGens containing a specific feature:

| Feature | streaming | shock | reconnection | turbulence | magnetosphere | wald | accretion |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| InitFields (uniform B) | ✓ | ✓ | | | | | |
| InitFields (non-uniform B) | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| InitFields (spherical coords) | | | | | ✓ | | |
| InitFields (vector potential A) | | | | | | ✓ | |
| InitPrtls (uniform Maxwellian) | ✓ | ✓ | ✓ | ✓ | | | |
| InitPrtls (non-uniform distribution) | | | ✓ | | | | |
| InitPrtls (GR particles) | | | | | | | ✓ |
| ext_current | | | | ✓ | | | |
| MatchFields | | | ✓ | | ✓ | | |
| CustomPostStep | | ✓ | ✓ | ✓ | | | ✓ |
| Spherical coordinates | | | | | ✓ | | |
| GRPIC / Kerr-Schild | | | | | | ✓ | ✓ |
