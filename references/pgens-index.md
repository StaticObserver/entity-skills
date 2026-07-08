# 官方 PGen 参考索引

> 基于 Entity v1.4.4 源码 (`pgens/` 目录)，共 7 个 PGen。
> 源码地址：https://github.com/entity-toolkit/entity/tree/v1.4.4/pgens

编写 PGen 时可参考这些官方实现，每个 PGen 展示了不同的功能组合和代码模式。

---

## 一览

| PGen | Engine | Metric | Dim | 核心功能 |
|------|--------|--------|-----|---------|
| [streaming](#streaming) | SRPIC | Minkowski | 1D/2D/3D | 均匀中性等离子体 + 漂移速度 + 倾斜 B 场 |
| [shock](#shock) | SRPIC | Minkowski | 1D/2D/3D | 部分填充等离子体 + 移动注入器 replenish |
| [reconnection](#reconnection) | SRPIC | Minkowski | 2D/3D | Harris 电流片 + guide field + open BC + replenish |
| [turbulence](#turbulence) | SRPIC | Minkowski | 2D/3D | 天线驱动湍流 + Fourier 模式 + 随机驱动 |
| [magnetosphere](#magnetosphere) | SRPIC | Spherical/QSpherical | 2D | 旋转磁化星体 + 偶极/单极场 + 球坐标 |
| [wald](#wald) | GRPIC | Kerr-Schild family | 2D | 黑洞磁层 Wald 解 + 竖直 B 场 |
| [accretion](#accretion) | GRPIC | Kerr-Schild family | 2D | 黑洞磁层 + pair cascade 注入 + GJ 密度 |

---

## streaming

**最简单的入门 PGen**。均匀等离子体 + 恒定倾斜磁场，适合作为新 PGen 的起点。

**功能清单**：
- `InitFields` — 均匀倾斜 B 场（Bmag, Btheta, Bphi），E = 0
- `InitPrtls` — 成对注入 Maxwellian 分布粒子（nspec 必须为偶数），支持每物种独立温度和漂移速度

**可参考的模式**：traits 声明、参数读取、InjectUniformMaxwellians 用法、多物种循环

---

## shock

**部分填充 + 移动注入器**的典型实现。等离子体初始只占据域的一部分，注入窗口随时间推进不断补充新鲜等离子体。

**功能清单**：
- `InitFields` — 均匀倾斜 B 场，E = -v x B
- `InitPrtls` — 部分填充 Maxwellian 分布（filling_fraction 控制填充比例），两个物种不同温度
- `CustomPostStep` — 移动注入器：清除窗口内旧粒子 → 重置 EM 场 → 注入新 Maxwellian 分布

**可参考的模式**：部分域填充、CustomPostStep 粒子 replenish、场重置

---

## reconnection

**磁重联**的完整实现。Harris 型电流片 + guide field + 开放边界 + 边界 replenish。

**功能清单**：
- `InitFields` — Harris 电流片 B 场（tanh 剖面）+ guide field
- `InitPrtls` — 均匀背景 Maxwellian + 电流片非均匀密度层，CurrentLayer 空间分布，电流片内漂移速度
- `CustomPostStep` — 开放边界激活后，在顶部/底部边界 replenish 背景密度粒子
- `MatchFields` — x1 方向 MATCH 边界场值

**可参考的模式**：非均匀场（tanh）、非均匀粒子分布（CurrentLayer）、Open BC + replenish、MatchFields、漂移速度计算

---

## turbulence

**天线驱动湍流**。通过 Fourier 模式叠加 + 随机驱动模拟湍动谱。

**功能清单**：
- `InitFields` — 多 Fourier 模式叠加的横向磁场扰动 + 引导场 bx3 = 1.0
- `ExternalCurrent` — 由矢量势旋度计算驱动电流（jx1/jx2/jx3）
- `InitPrtls` — 单温度 Maxwellian 注入
- `CustomPostStep` — 随机驱动（Langevin 型噪声 + 阻尼），粒子 escape/reset 循环

**可参考的模式**：ext_current（天线驱动）、Fourier 模式叠加、CustomPostStep 随机驱动、escape 粒子处理

---

## magnetosphere

**球坐标 + 旋转星体磁层**。SRPIC 下使用 Spherical/QSpherical 坐标的唯一官方 PGen。

**功能清单**：
- `InitFields` — 偶极场（r⁻³ 衰减，cosθ 角分布）或单极场（r⁻² 衰减）
- `DriveFields`（继承 InitFields）— 叠加刚性旋转感应电场（E = -v×B，v = Ω×r）
- `MatchFields` — 内边界匹配场值（传递时间参数给 DriveFields）

**可参考的模式**：Spherical 坐标、继承式 Field Setter（InitFields → DriveFields）、MatchFields 传递时变参数、球坐标下的场分量

---

## wald

**GRPIC 黑洞磁层初始化**。仅设初始场，无粒子。

**功能清单**：
- `InitFields` — Wald 真空解（磁势 A₃ → 有限差分计算 B 和 D）或竖直均匀 B 场
- 支持 `Kerr_Schild` / `QKerr_Schild` / `Kerr_Schild_0` 三种度规

**可参考的模式**：GRPIC traits、势方法（A₃/A₀/A₁）、GR metric API（spin、h_ij、alpha）

---

## accretion

**GRPIC 黑洞磁层 + pair cascade**。7 个 PGen 中最复杂的。

**功能清单**：
- `InitFields` — Wald 解 + 竖直 B 场（与 wald 类似）
- `InitPrtls` — 在磁化参数超过阈值且密度低于阈值的区域注入 e⁻/e⁺ 对（Goldreich-Julian 密度标度）
- `CustomPostStep` — 周期性 pair injection 循环

**可参考的模式**：GRPIC + 粒子注入、条件注入（sigma > threshold, density < threshold）、GJ 密度计算、Kerr-Schild 坐标下的粒子初始化

---

## 功能矩阵

从上到下排列，可快速找到包含特定功能的 PGen：

| 功能 | streaming | shock | reconnection | turbulence | magnetosphere | wald | accretion |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| InitFields (均匀 B) | ✓ | ✓ | | | | | |
| InitFields (非均匀 B) | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| InitFields (球坐标) | | | | | ✓ | | |
| InitFields (势方法 A) | | | | | | ✓ | |
| InitPrtls (Uniform Maxwellian) | ✓ | ✓ | ✓ | ✓ | | | |
| InitPrtls (NonUniform) | | | ✓ | | | | |
| InitPrtls (GR 粒子) | | | | | | | ✓ |
| ext_current | | | | ✓ | | | |
| MatchFields | | | ✓ | | ✓ | | |
| CustomPostStep | | ✓ | ✓ | ✓ | | | ✓ |
| Spherical 坐标 | | | | | ✓ | | |
| GRPIC / Kerr-Schild | | | | | | ✓ | ✓ |
