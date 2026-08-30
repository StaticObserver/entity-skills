# Entity Workspace 0.8.0 发布候选开发记录

状态：实现完成并进入分支 `0.8.0rc`，目标发布版本为 0.8.0；本文保留原阶段与验收记录。

## 1. 目标

实现以 Source、PGen、Build、Run 为唯一基本对象的文件系统工具：

```text
Source + PGen → Build → Run
```

其他内容均由四对象派生：

- deps、Site 是 Build 属性；
- TOML、Data、Attempt 是 Run 属性或记录；
- Analysis 是一个或多个 Run 的组合结果；
- Project、Workspace 只负责组织目录。

不使用数据库；除 Source Git commit 外不使用 Hash；冲突只报告，不自动修复。

## 2. 开发边界

- 0.8.0 实现位于 `vnext/`，旧 Ledger 仅作迁移与历史参考。
- 发布候选分支：`0.8.0rc`。
- Python 标准库优先，不新增运行时依赖。
- JSON 和目录是权威，不建立隐藏状态。
- CLI 只提供确定的文件操作、脚本生成、提交和查询。
- 不实现 Case、current/ref、seal、release、事务状态机和内容 Hash。

## 3. 代码布局

```text
vnext/
├── entity/
│   ├── cli.py
│   ├── paths.py
│   ├── records.py
│   ├── objects.py
│   ├── site.py
│   ├── build.py
│   ├── run.py
│   ├── analysis.py
│   └── check.py
├── bin/
│   └── entity
├── schemas/
│   └── examples/
└── tests/
    ├── unit/
    └── journeys/
```

模块保持单一职责：

- `paths.py`：目录推导；
- `records.py`：JSON 读取、写入和错误报告；
- `objects.py`：四对象字段和关系；
- `site.py`：Site 配置与本地/SSH 操作；
- `build.py`：deps 与 Build 脚本；
- `run.py`：Attempt、运行脚本和提交；
- `analysis.py`：派生分析记录；
- `check.py`：只读诊断。

## 4. 阶段计划

### P0：冻结合同

交付：

- 四对象最小 JSON 示例；
- Workspace/Site 示例目录；
- local、Slurm、MPI 三类 Site 示例；
- 明确 ID、路径和 JSON 权威边界。

完成条件：仅凭示例文件即可推导所有对象关系和目录。

### P1：文件与目录核心

实现：

- Workspace 定位与初始化；
- Project 目录初始化；
- JSON 原子写入和普通读取；
- 基于对象 ID 的路径推导；
- 清晰的缺失、重复和格式错误。

不实现：数据库、锁服务、自动迁移和自动修复。

完成条件：临时目录中可以创建、移动并重新读取完整 Workspace。

### P2：Source 与 PGen

实现：

- `source add/show/list`；
- 读取并记录 Git remote、commit、checkout；
- `pgen add/show/list`；
- PGen 独立于 Source；
- Build 准备时复制实际 PGen 文件。

完成条件：同一个 PGen 可以与两个 Source commit 分别创建 Build 记录。

### P3：deps 与 Build

实现：

- Site `deps/<deps-id>/` 初始化和读取；
- `deps.json`、`env.sh`、依赖脚本和日志目录；
- Build 读取 Source、PGen、Site、deps 和编译选项；
- 生成 `scripts/build.sh`；
- 建立 `work/`、`bin/`、`logs/`；
- 写 `build-result.json`。

同步简化 `entity-env-build`：

- `requirements.json` 合并进 `build.json`；
- `entity-deps.local.json` 简化为 `deps.json`；
- `entity-build.sh` 改为 Build 下的 `scripts/build.sh`。

完成条件：fake compiler 可以完成 Build，并留下 PGen 副本、脚本、日志、可执行文件和结果 JSON。

### P4：Run、Attempt 与调度器

实现：

- `run create` 保存 `run.json` 和原始 `input.toml`；
- `run prepare` 创建新 Attempt；
- 生成调度器无关的 `run.sh`；
- Slurm Site 生成 `job.slurm`；
- 无调度器 Site 直接运行并记录 PID；
- Slurm 提交后记录 job ID；
- 提交结果未知时只报告并提示查询，不自动重投；
- `run status` 查询 PID、`squeue` 或 `sacct`。

脚本矩阵：

| Site | Build | 结果 |
|---|---|---|
| direct | non-MPI | 直接执行 Entity |
| direct | MPI | 使用 Site MPI launcher |
| Slurm | non-MPI | `job.slurm` + 直接执行 Entity |
| Slurm | MPI | `job.slurm` + Site MPI launcher |

完成条件：四种组合均生成正确脚本；Slurm 不默认等同于 `srun`。

### P5：Data 与 Analysis

实现：

- Run 下建立 `data/` 和 `analysis/`；
- 只读数据摘要：文件数、大小、时间、checkpoint 数量和备注；
- Project 通用 `scripts/`；
- 单 Run `analysis.json`；
- 多 Run 联合 `analysis.json`。

不实现：Data ID、内容 Hash、seal、revision 和 current。

完成条件：单 Run 和多 Run 分析均能从 Run ID 解析实际输入目录。

### P6：检查与状态

实现 `entity check` 和 `entity show`：

- JSON 是否可解析；
- Source/PGen/Build/Run 引用是否存在；
- Git checkout 是否处于记录的 commit；
- Workspace 与 Site 路径是否存在；
- deps、MPI、调度器和资源配置是否完整；
- Site 结果与 Workspace 关系是否冲突。

规则：

- 只报告；
- 不写文件；
- 不自动修复；
- 普通命令不强制先运行 `check`。

完成条件：人为制造的断链和冲突能被准确定位到文件与字段。

### P7：旧版导入

实现只读导入器：

- 读取旧 Workspace/SQLite 导出；
- 生成新的 JSON 目录到指定空目录；
- Case 只作为旧路径信息，不进入新模型；
- Data 合并到对应 Run；
- 无法映射的内容写入 `migration-report.json`；
- 不修改旧 Workspace 和 Site 数据。

完成条件：至少一个真实旧项目可导入并通过 `entity check`；剩余冲突全部进入报告。

### P8：独立验收与切换

本地验收：

- 在临时 Workspace 和 fake Site 完成完整用户旅程；
- 使用 fake compiler、fake executable 和 fake Slurm；
- 确认没有写入旧 Ledger 或用户原始数据。

Kimi Code 验收：

- 从已提交分支建立独立 worktree；
- 使用独立临时 Workspace、Site、deps 和 fake Slurm；
- 不加载已安装的旧 Entity 技能；
- 只按架构文档和 CLI help 完成黑盒旅程；
- 输出问题清单和可复现步骤，不直接修改开发 worktree。

切换条件：

- 四对象完整旅程通过；
- local、Slurm、MPI 脚本矩阵通过；
- Kimi Code 未发现阻断问题；
- 旧项目导入不修改原数据；
- 用户确认后再替换旧入口。

## 5. CLI 范围

第一版只提供：

```text
entity workspace init|show
entity project init|show
entity site add|show|list
entity source add|show|list
entity pgen add|show|list
entity deps add|show|list
entity build create|prepare|run|show
entity run create|prepare|submit|status|show
entity analysis record|show
entity check
```

不提供自动工作流、自动重试、自动修复和隐式状态推进。

## 6. 测试策略

只测试稳定事实和真实故障边界：

1. 四对象引用关系；
2. Workspace/Site 路径推导；
3. JSON 读写和断链报告；
4. direct/Slurm × non-MPI/MPI 脚本矩阵；
5. Build、Run、Data、Analysis 用户旅程；
6. 旧版只读导入；
7. 原始目录不被修改。

测试约束：

- 不按函数逐个堆测试；
- 一个固定规则对应一组测试；
- 优先端到端旅程和少量边界测试；
- 第一版目标约 30–40 个高价值测试；
- 新测试必须对应一条架构规则或一个已复现故障。

## 7. 提交顺序

```text
Commit 1  架构合同与示例
Commit 2  Workspace、JSON、路径核心
Commit 3  Source、PGen
Commit 4  deps、Build、env-build 简化
Commit 5  Run、Attempt、direct/Slurm/MPI
Commit 6  Data、Analysis、check
Commit 7  旧版导入
Commit 8  Kimi Code 验收修复与报告
```

每个提交必须能够独立运行其相关测试；旧实现直到最终切换前保持不变。
