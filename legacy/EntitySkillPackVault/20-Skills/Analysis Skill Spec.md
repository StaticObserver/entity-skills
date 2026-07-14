# Analysis Skill 规范

## 使命

把 Entity 输出转换成有证据支撑的诊断和可复用分析 artifact。

## 核心工具

可用时使用 nt2py：

- `nt2.Data(...)`；
- `data.fields`；
- `data.particles`；
- `data.spectra`；
- `data.diagnostics`；
- 当 lazy xarray 访问不合适时使用 raw readers。

## 必要输入

收集：

- output path；
- simulation name；
- 已知时记录 Entity commit；
- 可用时记录 TOML 和 pgen 路径；
- 分析问题；
- 目标 quantities；
- species；
- time range 或 output steps。

## 工作流

1. 定位 output directory 和 metadata 文件。
2. 如果存在 `.err`，先检查 `.err`。
3. 检查 `.info`、`.log`、stats CSV。
4. lazy load 数据。
5. 在加载到内存前，先按 time、space、species 缩小范围。
6. 生成诊断和图。
7. 说明证据强度和 caveats。
8. 有价值时保存 analysis script 或 notebook。
9. 写 analysis report。

## 证据强度

| 标签 | 含义 |
| --- | --- |
| visual | 图像提示某种模式，但尚无定量检查。 |
| numerical | 计算诊断支持该说法。 |
| regression | 与旧 run、benchmark 或解析预期比较过。 |
| unresolved | 数据不足或诊断之间存在矛盾。 |

## 常见诊断

- 各 species 粒子数；
- 场能和粒子能；
- `E.B` 和 `B^2`；
- charge density 与 divergence consistency；
- spectra 和 phase-space plots；
- output quantity 是否存在及其单位；
- checkpoint restart 后的连续性。

