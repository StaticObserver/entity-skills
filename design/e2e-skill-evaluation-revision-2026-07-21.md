# E2E 评测修订：资源自发现任务契约与运行过程监控

日期：2026-07-21
状态：task/fixtures/source-cache/collector 已实现（2026-07-21）；待 probe gate 与 pilot
前序：`design/e2e-skill-evaluation-project-2026-07-19.md`（项目总则不变，本文修订任务契约与过程监控两部分）

## 1. 新任务契约

### 1.1 评测只提供两样东西

- `task.md`：任务目标、交付物契约、站点边界、资源上限、安全约束；
- `physics-spec.json`：冻结的物理语义（与 07-19 文档 §3.2 一致，不改动）。

源码路径、依赖缓存路径、可写根、作业命名等一律不出现在任务输入中。

### 1.2 task.md 必须包含的内容

task.md 需要把任务描述清楚，并明确以下**站点使用边界**（这些是约束，不是资源位置）：

1. 计算必须发生在 **siyuan 集群**，不得使用其他站点（siyuan 与 pi2 是两个不同的
   集群，不得混用）；
2. **禁止在登录节点编译**；编译必须发生在计算资源上（交互或作业方式由 agent 自决）；
3. 作业提交目标为 **debuga100 分区**（GPU 资源），受资源上限约束；
4. **数据分析使用 CPU 资源**，不得占用 GPU 节点做分析；
5. 资源上限：1 node / **2 GPU（MPI，2 tasks）** / 10 min walltime；
6. 安全约束不变：禁止公网、凭据不得入产物、不修改共享只读内容、缺关键决策时停下
   来报告而非自行假设。

task.md **不得包含**：Entity 源码位置、依赖缓存位置、具体可写路径、站点内部用户名、
任何"已由评测运行时提供"的字样。agent 需要通过环境探测（ssh 配置、集群上可读的公共
缓存、已有软件栈）自行定位这些资源。

### 1.3 本地源码缓存（维护者预置）

评测运行前由维护者在 siyuan 上准备一个**只读源码缓存**，包含：

| 组件 | 版本 | 说明 |
|---|---|---|
| Entity | v1.4.4（tag） | 冻结版本，与 physics-spec 一致 |
| Kokkos | 5.0.1 | modern profile 默认（entity-env-build 版本策略） |
| ADIOS2 | 2.11.x | modern profile |
| OpenMPI | 4.1.6 | MPI=ON 所需；agent 也可选用站点既有 MPI |
| HDF5 | 1.14.6（tag `hdf5_1.14.6`） | ADIOS2 依赖 |

约束：

- 缓存内容与版本指纹（sha256）记录在评测 manifest 中，可提交仓库；
- 缓存放置在 agent 可合理发现的只读位置，但**路径不出现在 task.md**（§1.5 probe
  gate 验证可发现性）；
- 提供源码不等于强制源码构建：agent 仍可选用站点已有的等价依赖，但必须通过兼容性
  收束并在 submission 中给出身份与指纹。

### 1.4 交付物契约不变

`submission.json` schema 沿用现有版本。它是裁判接口，不是资源提示；no-skill 组同样适
用，不要求模仿 Router 内部对象。

### 1.5 可发现性前提（probe gate）

"可发现但未声明"必须被验证，否则测的是环境布置而不是 agent 能力。正式开跑前由维护者
执行一次 probe：

- 确认 siyuan 集群上存在 agent 可合理发现的源码缓存（§1.3）与站点软件栈；
- 确认发现路径不依赖本评测仓库的私有知识；
- probe 结论写入试验 manifest。probe 失败则先修环境，不开跑。

### 1.6 新 task.md 草案

```markdown
# End-to-end Entity simulation task

Run the controlled Entity simulation described by the supplied
`physics-spec.json` on the siyuan cluster.

Complete the full lifecycle:

1. create a consistent `docs/design.md`, `pgen.hpp`, and Entity TOML input;
2. discover and converge a CUDA + MPI build environment for this PGen;
3. perform a clean Entity build (MPI enabled);
4. submit exactly one Slurm job within the stated resource budget and wait for
   its terminal result;
5. inspect the produced data with nt2py and perform the requested field and
   particle analysis;
6. write all required artifacts and a final `submission.json` that conforms to
   the supplied schema.

Site rules:

- All computation happens on the siyuan cluster. Do not use any other site.
- Do not compile on login nodes.
- Submit the GPU job to the `debuga100` partition, within the resource budget:
  1 node, 2 GPUs, 2 MPI tasks, 10 minutes walltime.
- Use CPU resources for data analysis; do not occupy GPU nodes for analysis.

Resource locations are intentionally not specified. Discover the available
Entity source, dependency sources, and writable roots yourself. Do not use the
public network. Do not modify shared read-only content. Do not expose
credentials in source files, logs, or results. Keep analysis artifacts
outside the raw-data root.

If a required scientific or resource decision is genuinely missing, report it
precisely and stop before creating external effects. Do not silently change
the physics specification or resource ceiling.
```

## 2. 运行过程监控（observability v2）

### 2.1 独立性与可开关（硬要求）

监控是被测系统之外的独立层，满足三条：

1. **零侵入**：不修改任何 skill 的 SKILL.md、脚本或 Router 代码；不在被测 workspace
   的 skill 目录内安装 hook 或探针。skills 本身不知道监控是否存在。
2. **可整体开关**：由评测 harness 的一个开关控制（如 `OBSERVE=on|off` 或
   `--observe` 标志）。关闭时 agent 的运行方式与不监控完全一致——同一命令行、同一
   settings、同一环境。
3. **开销在带外**：采集与解析发生在被测进程之外或结束之后，不在 agent 的工具调用
   路径上增加任何同步等待，不占用 agent 的上下文窗口。token 与耗时读数反映的是
   agent 原生行为，不含监控自身成本。

### 2.2 证据分级

沿用 declared / observed / verified 三分：agent 报告是 declared，采集流是 observed，
oracle 独立复核是 verified。监控只增加 observed 证据，不改变 oracle 判定逻辑。

### 2.3 三条采集通道

**通道 1：结构化事件流（主 trace）**
被测 Claude Code 以 headless 方式运行，harness 包装命令行：

```bash
claude -p "$(cat task.md)" --output-format stream-json --verbose ...
```

开关关闭时就是不带输出重定向的同一命令。JSONL 事件包含每条 assistant message 的
`usage`（input / output / cache_read / cache_creation tokens）、每个 tool_use /
tool_result、以及最终 result（总耗时、总 token）。token 逐条从 usage 累计。解析全部
在运行结束后离线进行。

**通道 2：Hooks 侧信道（独立动作时间线）**
评测 harness 注入一份独立 settings（与被测 agent 自身配置分离），配置
`PreToolUse` / `PostToolUse` hook，异步追加写 JSONL：时间戳、tool 名、命令指纹（脱
敏）、退出状态。开关关闭时不注入该 settings。hook 脚本只做追加写，不阻塞、不返回
决策，对工具调用路径的影响可忽略；该流独立于 transcript，即使主 trace 损坏也保留带
精确时间戳的重要动作日志，并作为 ssh / sbatch 等外部副作用的审计依据。

**通道 3：外部事实（已有）**
scheduler snapshot、receipt、产物 hash —— 现有 oracle 体系不变，本就不在被测路径上。

### 2.4 确定性阶段切分

不要求 agent 打阶段标记。后处理按工具调用模式把 trace 切成有序 phase：

| phase | 切分信号（首个命中的工具调用模式） |
|---|---|
| discover | 探索性 ssh / ls / find / 环境探测，直到站点与源码确定 |
| pgen | 写 `pgen.hpp` / `design.md`、PGen preflight |
| env-build | cmake / make / entity-build 相关调用 |
| run | `entityctl plan/apply` 或 `sbatch` |
| analysis | `import nt2` / 分析脚本执行 |
| submission | 写 `submission.json`（trace 终止信号） |

切分规则放在 collector 配置里，可按 phase 信号表迭代，但不按单次结果回调。

### 2.5 输出：`phases.json`

每条 assistant message 按时间戳归入所在段，累计每段：

- wall time（起止时间戳；Slurm 排队等待单独标注，不计入 agent 效率，同 07-19 §5.3）；
- token：input / output / cache_read / cache_creation **分列**（cache 两项必须单列，
  用于回答"skills 上下文成本是否值得"）；
- 工具调用数、失败调用数、SSH 往返数。

归不了段的计入 `unclassified`；其 token 占比过高（阈值暂定 10%）说明切分规则失效，
本轮 trace 标注为不可比较，先修规则再开跑。

### 2.6 落地位置

扩展现有 `tools/skill_observability`：

1. 新增 CC stream-json transcript parser（离线）；
2. 新增 phase segmenter（规则表驱动，离线）；
3. trace schema 增加 `phases[]`；
4. harness 增加监控开关，控制输出重定向与 hook settings 注入；
5. 汇总报告直接读 `phases.json` 填 07-19 文档 §8 的"执行成本"维度。

## 3. 公平性影响

- S/N 两组收到完全相同的新 task.md，发现阶段对两组同样受测，对照公平性不变；
- 发现阶段的耗时与 token 计入比较，但排队时间仍单独报告；
- 若某组在 discover 阶段失败，按"完成阶段数"计入自主完成度（07-19 §8 第 2 项），
  不以效率补偿。

### 3.1 无 skill 组（N）如何观测

监控仪器与被测条件无关：它观测的是 agent 的可观测行为（工具调用、token、时间戳），
不观测 skill 本身。因此对 N 组完全同构：

- stream-json 采集、hooks 侧信道、transcript 导入都由 harness 在带外完成，两组一致；
- 阶段切分规则匹配的是**任务交付物**而非 skill 接口——`pgen.hpp`、`design.md`、
  `cmake/make`、`sbatch/squeue`、`import nt2`、`submission.json` 都是 task.md 强制
  要求的产物，N 组同样产生；S 特有的 `entityctl` 等信号只是 run 阶段的规则之一，
  N 组直接 `sbatch` 同样命中；
- N 组 `start` 不带 `--skill`，`resource_matches` 自然为空，不报错也不缺数据。

唯一 S-only 的观测是 skill 证据验证器（router-operation、pgen-preflight、env-build、
nt2py-inventory）。它们不是裁判接口：两组的共同裁判是 oracle Gates A–E，读取
scheduler、raw data、submission 等外部事实。N 组的 phases.json 与 S 组结构完全相同，
可直接进入同一汇总比较（已有 N 组风格转录的切分测试覆盖）。

## 4. 实施顺序

1. 准备本地源码缓存（§1.3）并记录版本指纹 manifest；
2. 按 §1.6 落地新 `task.md`，更新 `evals/e2e-neutral-streaming/` fixtures
   （含 physics-spec 的 MPI 与 2 GPU 资源上限）；
3. 执行 §1.5 probe gate，确认资源可发现；
4. 实现 collector 的 parser + segmenter + `phases.json` 与监控开关（§2.6），用
   gold run 的既有 trace 回归验证切分规则；
5. pilot：S/N 各一次，检验发现阶段可观测、监控数据完整、开关关闭时行为与裸跑一致；
6. 通过后才启动 formal 配对（沿用 07-19 §5.3 顺序）。
