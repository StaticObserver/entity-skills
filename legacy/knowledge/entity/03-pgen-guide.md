# Problem Generator (pgen.hpp) Guide (Archived)

Problem generators define a simulation's **initial conditions**. Each lives in its own subdirectory: `pgens/<name>/pgen.hpp`. Selected at compile time via `-D pgen=<name>`.

## File Structure

```
pgens/<name>/
├── pgen.hpp      # Problem generator code (required)
├── <name>.toml   # Reference input file (recommended)
└── <name>.py     # Visualization script (recommended)
```

## Code Template Skeleton

```cpp
#pragma once

#include "archetypes/problem_generator.h"
#include "archetypes/field_setter.h"
#include "archetypes/energy_dist.h"
#include "archetypes/spatial_dist.h"
#include "archetypes/particle_injector.h"

namespace user {

template <typename S, typename M>
struct PGen : public arch::ProblemGenerator<S, M> {

  // ---- Compatibility declarations (REQUIRED) ----
  // Shortens compile time by limiting template instantiation
  static constexpr auto engines = {
    SimEngine::SRPIC, SimEngine::GRPIC
  };
  static constexpr auto metrics = {
    Metric::Minkowski, Metric::Spherical
  };
  static constexpr auto dimensions = { 1, 2, 3 };

  // ---- Constructor ----
  PGen(SimulationParams& params, Metadomain<S, M>& metadomain)
    : ProblemGenerator<S, M>(params, metadomain) {}

  // ===== FIELD INITIALIZATION =====
  // Define a class with methods for each field component.
  // Methods take coord_t<D>& (physical coordinates) and return real_t.
  // SR: return in tetrad (orthonormal) basis
  // GR: return in coordinate basis
  // Code does staggering/conversion automatically.

  struct InitFields {
    // Electric field components (use correct names for your metric/engine)
    real_t ex1(coord_t<D>& x) { return 0.0; }
    real_t ex2(coord_t<D>& x) { return 0.0; }
    real_t ex3(coord_t<D>& x) { return 0.0; }

    // Magnetic field components
    real_t bx1(coord_t<D>& x) { return 0.0; }
    real_t bx2(coord_t<D>& x) { return 0.0; }
    real_t bx3(coord_t<D>& x) { return 0.0; }
  };

  // The instance MUST be named "init_flds"
  InitFields init_flds;

  // ===== PARTICLE INITIALIZATION =====

  // Called once at simulation start
  void InitPrtls(Domain<S, M>& domain) {
    // Use arch built-in archetypes:

    // Uniform injection with Maxwellian energy distribution
    arch::InjectUniform<S, M>(
      domain,                           // Domain reference
      "electrons",                      // Species label from TOML
      arch::Maxwellian<S, M>(T),       // Energy distribution
      n_density                         // Number density
    );

    // Non-uniform injection
    arch::InjectNonUniform<S, M>(
      domain,
      "positrons",
      MySpatialDist<S, M>(),           // Custom spatial distribution
      MyEnergyDist<S, M>(),            // Custom energy distribution
      1.0                               // Density factor
    );
  }
};
```

## Compatibility Declaration

Must match the simulation engine, metric, and grid dimensionality. Available values:

**Engines**: `SimEngine::SRPIC`, `SimEngine::GRPIC`

**Metrics**: `Metric::Minkowski`, `Metric::Spherical`, `Metric::QSpherical`, `Metric::Kerr_Schild`, `Metric::QKerr_Schild`, `Metric::Kerr_Schild_0`

**Dimensions**: `1`, `2`, `3`

If your setup only works in 2D Minkowski SR, declare:
```cpp
static constexpr auto engines = { SimEngine::SRPIC };
static constexpr auto metrics = { Metric::Minkowski };
static constexpr auto dimensions = { 2 };
```

## Field Initialization (init_flds)

The field init class methods correspond to field components. Naming convention depends on coordinate system:

### Cartesian (Minkowski, Kerr_Schild):
- Electric: `ex1=Ex`, `ex2=Ey`, `ex3=Ez`
- Magnetic: `bx1=Bx`, `bx2=By`, `bx3=Bz`

### Spherical:
- Electric: `ex1=Er`, `ex2=Eθ`, `ex3=Eφ`
- Magnetic: `bx1=Br`, `bx2=Bθ`, `bx3=Bφ`

### Coordinate Basis Convention:
- **SR (SRPIC)**: Return fields in **local tetrad (orthonormal) basis**
- **GR (GRPIC)**: Return fields in **coordinate basis**
- The code handles conversions to code units and staggering automatically

## Particle Initialization (InitPrtls)

### Built-in Archetypes

**`arch::Maxwellian<S, M>(temperature)`** — Maxwell-Boltzmann energy distribution.
Temperature in units of m0 c^2.

**`arch::InjectUniform<S, M>(domain, species_label, energy_dist, density)`** — Uniform spatial distribution with specified energy.

**`arch::InjectNonUniform<S, M>(domain, species_label, spatial_dist, energy_dist, density_factor)`** — Custom spatial and energy distributions.

### Custom Spatial Distribution

Inherit from `arch::SpatialDistribution<S, M>`:
```cpp
template <typename S, typename M>
struct MySpatialDist : public arch::SpatialDistribution<S, M> {
  // Return probability at a given physical coordinate
  real_t operator()(coord_t<D>& x) {
    return /* probability density at position x */;
  }
};
```

### Custom Energy Distribution

Inherit from `arch::EnergyDistribution<S, M>`:
```cpp
template <typename S, typename M>
struct MyEnergyDist : public arch::EnergyDistribution<S, M> {
  // Set velocity in local tetrad basis for a particle
  void operator()(vec_t<D>& v, coord_t<D>& x, int species_index) {
    v[0] = /* vx1 in tetrad basis */;
    v[1] = /* vx2 */;
    v[2] = /* vx3 */;
  }
};
```

All quantities are in **natural physical units** (positions = global physical coords, vectors = local tetrad basis).

## CustomPostStep

Hook called at the end of each timestep. Use for particle injection, boundary handling, or custom physics.

```cpp
void CustomPostStep(std::size_t step, long double time, Domain<S, M>& domain) {
  // Access fields (in CODE UNITS — not physical units!)
  auto& fields = domain.fields;

  // Access particles
  auto& species = domain.species[0];   // First species
  auto& particles = species.particles; // Particle container

  // Iterate over particles, inject new ones, modify fields...
}
```

**IMPORTANT**: Raw quantities in `domain` are in **code units**. You MUST convert if comparing with physical values.

### Particle Purging Example
```cpp
// Tag particles beyond x1 > x_max as dead
for (auto& p : particles) {
  if (p.x1 > x_max) {
    p.tag = ParticleTag::dead;
  }
}
// WARNING: Removing charged particles violates charge conservation!
// Reset E-fields afterwards if needed.
```

## External Force (ext_force)

Define a struct named `ext_force` with optional methods:
```cpp
struct ExtForce {
  std::vector<int> species = {0, 1};  // Which species this applies to

  // Each method: species_index, time, coordinate → acceleration in tetrad basis
  real_t fx1(int sp, real_t time, coord_t<D>& x) { return 0.0; }
  real_t fx2(int sp, real_t time, coord_t<D>& x) { return 0.0; }
  real_t fx3(int sp, real_t time, coord_t<D>& x) { return 0.0; }
} ext_force;
```
All methods are optional — code detects which are present at compile time.

## External Current (ext_current) — v1.2.0+

Source terms for Ampere's law. **Limited to Minkowski space.**
```cpp
struct ExtCurrent {
  // All three components MUST be defined (return 0 if unused)
  // Currents in units of j₀
  real_t jx1(real_t time, coord_t<D>& x) { return 0.0; }
  real_t jx2(real_t time, coord_t<D>& x) { return 0.0; }
  real_t jx3(real_t time, coord_t<D>& x) { return 0.0; }
} ext_current;
```

## Custom Field Output

List names in TOML: `[output.fields] custom = ["my_field"]`

```cpp
void CustomFieldOutput(
    const std::string& name,   // Field name as in TOML
    double* buffer,            // Output buffer to fill
    int index,                 // Buffer index
    std::size_t step,
    long double time,
    Domain<S, M>& domain
) {
  if (name == "my_field") {
    buffer[index] = /* computed value */;
  }
}
```
Output is written as-is — ensure your quantity is covariant (resolution-independent).

Alternative approach: precompute in `CustomPostStep`, deep-copy to buffer here.

## Custom Stats

List names in TOML: `[output.stats] custom = ["my_stat"]`

```cpp
real_t CustomStat(const std::string& name, Domain<S, M>& domain) {
  if (name == "my_stat") {
    return /* scalar value */;
  }
  return 0.0;
}
```
Reduction across meshblocks is done automatically (values are summed).

## Boundary Conditions in PGen

### Match Boundaries (v1.2.0+)
Define `MatchFields(simtime_t)` returning a struct with field methods:
```cpp
auto MatchFields(simtime_t time) {
  struct MatchData {
    real_t ex1(coord_t<D>& x) { return target_value; }
    real_t bx1(coord_t<D>& x) { return target_value; }
    // ...
  };
  return MatchData{};
}

// Direction-specific matching:
auto MatchFieldsInX1(simtime_t time) { /* ... */ }
auto MatchFieldsInX2(simtime_t time) { /* ... */ }
```
Configure `ds` in TOML: `boundaries.match_ds = 0.5` (default: 1% of domain).

### Fixed Boundaries
Define `FixFieldsConst(...)` to set boundary values directly.

### Runtime BC Changes
In `CustomPostStep`, change BCs mid-simulation:
```cpp
metadomain.setFldsBC(bc_in::Mx1, FldsBC::MATCH);   // -X1 direction
metadomain.setFldsBC(bc_in::Px1, FldsBC::MATCH);   // +X1 direction
```

## Key Headers to Include

```cpp
#include "archetypes/problem_generator.h"
#include "archetypes/field_setter.h"
#include "archetypes/energy_dist.h"
#include "archetypes/spatial_dist.h"
#include "archetypes/particle_injector.h"
```

## Important Rules

1. Everything must be in `namespace user {}`
2. `init_flds` instance name is **mandatory** — code looks for this exact name
3. `ext_force` and `ext_current` instance names are **mandatory** if used
4. SR fields return in **tetrad basis**, GR fields in **coordinate basis**
5. `InitPrtls` takes **physical units**; `CustomPostStep` works in **code units**
6. GPU simulations are **not bitwise reproducible** — particle tracking IDs differ between runs
7. Dead particle removal breaks charge conservation — reset fields if needed
