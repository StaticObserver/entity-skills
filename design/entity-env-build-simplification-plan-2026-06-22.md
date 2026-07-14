# entity-env-build Optimization Plan

日期：2026-06-22

依据：`design/entity-env-build-harness-review-2026-06-22.md`

目标：把 `entity-env-build` 从“已经可用但控制面偏宽的 Harness 原型”收束成“小而硬、简洁优雅、可恢复”的 build harness。优化重点不是继续堆新能力，而是减少分支、统一状态、让主链路更可信。

## 1. 当前基线

当前已经稳定下来的主链路是：

```text
requirements.json
  -> entity-deps.local.json
  -> entity_compat.py
  -> env.sh
  -> entity-build.sh
  -> entity_run.py build result
```

已完成且应保留：

- `entity_checkpoint.py validate` 默认阻塞 invalid/partial requirements。
- `entity_generate.py env/build` 默认只接受 `compatibility.status=pass`。
- `entity_checkpoint.py record-install` 已能结构化记录依赖安装证据。
- `entity_run.py build` 已能执行生成脚本并写回 `requirements.json.build_result`。
- `tests/test_hard_gates.py` 已覆盖 hard gates、warn gate、stale env、record-install、requirements drift、runner 成功/失败。

当前真正需要优化的不是再补更多边角功能，而是：

- `SKILL.md` 偏重，主流程和长诊断材料混在一起。
- `.entity-session.json` 的位置和初始化方式不统一。
- session/log/compat archive/site notes helper 存在，但没有形成简洁状态模型。
- source-build sub-agent 权限描述和实际构建动作矛盾。
- compat pass 的覆盖范围还没有被显式建模。
- cluster configure/build policy 需要更精确，但不能扩成远程编排框架。

## 2. 设计原则

### 2.1 先减法，再硬化

不要用“每个问题一个补丁”的方式演进。后续任何改动都必须满足至少一个条件：

- 删除一个概念分支；
- 统一一类状态迁移；
- 把人工判断变成确定性 artifact；
- 让 `pass/fail` 的含义更可信。

不满足这些条件的功能，暂缓。

### 2.2 主链路只有少数核心 artifact

核心 artifact 限定为：

```text
requirements.json
entity-deps.local.json
env.sh
entity-build.sh
requirements.json.build_result
```

辅助 artifact 可以存在，但不进入完成条件：

```text
.entity-session.json
~/.entity-env-build/run.log
~/.entity-env-build/compat/<run_id>.json
~/.entity-env-build/site-notes/<hostname>.md
```

只有当辅助 artifact 由统一状态层维护后，才允许进入 hard requirement。

### 2.3 少数入口，统一状态

保留少数核心入口：

```text
entity_checkpoint.py validate/create/record-install
entity_compat.py
entity_generate.py deps/env/build
entity_run.py build
```

不要给每个脚本临时加一套 session/log/report 逻辑。需要状态时，先抽一个小的共享状态转移层。

## 3. 目标形态

目标不是大型 orchestrator，而是一条清楚的最小流水线：

```text
validate requirements
  -> create/update checkpoint
  -> check compatibility
  -> generate env
  -> generate build script
  -> run build
  -> record result
```

每一步都应满足：

- 输入是前一步的 validated artifact；
- 输出是确定性文件或结构化 JSON 字段；
- 失败时返回非零退出码；
- 用户/Agent 能从 artifact 看出下一步是什么。

## 4. Phase Plan

## Phase 0: 文档减法和边界收束

目标：先降低 Agent 入口复杂度，不改主代码。

修改：

1. 精简 `SKILL.md` 主体，只保留：
   - mission；
   - boundaries；
   - hard rules；
   - minimal phase workflow；
   - 每步运行哪个脚本；
   - completion criteria；
   - reference routing。

2. 下沉或降级：
   - long failure diagnosis -> references；
   - network-unavailable scenarios -> references；
   - remote/sub-agent prompt details -> references；
   - site-notes 自动维护 -> optional；
   - compat archive -> optional；
   - session state -> optional until ownership is fixed。

3. README/CLAUDE 只保留入口索引，不复述独立 policy。

验收：

- `SKILL.md` 主流程能在 150-220 行内读完。
- `SKILL.md` 不再要求运行当前不可直接运行的 `python3 -c` session 初始化片段。
- 未脚本托管的能力不再写成 hard requirement。

## Phase 1: 统一 artifact ownership

目标：解决 `.entity-session.json` 和 artifact 路径的边界混乱。

决策：

优先采用 pgen/build-run 级 session：

```text
$PGEN_DIR/_build/.entity-session.json
```

理由：

- 一次 Entity build 实际绑定一个 pgen/backend/dependency set。
- `requirements.json`、`entity-deps.local.json`、`env.sh`、`entity-build.sh` 都在 `_build/` 下最自然。
- root-level session 容易混入多 pgen 状态，恢复边界不清。

修改：

- `references/json-contracts.md` 明确 artifact ownership。
- `SKILL.md` 示例统一指向 `$PGEN_DIR/_build/`。
- 如保留 root-level `$ENTITY_WORKDIR/.entity-session.json`，只能作为 workspace index，不作为 build-run state。

验收：

- 文档中只出现一种 build-run session 位置。
- 所有 artifact path examples 与 `entity_generate.py` 的默认路径一致。
- 恢复说明不依赖聊天记录。

## Phase 2: 抽最小状态转移层

目标：避免到处给 CLI 打补丁，用一个小接口统一记录主链路进度。

新增或重构：

```text
scripts/entity_state.py
```

建议接口：

```python
record_step(artifacts_dir, step, status, inputs=None, outputs=None, run_id=None, message="")
load_state(artifacts_dir)
```

只记录主链路关键状态：

```text
requirements_validated
checkpoint_updated
compatibility_checked
env_generated
build_script_generated
build_executed
```

不要第一版就接入 site-notes、remote、multi-machine memory。

接入顺序：

1. `entity_checkpoint.py validate/create/record-install`
2. `entity_compat.py`
3. `entity_generate.py env/build`
4. `entity_run.py build`
5. `entity_generate.py deps`

验收：

- 每个主链路 CLI 成功后，`.entity-session.json` 有对应 step。
- 失败不破坏已有 state。
- 测试只验证少数 step，不复制每个脚本的内部细节。

## Phase 3: 修正 sub-agent contract

目标：让 source-build 子代理 contract 与实际写入行为一致。

修改：

- 将 `Read only — no write access` 改为：
  - 可以写入指定 build tree、install prefix、log dir；
  - 禁止修改 `requirements.json`；
  - 禁止修改 `entity-deps.local.json`；
  - 只能返回结构化 result。
- `SKILL.md` 和 source-build prompt 都写明允许写入目录。
- 主 Agent 只通过 `entity_checkpoint.py record-install` 写回 checkpoint。

验收：

- 文档不再出现“执行 build script”与“no write access”矛盾。
- source-build result handoff 的唯一 checkpoint 写入口是 `record-install`。

## Phase 4: 明确 compatibility coverage

目标：让 `compatibility.status=pass` 的含义和实现范围一致。

修改：

`entity_compat.py` 输出增加 coverage metadata：

```json
{
  "compatibility": {
    "status": "pass",
    "checker_version": 1,
    "coverage": {
      "requirements_checkpoint_match": "implemented",
      "dependency_path_existence": "implemented",
      "compiler_signature": "partial",
      "path_list_existence": "not_implemented",
      "cmake_package_probe": "not_implemented",
      "mpi_output_mode": "partial"
    }
  }
}
```

规则：

- `not_implemented` 不能悄悄算进完整 pass contract。
- 如果某项是当前 build 必需但尚未实现，应给 `warn` 或 `fail`，由默认 gate 阻塞。
- coverage 是解释 pass 可信度的手段，不是增加新放行路径。

优先补齐检查：

1. compiler signature：realpath、family、version、wrapper relation。
2. `PATH` / `CMAKE_PREFIX_PATH` / `LD_LIBRARY_PATH` existence。
3. `cmake_config` 所属 prefix 是否进入 `CMAKE_PREFIX_PATH`。
4. 最小 CMake package probe。
5. MPI on/off 与 ADIOS2/HDF5 serial/MPI mode consistency。

验收：

- coverage metadata 出现在 compat result 中。
- 未覆盖 required check 不会被误认为完整 pass。
- 现有 hard gate tests 继续通过。

## Phase 5: 精确化 cluster policy，不扩成 remote framework

目标：解决 login node / compute node 规则歧义，但保持实现轻量。

文档拆分四类动作：

| 动作 | login node | compute node | 说明 |
| --- | --- | --- | --- |
| download/materialize | 可允许 | 可允许 | 取决于网络；记录来源 |
| configure | 可在特定条件下允许 | 推荐 | GPU/tool-linked configure 需谨慎 |
| compile/link | 默认禁止 | 推荐/必须 | cluster 上默认走 scheduler |
| run/test | 默认禁止 | 推荐/必须 | 依赖 GPU/MPI runtime |

第一版只做文档和 build-plan 字段，不做自动 scheduler abstraction。

可选 artifact：

```json
{
  "execution_plan": {
    "configure_context": "login|compute",
    "build_context": "compute",
    "scheduler": "slurm|pbs|manual",
    "notes": []
  }
}
```

验收：

- `SKILL.md` 不再同时给出含糊的 “NEVER compile on login nodes” 和未定义的 login configure 例外。
- 不引入自动远程执行框架。

## Phase 6: 清理 prompt 和 remote 语义

目标：让独立验证真的验证当前 artifact。

修改：

- compat sub-agent prompt 以文件路径和 hash 为主。
- 内联 JSON 只作为摘要，不作为验证对象。
- remote prompt 标注 experimental。
- 远程验证要求脚本版本一致：同一 commit/hash，或显式上传本次 scripts。

验收：

- prompt 不再写 “no file reads needed”。
- sub-agent verdict 记录 requirements/checkpoint hash。
- remote 不是主链路完成条件。

## 5. 最小测试矩阵

每次代码优化至少运行：

```bash
python3 -m py_compile scripts/*.py
python3 -m unittest tests/test_hard_gates.py
```

新增测试按阶段补，不一次铺满：

| Phase | Test | Expected |
| --- | --- | --- |
| Phase 1 | artifact/session path examples align with generated defaults | no duplicate build-run state location |
| Phase 2 | CLI success records one state step | `.entity-session.json` updated |
| Phase 2 | CLI failure does not erase prior state | previous state preserved |
| Phase 3 | source-build contract forbids JSON writes but allows build dir writes | docs/prompt consistent |
| Phase 4 | compat result includes coverage metadata | coverage keys present |
| Phase 4 | missing required path list entry | fail or blocking warn |
| Phase 4 | compiler same class but different version/path | warn/fail unless accepted |
| Phase 5 | cluster plan separates configure/build context | execution_plan explicit |
| Phase 6 | compat prompt includes file hashes | no stale inline-only validation |

## 6. 推荐执行顺序

按收益和复杂度排序：

1. Phase 0：文档减法。先把 hard requirement 和 optional note 分开。
2. Phase 1：统一 artifact ownership。这个不做，状态层会继续混乱。
3. Phase 3：修 source-build sub-agent contract。成本低，能消除直接矛盾。
4. Phase 6：修 compat prompt fresh-read 语义。成本低，提升验证可信度。
5. Phase 4：增加 compatibility coverage metadata，再逐步补高价值检查。
6. Phase 2：抽最小状态转移层。等 artifact ownership 稳定后再接主 CLI。
7. Phase 5：精确化 cluster policy。先文档化，不做远程框架。

注意：Phase 2 不应变成大 orchestrator。它只是统一记录主链路状态，不负责替 Agent 做所有决策。

## 7. 暂缓事项

短期不做：

- 自动 dependency discovery 全覆盖；
- 自动 remote build orchestration；
- 自动 scheduler submission abstraction；
- 多 sub-agent 并行构建；
- site-notes 自动归纳；
- 完整 machine memory database；
- GUI/dashboard；
- 大型 `entity_env_build.py run-all` 总控命令。

这些都可能有价值，但会把项目重新推向复杂控制面。当前目标是让最小主链路稳定可信。

## 8. 完成标准

优化完成后，应能回答三个问题：

1. 如果某个 CLI 返回 success，下一步是否真的可以信任它的输出 artifact？
2. 如果失败，是否能从 JSON/state/log 看出失败在哪一步，而不是回聊天记录里找？
3. 如果 Agent 中断，是否能从 `_build/` 下的 artifact chain 恢复？

如果答案都是“是”，这个 skill 就已经足够好。后续优化应以删除复杂度为优先，而不是扩大功能面。
