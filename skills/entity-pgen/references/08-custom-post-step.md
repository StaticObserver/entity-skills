# 08 — 时间步钩子（CustomPostStep）

> 基于 Entity v1.4.4

## 何时使用

当你需要在每个（或每第 N 个）时间步执行自定义逻辑时使用。触发关键词：时间步钩子、周期性注入、粒子补充、移动注入器、动态边界切换、移动窗口、活塞、粒子清理、场驱动。

**如果你的模拟不需要任何时间步级别的自定义行为，请跳过本参考文档。**

---

## 基本签名

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain);
```

| 参数 | 含义 | 备注 |
|-----------|---------|------|
| `step` | 当前步索引（从 0 开始） | 用于 `step % N` 频率控制 |
| `time` | 当前模拟时间 | **代码单位** |
| `domain` | 可读写的 Domain | fields、species、particles、mesh |

### Domain 提供的访问内容

- `domain.fields.em` — EM 场数组（Kokkos View）
- `domain.species[s]` — 第 s 个物种的粒子数据
- `domain.species[s].particles` — 粒子容器（i1、dx1、tag、ux1、ux2、ux3 等）
- `domain.species[s].rangeActiveParticles()` — 活跃粒子的 Kokkos 迭代范围
- `domain.mesh` — 网格元数据
- `domain.mesh.metric` — 度规对象

### 单位系统

**CustomPostStep 使用代码单位。** 这与使用物理单位的 InitPrtls 不同。

- `domain.fields.em(i, j, em::ex1)` → 代码单位下的电场
- `species.particles.ux1(p)` → 代码单位下的四速度
- `time` → 代码单位下的时间

---

## 子模式 1：补充注入

**来源**：reconnection、shock、accretion、replenish 示例

在某一区域内维持目标密度，每 N 步补充不足的粒子：

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

详见 `03-particle-injection.md` 中的"补充注入"一节。

---

## 子模式 2：移动注入器

**来源**：shock pgen

注入器以固定速度扫过模拟区域，清除旧区域的粒子、重置场，并注入新粒子：

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

## 子模式 3：动态边界条件切换

**来源**：reconnection pgen

在指定时间之后开放边界：

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

**前提条件**：PGen 构造函数必须接受非 const 的 `Metadomain<S, M>&`（而不是 `const Metadomain<S, M>&`）。

---

## 子模式 4：移动窗口

**来源**：moving_window 示例

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

## 子模式 5：CustomParticleUpdate / 活塞

**注意**：这是一个**独立的 trait**（不属于 CustomPostStep），仅为方便起见记录在此。

### 签名

```cpp
auto CustomParticleUpdate(simtime_t time, spidx_t sp, const Domain<S, M>& domain) const -> UpdateFunctor;
```

返回一个在 pusher 循环中对每个粒子调用的函子：

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

### TOML 参数

```toml
[setup]
  piston_velocity = 0.5
```

---

## 场重置工具模式

在任何需要手动设置场的场景中：

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

**忘记 `CommunicateFields` 是最常见的场重置 bug。**

---

## 必需的 include

```cpp
#include "archetypes/field_setter.h"       // SetEMFields_kernel
#include "archetypes/particle_injector.h"  // Inject* functions
#include "archetypes/spatial_dist.h"       // ReplenishUniform, Replenish
#include "archetypes/utils.h"              // ComputeMomentWithSpecies
#include "archetypes/moving_window.h"      // MoveWindow
#include "archetypes/piston.h"             // Piston
```

---

## 约束与不兼容性

| 约束 | 描述 |
|------------|-------------|
| 移除死亡粒子会破坏电荷守恒 | 移除带电粒子后，必须重置 E 场或通过注入进行补偿 |
| GPU 上无法逐位复现 | Kokkos parallel_for/reduce 的排序可能在多次运行之间不同 |
| kernel 中使用 `raise::KernelError()` / host 中使用 `raise::Error()` | 不要在 `Kokkos::parallel_for` 的 Lambda 内调用 `raise::Error()` |
| MovingWindow + 动态边界条件 | 两者都需要非 const 的 Metadomain；它们可以共存 |

---

## 常见陷阱

1. **单位混淆** — `domain.fields.em` 是代码单位，`time` 也是代码单位。它们与 InitPrtls 的物理单位不同
2. **忘记 CommunicateFields** — 手动设置场之后没有调用 `CommunicateFields` → 幽灵单元数值失同步 → 边界处出现异常场
3. **忘记 step % N 守卫** — 每一步都运行昂贵的注入/计算 → 性能严重下降
4. **static 变量与多 domain** — 在 MPI 下运行时，static 变量只影响当前 rank 的 domain 列表中的一个 domain
5. **未检查粒子的死亡标记** — 在 `rangeActiveParticles()` 迭代中，粒子可能已被标记为死亡；务必检查 `tag(p) == ParticleTag::dead` 并跳过
6. **无频率控制的无界注入** — 每一步都注入粒子且不做清理 → 粒子数量爆炸 → 超出 maxnpart
