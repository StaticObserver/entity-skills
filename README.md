# Entity Skills Package

一套帮助 Agent 使用 [Entity](https://github.com/entity-toolkit/entity) 完成天体物理模拟的 skills package。

`skills/entity-router/SKILL.md` 是模拟项目的确定性记录入口。Router 把
公共模型收敛为 `Project → Case → Identity → Evidence`：Agent 负责与用户对话、
科学判断和流程编排，Router 提供确定性原语——读取（status/show）、生成
（render-run/snapshot-source）、记录（record build/run-prepare/run-launch/
run-exit/data/intent）和探测（status --live）。写入类原语自带证据探测，
先验证、后落账，失败零写入。边界明确的只读或 standalone 领域任务仍可直接
调用对应 owner skill。

- `entity-pgen`：PGen、匹配 TOML 和设计记录；
- `entity-env-build`：依赖环境与 Entity 编译；
- `entity-nt2py`：nt2py 数据访问、绘图和导出。

每种模拟活动（搭环境、写 PGen、编译、跑模拟、分析、debug）有一份
playbook 供 Agent 参考，流程顺序由 Agent 按用户目标自行编排，不单独建立
run skill。SQLite `router.db`（schema v2）是唯一结构化 controller
authority；Local 与 SSH 使用同一个内容寻址 executor。

```text
entity-skills/
├── skills/
│   ├── entity-router/
│   │   ├── SKILL.md
│   │   ├── playbooks/
│   │   ├── agents/
│   │   ├── scripts/
│   │   ├── references/
│   │   └── templates/
│   ├── entity-pgen/
│   ├── entity-env-build/
│   └── entity-nt2py/
├── tests/
├── tools/skill_observability/
├── evals/e2e-neutral-streaming/
├── design/
└── legacy/
```

当前架构见 `design/router-case-centric-restructure-2026-07-23.md`，迁移计划见
`design/router-restructure-migration-2026-07-23.md`。`router-v5-*`、
`architecture-v4.md` 和 `model-efficient-router-flow.md` 是历史设计，不代表当前
公共入口。skill 执行观测合同见 `design/skill-observability.md`。`design/` 和
`legacy/` 不属于 Router 运行时上下文。

## 公共控制状态

Codex、Claude Code、Kimi Code 和普通 shell 默认共享控制机上的
`~/.entity-router/router.db`（schema v2：Site、Case、项目绑定、identity 与
审计事件；并发为单写文件锁）。identity、事件和 evidence reference 不写入
客户端私有目录或源码仓库。远端不可用时仍可读取最后一次控制快照，但缓存
evidence 不代表当前远端事实。

```bash
python3 skills/entity-router/scripts/entityctl.py doctor
python3 skills/entity-router/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  install --source-root /path/to/entity-skills/skills
python3 skills/entity-router/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  site add --profile /absolute/site-profile.json
python3 skills/entity-router/scripts/entityctl.py site list
python3 skills/entity-router/scripts/entityctl.py export --output /absolute/export.json

# 读取项目状态（仪表盘：就绪板 + Run 台账 + 待决 + 建议下一步）
python3 skills/entity-router/scripts/entityctl.py status \
  --project-root /absolute/project [--live] [--json]
python3 skills/entity-router/scripts/entityctl.py show --project-root /absolute/project

# 生成（零写入）
python3 skills/entity-router/scripts/entityctl.py render-run \
  --project-root /absolute/project --toml input.toml --site <site> [--gpus N]
python3 skills/entity-router/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  snapshot-source --project-root /absolute/project

# 记录（先探测证据，后落账）
python3 skills/entity-router/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  record run-prepare --project-root /absolute/project --toml input.toml --site <site>
python3 skills/entity-router/scripts/entityctl.py ... record run-launch --project-root ...
python3 skills/entity-router/scripts/entityctl.py ... record run-exit  --project-root ...
python3 skills/entity-router/scripts/entityctl.py ... record build --project-root ... \
  --site <site> --checkpoint deps.local.json --executable /abs/entity.xc
python3 skills/entity-router/scripts/entityctl.py ... record data   --project-root ...
python3 skills/entity-router/scripts/entityctl.py ... record intent --project-root ... \
  --text "<当前研究目标>"
```

`record run-prepare` 要求模拟参数已确认（`pgen_preflight.py confirm` 写入的
`<input>.decisions.json` 与 TOML 字节匹配）；`record run-launch` 有 receipt
保护，重复执行不会重复提交，绕过 Router 提交的作业用 `--adopt-job/--adopt-pid`
认领；`status` 默认只读本地 controller，`--live` 最多执行三次有界 scheduler
查询。

`entityctl install` 将一个经过 hash 验证的运行版本发布到
`~/.entity-skills/bundles/`；Codex、Claude Code 和 Kimi Code 的 discovery 目录只保留
指向同一 bundle 的符号链接投影，不再分别维护三套文件。

`entity-pgen` 的直接调用分为只读和 standalone 修改。它在写入前必须运行自身的 preflight；preflight 查询 Router store，target 落在注册 Case 的 source/identity/active-run Locator 内即视为受管，受管写入须由 Router 的 record 原语登记。Router 控制状态位于独立 control root，不依赖源码祖先目录中的 `_case/` 标记。

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
  --expect allowed

python3 tools/skill_observability/skill_observer.py finish \
  --run-dir <run-dir> --status completed

python3 tools/skill_observability/skill_observer.py validate \
  --run-dir <run-dir>
```

`evidence` 支持历史 `router-action`、`env-build`
和 `nt2py-inventory` 等校验器。完整协议与证据等级见
`design/skill-observability.md`。

## 端到端 Skill 对照评测

`evals/e2e-neutral-streaming/` 是轻量 A/B 对照：skill/no-skill 两组跑同一个
模拟任务，对照 trace、token 消耗和完成时间。任务文本、物理参数和启动方式见
`evals/e2e-neutral-streaming/RUNBOOK.md`。对照 oracle（`oracle/` 下 5 个 gate 与
`thresholds.json`，由 `tests/test_oracle.py` 覆盖）仍然保留；schema 与 fake Slurm
脚手架已于 2026-07-21 移除，历史版本见 git 记录。

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
