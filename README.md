# Entity Skills Package

一套帮助 Agent 使用 [Entity](https://github.com/entity-toolkit/entity) 完成天体物理模拟的 skills package。

`skills/entity-router/SKILL.md` 是受管 simulation 工作流的控制入口。需要 Case 状态、跨领域交接、构建运行、恢复或持续追踪时，由 Router 选择 playbook 并按需调用三个同级子 skill。边界明确的领域任务可以直接调用对应 skill；一旦目标属于受管 Case，修改操作必须持有 Router Action Contract。

- `entity-pgen`：PGen、匹配 TOML 和设计记录；
- `entity-env-build`：依赖环境与 Entity 编译；
- `entity-nt2py`：nt2py 数据访问、绘图和导出。

Simulation 的准备、运行、续跑和状态恢复由 Router 按自身 `playbooks/` 管理，不单独建立 run skill。

初版 Router 将专业工作和 Router-owned run 操作放入 Case-bound Worker；Router 只保留控制上下文。`skills/entity-router/scripts/entity_router_state.py` 负责 Case、Workflow、Action Contract、revision、事件和 stale 状态。

确定性 flow façade 是受管事务的默认路径。Router 通过 `entityctl.py flow` 完成
compact inspect/check、allowlisted execute、scheduler-safe launch/watch、nt2
inventory 和 model Worker prepare/resume；Case mutation 仍全部经 state CLI。
`ENTITY_ROUTER_LEGACY_LOOP=1` 只用于恢复缺少 flow orchestration 字段的历史 Action。

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

当前共享状态与高层入口设计见 `design/architecture-v4.md`；v3 资源图基准见
`design/architecture.md`，workspace 和状态细节见 `design/workspace-and-state.md`，
模型高效执行流程见 `design/model-efficient-router-flow.md`，skill 执行观测和日志
合同见 `design/skill-observability.md`。`design/` 和 `legacy/` 不属于 Router 运行时上下文。

## 公共控制状态

Codex、Claude Code、Kimi Code 和普通 shell 默认共享控制机上的
`~/.entity-router`。Case、Action、事件、evidence 和 project binding 不写入客户端
私有目录或源码仓库。远端不可用时仍可读取最后一次控制快照，但缓存 evidence 不代表
当前远端事实。

```bash
python3 skills/entity-router/scripts/entityctl.py doctor
python3 skills/entity-router/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  bundle install --source-root /path/to/entity-skills/skills
python3 skills/entity-router/scripts/entityctl.py project bind \
  --project-root /absolute/project --case <case_uid>
python3 skills/entity-router/scripts/entityctl.py inspect \
  --project-root /absolute/project
python3 skills/entity-router/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  writer acquire --case <case_uid> --expected-revision <n> \
  --lease-id <lease-id> --ttl-seconds 900
python3 skills/entity-router/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  --writer-lease-id <lease-id> flow execute --request <flow-request.json>
```

`entityctl inspect` 是紧凑只读入口；`entityctl run-status` 从 Case 推导当前 run
Locator，并最多执行一次远端调用。详细存放合同、provenance 和迁移计划见
`design/architecture-v4.md`。

`entityctl bundle install` 将一个经过 hash 验证的运行版本发布到
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
