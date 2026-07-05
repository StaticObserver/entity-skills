# 08 — 时间步钩子（CustomPostStep）

## 何时使用

需要在每个（或每 N 个）时间步执行自定义逻辑时。触发关键词：时间步钩子、周期性注入、补充粒子、移动注入器、动态边界切换、移动窗口、piston、粒子清理、场驱动。

**如果模拟不需要任何时间步级别的自定义行为，跳过此 reference。**

---

## 基础签名

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain);
```

| 参数 | 含义 | 注意 |
|------|------|------|
| `step` | 当前步序号（从 0 开始） | 用于 `step % N` 频率控制 |
| `time` | 当前模拟时间 | **代码单位** |
| `domain` | 可读写的 Domain | fields, species, particles, mesh |

### Domain 可访问的内容

- `domain.fields.em` — 电磁场数组（Kokkos View）
- `domain.species[s]` — 第 s 个物种的粒子数据
- `domain.species[s].particles` — 粒子容器（i1, dx1, tag, ux1, ux2, ux3, ...）
- `domain.species[s].rangeActiveParticles()` — 活粒子的 Kokkos 遍历范围
- `domain.mesh` — 网格元数据
- `domain.mesh.metric` — metric 对象

### 单位系统

**CustomPostStep 中使用代码单位。**这与 InitPrtls 的物理单位不同。

- `domain.fields.em(i, j, em::ex1)` → 代码单位电场
- `species.particles.ux1(p)` → 代码单位四速
- `time` → 代码单位时间

---

## 子模式 1：Replenish 补充注入

**来源**：reconnection, shock, accretion, replenish examples

保持某个区域的目标密度，每 N 步补充不足的粒子：

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    const int replenish_interval = 100;
    if (step % replenish_interval != 0) return;

    // 1. 计算当前密度
    ndfield_t<M::Dim, 3> buff("density", domain.mesh.rangeActiveCells());
    arch::ComputeMomentWithSpecies<S, M, FldsID::N, 3>(
        params, domain, { 1, 2 }, buff, {}, 0u, 0u);

    // 2. Replenish
    arch::spatial_dist::ReplenishUniform<M, 3> sdist(
        domain.mesh.metric, buff, 0u, target_density);

    // 3. 注入
    arch::InjectNonUniform<S, M, ED1, ED2, decltype(sdist)>(
        params, domain,
        { 1, 2 },              // 物种
        { edist1, edist2 },    // 能量分布
        sdist,                  // 补充分布
        target_density,
        false                   // use_weights
    );
}
```

详细说明见 `03-particle-injection.md` 的"补充注入"部分。

---

## 子模式 2：Moving Injector 移动注入器

**来源**：shock pgen

注入器以固定速度扫过模拟区域，清除旧区域粒子、重置场、注入新粒子：

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    if (step % injection_frequency != 0) return;

    // 1. 计算注入区域
    real_t x_init = global_xmin + filling_fraction * (global_xmax - global_xmin);
    real_t xmax = x_init + injector_velocity * (std::max(time - injection_start, ZERO) + dt);
    real_t xmin = xmax - injection_frequency * dt;

    // 2. 构建清除区域 box
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

    // 3. 重置清除区域的场
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

    // 4. 标记清除区域的粒子为 dead
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

    // 5. 在新区域注入
    boundaries_t<real_t> inj_box;
    inj_box.emplace_back(xmin, xmax);
    for (auto d = 1u; d < M::Dim; ++d) inj_box.push_back(Range::All);

    arch::InjectUniformMaxwellians<S, M>(
        params, domain, 1.0, temperatures, { 1, 2 }, drifts, false, inj_box
    );
}
```

---

## 子模式 3：Dynamic BC 动态边界切换

**来源**：reconnection pgen

在指定时间后打开边界：

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

**前置条件**：PGen 的 constructor 必须用 non-const `Metadomain<S, M>&`（不是 `const Metadomain<S, M>&`）

---

## 子模式 4：Moving Window 移动窗口

**来源**：moving_window example

```cpp
// 在 PGen 中定义一个 MovingWindow 内部 struct
struct MovingWindow {
    real_t pos_i;     // 整数格点位置
    real_t pos_di;    // 分数部分
    real_t v;         // 窗口速度

    void init(const M& metric, real_t global_x) {
        // 物理坐标 → 计算坐标
        pos_i = metric.template convert<1, Crd::Ph, Crd::Cd>(global_x);
        pos_di = ZERO;
    }

    void update(real_t dt, ncells_t N_GHOSTS,
                Metadomain<S, M>& metadomain, Domain<S, M>& domain) {
        // 累加位移
        pos_di += v * dt / domain.mesh.template dx<1>();
        real_t shift = math::floor(pos_di);
        pos_i += shift;
        pos_di -= shift;

        // 触发窗口移动
        while (pos_i >= static_cast<real_t>(N_GHOSTS)) {
            arch::MoveWindow<M, in::x1>(domain, metadomain, N_GHOSTS);
            pos_i -= N_GHOSTS;
        }
    }
};

MovingWindow moving_window;

// InitPrtls 中初始化
void InitPrtls(Domain<S, M>& domain) {
    moving_window.init(domain.mesh.metric, global_xmin);
    // ... 粒子注入 ...
}

// CustomPostStep 中每步调用
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
    moving_window.update(dt, N_GHOSTS, metadomain, domain);
}
```

---

## 子模式 5：CustomParticleUpdate / Piston

**注意**：这是一个**独立的 trait**（不是 CustomPostStep 的一部分），在这里一并说明。

### 签名

```cpp
auto CustomParticleUpdate(simtime_t time, spidx_t sp, const Domain<S, M>& domain) const -> UpdateFunctor;
```

返回一个 functor，在 pusher 循环内对每个粒子调用：

```cpp
struct PistonUpdate {
    real_t x_piston, v_piston, global_xmax;

    Inline void operator()(
        spidx_t           p,       // 粒子索引
        const kernel::sr::PusherContext& ctx,      // ctx.dt 可用
        const kernel::sr::PusherBoundaries<D>&,    // 暂时忽略（活塞用自定义逻辑）
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
// 1. 内核调用
Kokkos::parallel_for(
    "SetFields",
    CreateRangePolicy<M::Dim>(x_min, x_max),
    arch::SetEMFields_kernel<S, M, FieldSetterType>{
        domain.fields.em, field_setter, domain.mesh.metric
    }
);

// 2. 必须后跟通信（同步 ghost cells）
metadomain.CommunicateFields(domain, Comm::E | Comm::B);
```

**忘记 `CommunicateFields` 是最常见的场重置 bug**。

---

## 所需 Includes

```cpp
#include "archetypes/field_setter.h"       // SetEMFields_kernel
#include "archetypes/particle_injector.h"  // Inject* 函数
#include "archetypes/spatial_dist.h"       // ReplenishUniform, Replenish
#include "archetypes/utils.h"              // ComputeMomentWithSpecies
#include "archetypes/moving_window.h"      // MoveWindow
#include "archetypes/piston.h"             // Piston
```

---

## 约束与不兼容

| 约束 | 说明 |
|------|------|
| 死粒子删除破坏 charge conservation | 移除带电粒子后必须重置 E 场或通过注入补偿 |
| GPU 非 bitwise 可重复 | Kokkos parallel_for/reduce 在不同运行中顺序可能不同 |
| `raise::KernelError()` in kernel / `raise::Error()` in host | 不要在 `Kokkos::parallel_for` 的 Lambda 中调用 `raise::Error()` |
| MovingWindow + Dynamic BC | 两者都需要 non-const Metadomain，可以共存 |

---

## 常见陷阱

1. **单位混淆** — `domain.fields.em` 是代码单位，`time` 是代码单位。和 InitPrtls 的物理单位不一样
2. **CommunicateFields 遗忘** — 手动设置场后不调用 `CommunicateFields` → ghost cells 值不同步 → 边界处场异常
3. **step % N 守卫遗忘** — 每步执行昂贵的注入/计算 → 性能大幅下降
4. **static 变量配合 multi-domain** — MPI 运行时 static 变量只影响当前 rank 的 domain 列表中的一个
5. **particle tag 没检查 dead** — 在 `rangeActiveParticles()` 遍历中粒子可能已被标记 dead，需要先检查 `tag(p) == ParticleTag::dead` 并跳过
6. **没有频控的无限注入** — 每步注入粒子但不清除 → 粒子数爆炸 → maxnpart 超限
