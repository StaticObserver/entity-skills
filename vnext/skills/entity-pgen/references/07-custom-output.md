# 07 — Custom Output (CustomFieldOutput + CustomStat)

> Based on Entity v1.4.4

## When to use

Use this when you need to output custom diagnostic quantities beyond the standard field quantities (E, B, J, Rho, T00, etc.). Trigger keywords: custom field, derived field, scalar diagnostics, CustomFieldOutput, CustomStat, extra output quantities.

**If the standard output quantities (`[output.fields] quantities`) already meet your needs, skip this reference.**

---

## CustomFieldOutput (custom field quantities)

### Function signature

```cpp
void CustomFieldOutput(
    const std::string& name,      // Field quantity name (from TOML custom list)
    double*             buffer,   // Output buffer
    int                 index,    // Buffer index for the current grid point
    std::size_t         step,     // Current timestep
    long double         time,     // Current simulation time
    Domain<S, M>&       domain    // Domain (can read fields.em, species)
);
```

### Parameter description

| Parameter | Meaning |
|-----------|---------|
| `name` | Name defined in TOML `[output.fields] custom = ["my_field"]` |
| `buffer` | Output data buffer (one-dimensional, flattened by grid point) |
| `index` | buffer[index] = value at the current grid point |
| `step` | Current timestep index |
| `time` | Current time (code units) |
| `domain` | Provides access to `domain.fields.em`, `domain.species`, etc. |

### TOML configuration

```toml
[output.fields]
  custom = ["my_field_1", "my_field_2"]
```

### Code example

```cpp
void CustomFieldOutput(
    const std::string& name,
    double* buffer,
    int index,
    std::size_t step,
    long double time,
    Domain<S, M>& domain
) {
    if (name == "E_squared") {
        auto& em = domain.fields.em;
        buffer[index] = static_cast<double>(
            SQR(em(em::ex1)) + SQR(em(em::ex2)) + SQR(em(em::ex3))
        );
    } else if (name == "axion_charge") {
        // Custom physical quantity
        auto& em = domain.fields.em;
        buffer[index] = static_cast<double>(
            epsilon * k * em(em::bx1) * math::sin(k * x - omega * time)
        );
    }
}
```

**Important**: make sure the returned value is written as a `double` (explicit cast).

---

## CustomStat (custom scalar statistics)

### Function signature

```cpp
auto CustomStat(
    const std::string& name,   // Statistics name (from TOML custom list)
    Domain<S, M>&       domain // Domain
) -> real_t;
```

### Parameter description

| Parameter | Meaning |
|-----------|---------|
| `name` | Name defined in TOML `[output.stats] custom = ["my_stat"]` |
| `domain` | Domain (same as CustomFieldOutput) |
| Return value | Scalar value. The engine automatically **sums** it across meshblocks |

### TOML configuration

```toml
[output.stats]
  enable     = true
  interval   = 100
  quantities = ["B^2", "E^2", "ExB"]  # Standard quantities
  custom     = ["total_axion_energy"]
```

### Code example

```cpp
auto CustomStat(const std::string& name, Domain<S, M>& domain) -> real_t {
    if (name == "total_axion_energy") {
        auto& em = domain.fields.em;
        real_t energy = ZERO;
        auto range = domain.mesh.rangeActiveCells();
        Kokkos::parallel_reduce(
            "axion_energy",
            range,
            Lambda(cell_t i, cell_t j, real_t& sum) {
                sum += 0.5 * SQR(em(i, j, em::ex1));
            },
            energy
        );
        return energy;
    }
    return ZERO;
}
```

---

## Alternative: precompute in CustomPostStep

For complex diagnostic quantities, precompute into a buffer in CustomPostStep, then just do a deep copy in CustomFieldOutput:

```cpp
// Maintain an ndfield_t buffer member in PGen
ndfield_t<M::Dim, 3> my_buffer;

void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    // Precompute each step
    auto& em = domain.fields.em;
    auto range = domain.mesh.rangeActiveCells();
    Kokkos::parallel_for("precompute", range,
        Lambda(cell_t i, cell_t j) {
            my_buffer(i, j, 0) = /* complex computation */;
        });
}

void CustomFieldOutput(...) {
    if (name == "my_field") {
        buffer[index] = static_cast<double>(my_buffer(i, j, 0));
    }
}
```

This way the heavy computation runs only once in CustomPostStep, rather than being repeated at every output timestep.

---

## Required includes

```cpp
#include "framework/domain/domain.h"
```

No additional archetypes are needed. `Kokkos::parallel_for` and `Kokkos::parallel_reduce` can be used directly.

---

## Constraints and incompatibilities

| Constraint | Description |
|------------|-------------|
| CustomStat return values are automatically summed | Automatically reduced by summation across meshblocks. To get an average → divide by the number of meshblocks outside TOML |
| Output data is double | The buffer is `double*`, but `real_t` read from `em(i,j,em::ex1)` may be float. An explicit cast is required |
| TOML custom names must match | `custom = ["my_field"]` and the code's `name == "my_field"` must match character for character |
| CustomStat output frequency | Controlled by `[output.stats] interval`, not by the `CustomPostStep` frequency |

---

## Common pitfalls

1. **Not registered in TOML** — `CustomFieldOutput` implemented in code but not listed in TOML's `custom = [...]` → the method is never called
2. **double vs real_t** — `real_t` may be `float` (single precision). You must cast to `double` before writing to `buffer`
3. **Misunderstanding CustomStat reduction semantics** — the engine performs a **sum**, not an average. To output an average, divide by the number of meshblocks yourself
4. **Reading em outside a kernel** — `domain.fields.em(i,j,comp)` can only be used inside a Kokkos kernel (parallel_for/parallel_reduce). Host-side operations require a different path
5. **Repeating heavy computation on every output step** — if the computation is expensive but the output frequency is low, use the CustomPostStep precompute + buffer approach
