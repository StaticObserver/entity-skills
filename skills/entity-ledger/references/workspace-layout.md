# Workspace 与 Computation Site 布局契约

一个资源的 identity 始终是 `(site_id, 绝对路径)` 这一对组合加上它的
fingerprint。一个 Computation Site 可以是一台本地机器，也可以是一个
SSH 访问边界，覆盖一台 HPC 登录节点、scheduler、计算节点和共享文件系统。

## Workspace(开发环境,唯一工作目录)

```text
entity-workspace/                    # 位置用户自选;entityctl workspace init/adopt
├── workspace.yaml                   # workspace_id、schema 版本、创建/迁移历史
├── projects/
│   └── <project>/                   # 人可读的树,用户日常工作的地方
│       ├── project.yaml             # project_uid、slug、source authority 登记
│       ├── source/                  # source authority(名字登记在 project.yaml)
│       └── cases/
│           └── <case>/              # 意图边界:intent.md、decisions.json
├── sites/
│   └── <site>.yaml                  # site 档案(权威):见下
└── .ledger/                         # 控制器状态(机器读写)
    ├── ledger.db                    # controller authority
    └── snapshots/                   # 源码快照 tar(内容寻址)
```

`ledger.db` 只包含紧凑的事实和证据引用。它绝不放在源代码检出目录
内(`.ledger/` 位于 workspace 根,不在任何 source authority 内部),也
绝不复制到 `.codex`、`.claude` 或 `.kimi-code` 等 provider 私有根目录。
新 workspace 的 `.ledger/` 只有 `ledger.db` 与 `snapshots/`;
`registry.json`、`sites/`、`cases/` 等前 v3 文件只可能存在于尚未收编的
旧 `~/.entity-ledger`——它们由 `workspace import` 处理,运行时绝不读取。

控制器 home 的解析顺序:显式参数(`--ledger-home`,以及
`ENTITY_LEDGER_HOME`/`ENTITY_ROUTER_HOME` 环境变量)>
`ENTITY_WORKSPACE` 环境变量 > `~/.entity-ledger/active-workspace` 指针 >
旧 `~/.entity-ledger`(兼容回退,打 deprecation 警告)。snapshots 随 db
一起解析到同一 home 下。

## Site 档案(sites/<site>.yaml,权威)

```yaml
site_id: m87
schema_version: 1
transport: {"kind": "ssh", "alias": "m87"}    # 或 {"kind": "local"}
scheduler: {"kind": "slurm"}
machine: {"os": "...", "arch": "...", "gpus": [...]}   # site discover 落盘
site_root: /home/staticobserver/entity-compute
projects: ["bh-reconnection"]                 # 该 site 上的 project 子树
deps: [{"stack_id": "...", "status": "verified", "packages": [...]}]
notes: |                                      # 自由文本,保留人的经验
  ...
```

档案是权威;ledger.db 的 `sites` 表由 `entityctl site sync` 从档案刷
新(映射时 `transport.alias` 改写为 db profile 的 `transport.ssh_alias`,
`templates/site-profile.schema.json` 用的是后者)。只在 db 里存在的
site(旧 `site add` 登记的)在 `site list` 中标注 db-only,保持可用,
不自动删除。凭证、SSH 私钥不进档案;档案只记 SSH alias 名。密码、令
牌、可变会话记忆以及完整的 skill 副本都不应进入项目或控制器状态。

## Computation Site 文件树

```text
<site_root>/                          # entityctl site init 创建骨架
├── entity-site.yaml                  # 站点标记:site_id、schema 版本、roots 清单
├── deps/                             # 共享依赖栈(site 级,跨 project 复用)
├── checkouts/                        # 物化源码(不可变,内容寻址)
└── projects/
    └── <project>/                    # 每个 project 一棵独立子树
        ├── builds/<case>/<build_id>/ #   不可变
        ├── runs/<case>/<run_id>/     #   不可变;原始数据权威位置
        └── staging/<case>/<op_id>/   #   暂存 + receipt
```

profile 带 `site_root` 时,新资源的路径推导用这棵树(layout
`site-tree`,路径段用可读的 project/case slug);没有 `site_root` 的旧
profile 保持旧的独立 roots 推导(layout `legacy-roots`,路径段用
case_uid)并标注 legacy。旧 Locator 在两种 layout 下都可读取;迁移(阶
段 5)之前两套并存。构建和运行在其 identity 提交之后即不可变。原始数
据在执行/数据 Site 保持权威;只取回盘点清单、日志、图件、报告或明确
选定的子集。

## 源权威

每个 Project 只有一个可编辑的源权威(登记在 project.yaml,默认
`source/`)。干净的 Git 工作树或内容寻址 manifest 标识其确切内容。脏
文件和未跟踪文件也包含在 manifest 中;仅有 `dirty=true` 不构成一个
identity。其他检出目录在证明完全相等之前都只是副本。PGen、TOML 和
design 的编辑只发生在源权威处。

## 执行边界

控制器推导允许的根目录和不可变的执行请求。Site 执行器只能在这些根
目录之下写入,且绝不写 `ledger.db`。receipt 保留在该次操作的暂存根
目录下,以便 record 原语在控制器进程丢失后重跑时认领既有效果、不重
复提交。

Site 本地的 module 配置或策略应放在受信任的 Site 适配器中,而不是
record 原语参数或通用 Ledger 核心中。
