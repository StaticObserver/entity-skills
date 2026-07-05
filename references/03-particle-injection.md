# 03 — 粒子注入（InitPrtls + Replenish）

## 何时使用

当模拟需要包含粒子时。触发关键词：等离子体、粒子初始化、电子/离子注入、Maxwellian 分布、空间分布、补充注入、粒子 replenish、pair plasma。

**如果只是真空模拟（无粒子），跳过此 reference。**

---

## 注入阶段

粒子注入有两个阶段，代码入口不同：

| 阶段 | 入口方法 | 使用单位 | 时机 |
|------|---------|---------|------|
| 初始注入 | `InitPrtls(Domain<S,M>&)` | **物理单位** | 模拟开始时调用一次 |
| 补充注入 | `CustomPostStep(...)` | **代码单位** | 每个时间步调用 |

---

## 初始化注入（InitPrtls 中）

### 签名

```cpp
void InitPrtls(Domain<S, M>& domain);
```

### InjectUniformMaxwellians（最常用）

配对物种（如 e-/e+）均匀注入 + 麦克斯韦分布：

```cpp
void InitPrtls(Domain<S, M>& domain) {
    // 定义温度和漂移速度
    auto temperatures = std::make_pair(T_e, T_p);  // {species1, species2}
    auto drifts = std::make_pair(
        std::vector<real_t>{ ux1, uy1, uz1 },       // species1 四速
        std::vector<real_t>{ ux2, uy2, uz2 }        // species2 四速
    );

    arch::InjectUniformMaxwellians<S, M>(
        params,                         // SimulationParams
        domain,                         // Domain ref
        1.0,                            // 总密度（单位 n0）
        temperatures,                   // std::pair<real_t, real_t>
        { 1, 2 },                       // 物种索引（1-based）
        drifts,                         // 漂移速度
        false,                          // use_weights（PGen 注入必须 false，TOML 处理）
        box                             // optional: boundaries_t<real_t> 注入区域
    );
}
```

### InjectUniformMaxwellian（单温度）

```cpp
arch::InjectUniformMaxwellian<S, M>(
    params, domain,
    1.0,              // 密度
    0.01,             // 统一温度
    { 1, 2 },         // 物种
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
    { 1, 2 },                       // 物种
    { edist1, edist2 },            // 能量分布 pair
    1.0, false, box
);
```

### InjectNonUniform（自定义空间分布）

```cpp
auto sdist = MySpatialDistribution<D>(params);

arch::InjectNonUniform<S, M>(
    params, domain,
    { 1, 2 },                       // 物种
    { edist1, edist2 },            // 能量分布
    sdist,                          // 空间分布
    1.0,                            // 密度因子
    false, box
);
```

### InjectGlobally（预计算粒子数据）

从 TOML 中的数组数据注入单个粒子：

```cpp
void InitPrtls(Domain<S, M>& domain) {
    // TOML: [[setup.prtls]]
    //   x1 = [...]  x2 = [...]  ux1 = [...]  ux2 = [...]  ux3 = [...]
    // [[setup.prtl_species]]
    //   species = [0, 1, 0, ...]   // 每个粒子的物种索引

    auto prtls_data = params.template get<std::map<std::string,
        std::vector<real_t>>>("setup.prtls");

    arch::InjectGlobally<S, M>(
        metadomain, domain,
        0,                  // 物种索引
        prtls_data,
        false
    );
}
```

数据 map 的 key 支持：`"x1"`, `"x2"`, `"x3"`, `"ux1"`, `"ux2"`, `"ux3"`

---

## 补充注入（CustomPostStep 中）

### Replenish 模式（最常用）

先计算当前密度，不够才注入：

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    if (step % 100 != 0) return;  // 每 100 步注入一次

    // Step 1: 计算当前密度到 buffer
    ndfield_t<M::Dim, 3> density_buffer("density", domain.mesh.rangeActiveCells());
    arch::ComputeMomentWithSpecies<S, M, FldsID::N, 3>(
        params, domain, { 1, 2 }, density_buffer, {}, 0u, 0u);

    // Step 2: 构建 replenish 空间分布
    arch::spatial_dist::ReplenishUniform<M, 3> sdist(
        domain.mesh.metric, density_buffer, 0u, target_density);

    // Step 3: 注入不足的部分
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
- 对比当前密度和目标密度
- `(0.9 * target > current)` → 注入 `(target - current) / target_max`
- 否则返回 0（不需要注入）

### 非均匀目标 Replenish

```cpp
// 自定义目标密度 profile
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

## 能量分布 Archetypes

| Archetype | 构造 | 说明 |
|-----------|------|------|
| `Maxwellian<D, C>(pool, T, drift)` | (random_pool, 温度, 漂移四速) | 漂移麦克斯韦，最常用 |
| `Cold<D>` | () | v = 0 |
| `Powerlaw<D>(pool, gmin, gmax, index)` | (random_pool, gamma_min, gamma_max, 幂律指数) | 相对论幂律 |
| `JuttnerSinge(v, T, pool)` | 自由函数，非 archetype | 相对论 Juttner-Synge 分布 |

### 自定义能量分布接口

```cpp
template <Dimension D>
struct MyEnergyDist {
    random_number_pool_t& pool;

    // 必须：设置速度（local tetrad basis）
    Inline void operator()(const coord_t<D>& x, vec_t<Dim::_3D>& v) const {
        // 可以使用内置辅助函数
        JuttnerSinge(v, temperature, pool);
        // 或手动设置
        v[0] = drift_ux;
        v[1] = ZERO;
        v[2] = ZERO;
    }
};
```

---

## 空间分布接口

### InjectNonUniform 用的空间分布

```cpp
template <Dimension D>
struct MySpatialDist {
    // 返回 { 密度分数(0~1), 采样/排序权重 }
    Inline auto operator()(const coord_t<D>& x) const
        -> Kokkos::pair<real_t, real_t> {
        real_t density = math::exp(-SQR(x[0]) / SQR(sigma));
        return { density, density };  // { 注入概率, 采样权重 }
    }
};
```

### PointDistribution 模式（访问 EM 场）

某些 PGen（如 accretion）的空间分布需要读取当前 EM 场：

```cpp
template <class M>
struct PointDistribution {
    // 在构造时通过 Domain* 读取场和密度
    PointDistribution(const SimulationParams& p, const M& metric,
                      Domain<SimEngine::GRPIC, M>* domain_ptr) {
        // 预计算 sigma_crit，读取 fields.em, fields.buff
        auto& em = domain_ptr->fields.em;
        // ... 使用 em(i1, i2, em::bx1) 等读取场值
    }

    Inline auto operator()(const coord_t<M::Dim>& x) const
        -> Kokkos::pair<real_t, real_t> {
        real_t prob = sigma_crit(x) / sigma_max;
        return { prob, prob };
    }
};
```

**Key**: PointDistribution 的构造在 `InitPrtls` 中（Host 端），读取场在构造时完成（非 kernel 内），`operator()` 只做查找。

---

## 注入 Box 定义

```cpp
// 全区域注入
boundaries_t<real_t> box;
for (auto d = 0u; d < M::Dim; ++d) {
    box.push_back(Range::All);
}

// 部分区域注入（x1 方向 [xmin, xmax]）
boundaries_t<real_t> box;
box.emplace_back(xmin, xmax);
for (auto d = 1u; d < M::Dim; ++d) {
    box.push_back(Range::All);
}

// 使用 if constexpr 处理不同维度的 box
boundaries_t<real_t> box;
if constexpr (M::Dim == Dim::_2D) {
    box.emplace_back(xmin, xmax);
    box.emplace_back(ymin, ymax);
} else {
    box.emplace_back(xmin, xmax);
}
```

---

## 所需 Includes

```cpp
#include "archetypes/particle_injector.h"  // InjectUniform*, InjectNonUniform, InjectGlobally
#include "archetypes/energy_dist.h"        // Maxwellian, Cold, Powerlaw, JuttnerSinge
#include "archetypes/spatial_dist.h"       // ReplenishUniform, Replenish
#include "archetypes/utils.h"              // ComputeMomentWithSpecies
```

---

## 约束与不兼容

| 约束 | 说明 |
|------|------|
| 1-based species 索引 | `arch::InjectUniform` 等用 `{1, 2}` 不是 `{0, 1}`，对应 TOML 第 1、2 个 species |
| use_weights | PGen 中注入时传 `false`，TOML 单独设 `use_weights = true` |
| ppc0 和 density 的关系 | 总粒子数 ≈ ppc0 × density × N_cells。ppc0 不够 → NaN |
| Replenish 的 buffer 维度 | `ComputeMomentWithSpecies` 的模板参数 N 是 buffer 的最后一维大小 |
| Cold 分布 + 漂移 | 不能直接设漂移。需要自定义 EnergyDistribution 或直接用 Maxwellian 配合低温 |

---

## 常见陷阱

1. **0-based vs 1-based species 索引** — `arch::InjectUniform` 等用 1-based 索引（TOML species 顺序），不是 C++ 的 0-based
2. **ppc0 不够** — 粒子数太少 → 统计噪声 → NaN 传播。建议 ppc0 >= 16，高精度用 128+
3. **maxnpart 超限** — 增加 species 的 maxnpart 或降低 ppc0/密度
4. **Replenish 忘记 step % N 控制** — 每步都补充会大幅拖慢性能
5. **死粒子不清理** — `clear_interval` 控制清理频率。死粒子太多 → 浪费内存但不会破坏物理
6. **死粒子删除破坏 charge conservation** — 移除带电粒子后需要重置 E 场或通过注入补偿
7. **InjectGlobally 的 data key 错误** — key 必须是 `"x1"` `"ux1"` 等全小写带下标的格式
