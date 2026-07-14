# 07 — Custom Output (CustomFieldOutput + CustomStat)

> Based on Entity v1.4.4

## When to Use

When you need to output custom diagnostics beyond the standard field quantities (E, B, J, Rho, T00, etc.). Trigger keywords: custom field, derived field, scalar diagnostics, CustomFieldOutput, CustomStat, extra output quantities.

**If the standard output quantities (`[output.fields] quantities`) are sufficient, skip this reference.**

---

## CustomFieldOutput (Custom Field Quantities)

### Signature

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

### Parameter Description

| Parameter | Meaning |
|-----------|---------|
| `name` | Name defined in TOML `[output.fields] custom = ["my_field"]` |
| `buffer` | Output data buffer (1D, flattened by grid points) |
| `index` | buffer[index] = value at current grid point |
| `step` | Current timestep index |
| `time` | Current time (code units) |
| `domain` | Can access `domain.fields.em`, `domain.species`, etc. |

### TOML Configuration

```toml
[output.fields]
  custom = ["my_field_1", "my_field_2"]
```

### Code Example

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

**Important**: Ensure the return value is written as `double` type (explicit cast).

---

## CustomStat (Custom Scalar Statistics)

### Signature

```cpp
auto CustomStat(
    const std::string& name,   // Statistics name (from TOML custom list)
    Domain<S, M>&       domain // Domain
) -> real_t;
```

### Parameter Description

| Parameter | Meaning |
|-----------|---------|
| `name` | Name defined in TOML `[output.stats] custom = ["my_stat"]` |
| `domain` | Domain (same as CustomFieldOutput) |
| Return value | Scalar value. The engine automatically **sums** across meshblocks |

### TOML Configuration

```toml
[output.stats]
  enable     = true
  interval   = 100
  quantities = ["B^2", "E^2", "ExB"]  # Standard quantities
  custom     = ["total_axion_energy"]
```

### Code Example

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

## Alternative: CustomPostStep Precomputation

For complex diagnostics, precompute into a buffer in CustomPostStep, then only deep-copy in CustomFieldOutput:

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

This way heavy computation is only done once in CustomPostStep, not repeated at each output timestep.

---

## Required Includes

```cpp
#include "framework/domain/domain.h"
```

No additional archetype needed. `Kokkos::parallel_for` and `Kokkos::parallel_reduce` can be used directly.

---

## Constraints and Incompatibilities

| Constraint | Description |
|------------|-------------|
| CustomStat return value is auto-summed | Automatically reduces by sum across meshblocks. To get an average → divide by meshblock count outside TOML |
| Output data is double | buffer is `double*`, but `real_t` read from `em(i,j,em::ex1)` may be float. Must explicitly cast |
| TOML custom names must match | `custom = ["my_field"]` and `name == "my_field"` in code must be character-for-character identical |
| CustomStat output frequency | Controlled by `[output.stats] interval`, not `CustomPostStep` frequency |

---

## Common Pitfalls

1. **Not registered in TOML** — implemented `CustomFieldOutput` in code but not listed in TOML's `custom = [...]` → method is not called
2. **double vs real_t** — `real_t` may be `float` (single precision). Cast to `double` before writing to `buffer`
3. **Misunderstanding CustomStat reduce semantics** — the engine **sums**, not averages. To output an average, divide by meshblock count yourself
4. **Reading em outside kernel** — `domain.fields.em(i,j,comp)` can only be used inside Kokkos kernels (parallel_for/parallel_reduce). Host-side operations need a different path
5. **Heavy computation repeated at each output step** — if computation is expensive but output frequency is low, use the CustomPostStep precompute + buffer approach
