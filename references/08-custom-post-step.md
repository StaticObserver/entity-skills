# 08 — Timestep Hook (CustomPostStep)

> Based on Entity v1.4.4

## When to Use

When you need to execute custom logic at every (or every N-th) timestep. Trigger keywords: timestep hook, periodic injection, particle replenishment, moving injector, dynamic boundary switching, moving window, piston, particle cleanup, field driving.

**If your simulation does not require any timestep-level custom behavior, skip this reference.**

---

## Basic Signature

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain);
```

| Parameter | Meaning | Note |
|-----------|---------|------|
| `step` | Current step index (0-based) | Used for `step % N` frequency control |
| `time` | Current simulation time | **Code units** |
| `domain` | Read-write Domain | fields, species, particles, mesh |

### What Domain Provides Access To

- `domain.fields.em` — EM field arrays (Kokkos View)
- `domain.species[s]` — Particle data for species s
- `domain.species[s].particles` — Particle container (i1, dx1, tag, ux1, ux2, ux3, ...)
- `domain.species[s].rangeActiveParticles()` — Kokkos iteration range for active particles
- `domain.mesh` — Mesh metadata
- `domain.mesh.metric` — Metric object

### Unit System

**CustomPostStep uses code units.** This differs from InitPrtls which uses physical units.

- `domain.fields.em(i, j, em::ex1)` → electric field in code units
- `species.particles.ux1(p)` → four-velocity in code units
- `time` → time in code units

---

## Sub-pattern 1: Replenish Injection

**Source**: reconnection, shock, accretion, replenish examples

Maintain a target density in a region, replenishing insufficient particles every N steps:

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    const int replenish_interval = 100;
    if (step % replenish_interval != 0) return;

    // 1. Compute current density
    ndfield_t<M::Dim, 3> buff("density", domain.mesh.rangeActiveCells());
    arch::ComputeMomentWithSpecies<S, M, FldsID::N, 3>(
        params, domain, { 1, 2 }, buff, {}, 0u, 0u);

    // 2. Replenish
    arch::spatial_dist::ReplenishUniform<M, 3> sdist(
        domain.mesh.metric, buff, 0u, target_density);

    // 3. Inject
    arch::InjectNonUniform<S, M, ED1, ED2, decltype(sdist)>(
        params, domain,
        { 1, 2 },              // species
        { edist1, edist2 },    // energy distributions
        sdist,                  // replenishment distribution
        target_density,
        false                   // use_weights
    );
}
```

See the "Replenish Injection" section in `03-particle-injection.md` for details.

---

## Sub-pattern 2: Moving Injector

**Source**: shock pgen

The injector sweeps through the simulation domain at a fixed velocity, clearing old-region particles, resetting fields, and injecting new particles:

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    if (step % injection_frequency != 0) return;

    // 1. Compute injection region
    real_t x_init = global_xmin + filling_fraction * (global_xmax - global_xmin);
    real_t xmax = x_init + injector_velocity * (std::max(time - injection_start, ZERO) + dt);
    real_t xmin = xmax - injection_frequency * dt;

    // 2. Build purge region box
    boundaries_t<bool> incl_ghosts;
    for (auto d = 0; d < M::Dim; ++d) {
        incl_ghosts.emplace_back(false, false);
    }
    boundaries_t<real_t> purge_box;
    purge_box.emplace_back(xmin, global_xmax);
    for (auto d = 1u; d < M::Dim; ++d) {
        purge_box.push_back(Range::All);
    }
    auto extent = domain.mesh.ExtentToRange(purge_box, incl_ghosts);

    // 3. Reset fields in purge region
    tuple_t<ncells_t, M::Dim> x_min, x_max;
    for (auto d = 0; d < M::Dim; ++d) {
        x_min[d] = extent[d].first;
        x_max[d] = extent[d].second;
    }
    Kokkos::parallel_for(
        "ResetFields",
        CreateRangePolicy<M::Dim>(x_min, x_max),
        arch::SetEMFields_kernel<S, M, decltype(init_flds)>{
            domain.fields.em, init_flds, domain.mesh.metric
        }
    );
    metadomain.CommunicateFields(domain, Comm::E | Comm::B);

    // 4. Mark particles in purge region as dead
    for (auto s = 0u; s < 2; ++s) {
        auto& species = domain.species[s];
        auto i1  = species.i1;
        auto dx1 = species.dx1;
        auto tag = species.tag;

        Kokkos::parallel_for(
            "RemoveParticles",
            species.rangeActiveParticles(),
            Lambda(prtldx_t p) {
                if (tag(p) == ParticleTag::dead) return;
                real_t x_Ph = domain.mesh.metric.template convert<1, Crd::Cd, Crd::XYH>(
                    static_cast<real_t>(i1(p)) + static_cast<real_t>(dx1(p)));
                if (x_Ph > xmin) tag(p) = ParticleTag::dead;
            }
        );
    }

    // 5. Inject in new region
    boundaries_t<real_t> inj_box;
    inj_box.emplace_back(xmin, xmax);
    for (auto d = 1u; d < M::Dim; ++d) inj_box.push_back(Range::All);

    arch::InjectUniformMaxwellians<S, M>(
        params, domain, 1.0, temperatures, { 1, 2 }, drifts, false, inj_box
    );
}
```

---

## Sub-pattern 3: Dynamic BC Switching

**Source**: reconnection pgen

Open boundaries after a specified time:

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    static bool boundaries_opened = false;

    if (!boundaries_opened && time >= t_open) {
        metadomain.setFldsBC(bc_in::Mx1, FldsBC::MATCH);
        metadomain.setFldsBC(bc_in::Px1, FldsBC::MATCH);
        metadomain.setPrtlBC(bc_in::Mx1, PrtlBC::ABSORB);
        metadomain.setPrtlBC(bc_in::Px1, PrtlBC::ABSORB);
        boundaries_opened = true;
    }
}
```

**Prerequisite**: The PGen constructor must accept a non-const `Metadomain<S, M>&` (not `const Metadomain<S, M>&`).

---

## Sub-pattern 4: Moving Window

**Source**: moving_window example

```cpp
// Define a MovingWindow inner struct in PGen
struct MovingWindow {
    real_t pos_i;     // integer cell position
    real_t pos_di;    // fractional part
    real_t v;         // window velocity

    void init(const M& metric, real_t global_x) {
        // Physical coordinate → computational coordinate
        pos_i = metric.template convert<1, Crd::Ph, Crd::Cd>(global_x);
        pos_di = ZERO;
    }

    void update(real_t dt, ncells_t N_GHOSTS,
                Metadomain<S, M>& metadomain, Domain<S, M>& domain) {
        // Accumulate displacement
        pos_di += v * dt / domain.mesh.template dx<1>();
        real_t shift = math::floor(pos_di);
        pos_i += shift;
        pos_di -= shift;

        // Trigger window shift
        while (pos_i >= static_cast<real_t>(N_GHOSTS)) {
            arch::MoveWindow<M, in::x1>(domain, metadomain, N_GHOSTS);
            pos_i -= N_GHOSTS;
        }
    }
};

MovingWindow moving_window;

// Initialize in InitPrtls
void InitPrtls(Domain<S, M>& domain) {
    moving_window.init(domain.mesh.metric, global_xmin);
    // ... particle injection ...
}

// Call every step in CustomPostStep
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    moving_window.update(dt, N_GHOSTS, metadomain, domain);
}
```

---

## Sub-pattern 5: CustomParticleUpdate / Piston

**Note**: This is a **separate trait** (not part of CustomPostStep), documented here for convenience.

### Signature

```cpp
auto CustomParticleUpdate(simtime_t time, spidx_t sp, const Domain<S, M>& domain) const -> UpdateFunctor;
```

Returns a functor called for each particle inside the pusher loop:

```cpp
struct PistonUpdate {
    real_t x_piston, v_piston, global_xmax;

    Inline void operator()(
        spidx_t           p,       // particle index
        const kernel::sr::PusherContext& ctx,      // ctx.dt available
        const kernel::sr::PusherBoundaries<D>&,    // ignore for now (piston uses custom logic)
        const ParticleArrays& particles,
        const M& metric
    ) const {
        arch::Piston<M>(SimulationParams, ctx.dt, particles,
                        metric, x_piston, v_piston, /* massive */ true);
    }
};

auto CustomParticleUpdate(simtime_t time, spidx_t sp,
                          const Domain<S, M>& domain) const -> PistonUpdate {
    real_t x_piston = global_xmax + v_piston * time;
    return PistonUpdate{ x_piston, v_piston, global_xmax };
}
```

### TOML Parameters

```toml
[setup]
  piston_velocity = 0.5
```

---

## Field Reset Utility Pattern

In any scenario requiring manual field setting:

```cpp
// 1. Kernel call
Kokkos::parallel_for(
    "SetFields",
    CreateRangePolicy<M::Dim>(x_min, x_max),
    arch::SetEMFields_kernel<S, M, FieldSetterType>{
        domain.fields.em, field_setter, domain.mesh.metric
    }
);

// 2. Must follow with communication (sync ghost cells)
metadomain.CommunicateFields(domain, Comm::E | Comm::B);
```

**Forgetting `CommunicateFields` is the most common field-reset bug.**

---

## Required Includes

```cpp
#include "archetypes/field_setter.h"       // SetEMFields_kernel
#include "archetypes/particle_injector.h"  // Inject* functions
#include "archetypes/spatial_dist.h"       // ReplenishUniform, Replenish
#include "archetypes/utils.h"              // ComputeMomentWithSpecies
#include "archetypes/moving_window.h"      // MoveWindow
#include "archetypes/piston.h"             // Piston
```

---

## Constraints and Incompatibilities

| Constraint | Description |
|------------|-------------|
| Dead particle removal breaks charge conservation | After removing charged particles, you must reset the E-field or compensate via injection |
| GPU not bitwise reproducible | Kokkos parallel_for/reduce ordering may differ across runs |
| `raise::KernelError()` in kernel / `raise::Error()` in host | Do not call `raise::Error()` inside a `Kokkos::parallel_for` Lambda |
| MovingWindow + Dynamic BC | Both require non-const Metadomain; they can coexist |

---

## Common Pitfalls

1. **Unit confusion** — `domain.fields.em` is in code units, `time` is in code units. These differ from InitPrtls physical units
2. **Forgotten CommunicateFields** — Not calling `CommunicateFields` after manually setting fields → ghost cell values out of sync → anomalous fields at boundaries
3. **Forgotten step % N guard** — Running expensive injection/computation every step → severe performance degradation
4. **static variables with multi-domain** — When running under MPI, static variables only affect one domain in the current rank's domain list
5. **Not checking particle tag for dead** — In `rangeActiveParticles()` iterations, particles may already be marked dead; always check `tag(p) == ParticleTag::dead` and skip
6. **Unbounded injection with no frequency control** — Injecting particles every step without cleanup → particle count explosion → maxnpart exceeded
