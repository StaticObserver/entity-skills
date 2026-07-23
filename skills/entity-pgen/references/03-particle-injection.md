# 03 — 粒子注入（InitPrtls + Replenish）

> 基于 Entity v1.4.4

## 何时使用

当模拟需要包含粒子时使用。触发关键词：等离子体、粒子初始化、电子/离子注入、Maxwellian 分布、空间分布、补充注入、粒子补充、对等离子体。

**如果这是真空模拟（无粒子），请跳过本参考文档。**

---

## 注入阶段

粒子注入分为两个阶段，代码入口点不同：

| 阶段 | 入口方法 | 使用的单位 | 时机 |
|------|---------|---------|------|
| 初始注入 | `InitPrtls(Domain<S,M>&)` | **物理单位** | 在模拟开始时调用一次 |
| 补充注入 | `CustomPostStep(...)` | **代码单位** | 每个时间步调用 |

---

## 初始注入（在 InitPrtls 中）

### 函数签名

```cpp
void InitPrtls(Domain<S, M>& domain);
```

### InjectUniformMaxwellians（最常用）

成对粒子种类（例如 e-/e+）均匀注入 + Maxwellian 分布：

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

### InjectUniformMaxwellian（单一温度）

```cpp
arch::InjectUniformMaxwellian<S, M>(
    params, domain,
    1.0,              // Density
    0.01,             // Uniform temperature
    { 1, 2 },         // Species
    drifts, use_weights, box
);
```

### InjectUniform（自定义能量分布）

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

### InjectNonUniform（自定义空间分布）

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

### InjectGlobally（预先计算的粒子数据）

从 TOML 中的数组数据注入单个粒子：

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

支持的数据映射键：`"x1"`、`"x2"`、`"x3"`、`"ux1"`、`"ux2"`、`"ux3"`

---

## 补充注入（在 CustomPostStep 中）

### Replenish 模式（最常用）

首先计算当前密度，仅在密度不足处注入：

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

**ReplenishUniform 原理**：
- 将当前密度与目标密度进行比较
- `(0.9 * target > current)` → 注入 `(target - current) / target_max`
- 否则返回 0（无需注入）

### 非均匀目标补充

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

## 能量分布 Archetype

| Archetype | 构造方式 | 描述 |
|-----------|------|------|
| `Maxwellian<D, C>(pool, T, drift)` | (random_pool, 温度, 漂移四速度) | 带漂移的 Maxwellian，最常用 |
| `Cold<D>` | () | v = 0 |
| `Powerlaw<D>(pool, gmin, gmax, index)` | (random_pool, gamma_min, gamma_max, 幂律指数) | 相对论性幂律 |
| `JuttnerSynge(v, T, pool)` | 自由函数，不是 archetype | 相对论性 Juttner-Synge 分布 |

### 自定义能量分布接口

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

## 空间分布接口

### 用于 InjectNonUniform 的空间分布

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

### PointDistribution 模式（访问电磁场）

某些 PGen（例如吸积）需要在空间分布中读取当前电磁场：

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

**关键**：PointDistribution 在 `InitPrtls` 中构造（在 Host 端），字段读取发生在构造时（而非 kernel 内部），`operator()` 仅执行查找。

---

## 注入区域（box）定义

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

## 所需的头文件

```cpp
#include "archetypes/particle_injector.h"  // InjectUniform*, InjectNonUniform, InjectGlobally
#include "archetypes/energy_dist.h"        // Maxwellian, Cold, Powerlaw, JuttnerSynge
#include "archetypes/spatial_dist.h"       // ReplenishUniform, Replenish
#include "archetypes/utils.h"              // ComputeMomentWithSpecies
```

---

## 约束与不兼容性

| 约束 | 描述 |
|------|------|
| 1-based 粒子种类索引 | `arch::InjectUniform` 等使用 `{1, 2}` 而非 `{0, 1}`，对应 TOML 中第 1 和第 2 个粒子种类 |
| use_weights | 在 PGen 中注入时传 `false`；在 TOML 中单独设置 `use_weights = true` |
| ppc0 与密度的关系 | 总粒子数 ≈ ppc0 × 密度 × N_cells。ppc0 不足 → NaN |
| Replenish 缓冲区维度 | `ComputeMomentWithSpecies` 的模板参数 N 是缓冲区最后一维的大小 |
| Cold 分布 + 漂移 | 无法直接设置漂移。需要自定义 EnergyDistribution，或使用低温的 Maxwellian |

---

## 常见陷阱

1. **0-based 与 1-based 粒子种类索引** — `arch::InjectUniform` 等使用 1-based 索引（TOML 粒子种类顺序），而非 C++ 的 0-based
2. **ppc0 不足** — 粒子太少 → 统计噪声 → NaN 传播。建议 ppc0 >= 16，高精度场景使用 128+
3. **超出 maxnpart** — 增大多粒子种类的 maxnpart，或降低 ppc0/密度
4. **在 Replenish 中忘记 step % N 控制** — 每个时间步都补充会显著降低性能
5. **死亡粒子未清理** — `clear_interval` 控制清理频率。死亡粒子过多 → 浪费内存，但不会破坏物理
6. **移除死亡粒子破坏电荷守恒** — 移除带电粒子后，需要重置 E 场或通过注入进行补偿
7. **InjectGlobally 中的数据键错误** — 键必须是 `"x1"`、`"ux1"` 等全小写带下标格式
