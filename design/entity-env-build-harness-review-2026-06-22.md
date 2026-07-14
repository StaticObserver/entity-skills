# entity-env-build Harness Review

日期：2026-06-22

审查范围：`skills/entity-env-build/` 当前 live skill surface，包括 `SKILL.md`、`README.md`、`CLAUDE.md`、`scripts/`、`references/`、`tests/`。外层 `test-wtih-cc/` 只作为实践记录背景，不作为共享 skill 本体。

## 总体判断

`entity-env-build` 已经是一个可用的 build harness，而不是单纯知识型 skill。它的核心链路清楚：

```text
requirements.json
  -> entity-deps.local.json
  -> compatibility
  -> env.sh
  -> entity-build.sh
  -> entity_run.py build result
```

和 2026-06-21 版本相比，当前版本已经修掉了几个早期硬伤：

- `entity_checkpoint.py validate` 默认阻塞 `partial`，只有 `--allow-partial` 才退出 0。
- `entity_generate.py env/build` 默认只接受 `compatibility.status=pass`；`warn` 需要 `--allow-warnings` 加结构化用户确认。
- `entity_checkpoint.py record-install` 已存在，会验证真实路径并使 compatibility 失效。
- `entity_run.py build` 已存在，会托管执行生成脚本并写回 `requirements.json.build_result`。
- 测试覆盖了 hard gates、warn gate、stale env gate、record-install、requirements snapshot drift、build runner 成功/失败记录。

因此，当前主要问题已经不是“没有工具”或“硬门禁完全失效”，而是成熟 Harness 的闭环仍没有完全机械化：状态初始化路径不统一，session/compat/site notes helper 没有接入大多数 CLI，部分文档承诺仍超过脚本实际能力，远程/子代理编排 contract 存在矛盾。

## 设计原则补充：不要到处打补丁

后续优化不应变成“每发现一个洞，就给某个脚本加一个特例”。这会让 skill 越修越复杂，最后 Agent 看到的是一堆分支、flag 和例外，而不是一条可靠轨道。

更好的方向是：

- 少数核心 artifact：`requirements.json`、`entity-deps.local.json`、`env.sh`、`entity-build.sh`、`build_result`。
- 少数核心入口：validate、checkpoint/update、compat、generate、run。
- 一个统一状态转移函数，而不是在每个脚本里手写一份 session/log 更新逻辑。
- 文档只描述真实存在的执行路径；暂时没有脚本托管的能力，降级为 optional note，不写成 hard requirement。
- 修复优先减少概念和分支，而不是增加新命令、新 flag、新特殊情况。

换句话说，目标不是把所有 helper 都接到所有地方，而是把主链路收束到“短、硬、可验证”。优雅的 Harness 应该让 Agent 少判断，而不是让 Agent 学会更多补丁规则。

## P1 Findings

### P1.1 Session 初始化示例不可直接运行，且状态文件位置与 artifact layout 冲突

位置：

- `skills/entity-env-build/SKILL.md:130-139`
- `skills/entity-env-build/SKILL.md:141-153`
- `skills/entity-env-build/scripts/_json_io.py:247-284`

问题：

`SKILL.md` 要求确认路径后初始化 session state：

```bash
python3 -c "
from _json_io import init_session_state
init_session_state(Path('$ENTITY_WORKDIR'))
"
```

这个片段有两个直接问题：

- 从 skill 根目录运行时，`_json_io.py` 位于 `scripts/` 下，不在默认 import path。
- 即使设置 `PYTHONPATH=scripts`，片段也没有 `from pathlib import Path`，会 `NameError`。

本次探针：

```bash
ENTITY_WORKDIR="$tmp" python3 -c "from _json_io import init_session_state; init_session_state(Path('$tmp'))"
```

结果：`ModuleNotFoundError: No module named '_json_io'`。

```bash
ENTITY_WORKDIR="$tmp" PYTHONPATH=scripts python3 -c "from _json_io import init_session_state; init_session_state(Path('$tmp'))"
```

结果：`NameError: name 'Path' is not defined`。

即使修正 import：

```bash
PYTHONPATH=scripts python3 -c "from pathlib import Path; from _json_io import init_session_state; init_session_state(Path('$tmp'))"
```

实际写入的是：

```text
$ENTITY_WORKDIR/.entity-session.json
```

但 `SKILL.md` 的默认 artifact layout 又把 `.entity-session.json` 放在 pgen 级别：

```text
$PGEN_DIR/_build/.entity-session.json
```

Harness 影响：

这是第 4 层“记忆和状态”的入口。入口命令不能运行，会让 Agent 回退到聊天上下文；状态文件位置不统一，会导致恢复时不知道以 root session 还是 pgen session 为准。

建议：

- 增加正式 CLI，例如 `scripts/entity_checkpoint.py session-init --workdir ... --artifacts-dir ...` 或 `scripts/entity_session.py init`。
- 明确 session state 归属：如果一次 build 绑定一个 pgen，应放在 `$PGEN_DIR/_build/.entity-session.json`；如果 root 级 session 负责多 pgen，应把 pgen/build artifact path 明确记录进去。
- 所有文档示例都改为可直接运行的脚本命令，不使用裸 `python3 -c` 导入内部模块。

### P1.2 Dependency source-build sub-agent 权限 contract 自相矛盾

位置：

- `skills/entity-env-build/SKILL.md:402-453`
- `skills/entity-env-build/scripts/entity_generate.py:183-481`

问题：

`SKILL.md` 要求 source-build sub-agent 执行生成的 dependency build script，并返回 `prefix/cmake_config/version/compiler_signature/issues[]`。但同一段又写：

```text
Sub-agent permissions: Bash(bash build-<dep>.sh) and Read only — no write access.
```

dependency build script 的目的就是写 build tree、install prefix、logs。真正应该禁止的是“手改 JSON”，不是禁止所有写操作。

Harness 影响：

这是第 2 层“工具系统”和第 3 层“执行编排”的 contract 错误。按字面执行会导致子代理无法完成构建；放宽执行又会违反文档里的权限约束。Agent 在高风险 HPC 环境里会不知道该按哪条规则行动。

建议：

- 将权限改成：允许写入受限的 build/install/log 目录；禁止修改 `requirements.json` 和 `entity-deps.local.json`。
- 生成 build script 时把允许写入目录写入 prompt 和 script header。
- 子代理输出必须只通过 `entity_checkpoint.py record-install` 落入 checkpoint。

## P2 Findings

### P2.1 Session state、compat report、site notes helper 仍没有接入主 CLI 闭环

位置：

- `skills/entity-env-build/scripts/_json_io.py:149-189`
- `skills/entity-env-build/scripts/_json_io.py:247-348`
- `skills/entity-env-build/scripts/entity_checkpoint.py:142-167`
- `skills/entity-env-build/scripts/entity_checkpoint.py:333-407`
- `skills/entity-env-build/scripts/entity_compat.py:1069-1115`
- `skills/entity-env-build/scripts/entity_generate.py`
- `skills/entity-env-build/scripts/entity_run.py:45-122`

已实现：

- `_json_io.py` 有 `log_event()`、`save_compat_report()`、`init_session_state()`、`update_session_state()`、site-notes helper。
- `entity_run.py build` 会调用 `ensure_harness_home()` 和 `log_event()`，并写回 build result。

缺口：

- `entity_checkpoint.py validate/create/record-install` 不更新 `.entity-session.json`。
- `entity_compat.py` 不调用 `save_compat_report()`，也没有 `--run-id` / `--save-report`。
- `entity_generate.py env/build/deps` 不调用 `update_session_state()`，也不写 run log。
- site notes 仍靠 Agent prose 更新，不是脚本托管的结构化动作。

Harness 影响：

目前状态层是“可用零件”，不是执行轨道。任务中断后，Agent 仍可能依赖聊天记录判断走到哪一步；compat 证据也不一定有可追溯的独立报告。

建议：

- 不要给每个 CLI 分散打补丁。先定义一个最小 `run_context` / `state_transition` helper，由少数入口统一调用。
- 主链路只需要记录关键状态：requirements valid、checkpoint updated、compat checked、env generated、build script generated、build executed。
- `compat` report 是否归档应作为该统一状态转移的一部分，而不是在 `entity_compat.py` 旁边再长出一套独立逻辑。
- site notes 先降级为 optional reference；等主链路稳定后，再用一个结构化 append 工具接入。

### P2.2 Compatibility `pass` 仍小于文档承诺的 pass

位置：

- `skills/entity-env-build/references/compatibility-check.md:70-181`
- `skills/entity-env-build/scripts/entity_compat.py:96-157`
- `skills/entity-env-build/scripts/entity_compat.py:297-379`
- `skills/entity-env-build/scripts/entity_compat.py:1000-1066`

已改善：

`entity_compat.py` 已验证 schema version、requirements snapshot drift、compiler path、dependency path、部分 version profile、ADIOS2/Kokkos/CUDA 冲突、source-build install evidence，并会更新 checkpoint status。

仍缺口：

- Compiler consistency 主要按 basename/toolchain class 判断；同类不同路径/版本的 host compiler 仍可能被视为 pass。
- `paths.PATH`、`CMAKE_PREFIX_PATH`、`LD_LIBRARY_PATH` 条目存在性没有系统校验。
- 最小 CMake package probe 还没有实现。
- MPI wrapper output、ADIOS2/HDF5 serial-vs-MPI mode consistency 没有机械化验证。
- GPU architecture 与 Kokkos enabled arch 的匹配仍不完整。
- `compatibility-check.md` 标注了多个 Partial，但生成器只看最终 `pass`，不知道 pass 的覆盖范围。

Harness 影响：

这是第 5 层“评估和观测”的可信度问题。当前 `pass` 表示“通过已实现检查”，还不是“满足完整文档 contract”。对 HPC build 来说，这会把未覆盖风险伪装成可交付状态。

建议：

- 在 compatibility result 中增加 `coverage` / `implemented_checks_version` / `unimplemented_required_checks`。
- 对文档中仍为 Partial 的 required checks，要么实现，要么在 result 中明确降级为 `warn`。
- 优先实现 compiler signature、path list existence、CMake package probe、MPI/output mode consistency。

### P2.3 远程 compat prompt 和 SKILL.md 的 fresh-read 语义冲突

位置：

- `skills/entity-env-build/SKILL.md:455-487`
- `skills/entity-env-build/scripts/entity_generate.py:761-808`

问题：

`SKILL.md` 要求 compat sub-agent：

```text
Read both files from scratch.
```

但 `_compat_prompt()` 生成的 prompt 写的是：

```text
Read BOTH JSONs above — they are already in your context, no file reads needed.
```

远程示例还写了占位路径：

```text
ssh <remote> 'python3 /path/to/scripts/entity_compat.py ...'
```

没有把 skill scripts 的同步/定位方式作为输入。

Harness 影响：

独立 compat sub-agent 的价值在于从磁盘证据重新读取，而不是复用主 Agent 内联的旧快照。否则当文件在 prompt 生成后被修改，sub-agent 验证的就不是当前 artifact。

建议：

- compat prompt 以文件路径和 hash 为主；内联 JSON 只作为摘要。
- sub-agent verdict 必须记录 `requirements.json` 和 checkpoint 的 hash。
- 远程模式必须明确 scripts 如何同步，或要求远程已有相同 commit/hash 的 skill scripts。

### P2.4 Cluster policy 对 configure/build 的边界还不够精确

位置：

- `skills/entity-env-build/SKILL.md:65`
- `skills/entity-env-build/SKILL.md:525-533`
- `skills/entity-env-build/SKILL.md:579-582`

问题：

硬规则写着 cluster 上 “NEVER compile on login nodes”，并要求展示 login-vs-compute difference table；但当前 `SKILL.md` 中没有这个 table。后文又建议 Entity 的 `plog` FetchContent 场景：

```text
Run cmake configure on a login node (with internet) first
```

这可能是合理策略，但需要区分：

- dependency configure；
- Entity configure；
- actual compilation/linking；
- FetchContent download/materialization；
- GPU-tool-linked tools 是否会在 configure 阶段触发。

Harness 影响：

这是第 6 层“约束、校验、失败恢复”的规则歧义。Agent 可能过度保守而无法利用 login-node 网络，也可能误把 configure 当成允许的 build 操作。

建议：

- 把 cluster execution policy 拆成 `download/materialize`, `configure`, `compile/link`, `run/test` 四类动作。
- 补上文档里承诺的 login-vs-compute difference table。
- 让生成器支持 split execution plan：login-node configure only + compute-node build，且记录到 requirements/build plan。

## P3 Findings

### P3.1 SKILL.md 仍然偏重，入口规则和诊断手册混在一起

位置：

- `skills/entity-env-build/SKILL.md`
- `skills/entity-env-build/references/*`

问题：

`SKILL.md` 既包含任务边界、硬规则、三阶段流程，也包含故障树、网络失败策略、site notes 维护细节、cluster 特例、output contract。它可读，但作为 Agent 入口仍偏重。

建议：

- `SKILL.md` 保留触发条件、不可违反门禁、phase runner 顺序、状态转移表。
- 故障树、cluster policy、network fallback、dependency notes 继续下沉到 references。
- 每个 phase 应尽量以“必须运行哪个 CLI、期望写出哪个 artifact、什么状态允许继续”为中心。

### P3.2 README/CLAUDE 与 live scripts 仍有轻微 policy 依赖

位置：

- `skills/entity-env-build/README.md`
- `skills/entity-env-build/CLAUDE.md`
- `skills/entity-env-build/SKILL.md`
- `skills/entity-env-build/scripts/entity_schema.py`

问题：

README 和 CLAUDE 已经更新到提及 `record-install`、`entity_run.py`、strict gate，但它们仍复述了较多 policy。只要 `SKILL.md` 或 `entity_schema.py` 再变化，这些摘要容易再次漂移。

建议：

- 明确 policy source of truth：`SKILL.md` 负责流程和硬规则；`entity_schema.py` 负责 schema/default/profile；references 负责扩展说明。
- README/CLAUDE 尽量只保留短入口和命令索引。

## Harness 六层评分

| 层 | 当前状态 | 评分 | 说明 |
| --- | --- | --- | --- |
| 上下文管理 | 较强 | 7/10 | `requirements.json` 作为当前请求边界是正确方向；但 session 位置和初始化示例仍会污染恢复边界。 |
| 工具系统 | 较强 | 8/10 | checkpoint、compat、generate、run、record-install 都已成形；缺 session/site-notes/compat-report 的统一 CLI 接入。 |
| 执行编排 | 中等偏强 | 7/10 | 三阶段和 hard gates 清楚，测试覆盖关键门禁；cluster split execution 和 sub-agent contract 仍不够硬。 |
| 记忆和状态 | 中等 | 6/10 | JSON artifact chain 正确，helper 已有；session state 未成为每个 CLI 的事实来源。 |
| 评估和观测 | 中等偏强 | 7/10 | negative gates 和 runner 测试显著增强；compat pass coverage 仍需显式建模。 |
| 约束、校验、失败恢复 | 中等 | 6/10 | `record-install`、runner、warn gate 已改善；远程验证、site notes、cluster recovery 仍靠 prose。 |

总体：`6.8/10`。当前 skill 已经越过“文档型 skill”阶段，进入可执行 Harness 原型；离成熟 Harness 的差距主要在状态闭环、验证覆盖声明、远程/子代理 contract 和集群执行策略机械化。

## 建议修复顺序

1. 先做减法：把 `SKILL.md` 主流程压回一条最小闭环，未脚本化的 session/site-notes/remote 能力降级为 optional。
2. 统一 artifact ownership：明确 `.entity-session.json` 到底属于 root run 还是 pgen `_build/`，不要两套位置并存。
3. 抽一个小的状态转移层，而不是在每个脚本里分散补 `update_session_state()`、`log_event()`、`save_compat_report()`。
4. 修改 source-build sub-agent 权限描述：允许限定目录写入，禁止 JSON 写入。
5. 重写 compat sub-agent prompt：以文件路径/hash 为证据，不以内联 JSON 作为 fresh-read 输入。
6. 在 compatibility result 中加入 coverage/implemented checks；未实现 required checks 要么实现，要么显式降级。
7. 只补最影响 pass 可信度的检查：compiler signature、path list existence、CMake package probe、MPI/output mode consistency。
8. 拆分 cluster policy，但不要引入复杂远程框架；先把 login configure / compute build 的最小 plan 说清楚。

## 本次验证

已运行：

```bash
python3 -m py_compile scripts/*.py
python3 -m unittest tests/test_hard_gates.py
```

结果：通过，`12` 个测试全部通过。

已运行状态初始化负向探针：

- 文档原始片段从 skill root 运行失败：`ModuleNotFoundError: No module named '_json_io'`。
- 加 `PYTHONPATH=scripts` 后仍失败：`NameError: name 'Path' is not defined`。
- 修正 import 后实际写入 `$ENTITY_WORKDIR/.entity-session.json`，与文档里的 pgen `_build/.entity-session.json` layout 不一致。
