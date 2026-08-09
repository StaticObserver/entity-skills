# e2e-streaming-official @ astro 测试计划

> **阶段 0（评测包适配 astro）已完成 2026-08-05**:physics-spec 改
> VOLTA70/Slurm/astro-streaming,gate C sacct 分支接入并补单测，
> task.md / clean_remote.sh / RUNBOOK / README 同步；`pytest tests/`
> 323 全绿。
>
> **阶段 1（站点建设，pilot）已完成 2026-08-09**:pilot workspace
> `~/entity-workspace` 建起并 adopt;sites/astro-streaming.yaml 登记并
> sync;`site init` 在 astro 建好 `~/entity-compute` 新树 +
> entity-site.yaml;`site discover` 落 machine 节（分区/QoS 实测与本
> 计划 §1 一致）。deps 注册表两栈齐：build 栈
> `compiler12.3.0-kokkos5.1.0-fba1fb4dcb0d`(GCC 12.3.0 + CUDA 12.6 +
> kokkos 5.1.0-VOLTA70 + hdf5 1.14.5 + adios2 2.11.0;checkpoint
> compatibility pass、参数已确认；env.sh 在新树 deps/<stack_id>/),
> analysis 栈 `stack-882febbd968e`(miniconda python 3.12.8 + nt2py
> 1.5.3，本次 pip 安装）。run_round.sh 改为给 agent 发脱敏 spec
> (redact_spec.py)。发现的问题见会话报告（doctor 报既有 0.6.1 技能投
> 影漂移，与本次无关；executor sbatch `--gres=gpu:N` 不支持 typed
> gres，是 0.7.0 设计缺口，阶段 2 前需决策）。
>
> **阶段 2（TOML 校准 + gold run,pilot）已完成 2026-08-09**:typed
> gres 缺口已修（policy `default_gres` + `--gres`)。全流程：project
> streaming-eval / case twostream-gold(case-b57321c9abf1ce71)→
> snapshot-source → 编译（build-volta70-single-002,Slurm job 356999/
> 357001,fat CPU-only 32 核，4m05s；二进制烘 rpath 自包含）→ record
> build(build-f5171682c1d24b91，命中注册栈)→ render-run/record
> run-prepare/run-launch(**run-879cd51744bad483**,job 357003,
> fat+gpu:V100:1+qos512 无 --time;Slurm elapsed 2s，计算 ~1s)→
> run-exit(teardown abort,--reclassify 判 completed + exit_anomaly)
> → record data(data-138282d17045e948,109 文件）→ 分析（intelhigh
> job 357006,11s;analysis-eeb468cba15dff30)→ record analysis。
> status 六格全绿；oracle 自判 **overall pass**(A 门 pilot 用空
> transcript 虚过）。校准结论：final_time=50 充裕（γ=0.137 ω_pe 落在
> 冷双流理论带 0.1–0.15,t≈13.8 饱和，增长 7.1e3 倍，能量漂移 0.2%,
> 粒子数守恒）;Gate D 阈值已按观测带冻结；官方 pgen 无 seed knob,
> spec 已注明。pilot 修复的 0.7.0 bug 与 gate 增强见 CHANGELOG Fixed
> 与会话报告（含 build-001 树被误重链的事故记录）。

日期:2026-08-05。评测包:`evals/e2e-streaming-official/`(f46f724)。
被测对象:0.7.0 skill 全流程(Workspace / Computation Site / deps 注册表 /
record 原语 / analysis 管理)+ 官方 streaming pgen。被测 agent:Claude Code
headless。裁判:oracle 五门。

## 1. 站点事实(2026-08-05 实测 + site-notes)

- 访问:`ssh astro` → 登录节点 mgmt(40 核,EL8)。**mgmt 禁止重活**,
  编译也走 Slurm(CPU-only 作业,~5 min)。
- GPU:计算节点 gpu1 = V100S-32GB(当前空闲)+ A100-80GB(被其他用户
  长作业占用)。**本测试用 V100**:`fat` 分区,`--gres=gpu:V100:1`,
  **不写 --time**(用户指定,分区默认 MaxTime=3 天)。
- 分区策略(用户指定 2026-08-05):模拟 → fat/gpu1 V100;分析/渲染 →
  intelhigh,排队改 amdlow;不投 fat 做分析。
- QoS:qos512 可用。
- 已验证 deps(VOLTA70 栈,2026-08-04 axion-grpic 构建验证):
  `~/entity/deps/{kokkos/5.1.0, hdf5/1.14.5, adios2/2.11.0}`。
- 工具链:GCC 12.3.0(module gnu12/12.3.0)+ CUDA 12.6(`~/local/cuda-12.6`);
  已知坑:`NVCC_WRAPPER_DEFAULT_COMPILER` 要指 GCC 12.3 g++;
  `find_package(adios2)` 走 `CMAKE_PREFIX_PATH`,`-DADIOS2_ROOT` 无效。
- 源码:Entity v1.4.4 pristine 在 `~/entity/1.4.4`(含官方 pgens,
  `-DOFFLINE=ON` 禁 FetchContent);仓库内另有 source-cache 副本。
- Python(skill 工具/分析):`~/miniconda3/bin/python3`(3.12.8);
  系统 python 太旧。

## 2. 与 m87 版计划的差异

| 维度 | m87 版 | astro 版 |
|---|---|---|
| 调度器 | 无(direct 后端) | Slurm(sbatch/sacct) |
| Gate C | `.entity-exit-code` 证据 | sacct 事实(原 neutral gate_c 路径) |
| GPU | RTX 4070 Ti | V100(VOLTA70) |
| 编译 | 本地直接 | Slurm CPU-only 作业(fat,32 CPUs,no gres) |
| site 布局 | legacy roots | **新建 site_root 约定树**(见 §3 决定) |

## 3. 关键决定

1. **用新树不用旧树**:为本次测试登记新 site `astro-streaming`,
   `site_root = ~/entity-compute`,走 0.7.0 完整路径:`site init` 建树 +
   `entity-site.yaml` 标记 → `deps-add` 把既有 VOLTA70 栈登记进注册表 →
   `--kind analysis` 登记 miniconda 解释器。旧 astro* site 与旧树不动。
2. **gold run 由我们(Kimi)先跑**,作为 0.7.0 工作流的 pilot;阈值冻结
   后再跑正式 Claude Code 轮。pilot 发现的问题修完再测,避免拿已知坏掉
   的流程浪费 e2e 轮次。
3. **物理判据方向**:two-stream 是增长物理(不是 neutral 的守恒判据),
   Gate D 冻结时以 gold run 观测带为准,重点核增长率与饱和行为。

## 4. 阶段划分

### 阶段 0:评测包适配 astro(无站点依赖,可立即做)

- physics-spec.json:compile 段改 VOLTA70;资源段改 Slurm(fat、
  `--gres=gpu:V100:1`、无 --time、qos512);加"分析作业投 intelhigh/amdlow"
  约束(Gate A 检查项)。
- gate_c_job_data.py:恢复/接入 sacct 分支(sbatch job id、exit code、
  恰好一个 job、gres 上限);保留 direct 分支供 m87 复用。
- run_round.sh / clean_remote.sh:站点改 astro-streaming,清理走
  squeue/sacct 确认无残留作业。
- task.md:资源段改为"一个 Slurm 集群",不给分区名(deps/分区的自发现
  是考察点;site 档案里已登记的信息允许用)。
- 验收:oracle 单测全绿;RUNBOOK 更新。

### 阶段 1:站点建设(pilot,我们执行)

- `entityctl site init astro-streaming`(site_root=~/entity-compute,ssh)。
- `site discover` 落 machine 节;`site deps-add` 登记 VOLTA70 栈
  (checkpoint 来自一次真实 requirements 解析);
  `site deps-add --kind analysis` 登记 miniconda python。
- 验收:`site deps astro-streaming` 列出两栈;`entity-site.yaml` 在 astro
  上可读;全部 Locator 走新树。

### 阶段 2:TOML 校准 + gold run(pilot,我们执行)

- 用 0.7.0 全流程跑一遍:workspace init(本机)→ project/case →
  snapshot-source → requirements(pgen=streaming、VOLTA70、single)→
  checkpoint confirm → 编译作业(Slurm,fat,CPU-only)→ record build →
  render-run(fat、`--gres=gpu:V100:1`)→ run-prepare/run-launch →
  run-exit → record data → record analysis(manifest 全字段)。
- 校准点:final_time=50 下不稳定增长是否充分观测、单作业 walltime
  (目标 ≤10 min)、输出体量。
- 冻结:Gate D thresholds.json 以 gold run 观测带重写(增长率、漂移、
  能量、场噪声);seed 语义确认(官方 pgen 无 seed knob 则在 spec 注明)。
- 验收:oracle 对 gold run 产物判 pass;`status` 六格全绿(analysis 格
  established)。

### 阶段 3:正式 e2e 轮(Claude Code headless)

- `run_round.sh` 起轮;观测 trace 开;agent 从干净状态完成任务。
- oracle 五门判分;findings 文档记录技能归因(0.7.0 原语使用率、
  deps 注册表命中、record analysis 使用情况)。
- 验收:oracle overall pass/fail + 归因分析;与历史轮次
  (2026-07-22/23)对比。

### 阶段 4:清理与归档

- clean_remote.sh(squeue 确认无残留);astro 上本次树保留或删除由
  用户定;findings 归档,CHANGELOG/README 按需更新。

## 5. 风险与对策

- **gpu1 占用变化**:A100/V100 被其他用户抢占 → 作业排队,e2e 轮时间
  拉长;对策:跑前 `ssh gpu1 nvidia-smi` 确认,轮次时间窗放宽到 3 小时。
- **V100 算力低于 4070 Ti**:two-stream 128 cells/ppc 32 量级在 V100
  上仍然分钟级,风险低;若超时,缩 runtime。
- **GCC/CUDA 次版本混用**(12.3+12.6 工具链 vs 12.2/12.0 构建的 deps):
  bh-reconnection 已验证可行,checkpoint 会记录;若 compat 失败,回退
  用 deps 的原始工具链重新解析。
- **deps-add 的 env.sh 门禁**:VOLTA70 栈没有现成 env.sh——pilot 阶段
  按 stack.yaml 约定生成一个。
- **分析环境**:miniconda 里 nt2py 是否已装未知;阶段 1 核查,缺则用
  pip 装进该环境(并记入 stack recipe)。

## 6. 完成定义

- 阶段 0–2 完成 = gold run 全绿、阈值冻结、oracle 自判 pass。
- 全部完成 = 正式轮 oracle 判分 + findings 归档。
