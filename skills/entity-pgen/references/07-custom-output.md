# 07 — 自定义输出（CustomFieldOutput + CustomStat）

> 基于 Entity v1.4.4

## 何时使用

当需要输出标准场量（E、B、J、Rho、T00 等）之外的自定义诊断量时使用。触发关键词：custom field、derived field、scalar diagnostics、CustomFieldOutput、CustomStat、extra output quantities。

**如果标准输出量（`[output.fields] quantities`）已能满足需求，请跳过本篇参考文档。**

---

## CustomFieldOutput（自定义场量）

### 函数签名

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

### 参数说明

| 参数 | 含义 |
|-----------|---------|
| `name` | TOML 中 `[output.fields] custom = ["my_field"]` 定义的名称 |
| `buffer` | 输出数据缓冲区（一维，按格点展平） |
| `index` | buffer[index] = 当前格点处的值 |
| `step` | 当前时间步索引 |
| `time` | 当前时间（代码单位） |
| `domain` | 可访问 `domain.fields.em`、`domain.species` 等 |

### TOML 配置

```toml
[output.fields]
  custom = ["my_field_1", "my_field_2"]
```

### 代码示例

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

**重要**：确保返回值以 `double` 类型写入（显式转换）。

---

## CustomStat（自定义标量统计量）

### 函数签名

```cpp
auto CustomStat(
    const std::string& name,   // Statistics name (from TOML custom list)
    Domain<S, M>&       domain // Domain
) -> real_t;
```

### 参数说明

| 参数 | 含义 |
|-----------|---------|
| `name` | TOML 中 `[output.stats] custom = ["my_stat"]` 定义的名称 |
| `domain` | Domain（与 CustomFieldOutput 相同） |
| 返回值 | 标量值。引擎会自动在 meshblock 之间**求和** |

### TOML 配置

```toml
[output.stats]
  enable     = true
  interval   = 100
  quantities = ["B^2", "E^2", "ExB"]  # Standard quantities
  custom     = ["total_axion_energy"]
```

### 代码示例

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

## 替代方案：CustomPostStep 预计算

对于复杂的诊断量，在 CustomPostStep 中预计算到缓冲区，然后在 CustomFieldOutput 中只做深拷贝：

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

这样繁重的计算只在 CustomPostStep 中执行一次，而不会在每个输出时间步重复计算。

---

## 必需的 include

```cpp
#include "framework/domain/domain.h"
```

不需要额外的 archetype。`Kokkos::parallel_for` 和 `Kokkos::parallel_reduce` 可以直接使用。

---

## 约束与不兼容性

| 约束 | 说明 |
|------------|-------------|
| CustomStat 返回值会被自动求和 | 自动在 meshblock 之间按求和归约。要得到平均值 → 在 TOML 之外除以 meshblock 数量 |
| 输出数据为 double | buffer 是 `double*`，但从 `em(i,j,em::ex1)` 读取的 `real_t` 可能是 float。必须显式转换 |
| TOML 自定义名称必须匹配 | `custom = ["my_field"]` 与代码中的 `name == "my_field"` 必须逐字符完全一致 |
| CustomStat 输出频率 | 由 `[output.stats] interval` 控制，而不是 `CustomPostStep` 的频率 |

---

## 常见陷阱

1. **未在 TOML 中注册** — 在代码中实现了 `CustomFieldOutput`，但未在 TOML 的 `custom = [...]` 中列出 → 方法不会被调用
2. **double 与 real_t** — `real_t` 可能是 `float`（单精度）。写入 `buffer` 之前必须先转换为 `double`
3. **误解 CustomStat 的归约语义** — 引擎执行的是**求和**，而不是平均。要输出平均值，需自行除以 meshblock 数量
4. **在 kernel 之外读取 em** — `domain.fields.em(i,j,comp)` 只能在 Kokkos kernel（parallel_for/parallel_reduce）内部使用。host 端操作需要走另一条路径
5. **每个输出步都重复繁重的计算** — 如果计算开销大但输出频率低，请使用 CustomPostStep 预计算 + 缓冲区的方案
