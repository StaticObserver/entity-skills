# Entity Workspace 与状态机制

日期：2026-07-13  
状态：当前约定；初版 Case/Action 状态工具已实现

## 1. 总工作文件夹

总工作文件夹记为 `ENTITY_WORKDIR`。它同时保存多个 Entity checkout、共享依赖和所有 simulation problem。

```text
$ENTITY_WORKDIR/
├── entity-<version-or-label>/       # 不同版本的 Entity checkout
├── entity-<version-or-label>/
├── deps/                            # 多版本、多 PGen 共享依赖
└── problems/
    └── <case_id>/                   # 一个可独立恢复和切换的 Entity case
```

约定：

- Entity checkout 直接位于总工作文件夹下，不再增加一层 `source/`。
- checkout 名称建议使用 `entity-<version-or-label>`，但实际路径必须记录，不能只依赖目录名判断版本。
- `deps/` 只放共享依赖、依赖源码和依赖构建脚本。
- `problems/` 只放 simulation problem，不放 Entity 源码或共享依赖。

## 2. Case 文件夹

每个 case 使用一个独立文件夹，集中保存 PGen、构建、runs、分析和 Router 记忆。第一版 `case_id` 等于 PGen 名，以兼容 `entity-env-build`。

```text
$ENTITY_WORKDIR/problems/<case_id>/
├── pgen.hpp                         # 当前 PGen 的工作副本
├── <pgen>.toml                      # 与 PGen 匹配的工作配置
├── docs/
│   └── design.md                    # PGen/TOML 设计和当前状态
├── build/                           # Entity CMake build tree
├── _build/                          # entity-env-build 控制产物和状态
├── _case/                           # Case 关键记忆、控制状态和历史
│   ├── case.json
│   ├── events.jsonl
│   ├── actions/
│   │   └── <action_id>/
│   │       ├── request.json
│   │       └── result.json
│   └── history/
├── scripts/                         # 多个 run 共用的分析代码
├── run-<label-a>/                   # 一组参数对应的一次 simulation
├── run-<label-b>/
└── run-<label-c>/
```

保留名称：

- `build/`：实际 CMake 编译树，可清理和重建；
- `_build/`：构建 harness 的持久状态，不与 CMake tree 混放；
- `_case/`：Router 使用的 case 记忆、Action Contract、workflow 控制状态和 append-only 事件；
- `scripts/`：多个 run 可复用的分析函数、绘图工具和 notebook 基础代码；
- `run-*`：具体参数和运行数据。

`pgen.hpp` 是 case 文件夹内的权威工作副本。构建时如何映射到 Entity checkout 由 playbook 和 `entity-env-build` 明确处理，并记录 PGen hash；不允许存在多个无法判断真假的 PGen 副本。

## 3. Run 数据文件夹

一个 `run-<label>/` 对应一组确定参数和一次独立运行身份。

```text
run-<label>/
├── input.toml                       # 本次 run 使用的完整 TOML
├── run-manifest.yaml                # 输入身份和运行状态
├── data/                            # Entity 原始输出和 checkpoint
├── logs/                            # stdout、stderr、scheduler 日志
└── analysis/
    ├── scripts/                     # 本次 run 的分析代码
    ├── figures/
    ├── notebooks/                   # 按需使用
    └── analysis-report.md           # 按需生成
```

规则：

- run 文件夹直接放在 `<case_id>/` 下，不增加统一的 `runs/` 中间层。
- 名称使用 `run-<short-label>`；label 应能区分主要参数，但不承担完整元数据职责。
- 完整参数以 `input.toml` 和 `run-manifest.yaml` 为准。
- run 启动后，不原地修改其 TOML。参数变化应创建新的 run 文件夹。
- 从 checkpoint 续跑时创建新的 run 身份，并在 manifest 中引用 parent run 和 checkpoint。
- `data/` 保存原始输出，不放生成的图片和临时 notebook。
- `analysis/` 保存该 run 专属的脚本、图像和结论；共用逻辑放到 PGen 级 `scripts/`。

## 4. 构建目录

现有 `entity-env-build` 的主布局继续保留：

```text
$ENTITY_WORKDIR/problems/<case_id>/
├── build/
└── _build/
    ├── requirements.json
    ├── entity-deps.local.json
    ├── .entity-session.json
    ├── env.sh
    ├── entity-build.sh
    ├── build-logs/
    └── generated/
        └── source-builds/
```

职责：

- `requirements.json`：当前 build request 和最终 build result；
- `entity-deps.local.json`：依赖选择、兼容性和 `env.sh` 状态；
- `.entity-session.json`：构建流程的可恢复步骤状态；
- `env.sh`、`entity-build.sh`：派生产物，不手工维护；
- `build-logs/`：配置和编译日志；
- `build/`：CMake build tree，不作为状态源。

同一个 `<case_id>/build/` 表示当前有效构建。改变 Entity checkout、backend、precision、MPI 或其他关键编译选项后，必须重新验证或清理构建树。旧 run 依靠自身 manifest 保存当时的 build identity，不依靠当前 `build/` 复现历史。

## 5. 状态分层

不建立覆盖整个 workspace 的全能状态文件。每个 case 使用 `_case/case.json` 记录关键记忆和当前 workflow，同时从各 owner 产物恢复事实状态。

| 范围 | 状态文件 | 说明 |
|---|---|---|
| Machine | `~/.entity-env-build/run.log`、`site-notes/` | 机器经验和审计，不是 simulation 状态源 |
| Case/Router | `<case_id>/_case/case.json`、`events.jsonl`、`actions/` | Case 记忆、Action Contract、门禁和状态转移 |
| Build | `<case_id>/_build/.entity-session.json` | 构建步骤进度和失败点 |
| Build request/result | `<case_id>/_build/requirements.json` | 构建输入和最终结果 |
| Dependencies | `<case_id>/_build/entity-deps.local.json` | 依赖 checkpoint 和 compatibility |
| Run | `<run>/run-manifest.yaml` | 单次运行身份和生命周期 |
| Analysis | `<run>/analysis/` | 由脚本、图像和报告体现，不单设状态机 |

### Build 状态

构建状态由 `entity-env-build` 管理，至少覆盖：

```text
requirements_validated
  -> checkpoint_updated
  -> compatibility_checked
  -> env_generated
  -> build_script_generated
  -> build_executed
```

每一步记录 `status`、输入、输出、时间和必要的 run ID。失败后从最近的有效产物继续，不重新执行已经通过且未失效的步骤。

### Run 状态

`run-manifest.yaml` 的最小生命周期：

```text
prepared -> submitted/running -> completed
                            \-> failed
                            \-> stopped
```

`running` 不能只凭 manifest 判断。Router 必须重新检查进程、scheduler、退出码或最新日志，再更新状态。

### Analysis 状态

分析不建立独立状态文件：

- 脚本表示可复现方法；
- figures/notebooks 是派生产物；
- `analysis-report.md` 表示已经形成的结论；
- 未完成事项写入报告或当前 playbook，不写入全局状态库。

## 6. Router 恢复流程

Router 接手已有 workspace 或切换 case 时按以下顺序恢复：

1. 按精确 `case_id` 或路径选择 `problems/<case_id>/`；
2. 读取 `_case/case.json`，确认关键记忆、scope 和未闭合 action；
3. 重新读取 PGen/TOML/design、build、run 和 analysis 证据；
4. 比较 fingerprints，传播 stale；
5. 用实际进程、scheduler、日志和输出校验 run 状态；
6. 重新计算 allowed actions 和 next action；
7. 确定 next Action，并创建或复用对应的 Case-bound Worker。

存在多个 case、checkout 或 run 且无法唯一判断时，Router 不自动选择“最新”目录。离开当前 case 前必须写入 handoff summary 并安全挂起未完成 workflow。

## 7. 与 `entity-env-build` 的一致性

当前一致的部分主要在顶层布局和生成器默认路径：

- `ENTITY_WORKDIR` 包含多个 Entity checkout、`deps/` 和 `problems/`；
- 第一版 `case_id` 等于 PGen 名，因此 PGen 目录仍为 `$ENTITY_WORKDIR/problems/<pgen>/`；
- CMake build tree 为 `<case_id>/build/`；
- harness artifacts 为 `<case_id>/_build/`；
- build result 写入 `requirements.json`；
- machine-level notes 保留在 `~/.entity-env-build/`。

需要修正的部分：

- `entity-env-build/SKILL.md` 的多处操作命令和 checkpoint 搜索顺序仍使用 `$ENTITY_WORKDIR/entity-deps.local.json`；应统一改为当前 PGen 的 `_build/entity-deps.local.json`。
- `entity_checkpoint.py create` 未指定 `--output` 时仍把 `entity-deps.local.json` 写到 `ENTITY_WORKDIR` 根目录；应根据 `requirements.json` 定位当前 PGen 的 `_build/`。
- 所有 build CLI 必须把 `.entity-session.json` 写到同一个 `_build/`，不能根据不同 artifact parent 产生多份 session state。
- `SKILL.md` 中 PGen 根目录的单一 `pgen.toml` 约定应改为每个 `run-*/input.toml`。
- `.entity-session.json` 的文档应与当前实际 `steps/last_step/last_status` 结构一致。

这些修改只调整路径和状态收敛，不改变现有 build artifact chain。
