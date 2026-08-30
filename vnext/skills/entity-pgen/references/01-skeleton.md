# 01 — PGen Skeleton

> Based on Entity v1.4.4

## When to Use

**Required reading**. This is the starting point for every PGen. It defines the structure of the PGen struct, compile-time compatibility checks, constructor signatures, and parameter-reading patterns.

---

## API Signatures

### PGen Struct Template

```cpp
namespace user {
  using namespace ntt;

  template <SimEngine::type S, class M>
  struct PGen {
    // Compatibility declarations (required)
    static constexpr auto engines {
      ::traits::pgen::compatible_with<SimEngine::SRPIC> {}
    };
    static constexpr auto metrics {
      ::traits::pgen::compatible_with<Metric::Minkowski> {}
    };
    static constexpr auto dimensions {
      ::traits::pgen::compatible_with<Dim::_1D, Dim::_2D, Dim::_3D> {}
    };

    // Members
    const SimulationParams& params;
    Metadomain<S, M>&       metadomain;  // or const Metadomain<S, M>&
    const real_t            D = M::Dim;  // Dimension abbreviation

    // TOML parameters (read from [setup])
    real_t param1, param2;

    // Sub-structures (defined by other references)
    InitFields<D> init_flds;  // Optional (field remains zero when absent)

    // Constructor
    PGen(const SimulationParams& p, Metadomain<S, M>& m)
      : params { p }, metadomain { m }, ...
      , init_flds { ... } {}

    // The following methods are optional, define as needed:
    // void InitPrtls(Domain<S, M>&);
    // void CustomPostStep(timestep_t, simtime_t, Domain<S, M>&);
    // auto MatchFields(simtime_t) const -> ...;
    // auto FixFieldsConst(...) const -> ...;
    // ...
  };
}
```

---

## Parameter Reference

### Template Parameters

| Parameter | Meaning | When Determined |
|------|------|---------|
| `S` | `SimEngine::type` enum: `SRPIC` or `GRPIC` | determined by CMake at compile time |
| `M` | metric class (e.g. `Metric<Dim::_2D, Coord::Cartesian>`) | determined at compile time by the TOML grid.metric |

### Trait Enum Values

#### Engines
| Enum Value | Meaning |
|--------|------|
| `SimEngine::SRPIC` | special-relativistic PIC |
| `SimEngine::GRPIC` | general-relativistic PIC |

#### Metrics
| Enum Value | Meaning | Applicable Engines |
|--------|------|---------|
| `Metric::Minkowski` | flat spacetime (Cartesian/spherical) | SRPIC, GRPIC |
| `Metric::Spherical` | spherical coordinates | SRPIC |
| `Metric::QSpherical` | modified spherical coordinates (adjustable grid spacing) | SRPIC |
| `Metric::Kerr_Schild` | Kerr-Schild coordinates (rotating black hole) | GRPIC |
| `Metric::QKerr_Schild` | modified Kerr-Schild | GRPIC |
| `Metric::Kerr_Schild_0` | Kerr-Schild zero-spin limit | GRPIC |

#### Dimensions
| Enum Value | Meaning |
|--------|------|
| `Dim::_1D` | 1D |
| `Dim::_2D` | 2D |
| `Dim::_3D` | 3D |

### Trait Declaration Syntax

```cpp
// Declare compatibility with multiple engines:
static constexpr auto engines {
  ::traits::pgen::compatible_with<SimEngine::SRPIC, SimEngine::GRPIC> {}
};

// Compatible with only one:
static constexpr auto metrics {
  ::traits::pgen::compatible_with<Metric::Minkowski> {}
};

// Partial dimensions:
static constexpr auto dimensions {
  ::traits::pgen::compatible_with<Dim::_2D> {}
};
```

### Constructor Signature Choices

```cpp
// Use const Metadomain — no need to dynamically modify BCs
PGen(const SimulationParams& p, const Metadomain<S, M>& m);

// Use non-const Metadomain — needed when CustomPostStep
// calls metadomain.setFldsBC() or metadomain.setPrtlBC()
PGen(const SimulationParams& p, Metadomain<S, M>& m);
```

### Parameter Reading

`SimulationParams` provides the template method `get<T>(key, default)`:

```cpp
// Read from TOML
real_t temperature = params.template get<real_t>("setup.temperature");
int    n_species   = params.template get<int>("particles.nspec");

// With default value
real_t Bmag = params.template get<real_t>("setup.Bmag", 1.0);
int    freq = params.template get<int>("setup.injection_frequency", 100);

// Read arrays
auto xi_min = params.template get<std::vector<real_t>>("setup.xi_min");
```

**Important**: the keys in `params.template get<>()` correspond directly to TOML paths, with levels separated by `.`.

---

## Required Includes

```cpp
#pragma once

#include "global.h"
#include "enums.h"

#include "traits/pgen.h"           // compatible_with mechanism
#include "utils/error.h"           // raise::Error, raise::KernelError
#include "utils/numeric.h"         // SQR, ZERO, ONE, math namespace

// Field initialization
#include "archetypes/field_setter.h"

// Particle injection
#include "archetypes/energy_dist.h"
#include "archetypes/spatial_dist.h"
#include "archetypes/particle_injector.h"

// Utilities
#include "archetypes/utils.h"

// Framework
#include "framework/domain/metadomain.h"
#include "framework/domain/domain.h"
```

---

## Minimal Runnable PGen

Entity's feature detection is implemented via `if constexpr` — nonexistent methods/members are silently skipped. Therefore, a minimal PGen skeleton only needs trait declarations plus an empty constructor.

### Overview of Optional Members/Methods

The following members/methods are **all optional** (the engine detects their presence via traits and skips them if absent):

| Member/Method | Behavior When Absent |
|-----------|--------------|
| `init_flds` | fields remain zero (vacuum) |
| `InitPrtls()` | no particles injected (fields-only simulation) |
| `CustomPostStep()` | no time-step hook |
| `MatchFields()` | MATCH boundary unavailable |
| `FixFieldsConst()` | FIXED boundary unavailable |
| `AtmFields()` | ATMOSPHERE boundary unavailable |
| `ext_current` | no external current source |
| `ext_force` | no external force |
| `ExternalFields()` | no external E/B/force |
| `CustomFieldOutput()` | no custom field output |
| `CustomStat()` | no custom statistics |
| `CustomParticleUpdate()` | no custom particle update |

Compilation only requires `pgens/<name>/pgen.hpp` to exist (CMake's `set_problem_generator()` only checks this file).

### Code Example: Simplest Skeleton (traits + empty constructor only)

```cpp
#pragma once
#include "enums.h"
#include "global.h"
#include "traits/pgen.h"
#include "framework/domain/metadomain.h"

namespace user {
  using namespace ntt;

  template <SimEngine::type S, class M>
  struct PGen {
    static constexpr auto engines {
      ::traits::pgen::compatible_with<SimEngine::SRPIC> {}
    };
    static constexpr auto metrics {
      ::traits::pgen::compatible_with<Metric::Minkowski> {}
    };
    static constexpr auto dimensions {
      ::traits::pgen::compatible_with<Dim::_1D> {}
    };
    PGen(const SimulationParams&, const Metadomain<S, M>&) {}
  };
} // namespace user
```

### Code Example: Minimal PGen with InitFields

```cpp
#pragma once

#include "global.h"
#include "enums.h"
#include "traits/pgen.h"

#include "archetypes/field_setter.h"
#include "archetypes/utils.h"
#include "framework/domain/metadomain.h"

namespace user {
  using namespace ntt;

  template <Dimension D>
  struct InitFields {
    Inline auto bx1(const coord_t<D>&) const -> real_t { return 1.0; }
    Inline auto ex1(const coord_t<D>&) const -> real_t { return ZERO; }
  };

  template <SimEngine::type S, class M>
  struct PGen {
    static constexpr auto D { M::Dim };
    static constexpr auto engines {
      ::traits::pgen::compatible_with<SimEngine::SRPIC> {}
    };
    static constexpr auto metrics {
      ::traits::pgen::compatible_with<Metric::Minkowski> {}
    };
    static constexpr auto dimensions {
      ::traits::pgen::compatible_with<Dim::_2D> {}
    };

    const SimulationParams& params;
    Metadomain<S, M>&       metadomain;
    InitFields<D>           init_flds;

    PGen(const SimulationParams& p, Metadomain<S, M>& m)
      : params { p }, metadomain { m } {}
  };
} // namespace user
```

This minimal PGen only sets a uniform B field with Bx1=1.0 in 2D SRPIC Minkowski, with no particles. All other PGens extend from this skeleton.

---

## Constraints and Incompatibilities

- **The `init_flds` instance name is mandatory** — the code detects a member named `init_flds` via C++20 concepts
- **Trait declarations must match the TOML** — if the TOML has `engine = "GRPIC"` but the traits only declare SRPIC compatibility, compilation fails
- **D = M::Dim** — standard abbreviation convention; subsequent InitFields and all methods use D instead of an explicit dimension

---

## Common Pitfalls

1. **Forgetting `using namespace ntt`** — ZERO, ONE, SQR, math::cos, etc. are all in the ntt namespace
2. **Declaring traits for unused dimensions** — causes compilation failures for untested dimensions; only declare dimensions actually supported
3. **Wrong choice between const and non-const Metadomain** — using const but later needing setFldsBC() causes a compilation failure. Using non-const when const would suffice is harmless (just a slightly looser constraint)
4. **Missing `template` keyword before `get<type>()`** — because PGen is itself a template class, calling the template method requires writing `params.template get<>()`
5. **`Dim::_2D` vs `Dim::_3D`** — `_2D` is not `2D` (the leading underscore is the enum naming convention); getting it wrong causes a compile error
6. **Dimensions in spherical coordinates** — 2D spherical coordinates are actually (r, theta), but Entity internally still treats this as dimension 2. Boundaries automatically handle periodicity in the phi direction
