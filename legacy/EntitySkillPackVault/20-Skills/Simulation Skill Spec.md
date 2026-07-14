# Simulation Skill 规范

## 使命

帮助用户可复现地运行 Entity 模拟。

这个 skill 关注运行正确性、运行元数据和第一轮验证。默认不修改 Entity 核心源码。

## 允许范围

可以创建或编辑：

- TOML 输入文件；
- 用户控制 case 目录下的 pgen 文件；
- build scripts；
- run scripts 和 Slurm scripts；
- run manifests；
- smoke-test notes。

避免修改：

- `src/engines`；
- `src/kernels`；
- `src/framework`；
- output writer 内部。

如果必须修改这些内容，路由到 [[Development Skill Spec|Development Skill]]。

## 必要输入

收集或推断：

- 物理目标；
- Entity checkout 路径和版本；
- 目标 engine：SRPIC 或 GRPIC；
- metric 和坐标系统；
- 维度；
- pgen 选择或 custom pgen 需求；
- 机器和 backend：CPU、CUDA、HIP、MPI；
- 运行规模；
- 输出需求；
- checkpoint 策略。

## 工作流

1. 探测 checkout 和版本。
2. 读取该 checkout 的 `input.example.toml`。
3. 检查选定 pgen 和参考 TOML。
4. 起草 simulation plan。
5. 生成或更新 TOML。
6. 生成 build command。
7. 生成 run command 或 scheduler script。
8. 在用户要求且可行时运行小型 smoke test。
9. 检查 `.info`、`.err`、`.log`、stdout 和 stats CSV。
10. 写 run manifest。

## 必要输出

使用 [[90-Templates/Run Manifest Template|Run Manifest 模板]]。

包含：

- checkout commit；
- build flags；
- pgen；
- TOML 路径；
- run command；
- output path；
- checkpoint 策略；
- validation status；
- known risks。

## 验证级别

| 级别 | 含义 |
| --- | --- |
| Config check | TOML 与 build/run commands 内部一致。 |
| Smoke run | 小型运行可以启动并写出预期 metadata。 |
| Numerical sanity | 基本 stats 和输出量有界且合理。 |
| Physics validation | 领域诊断支持目标物理结论。 |

不要在 analysis 支持前声称某次运行已经完成物理验证。

