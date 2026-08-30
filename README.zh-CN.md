# Entity Skills 0.8.0 发布候选

`0.8.0rc` 分支是 0.8.0 的发布候选。有效实现位于 `vnext/`；根目录旧 `skills/`、
`tests/`、Router/Ledger 代码和早期设计文档仅作为 0.7.x 迁移与历史材料保留。

## 模型

```text
Source + PGen -> Build -> Run
```

- Source 记录仓库和一个 Git commit。
- PGen 是独立的用户代码包。
- Build 记录 Source、PGen、Site、deps、编译选项和运行能力。
- Run 记录一个 Build 和一份精确 TOML。
- Build/TOML 不变时，资源、环境或重投变化只创建新的 Attempt。
- Data 属于 Run；Analysis 记录一个或多个精确 `{build, run}` 输入。

Workspace、Project、Site、deps、Attempt、Data 和 Analysis 只组织或派生事实，
不再建立第二套对象层级或生命周期状态机。

## 目录

```text
vnext/
├── entity/                      # 0.8.0 运行时
├── bin/entity                   # 直接 CLI 入口
├── schemas/examples/            # JSON 字段示例
├── skills/
│   ├── entity-workspace/
│   ├── entity-env-build/
│   ├── entity-pgen/
│   └── entity-nt2py/
├── tests/
├── ARCHITECTURE.md
└── README.md
```

0.8.0 不再提供 `entity-ledger`。跨会话对象关系、Site 操作、Build/Run
创建、提交和状态跟踪统一归 `entity-workspace`。

## 快速开始

```bash
cd vnext
python3 -m pip install .
entity --version
entity workspace init /absolute/workspace
export ENTITY_WORKSPACE=/absolute/workspace
entity project init --project demo
```

不安装时也可直接使用 `vnext/bin/entity`。实际调用前先查看子命令 `--help`：

```text
workspace  project  site  source  pgen  deps
build      run      analysis  check  migrate
```

维护中的合同见 [vnext/README.md](vnext/README.md)、
[vnext/ARCHITECTURE.md](vnext/ARCHITECTURE.md) 和
[vnext/schemas/examples](vnext/schemas/examples)。

## 使用边界

0.8.0 面向协作式、文件优先的科学工作区，不把输入视为敌对的多租户安全边界。
JSON、TOML、Git commit 和 Site 上的实际文件是权威。运行时有意不加入数据库、
内容 Hash、seal/release、权限加固或强制工作流门槛。

已登记的 PGen、Build 或 Run 输入发生变化时使用新 ID，不用原地修改表示另一个对象。
`entity check` 只读报告结构矛盾和缺失事实；它不强制不可变性，也不是无关工作的
前置门槛。提交 intent 只保留最小恢复信息，用于阻止结果不明时自动重复提交。

## 验证

```bash
PYTHONPATH=vnext python3 -W error::ResourceWarning \
  -m unittest discover -s vnext/tests -t vnext -v
python3 -m compileall -q vnext
git diff --check
```

四个技能使用 Codex `skill-creator` 的 `quick_validate.py` 校验。自动化测试使用
本地 fixture、fake Entity 和 fake Slurm；真实 SSH/HPC canary 是独立发布检查。

## 旧 0.7.x

根目录旧实现继续可读，便于已有 Workspace 导出和迁移对照。它不是 0.8.0 的
运行时或 Agent 入口；其中版本号、测试和历史设计文档仍只属于 0.7.x。
