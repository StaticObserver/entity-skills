# 07 — 自定义输出（CustomFieldOutput + CustomStat）

> 基于 Entity v1.4.4

## 何时使用

需要在标准场量（E, B, J, Rho, T00 等）之外输出自定义诊断量时。触发关键词：自定义场、derived field、标量诊断量、CustomFieldOutput、CustomStat、额外输出量。

**如果标准输出量（[output.fields] quantities）已经够用，跳过此 reference。**

---

## CustomFieldOutput（自定义场量）

### 签名

```cpp
void CustomFieldOutput(
    const std::string& name,      // 场量名称（来自 TOML custom 列表）
    double*             buffer,   // 输出缓冲区
    int                 index,    // 当前网格点的 buffer 索引
    std::size_t         step,     // 当前时间步
    long double         time,     // 当前模拟时间
    Domain<S, M>&       domain    // Domain（可读 fields.em, species）
);
```

### 参数说明

| 参数 | 含义 |
|------|------|
| `name` | TOML `[output.fields] custom = ["my_field"]` 中定义的名字 |
| `buffer` | 输出数据缓冲区（1D，按网格点展平） |
| `index` | buffer[index] = 当前网格点的值 |
| `step` | 当前时间步序号 |
| `time` | 当前时间（代码单位） |
| `domain` | 可访问 `domain.fields.em`, `domain.species` 等 |

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
        // 自定义物理量
        auto& em = domain.fields.em;
        buffer[index] = static_cast<double>(
            epsilon * k * em(em::bx1) * math::sin(k * x - omega * time)
        );
    }
}
```

**重要**：返回值写入前确保是 `double` 类型（显式 cast）。

---

## CustomStat（自定义标量统计量）

### 签名

```cpp
auto CustomStat(
    const std::string& name,   // 统计量名称（来自 TOML custom 列表）
    Domain<S, M>&       domain // Domain
) -> real_t;
```

### 参数说明

| 参数 | 含义 |
|------|------|
| `name` | TOML `[output.stats] custom = ["my_stat"]` 中定义的名字 |
| `domain` | Domain（与 CustomFieldOutput 相同） |
| 返回值 | 标量值。引擎自动跨 meshblock **求和** |

### TOML 配置

```toml
[output.stats]
  enable     = true
  interval   = 100
  quantities = ["B^2", "E^2", "ExB"]  # 标准量
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

对于复杂的诊断量，在 CustomPostStep 中预计算到 buffer，然后在 CustomFieldOutput 中只做 deep-copy：

```cpp
// 在 PGen 中维护一个 ndfield_t buffer 成员
ndfield_t<M::Dim, 3> my_buffer;

void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    // 每步预先计算
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

这样复杂计算只在 CustomPostStep 做一次，不在每个输出时间步重复。

---

## 所需 Includes

```cpp
#include "framework/domain/domain.h"
```

不需要额外 archetype。`Kokkos::parallel_for` 和 `Kokkos::parallel_reduce` 可以直接使用。

---

## 约束与不兼容

| 约束 | 说明 |
|------|------|
| CustomStat 返回值自动求和 | 跨 meshblock 自动 reduce by sum。如果要做平均值 → 在 TOML 外面除 meshblock 数量 |
| 输出数据是 double | buffer 是 `double*`，而从 `em(i,j,em::ex1)` 读出的 `real_t` 可能是 float。必须显式 cast |
| TOML custom 名字必须匹配 | `custom = ["my_field"]` 和代码中的 `name == "my_field"` 必须字符级一致 |
| CustomStat 的输出频率 | 由 `[output.stats] interval` 控制，不是 `CustomPostStep` 的频率 |

---

## 常见陷阱

1. **未注册到 TOML** — 代码中实现了 `CustomFieldOutput` 但没有在 TOML 的 `custom = [...]` 中列出 → 方法不被调用
2. **double vs real_t** — `real_t` 可能是 `float`（单精度）。在写入 `buffer` 前 cast 到 `double`
3. **CustomStat reduce 语义误解** — 引擎**求和**不是平均。如果想输出平均值，自己除 meshblock 数量
4. **在 kernel 外读 em** — `domain.fields.em(i,j,comp)` 只能在 Kokkos kernel（parallel_for/parallel_reduce）中使用。Host 端操作需要不同的路径
5. **复杂计算在每个输出步重复** — 如果计算量大但输出频率低，用 CustomPostStep 预计算 + buffer 方案
