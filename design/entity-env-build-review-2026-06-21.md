# entity-env-build skill 评估

日期：2026-06-21

## 1. 总体结论

`entity-env-build` 的方向是对的。它已经不只是知识文档，而是开始形成一套 Harness：

```text
requirements.json
  -> entity-deps.local.json
  -> compatibility
  -> env.sh
  -> entity-build.sh
```

这个结构把当前构建请求、依赖状态、环境加载脚本和 Entity 编译脚本分开管理，是正确的状态模型。

但它现在还不能算成熟 Harness。主要问题不是知识不够，而是很多关键约束仍停留在文档层，脚本层没有完全强制执行。换句话说：规则写得比较清楚，但机械化门禁还不够硬。

## 2. 主要问题

### P1: compatibility checker 会 false pass

`skills/entity-env-build/scripts/check_compatibility.py` 的 `has_installed_dependency()` 只要看到 `prefix`、`cmake_config` 或 `bin` 字段非空，就认为依赖有 installed/discoverable evidence。

这会导致不存在的路径也能通过 compatibility check。

实际负向测试中，使用以下不存在路径构造 checkpoint：

```text
/tmp/does-not-exist/c++
/tmp/does-not-exist/kokkos
/tmp/does-not-exist/hdf5
/tmp/does-not-exist/adios2
```

`check_compatibility.py` 仍返回：

```json
{
  "status": "pass",
  "issues": []
}
```

这是当前最严重的问题。它直接破坏 Harness 第 5 层“评估和观测”和第 6 层“约束、校验、失败恢复”。

应改为至少检查：

- compiler path 是否存在且可执行；
- selected dependency prefix 是否存在；
- `cmake_config` 是否存在；
- `CMAKE_PREFIX_PATH` 是否包含可发现路径；
- source-build dependency 是否有已安装证据，而不是只有 generated script；
- MPI/HDF5/ADIOS2 的 serial/MPI 模式是否有真实 probe evidence。

### P1: entity-build.sh 生成器可以绕过 compatibility gate

`generate_env_sh.py` 会拒绝在 `compatibility.status != pass` 时生成 `env.sh`，这是正确的。

但 `generate_entity_build_sh.py` 只检查传入的 `env.sh` 文件是否存在，不确认：

- `env.sh` 是否由当前 `entity-deps.local.json` 生成；
- 当前 checkpoint 的 compatibility 是否仍为 `pass`；
- `requirements.json` 是否和 checkpoint 中记录的 requirements 一致；
- `env.sh` 是否 stale；
- `env.sh` 是否被手写或来自旧构建。

这会让 stale env 或手写 env 进入 Entity 编译阶段，违反 skill 自己的硬规则。

应让 `generate_entity_build_sh.py` 显式读取 checkpoint，或让 `env.sh` 中记录 checkpoint hash / requirements hash，并在生成 build script 前验证。

### P2: 最脆弱的状态构造仍主要靠模型自由发挥

当前脚本覆盖了：

- source-build script 生成；
- compatibility check；
- `env.sh` 生成；
- `entity-build.sh` 生成。

但以下关键动作仍主要靠 agent 手写或自由判断：

- 从用户请求生成 `requirements.json`；
- 探测本地 CMake/compiler/CUDA/HIP/MPI/Kokkos/HDF5/ADIOS2；
- 修复或合并旧 checkpoint；
- 记录 rejected candidates；
- 将 source-build 执行结果写回 selected dependency；
- 记录 build execution result。

这些恰恰是最容易漂移的部分。成熟 Harness 应该把这些 fragile 操作收进脚本或低自由度流程。

建议补充：

```text
scripts/generate_requirements.py
scripts/discover_dependencies.py
scripts/repair_checkpoint.py
scripts/record_dependency_install.py
scripts/run_entity_build.py
```

### P2: 版本矩阵需要绑定到可验证来源

当前 skill 把 Entity 版本和依赖 profile 写成硬规则：

```text
Entity 1.4.x and older -> C++17 + Kokkos 4.x + ADIOS2 2.10.x
Entity newer than 1.4.x -> C++20 + Kokkos 5.x + ADIOS2 2.11.x
```

这个方向可能有价值，但不能只作为静态文档常量存在。不同 Entity checkout、branch、submodule 状态或 `dependencies.py` 规则可能不同。

建议从目标 checkout 中提取或确认：

- `dependencies.py`；
- submodule commit；
- tag/branch；
- CMake defaults；
- 已验证 build matrix。

然后把 profile 写回 `requirements.json` 和 `entity-deps.local.json`，并记录证据来源。

### P2: SKILL.md 过重，progressive disclosure 还不够干净

`skills/entity-env-build/SKILL.md` 已经超过 500 行，并且与 `references/` 中的内容有重复。

对 Codex skill 来说，`SKILL.md` 应该主要保留：

- 触发条件；
- 任务边界；
- 硬规则；
- 执行轨道；
- 什么时候读取哪个 reference；
- 必须运行哪些脚本；
- 输出 contract。

详细 JSON shape、compatibility checklist、compile options、dependency source-build 细节应尽量放在 references 或脚本里。

此外，`skills/entity-env-build/README.md` 对 live skill 来说是额外入口。除非这个 repo 明确需要人类阅读说明，否则应考虑删除或移到设计文档中。

### P2: 嵌套 Git 元数据会影响 package 边界

`skills/entity-env-build/.git` 存在独立 Git 仓库元数据，并指向：

```text
https://github.com/StaticObserver/entity-env-build-skill.git
```

如果 `entity-skills` 要作为统一 skills package 管理，嵌套 `.git` 会让外层 repo 对该 skill 的追踪不透明。

应二选一：

- 明确把 `skills/entity-env-build` 做成 submodule；
- 移除嵌套 `.git`，让它成为外层 package 的普通目录。

## 3. 按 Harness 六层评估

### 3.1 上下文管理

当前状态：方向正确，但还不够机械化。

优点：

- 明确要求从当前用户请求开始；
- 使用 `requirements.json` 表示当前构建请求；
- 区分 `ENTITY_CHECKOUT` 和 `ENTITY_WORKDIR`；
- 不让旧 checkpoint 覆盖当前需求。

问题：

- `requirements.json` 仍主要靠 agent 手动生成；
- 缺 schema validator；
- 缺 requirements completeness gate；
- 缺 current request 与 checkpoint 的 hash 或 fingerprint。

改进方向：

- 增加 `generate_requirements.py` 或 schema-driven template；
- 增加 `validate_requirements.py`；
- 在 checkpoint 中记录 `requirements_hash`、`checkout_commit`、`workdir`、`target_context`。

### 3.2 工具系统

当前状态：已有工具雏形，但工具覆盖不完整。

已有工具：

- `generate_dependency_build_scripts.py`
- `check_compatibility.py`
- `generate_env_sh.py`
- `generate_entity_build_sh.py`

问题：

- 缺 dependency discovery 工具；
- 缺 checkpoint repair 工具；
- 缺 build execution wrapper；
- 工具结果没有统一 result shape；
- `check_compatibility.py` 的真实 probe 不足。

改进方向：

- 将探测、选择、修复、记录执行结果都变成脚本；
- 每个脚本输出 machine-readable JSON；
- 所有脚本都写回同一状态模型。

### 3.3 执行编排

当前状态：流程清楚，但 gate 没有全部硬化。

优点：

- 文档中有明确顺序；
- 区分 requirement phase、environment phase、Entity build phase；
- 要求 compatibility pass 后再生成 `env.sh`；
- 要求 `entity-build.sh` 从 `requirements.json + env.sh` 生成。

问题：

- `entity-build.sh` 生成没有强制读取 compatibility；
- build execution result 没有脚本托管；
- source-build 执行后如何更新 selected dependency 仍靠人工；
- 失败后的分支流程没有具体实现。

改进方向：

- 增加一个总控脚本或 playbook runner；
- 每一步只接受前一步的 validated artifact；
- 每一步失败都写入 remediation plan；
- build 执行统一由脚本记录 stdout/stderr/log/status。

### 3.4 记忆和状态

当前状态：这是当前设计最强的一层。

优点：

- `requirements.json` 作为当前请求；
- `entity-deps.local.json` 作为本地依赖 checkpoint；
- `env.sh` 和 `entity-build.sh` 都是 derived artifact；
- 明确要求不从 chat history 或 shell history 重建状态。

问题：

- state consistency 没有被脚本充分验证；
- checkpoint 是否满足当前 requirements 的判断不够深；
- `status.ready_for_entity_build` 等字段没有统一更新者；
- build result 的 pass/fail 没有实际执行 wrapper。

改进方向：

- 给每个 derived artifact 写入来源 hash；
- 增加状态迁移规则；
- 让脚本负责更新 status，而不是让 agent 手动编辑。

### 3.5 评估和观测

当前状态：短板明显。

优点：

- 有 compatibility result shape；
- 有 checks/issues；
- 有日志目录概念；
- 有基本脚本验证建议。

问题：

- compatibility checker 会 false pass；
- 没有真实 CMake package probe；
- 没有 compiler version probe；
- 没有 `bash -n env.sh` 自动验证；
- 没有 `entity-build.sh` 执行日志和结果记录脚本。

改进方向：

- compatibility check 必须从字段检查升级到 probe-based check；
- 默认运行 `cmake --find-package` 或最小 CMake probe；
- 记录每个 probe 的 command、exit code、stdout/stderr 摘要；
- build wrapper 写入 `build_result.status`、`started_at`、`finished_at`、`logs`。

### 3.6 约束、校验、失败恢复

当前状态：约束写得多，恢复机制偏弱。

优点：

- 明确禁止默认写入 source checkout；
- 明确禁止默认 Spack/Docker；
- 明确 MPI、output、CUDA nvcc_wrapper 等约束；
- source-build MPI 暂停自动生成，这是保守设计。

问题：

- 约束有些只在 prose 中；
- compatibility fail 后没有标准 remediation action；
- stale checkpoint 如何修复没有脚本；
- dependency source-build 失败后如何恢复没有流程；
- 生成器缺少对旧 artifact 的失效判断。

改进方向：

- 每个 fail check 都必须给 remediation；
- 增加 checkpoint repair；
- 增加 stale artifact detection；
- 对 source-build 失败提供 clean/retry/resume 路径；
- 对不确定项输出 user confirmation request，而不是继续猜。

## 4. 建议修复顺序

1. 修复 `check_compatibility.py` 的 false pass。
2. 让 `generate_entity_build_sh.py` 强制验证当前 checkpoint compatibility。
3. 增加 `validate_requirements.py`，至少保证 `requirements.json` 完整性。
4. 增加 dependency discovery / checkpoint repair 脚本。
5. 增加 build execution wrapper，负责执行 `entity-build.sh` 并写回结果。
6. 精简 `SKILL.md`，把重复细节移动到 references。
7. 处理 `skills/entity-env-build/.git` 的 package 边界问题。

## 5. 验证记录

已完成：

```bash
python3 -m py_compile skills/entity-env-build/scripts/*.py
```

结果：通过。

未完成：

```bash
python3 /Users/SoulDancer/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/entity-env-build
```

结果：当前 Python3 环境缺少 `yaml` 模块，未能运行 quick validate。

注意：当前 shell 中 `python` 指向 Python 2.7，运行这些 Python 3 脚本会出现语法错误。应使用 `python3`，或在 skill 文档和脚本示例中统一写 `python3`。

## 6. 外部依据

Entity 官方 wiki 当前说明：

- 编译需要 CMake、C++ compiler，CUDA/HIP/MPI 视需求启用；
- Kokkos 和 ADIOS2 可随代码 in-tree 构建，但 ADIOS2 外部安装通常更快；
- 系统已有 MPI/HDF5 时，官方建议优先复用；
- `dependencies.py` 是官方推荐的依赖脚本生成入口；
- Entity 编译使用 `cmake -B build -D pgen=<...>`，布尔选项使用 `ON/OFF`；
- `pgen`、`pgens`、`precision`、`deposit`、`shape_order`、`output`、`mpi`、`gpu_aware_mpi`、`DEBUG`、`TESTS` 是官方页面列出的主要编译选项。

因此，`entity-env-build` 当前“local/system reuse first、source-build last resort、requirements/checkpoint/env/build-script 分层”的方向合理，但版本 profile 和 compatibility pass 必须从目标 checkout 与实际 probe 中得到证据。
