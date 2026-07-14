# Entity Skills Package

一套帮助 Agent 使用 [Entity](https://github.com/entity-toolkit/entity) 完成天体物理模拟的 skills package。

`skills/entity-router/SKILL.md` 是 Router 入口。它根据用户目标和 workspace 状态选择 playbook，并按需调用三个同级子 skill：

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
├── design/
└── legacy/
```

当前整体设计见 `design/architecture.md`，workspace 和状态细节见 `design/workspace-and-state.md`。`design/` 和 `legacy/` 不属于 Router 运行时上下文。

## 仓库与发布

四个 skill 由本仓库统一开发、测试和发布。`skills/` 下不使用嵌套 Git 仓库或 submodule；跨 skill 的契约修改应在同一个分支和 pull request 中完成。

- `main` 保存可用的整包状态；
- 开发使用短期分支，不为单个 skill 维护长期分支；
- release tag（例如 `v0.1.0`）固定一组经过联合验证的四个 skill；
- 旧的单 skill 仓库只保留历史，不再作为开发或发布入口。

详细协作约定见 `CONTRIBUTING.md`。

本地验证：

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s skills/entity-env-build/tests -v
```
