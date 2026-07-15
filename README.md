# Entity Skills Package

一套帮助 Agent 使用 [Entity](https://github.com/entity-toolkit/entity) 完成天体物理模拟的 skills package。

`skills/entity-router/SKILL.md` 是受管 simulation 工作流的控制入口。需要 Case 状态、跨领域交接、构建运行、恢复或持续追踪时，由 Router 选择 playbook 并按需调用三个同级子 skill。边界明确的领域任务可以直接调用对应 skill；一旦目标属于受管 Case，修改操作必须持有 Router Action Contract。

- `entity-pgen`：PGen、匹配 TOML 和设计记录；
- `entity-env-build`：依赖环境与 Entity 编译；
- `entity-nt2py`：nt2py 数据访问、绘图和导出。

Simulation 的准备、运行、续跑和状态恢复由 Router 按自身 `playbooks/` 管理，不单独建立 run skill。

初版 Router 将专业工作和 Router-owned run 操作放入 Case-bound Worker；Router 只保留控制上下文。`skills/entity-router/scripts/entity_router_state.py` 负责 Case、Workflow、Action Contract、revision、事件和 stale 状态。

```text
entity-skills/
├── skills/
│   ├── entity-router/
│   │   ├── SKILL.md
│   │   ├── agents/
│   │   ├── scripts/
│   │   ├── references/
│   │   ├── playbooks/
│   │   └── templates/
│   ├── entity-pgen/
│   ├── entity-env-build/
│   └── entity-nt2py/
├── tests/
├── tools/skill_observability/
├── design/
└── legacy/
```

当前整体设计见 `design/architecture.md`，workspace 和状态细节见 `design/workspace-and-state.md`，skill 执行观测和日志合同见 `design/skill-observability.md`。`design/` 和 `legacy/` 不属于 Router 运行时上下文。

`entity-pgen` 的直接调用分为只读和 standalone 修改。它在写入前必须运行自身的 preflight；preflight 查询 Router registry 和 Locator envelope，注册源码只有当前有效、site 匹配的 `pgen.*` Action 才允许修改。Router 控制状态位于独立 control root，不依赖源码祖先目录中的 `_case/` 标记。

## 仓库与发布

四个 skill 由本仓库统一开发、测试和发布。`skills/` 下不使用嵌套 Git 仓库或 submodule；跨 skill 的契约修改应在同一个分支和 pull request 中完成。

- `main` 保存可用的整包状态；
- 开发使用短期分支，不为单个 skill 维护长期分支；
- release tag（例如 `v0.1.0`）固定一组经过联合验证的四个 skill；
- 旧的单 skill 仓库只保留历史，不再作为开发或发布入口。

详细协作约定见 `CONTRIBUTING.md`。

## Skill 运行观测

`tools/skill_observability/skill_observer.py` 提供平台无关的 append-only
trace。它记录 skill 身份、关键决策、工具调用、artifact 和外部验证，
不记录隐藏思维链，也不回写 Router 或 owner 状态。

创建 run 时必须传入任务、Agent/tool 配置指纹和实际暴露的 skill。
Entity source、Router Case 和 raw data root 通过 `--protected-root` 显式保护；
skill source 会自动加入保护列表。

```bash
python3 tools/skill_observability/skill_observer.py start \
  --task-id <task-id> \
  --input-ref <task-ref> \
  --input-sha256 <task-sha256> \
  --variant full \
  --agent-provider <provider> \
  --agent-model <model> \
  --agent-configuration <agent-config-sha256> \
  --tool-profile <tool-profile> \
  --tool-configuration <tool-config-sha256> \
  --skill skills/entity-router \
  --skill skills/entity-pgen \
  --protected-root /absolute/entity-source \
  --protected-root /absolute/router-case \
  --protected-root /absolute/raw-data
```

使用返回的 `<run-dir>` 包装命令，小型 JSON 输出可作为脱敏证据保存：

```bash
python3 tools/skill_observability/skill_observer.py tool \
  --run-dir <run-dir> \
  --name pgen-preflight \
  --capture-json \
  --capture-json-name pgen-preflight \
  --capture-authority entity-pgen-preflight \
  -- python3 skills/entity-pgen/scripts/pgen_preflight.py <arguments>

python3 tools/skill_observability/skill_observer.py evidence pgen-preflight \
  --run-dir <run-dir> \
  --result <run-dir>/evidence/pgen-preflight.json \
  --expect allowed \
  --action-request /absolute/router-case/actions/<action-id>/request.json

python3 tools/skill_observability/skill_observer.py finish \
  --run-dir <run-dir> --status completed

python3 tools/skill_observability/skill_observer.py validate \
  --run-dir <run-dir>
```

`evidence` 同时支持 `router-action`、`env-build` 和 `nt2py-inventory`。
完整协议与证据等级见 `design/skill-observability.md`。

已有 Codex rollout 可增量导入。adapter 只保留 tool call/output 的 hash、大小、
顺序和关联 ID，显式忽略对话文本、reasoning 和 encrypted reasoning，
并排除 observer 自身调用：

```bash
python3 tools/skill_observability/skill_observer.py import-codex \
  --run-dir <run-dir> \
  --rollout /absolute/path/to/codex-rollout.jsonl
```

本地验证：

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s skills/entity-pgen/tests -v
python3 -m unittest discover -s skills/entity-env-build/tests -v
python3 -m py_compile \
  tools/skill_observability/*.py \
  tools/skill_observability/adapters/*.py
```
