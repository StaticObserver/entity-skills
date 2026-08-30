# 05 — External Forces (ext_force + ExternalFields)

> Based on Entity v1.4.4

## When to use

Use this when you need to apply external forces to particles. Trigger keywords: external acceleration, non-electromagnetic force, radiation reaction, external E/B fields, ExternalFields, radiation pressure.

**If particles are only subject to the Lorentz force, skip this reference.**

---

## Two approaches

| Approach | Capability | Complexity | When to use |
|----------|------------|------------|-------------|
| `ext_force` instance | Acceleration only: fx1/fx2/fx3 | Low | Simple space/time-dependent external forces |
| `ExternalFields` method | Acceleration + external E + external B | High | Need to provide field components, or switch per species |

---

## Approach 1: ext_force instance

### Signature

```cpp
struct ExtForce {
    // Which species are subject to this force (0-based C++ indices)
    std::vector<int> species = {0, 1};

    // Acceleration components (local tetrad basis)
    // All methods are optional — the code detects which ones exist
    Inline auto fx1(int sp, real_t time, const coord_t<D>& x) const -> real_t;
    Inline auto fx2(int sp, real_t time, const coord_t<D>& x) const -> real_t;
    Inline auto fx3(int sp, real_t time, const coord_t<D>& x) const -> real_t;
};

// Instance name ext_force is mandatory
ExtForce ext_force;
```

### Parameter description

| Parameter | Meaning | Notes |
|-----------|---------|-------|
| `sp` | Species index (value from the species vector) | 0-based C++ index |
| `time` | Current simulation time | Code units |
| `coord_t<D> x` | Particle physical coordinates | Code units |

### Code example

```cpp
struct ExtForce {
    std::vector<int> species = {0, 1};
    real_t amplitude, k, omega;

    Inline auto fx1(int sp, real_t time, const coord_t<D>& x) const -> real_t {
        return amplitude * math::cos(k * x[0] - omega * time);
    }
    // fx2, fx3 undefined → default to 0
};

// In PGen
ExtForce ext_force;

PGen(...)
  : ext_force { /* species= */ {0, 1}, amplitude, k, omega } {}
```

---

## Approach 2: ExternalFields method

### Signature

```cpp
// PGen method (not a standalone instance)
template <Dimension D>
struct ExtFields {
    // External force (optional)
    Inline auto fx1(...) const -> real_t;
    Inline auto fx2(...) const -> real_t;
    Inline auto fx3(...) const -> real_t;

    // External B field (optional)
    Inline auto bx1(...) const -> real_t;
    Inline auto bx2(...) const -> real_t;
    Inline auto bx3(...) const -> real_t;

    // External E field (optional)
    Inline auto ex1(...) const -> real_t;
    Inline auto ex2(...) const -> real_t;
    Inline auto ex3(...) const -> real_t;
};

// PGen method
auto ExternalFields(simtime_t time, spidx_t sp,
                    const Domain<S, M>& domain) const
    -> std::pair<bool, ExtFields<D>> {
    if (/* per-species condition */) {
        return { true, ExtFields<D>{ time, sp, ... } };
    }
    return { false, ExtFields<D>{} };  // No force applied
}
```

### Parameter description

| Parameter | Meaning |
|-----------|---------|
| `time` | Current simulation time |
| `sp` | Species index |
| `domain` | Current Domain (provides access to mesh and fields) |
| Return value `pair<bool, F>` | bool = whether to apply to this species; F = ExtFields functor |

### Key differences

- **ExternalFields constructs a new ExtFields instance on every call** (returned by value)
- **Can access domain.mesh.metric** → supports coordinate-dependent field computation
- **The bool return value controls per-species switching**
- **Provides force (fx) + B (bx) + E (ex) simultaneously** → fully replaces ext_force and part of ext_current functionality

### Code example

```cpp
template <SimEngine::type S, class M>
struct PGen {
    // ... other members ...

    template <Dimension D>
    struct ExtFields {
        real_t time;
        spidx_t sp;

        Inline auto fx1(const coord_t<D>& x) const -> real_t {
            return amplitude * math::cos(omega * time);
        }
        Inline auto bx3(const coord_t<D>& x) const -> real_t {
            return B_external * math::sin(k * x[0]);
        }
    };

    auto ExternalFields(simtime_t time, spidx_t sp,
                        const Domain<S, M>& domain) const
        -> std::pair<bool, ExtFields<D>> {
        // Only apply to species 0
        if (sp == 0) {
            return { true, ExtFields<D>{ time, sp } };
        }
        return { false, ExtFields<D>{} };
    }
};
```

---

## Trade-offs between the two approaches

```cpp
// ext_force → simple, efficient, suitable for forces that do not depend on domain
// ExternalFields → flexible, can access metric/domain, can set E+B+force simultaneously

// Choose ext_force when:
// - Only acceleration is needed
// - No dependency on domain's internal state
// - Behavior is uniform across all species

// Choose ExternalFields when:
// - Need to provide external E and B fields simultaneously
// - Need per-species conditional logic
// - Need to read domain state (e.g., metric, current field at position)
```

---

## Required headers

```cpp
#include "framework/domain/domain.h"  // Domain<S,M> type
```

ext_force does not require additional archetype headers.

---

## Constraints and incompatibilities

| Constraint | Description |
|------------|-------------|
| Choose either ext_force or ExternalFields | ExternalFields is a superset of ext_force |
| ext_force species are 0-based | Unlike InjectUniform's 1-based indexing! |
| fx returns acceleration in the tetrad basis | Different from ext_current's coordinate-basis convention |
| The ExternalFields ExtFields struct must be copyable by value | A new instance is returned on every call |

---

## Common pitfalls

1. **Species index confusion** — ext_force uses 0-based indexing (`{0, 1}`), particle injection uses 1-based indexing (`{1, 2}`)
2. **Basis confusion** — ext_force's fx is acceleration in the tetrad basis, ext_current's jx is a coordinate-basis component
3. **ExternalFields missing the bool check** — returning true for all species is equivalent to ext_force
4. **Accessing undefined behavior in ExtFields** — only define the ExtFields methods that are actually used; all other components default to zero
