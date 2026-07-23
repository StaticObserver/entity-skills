# 官方 PGen 参考索引

> 基于 Entity v1.4.4 源码（`pgens/` 目录），共 7 个 PGen。
> 源码地址：https://github.com/entity-toolkit/entity/tree/v1.4.4/pgens

编写 PGen 时可参考这些官方实现。每个 PGen 演示了不同的功能组合与代码模式。

---

## 概览

| PGen | 引擎 | 度规 | 维度 | 核心特性 |
|------|--------|--------|-----|---------------|
| [streaming](#streaming) | SRPIC | Minkowski | 1D/2D/3D | 均匀中性等离子体 + 漂移速度 + 斜向磁场 |
| [shock](#shock) | SRPIC | Minkowski | 1D/2D/3D | 部分填充等离子体 + 移动注入器补充粒子 |
| [reconnection](#reconnection) | SRPIC | Minkowski | 2D/3D | Harris 电流片 + 引导场 + 开放边界 + 粒子补充 |
| [turbulence](#turbulence) | SRPIC | Minkowski | 2D/3D | 天线驱动湍流 + Fourier 模 + 随机驱动 |
| [magnetosphere](#magnetosphere) | SRPIC | Spherical/QSpherical | 2D | 旋转磁化恒星 + 偶极/单极磁场 + 球坐标 |
| [wald](#wald) | GRPIC | Kerr-Schild 族 | 2D | 黑洞磁层 Wald 解 + 均匀垂直磁场 |
| [accretion](#accretion) | GRPIC | Kerr-Schild 族 | 2D | 黑洞磁层 + 对级联注入 + GJ 密度 |

---

## streaming

**最简单的入门 PGen**。均匀等离子体 + 恒定斜向磁场。是编写新 PGen 的理想起点。

**特性清单**：
- `InitFields` — 均匀斜向磁场（Bmag、Btheta、Bphi），E = 0
- `InitPrtls` — 成对注入的 Maxwellian 分布粒子（nspec 必须为偶数），支持各物种独立的温度与漂移速度

**参考模式**：traits 声明、参数读取、InjectUniformMaxwellians 用法、多物种循环

---

## shock

**部分填充 + 移动注入器的经典实现**。等离子体初始只占据计算域的一部分，注入窗口随时间推进，持续补充新鲜等离子体。

**特性清单**：
- `InitFields` — 均匀斜向磁场，E = -v x B
- `InitPrtls` — 部分填充的 Maxwellian 分布（filling_fraction 控制填充比例），两种物种温度不同
- `CustomPostStep` — 移动注入器：清除窗口内的旧粒子 → 重置电磁场 → 注入新的 Maxwellian 分布

**参考模式**：计算域部分填充、CustomPostStep 粒子补充、场重置

---

## reconnection

**磁重联的完整实现**。Harris 型电流片 + 引导场 + 开放边界 + 边界粒子补充。

**特性清单**：
- `InitFields` — Harris 电流片磁场（tanh 剖面）+ 引导场
- `InitPrtls` — 均匀背景 Maxwellian + 电流片非均匀密度层，CurrentLayer 空间分布，电流片内的漂移速度
- `CustomPostStep` — 开放边界激活后，在上/下边界补充背景密度粒子
- `MatchFields` — x1 方向 MATCH 边界场值

**参考模式**：非均匀场（tanh）、非均匀粒子分布（CurrentLayer）、开放边界 + 粒子补充、MatchFields、漂移速度计算

---

## turbulence

**天线驱动湍流**。通过 Fourier 模叠加 + 随机驱动来模拟湍流谱。

**特性清单**：
- `InitFields` — 多个 Fourier 模叠加产生的横向磁场扰动 + 引导场 bx3 = 1.0
- `ExternalCurrent` — 由矢势的旋度计算驱动电流（jx1/jx2/jx3）
- `InitPrtls` — 单温度 Maxwellian 注入
- `CustomPostStep` — 随机驱动（Langevin 型噪声 + 阻尼），粒子逃逸/重置循环

**参考模式**：ext_current（天线驱动）、Fourier 模叠加、CustomPostStep 随机驱动、逃逸粒子处理

---

## magnetosphere

**球坐标 + 旋转恒星磁层**。官方唯一一个在 SRPIC 下使用 Spherical/QSpherical 坐标的 PGen。

**特性清单**：
- `InitFields` — 偶极场（r⁻³ 衰减，cosθ 角向分布）或单极场（r⁻² 衰减）
- `DriveFields`（继承自 InitFields）— 叠加刚性旋转感应电场（E = -v×B，v = Ω×r）
- `MatchFields` — 内边界匹配场值（向 DriveFields 传递时间参数）

**参考模式**：球坐标、继承式 Field Setter（InitFields → DriveFields）、MatchFields 传递随时间变化的参数、球坐标下的场分量

---

## wald

**GRPIC 黑洞磁层初始化**。只设置初始场；不包含粒子。

**特性清单**：
- `InitFields` — Wald 真空解（磁矢势 A₃ → 用有限差分计算 B 和 D）或均匀垂直磁场
- 支持三种度规：`Kerr_Schild` / `QKerr_Schild` / `Kerr_Schild_0`

**参考模式**：GRPIC traits、矢势方法（A₃/A₀/A₁）、GR 度规 API（spin、h_ij、alpha）

---

## accretion

**GRPIC 黑洞磁层 + 对级联**。7 个 PGen 中最复杂的一个。

**特性清单**：
- `InitFields` — Wald 解 + 均匀垂直磁场（与 wald 类似）
- `InitPrtls` — 在磁化强度超过阈值且密度低于阈值的区域注入 e⁻/e⁺ 对（Goldreich-Julian 密度标度）
- `CustomPostStep` — 周期性对注入循环

**参考模式**：GRPIC + 粒子注入、条件注入（sigma > 阈值，密度 < 阈值）、GJ 密度计算、Kerr-Schild 坐标下的粒子初始化

---

## 特性矩阵

自上而下排列，便于快速查找包含特定特性的 PGen：

| 特性 | streaming | shock | reconnection | turbulence | magnetosphere | wald | accretion |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| InitFields（均匀磁场 B） | ✓ | ✓ | | | | | |
| InitFields（非均匀磁场 B） | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| InitFields（球坐标） | | | | | ✓ | | |
| InitFields（矢势方法 A） | | | | | | ✓ | |
| InitPrtls（均匀 Maxwellian） | ✓ | ✓ | ✓ | ✓ | | | |
| InitPrtls（非均匀分布） | | | ✓ | | | | |
| InitPrtls（GR 粒子） | | | | | | | ✓ |
| ext_current | | | | ✓ | | | |
| MatchFields | | | ✓ | | ✓ | | |
| CustomPostStep | | ✓ | ✓ | ✓ | | | ✓ |
| 球坐标 | | | | | ✓ | | |
| GRPIC / Kerr-Schild | | | | | | ✓ | ✓ |
