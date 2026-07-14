# 03 — Particle Injection (InitPrtls + Replenish)

> Based on Entity v1.4.4

## When to Use

When the simulation needs to include particles. Trigger keywords: plasma, particle initialization, electron/ion injection, Maxwellian distribution, spatial distribution, replenishment injection, particle replenish, pair plasma.

**If this is a vacuum simulation (no particles), skip this reference.**

---

## Injection Phases

Particle injection has two phases, with different code entry points:

| Phase | Entry Method | Units Used | Timing |
|------|---------|---------|------|
| Initial Injection | `InitPrtls(Domain<S,M>&)` | **Physical units** | Called once at simulation start |
| Replenishment Injection | `CustomPostStep(...)` | **Code units** | Called every timestep |

---

## Initial Injection (in InitPrtls)

### Signature

```cpp
void InitPrtls(Domain<S, M>& domain);
```

### InjectUniformMaxwellians (Most Common)

Paired species (e.g., e-/e+) uniform injection + Maxwellian distribution:

```cpp
void InitPrtls(Domain<S, M>& domain) {
    // Define temperatures and drift velocities
    auto temperatures = std::make_pair(T_e, T_p);  // {species1, species2}
    auto drifts = std::make_pair(
        std::vector<real_t>{ ux1, uy1, uz1 },       // species1 four-velocity
        std::vector<real_t>{ ux2, uy2, uz2 }        // species2 four-velocity
    );

    arch::InjectUniformMaxwellians<S, M>(
        params,                         // SimulationParams
        domain,                         // Domain ref
        1.0,                            // Total density (in units of n0)
        temperatures,                   // std::pair<real_t, real_t>
        { 1, 2 },                       // Species indices (1-based)
        drifts,                         // Drift velocities
        false,                          // use_weights (must be false for PGen injection; TOML handles it)
        box                             // optional: boundaries_t<real_t> injection region
    );
}
```

### InjectUniformMaxwellian (Single Temperature)

```cpp
arch::InjectUniformMaxwellian<S, M>(
    params, domain,
    1.0,              // Density
    0.01,             // Uniform temperature
    { 1, 2 },         // Species
    drifts, use_weights, box
);
```

### InjectUniform (Custom Energy Distribution)

```cpp
auto edist1 = arch::energy_dist::Maxwellian<D, Coord::Cartesian>(
    pool, T1, drift_vec1);
auto edist2 = arch::energy_dist::Maxwellian<D, Coord::Cartesian>(
    pool, T2, drift_vec2);

arch::InjectUniform<S, M>(
    params, domain,
    { 1, 2 },                       // Species
    { edist1, edist2 },            // Energy distribution pair
    1.0, false, box
);
```

### InjectNonUniform (Custom Spatial Distribution)

```cpp
auto sdist = MySpatialDistribution<D>(params);

arch::InjectNonUniform<S, M>(
    params, domain,
    { 1, 2 },                       // Species
    { edist1, edist2 },            // Energy distributions
    sdist,                          // Spatial distribution
    1.0,                            // Density factor
    false, box
);
```

### InjectGlobally (Pre-computed Particle Data)

Inject individual particles from array data in the TOML:

```cpp
void InitPrtls(Domain<S, M>& domain) {
    // TOML: [[setup.prtls]]
    //   x1 = [...]  x2 = [...]  ux1 = [...]  ux2 = [...]  ux3 = [...]
    // [[setup.prtl_species]]
    //   species = [0, 1, 0, ...]   // Species index for each particle

    auto prtls_data = params.template get<std::map<std::string,
        std::vector<real_t>>>("setup.prtls");

    arch::InjectGlobally<S, M>(
        metadomain, domain,
        0,                  // Species index
        prtls_data,
        false
    );
}
```

Supported data map keys: `"x1"`, `"x2"`, `"x3"`, `"ux1"`, `"ux2"`, `"ux3"`

---

## Replenishment Injection (in CustomPostStep)

### Replenish Pattern (Most Common)

First compute the current density and inject only where deficient:

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    if (step % 100 != 0) return;  // Inject every 100 steps

    // Step 1: Compute current density into buffer
    ndfield_t<M::Dim, 3> density_buffer("density", domain.mesh.rangeActiveCells());
    arch::ComputeMomentWithSpecies<S, M, FldsID::N, 3>(
        params, domain, { 1, 2 }, density_buffer, {}, 0u, 0u);

    // Step 2: Build replenish spatial distribution
    arch::spatial_dist::ReplenishUniform<M, 3> sdist(
        domain.mesh.metric, density_buffer, 0u, target_density);

    // Step 3: Inject the deficit
    arch::InjectNonUniform<S, M>(
        params, domain,
        { 1, 2 },
        { edist1, edist2 },
        sdist,
        target_density, false, box
    );
}
```

**ReplenishUniform Principle**:
- Compares current density against target density
- `(0.9 * target > current)` → inject `(target - current) / target_max`
- Otherwise returns 0 (no injection needed)

### Non-Uniform Target Replenish

```cpp
// Custom target density profile
struct TargetProfile {
    Inline auto operator()(const coord_t<Dim::_2D>& x) const -> real_t {
        return 1.0 * math::exp(-SQR(x[0]) / SQR(sigma));
    }
};

TargetProfile profile;
arch::spatial_dist::Replenish<M, 3, TargetProfile> sdist(
    metric, density_buffer, 0u, profile, max_density);
```

---

## Energy Distribution Archetypes

| Archetype | Construction | Description |
|-----------|------|------|
| `Maxwellian<D, C>(pool, T, drift)` | (random_pool, temperature, drift four-velocity) | Drifting Maxwellian, most commonly used |
| `Cold<D>` | () | v = 0 |
| `Powerlaw<D>(pool, gmin, gmax, index)` | (random_pool, gamma_min, gamma_max, power-law index) | Relativistic power-law |
| `JuttnerSynge(v, T, pool)` | Free function, not an archetype | Relativistic Juttner-Synge distribution |

### Custom Energy Distribution Interface

```cpp
template <Dimension D>
struct MyEnergyDist {
    random_number_pool_t& pool;

    // Required: set velocity (local tetrad basis)
    Inline void operator()(const coord_t<D>& x, vec_t<Dim::_3D>& v) const {
        // Can use built-in helper functions
        JuttnerSynge(v, temperature, pool);
        // Or set manually
        v[0] = drift_ux;
        v[1] = ZERO;
        v[2] = ZERO;
    }
};
```

---

## Spatial Distribution Interface

### Spatial Distribution for InjectNonUniform

```cpp
template <Dimension D>
struct MySpatialDist {
    // Returns { density fraction (0~1), sampling/sorting weight }
    Inline auto operator()(const coord_t<D>& x) const
        -> Kokkos::pair<real_t, real_t> {
        real_t density = math::exp(-SQR(x[0]) / SQR(sigma));
        return { density, density };  // { injection probability, sampling weight }
    }
};
```

### PointDistribution Pattern (Accessing EM Fields)

Some PGens (e.g., accretion) need to read the current EM field in their spatial distribution:

```cpp
template <class M>
struct PointDistribution {
    // Read fields and density at construction time via Domain*
    PointDistribution(const SimulationParams& p, const M& metric,
                      Domain<SimEngine::GRPIC, M>* domain_ptr) {
        // Pre-compute sigma_crit, read fields.em, fields.buff
        auto& em = domain_ptr->fields.em;
        // ... use em(i1, i2, em::bx1) etc. to read field values
    }

    Inline auto operator()(const coord_t<M::Dim>& x) const
        -> Kokkos::pair<real_t, real_t> {
        real_t prob = sigma_crit(x) / sigma_max;
        return { prob, prob };
    }
};
```

**Key**: PointDistribution is constructed in `InitPrtls` (on the Host side), field reading happens at construction time (not inside the kernel), and `operator()` only does lookup.

---

## Injection Box Definition

```cpp
// Full-domain injection
boundaries_t<real_t> box;
for (auto d = 0u; d < M::Dim; ++d) {
    box.push_back(Range::All);
}

// Partial-region injection (x1 direction [xmin, xmax])
boundaries_t<real_t> box;
box.emplace_back(xmin, xmax);
for (auto d = 1u; d < M::Dim; ++d) {
    box.push_back(Range::All);
}

// Use if constexpr for dimension-dependent box
boundaries_t<real_t> box;
if constexpr (M::Dim == Dim::_2D) {
    box.emplace_back(xmin, xmax);
    box.emplace_back(ymin, ymax);
} else {
    box.emplace_back(xmin, xmax);
}
```

---

## Required Includes

```cpp
#include "archetypes/particle_injector.h"  // InjectUniform*, InjectNonUniform, InjectGlobally
#include "archetypes/energy_dist.h"        // Maxwellian, Cold, Powerlaw, JuttnerSynge
#include "archetypes/spatial_dist.h"       // ReplenishUniform, Replenish
#include "archetypes/utils.h"              // ComputeMomentWithSpecies
```

---

## Constraints and Incompatibilities

| Constraint | Description |
|------|------|
| 1-based species indices | `arch::InjectUniform` etc. use `{1, 2}` not `{0, 1}`, corresponding to the 1st and 2nd species in the TOML |
| use_weights | Pass `false` during injection in PGen; set `use_weights = true` separately in TOML |
| Relationship of ppc0 and density | Total particle count ≈ ppc0 × density × N_cells. Insufficient ppc0 → NaN |
| Replenish buffer dimension | The template parameter N of `ComputeMomentWithSpecies` is the size of the buffer's last dimension |
| Cold distribution + drift | Cannot set drift directly. Need a custom EnergyDistribution or use Maxwellian with low temperature |

---

## Common Pitfalls

1. **0-based vs 1-based species indices** — `arch::InjectUniform` etc. use 1-based indices (TOML species order), not C++ 0-based
2. **Insufficient ppc0** — Too few particles → statistical noise → NaN propagation. Recommend ppc0 >= 16, use 128+ for high precision
3. **maxnpart exceeded** — Increase species' maxnpart or reduce ppc0/density
4. **Forgetting step % N control in Replenish** — Replenishing every step significantly degrades performance
5. **Dead particles not cleaned** — `clear_interval` controls cleaning frequency. Too many dead particles → wasted memory but does not break physics
6. **Dead particle removal breaks charge conservation** — After removing charged particles, need to reset E-field or compensate via injection
7. **Wrong data keys in InjectGlobally** — Keys must be `"x1"`, `"ux1"` etc. in all lowercase with subscript format
