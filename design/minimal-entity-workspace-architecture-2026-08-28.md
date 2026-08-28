# Entity Workspace 简化架构

## 1. 原则

- 系统只有 Source、PGen、Build、Run 四个基本对象。
- 只固定跨 Agent、跨项目、跨站点必须保持的事实。
- 事实来源是 Git commit、JSON、TOML 和 Site 上的实际文件。
- 不使用数据库。
- 除 Source 的 Git commit 外，不计算或校验 Hash。
- 冲突只报告，由人修复；系统不自动合并、覆盖或升级状态。
- 不规定 PGen、构建、运行和分析的固定顺序。

## 2. 四个基本对象

Source、PGen、Build、Run 是唯一的一等对象。只有它们拥有独立身份和核心 JSON 记录，架构、目录和命令均围绕它们建立。

```text
Source ─┐
        ├── Build ─── Run
PGen ───┘
```

- **Source**：一个 Entity Git commit。
- **PGen**：独立用户代码包，可与多个 Source 组合。
- **Build**：Source + PGen + Site + deps + 编译选项的产物。
- **Run**：一个 Build + 一份原始 TOML。

其他概念均由四个基本对象的属性或组合派生：

| 概念 | 归属或推导方式 |
|---|---|
| Project | 对 Source、PGen、Build、Run 的组织容器 |
| Workspace | Project 和 Site 配置的本地工作目录 |
| Site | Source、Build、Run 的位置与执行环境属性 |
| deps | Build 的环境属性，存放于 Site |
| TOML | Run 的固定输入属性 |
| Data | Run 的输出属性，始终属于该 Run |
| Attempt | Run 的一次提交记录 |
| Analysis | 一个或多个 Run 与分析脚本的组合结果 |

这些派生概念可以有目录和 JSON 记录，但不建立独立对象体系、全局身份、current 指针或生命周期状态机。

## 3. 四对象关系

1. Source 必须记录仓库和 Git commit。
2. 已用于 Build 的 PGen 不原地修改；修改后创建新 `pgen_id`。
3. Build 必须同时引用 Source、PGen、Site 和 deps。
4. Build 保存实际使用的 PGen 文件副本。
5. Run 只能引用一个 Build 和一份原始 TOML。
6. TOML 改变时创建新 Run；资源调整或重投只创建新 Attempt。
7. Data 只能位于对应 Run 下。
8. Analysis 必须记录输入 Run、脚本、参数和输出。
9. 路径由 Workspace、Project、Site 和对象 ID 确定。

## 4. Workspace

```text
<workspace>/
├── workspace.json
├── sites/
│   └── <site>.json
└── projects/
    └── <project>/
        ├── project.json
        ├── sources/
        │   └── <source-id>/
        │       ├── source.json
        │       └── checkout/
        ├── pgens/
        │   └── <pgen-id>/
        │       ├── pgen.json
        │       └── ...
        ├── builds/
        │   └── <build-id>/
        │       ├── build.json
        │       └── runs/
        │           └── <run-id>/
        │               ├── run.json
        │               ├── input.toml
        │               └── analysis/       # 单 Run analysis.json
        ├── scripts/
        └── analysis/
```

Workspace JSON 记录对象关系和用户选择。

### Source

```json
{
  "id": "entity-main-20260828",
  "repository": "https://github.com/entity-toolkit/entity.git",
  "git_commit": "abc123",
  "checkout": "checkout"
}
```

### PGen

```json
{"id": "decay-turb-v3", "name": "decaying turbulence", "entry": "pgen.hpp"}
```

### Build

```json
{
  "id": "build-20260828-a100",
  "source": "entity-main-20260828",
  "pgen": "decay-turb-v3",
  "site": "astro",
  "deps": "cuda12.4-gcc12-openmpi",
  "options": {"backend": "cuda", "gpu_arch": "sm80", "precision": "single"},
  "runtime": {"mpi": true, "gpu": true}
}
```

### Run

```json
{
  "id": "run-sigma01-001",
  "build": "build-20260828-a100",
  "toml": "input.toml",
  "resources": {
    "nodes": 2,
    "tasks": 8,
    "tasks_per_node": 4,
    "cpus_per_task": 8,
    "gpus_per_node": 4,
    "walltime": "12:00:00",
    "partition": "gpu",
    "account": "physics"
  },
  "environment": {"OMP_NUM_THREADS": "8"}
}
```

相同 Build 和 TOML 可以使用不同 `run_id` 重复运行。

## 5. Site

```text
<site_root>/
├── site.json
├── site-env.sh
├── checkouts/<source-id>/
├── deps/
│   └── <deps-id>/
│       ├── deps.json
│       ├── env.sh
│       ├── install/
│       ├── sources/
│       ├── scripts/
│       └── logs/
├── staging/deps/
└── projects/
    └── <project>/
        ├── builds/
        │   └── <build-id>/
        │       ├── build-result.json
        │       ├── pgen/
        │       ├── scripts/build.sh
        │       ├── work/
        │       ├── bin/entity
        │       ├── logs/
        │       └── runs/
        │           └── <run-id>/
        │               ├── input.toml
        │               ├── attempts/
        │               ├── data/
        │               └── analysis/
        └── analysis/
```

Site JSON 和实际文件记录执行现场。Analysis 的关系 JSON 在 Workspace；大型分析产物可以放在 Site 的 `analysis/`。

### Site 配置

```json
{
  "id": "astro",
  "root": "/home/user/entity-compute",
  "transport": {"kind": "ssh", "alias": "astro"},
  "environment": {"script": "site-env.sh"},
  "scheduler": {
    "kind": "slurm",
    "submit": "sbatch",
    "query": "squeue",
    "accounting": "sacct",
    "defaults": {"partition": "gpu", "account": "physics", "walltime": "24:00:00"}
  },
  "mpi": {"launcher": "mpirun", "template": ["mpirun", "-np", "{tasks}"]}
}
```

无调度器时使用 `"scheduler": {"kind": "none"}`。SSH 配置不保存凭据。

## 6. deps 与 Build

deps 是 Site 级可复用环境：`<site_root>/deps/<deps-id>/`。

`deps.json` 记录编译器、CUDA/ROCm、MPI 和库路径；`env.sh` 加载模块并导出环境变量。

| 内容 | 位置 |
|---|---|
| 依赖安装 | `deps/<deps-id>/install/` |
| 依赖源码 | `deps/<deps-id>/sources/` |
| 依赖构建脚本 | `deps/<deps-id>/scripts/` |
| 依赖日志 | `deps/<deps-id>/logs/` |
| 临时依赖构建 | `staging/deps/<deps-id>/` |
| Entity 构建脚本 | `builds/<build-id>/scripts/build.sh` |
| CMake 目录 | `builds/<build-id>/work/` |
| 可执行文件 | `builds/<build-id>/bin/entity` |

环境加载顺序：

```text
site-env.sh → deps/<deps-id>/env.sh → Build/Run 自定义变量
```

构建完成后写 `build-result.json`，记录状态、可执行文件、脚本、日志和退出码。

## 7. Attempt 与提交脚本

```text
<run-id>/attempts/<attempt-id>/
├── attempt.json
├── run.sh
├── job.slurm
├── submit-result.json
├── stdout.log
└── stderr.log
```

- `run.sh`：加载环境并启动 Entity，与调度器无关。
- `job.slurm`：申请 Slurm 资源并调用 `run.sh`，仅 Slurm Site 生成。
- `attempt.json`：记录本次采用的资源。
- `submit-result.json`：记录 Slurm job ID 或直接运行的 PID。

启动规则：

```text
build.runtime.mpi = false → 直接执行 Entity
build.runtime.mpi = true  → 使用 site.mpi.template
```

Slurm 不等于 `srun`。MPI launcher 由 Site 显式配置；非 MPI 程序不能使用多任务 launcher。

提交前写 `attempt.json`，提交后写 `submit-result.json`。提交结果未知时先查询调度器，不自动重复提交。

## 8. Data 与 Analysis

Data 直接位于 `<run-id>/data/`。`run.json` 可以记录文件数、时间范围、checkpoint 数量和人工备注，但不做内容 Hash。

- 通用分析脚本：`projects/<project>/scripts/`
- 单 Run 分析：`<run-id>/analysis/<analysis-id>/`
- 多 Run 联合分析：`projects/<project>/analysis/<analysis-id>/`

`analysis.json` 只记录 `id`、`runs`、`script`、`parameters` 和 `output`。

## 9. 权威边界

- Workspace `source.json`、`pgen.json`、`build.json`、`run.json`：对象关系和用户选择。
- Site `deps.json`：实际依赖环境。
- Site `build-result.json`：实际构建结果。
- Site `attempt.json`、`submit-result.json`：实际提交信息。
- Run `input.toml` 和 `data/`：实际输入和数据。

发生矛盾时报告两边事实，由人决定如何修复。

## 10. 技能边界

| 技能 | 负责内容 |
|---|---|
| `entity-pgen` | PGen、TOML |
| `entity-env-build` | deps、`env.sh`、`build.sh`、可执行文件、`build-result.json` |
| `entity-ledger` | JSON 关系、Run、Attempt、`run.sh`、`job.slurm`、提交和状态查询 |
| `entity-nt2py` | Run/Data 读取与 Analysis |

## 11. 检查

`entity check` 只报告：

- JSON 无法解析；
- 引用对象不存在；
- 记录路径不存在；
- Workspace 与 Site 记录冲突；
- MPI、调度器或资源配置明显不完整。

检查不修改文件，也不是普通操作的强制门槛。Case、SQLite、schema migration、内容 Hash、seal、release、current/ref 和自动冲突修复均不属于本架构。
