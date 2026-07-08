# 01 — PGen Skeleton

> Based on Entity v1.4.4

## When to Use

**Required reading**. This is the starting point for all PGens. Defines the structure of the PGen struct, compile-time compatibility checks, constructor signatures, and parameter reading patterns.

---

## API Signature

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

## Parameter Descriptions

### Template Parameters

| Parameter | Meaning | When Provided |
|------|------|---------|
| `S` | `SimEngine::type` enum: `SRPIC` or `GRPIC` | Determined at compile time by CMake |
| `M` | Metric class (e.g., `Metric<Dim::_2D, Coord::Cartesian>`) | Determined at compile time from TOML's grid.metric |

### Trait Enum Values

#### Engines
| Enum Value | Meaning |
|--------|------|
| `SimEngine::SRPIC` | Special Relativistic PIC |
| `SimEngine::GRPIC` | General Relativistic PIC |

#### Metrics
| Enum Value | Meaning | Applicable Engine |
|--------|------|---------|
| `Metric::Minkowski` | Flat spacetime (Cartesian/Spherical coordinates) | SRPIC, GRPIC |
| `Metric::Spherical` | Spherical coordinates | SRPIC |
| `Metric::QSpherical` | Modified spherical coordinates (adjustable grid spacing) | SRPIC |
| `Metric::Kerr_Schild` | Kerr-Schild coordinates (rotating black hole) | GRPIC |
| `Metric::QKerr_Schild` | Modified Kerr-Schild | GRPIC |
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

### Constructor Signature Selection

```cpp
// Use const Metadomain — no need to dynamically modify BCs
PGen(const SimulationParams& p, const Metadomain<S, M>& m);

// Use non-const Metadomain — needed when CustomPostStep
// calls metadomain.setFldsBC() or metadomain.setPrtlBC()
PGen(const SimulationParams& p, Metadomain<S, M>& m);
```

### Parameter Reading

`SimulationParams` provides a template method `get<T>(key, default)`:

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

**Important**: The key in `params.template get<>()` directly corresponds to the TOML path, with levels separated by `.`.

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

Entity's feature detection is implemented through `if constexpr` -- non-existent methods/members are silently skipped. Therefore, the minimal PGen skeleton only needs trait declarations + an empty constructor.

### Optional Members/Methods Overview

The following members/methods are **all optional** (the engine detects their existence via traits and skips them if absent):

| Member/Method | Behavior When Absent |
|-----------|--------------|
| `init_flds` | Fields remain zero (vacuum) |
| `InitPrtls()` | No particle injection (field-only simulation) |
| `CustomPostStep()` | No timestep hook |
| `MatchFields()` | MATCH boundary unavailable |
| `FixFieldsConst()` | FIXED boundary unavailable |
| `AtmFields()` | ATMOSPHERE boundary unavailable |
| `ext_current` | No external current source |
| `ext_force` | No external force |
| `ExternalFields()` | No external E/B/force |
| `CustomFieldOutput()` | No custom field output |
| `CustomStat()` | No custom statistics |
| `CustomParticleUpdate()` | No custom particle update |

Compilation only requires that `pgens/<name>/pgen.hpp` exists (CMake's `set_problem_generator()` only checks this file).

### Code Example: Bare Skeleton (traits + empty constructor only)

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

This minimal PGen only sets a uniform B-field of Bx1=1.0 with no particles, in 2D SRPIC Minkowski. All other PGens extend from this skeleton.

---

## Constraints and Incompatibilities

- **init_flds instance name is mandatory** — the code detects the member named `init_flds` via C++20 concepts
- **Trait declarations must match TOML** — if the TOML has `engine = "GRPIC"` but traits only declare SRPIC compatibility, compilation fails
- **D = M::Dim** — standard abbreviation convention; subsequent InitFields and all methods use D instead of explicit dimension

---

## Common Pitfalls

1. **Forgetting `using namespace ntt`** — ZERO, ONE, SQR, math::cos etc. are all in the ntt namespace
2. **Declaring traits for unused dimensions** — causes compilation failures in untested dimensions; only declare dimensions actually supported
3. **Wrong choice of const vs non-const Metadomain** — using const when you later need setFldsBC() causes compilation failure. Using non-const when const would suffice is not a problem (just slightly less strict)
4. **Missing `template` keyword before `get<type>()`** — because PGen itself is a template class, calling template methods requires `params.template get<>()`
5. **`Dim::_2D` vs `Dim::_3D`** — `_2D` is not `2D` (leading underscore is an enum naming convention); leads to compilation errors
6. **Dimensionality of Spherical coordinates** — 2D spherical coordinates are actually (r, theta), but Entity internally still treats it as dimension 2. Boundaries automatically handle periodicity in the phi dimension
