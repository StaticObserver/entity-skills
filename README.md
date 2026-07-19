# Entity Skills Package

一套帮助 Agent 使用 [Entity](https://github.com/entity-toolkit/entity) 完成天体物理模拟的 skills package。

`skills/entity-router/SKILL.md` 是受管 simulation 工作流的控制入口。Router v5
把公共模型收敛为 `Project → Goal → Operation → Evidence`：主 Agent 只提供用户语义，
程序派生 Case/Operation ID、路径、hash、Locator、claim、Step 和恢复状态。边界明确的
只读或 standalone 领域任务仍可直接调用对应 owner skill。

- `entity-pgen`：PGen、匹配 TOML 和设计记录；
- `entity-env-build`：依赖环境与 Entity 编译；
- `entity-nt2py`：nt2py 数据访问、绘图和导出。

Simulation run 的计划、提交、续接和状态恢复统一由 `entityctl.py plan/apply/status`
管理，不单独建立 run skill。SQLite `router.db` 是唯一结构化 controller authority；
Local 与 SSH 使用同一个内容寻址 executor 和同一份 StepSpec。旧 Case v3、Action 和
deterministic flow 只保留为一次性迁移及历史恢复材料。

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

当前实施合同见 `design/router-v5-goal-operation-architecture.md`；改造前基线见
`design/current-entity-router-architecture-2026-07-19.md`。`architecture-v4.md`、
`architecture.md` 和 `model-efficient-router-flow.md` 是历史设计，不代表当前公共入口。
skill 执行观测合同见 `design/skill-observability.md`。`design/` 和 `legacy/` 不属于
Router 运行时上下文。

## 公共控制状态

Codex、Claude Code、Kimi Code 和普通 shell 默认共享控制机上的
`~/.entity-router/router.db`。Operation、identity、事件和 evidence reference 不写入
客户端私有目录或源码仓库。远端不可用时仍可读取最后一次控制快照，但缓存 evidence
不代表当前远端事实。

```bash
python3 skills/entity-router/scripts/entityctl.py doctor
python3 skills/entity-router/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  install --source-root /path/to/entity-skills/skills
python3 skills/entity-router/scripts/entityctl.py migrate --from-v3 --dry-run
python3 skills/entity-router/scripts/entityctl.py migrate --from-v3
python3 skills/entity-router/scripts/entityctl.py plan \
  --project-root /absolute/project --goal goal.json --output plan.json
python3 skills/entity-router/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  apply --plan plan.json
python3 skills/entity-router/scripts/entityctl.py status \
  --project-root /absolute/project --live
```

`plan` 只写指定的 Plan artifact，不推进 controller 状态；同一 Plan 重复 `apply`
会根据 Step receipt 恢复，不重复 `sbatch`。`status` 默认只读本地 controller；
`--live` 最多执行一次远端调用。

`entityctl install` 将一个经过 hash 验证的运行版本发布到
`~/.entity-skills/bundles/`；Codex、Claude Code 和 Kimi Code 的 discovery 目录只保留
指向同一 bundle 的符号链接投影，不再分别维护三套文件。

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

已有 Codex、Claude Code 和 Kimi Code 记录均可增量导入。adapter 只保留 tool
call/output 的 hash、大小、顺序、原生 session/agent ID 和平台原始 usage，显式忽略
对话文本和 reasoning，并排除 observer 自身调用：

```bash
python3 tools/skill_observability/skill_observer.py import-codex \
  --run-dir <run-dir> \
  --rollout /absolute/path/to/codex-rollout.jsonl

python3 tools/skill_observability/skill_observer.py import-claude \
  --run-dir <run-dir> \
  --transcript /absolute/path/to/claude-session.jsonl

python3 tools/skill_observability/skill_observer.py import-kimi \
  --run-dir <run-dir> \
  --session /absolute/path/to/kimi-session-directory
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
