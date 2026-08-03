# Workspace 与 Computation Site:顶层模型设计

日期:2026-08-03。状态:已定稿,待实现。

## 1. 背景:三个实用问题

当前版本(0.6.x,entity-ledger + owner skills)在使用中暴露三个问题:

1. **agent 找不到服务器上的 deps 和以前用过的环境。**`deps_root`/
   `artifacts_root` 不在 site profile、不在 ledger;checkpoint 按 case 寻址,
   只回答"这个 case 能否复用";跨会话记忆只有散文 site-notes,无机器可读
   注册表。
2. **缺乏数据分析代码管理。**analysis 维度在 store/dashboard 是空壳(无
   record 原语);分析脚本散落各 project 目录,无登记、无版本对应关系。
3. **抽象层面缺两个一等概念**:一个源码维护/开发/工作的目录,和一个
   用于实际计算的环境。二者可在同一台机器,也可在不同机器,概念上隔离。

本设计解决问题 1 和 3,并为核心概念定界;问题 2(analysis)只预留槽位,
最后单独设计。

## 2. 顶层模型

```text
Workspace(开发环境,唯一工作目录)
└── Projects(研究主题,持有 source authority)
    └── Cases(意图边界内的研究线索)
        └── Identity 链:source → build → run → data → analysis(预留)

Computation Site(计算环境,约定文件树 + 结构化档案)
└── 持有:共享 deps 栈、物化 checkouts、projects/<p>/{builds,runs,staging}
```

- **Workspace** 是一个真实目录,是开发的唯一工作目录。它记录重建项目所需
  的一切事实(不含大产物本体),用户可以拿着整个目录迁移到任何机器上重新
  开始。一个 Workspace 下有多个 Projects。
- **Computation Site** 是一个受管的计算环境:一台机器(或"HPC 登录节点 +
  调度器 + 共享盘"的访问边界)上,一棵约定的文件树 + 一份登记在
  Workspace 里的档案。它只做三件事:持有共享 deps、物化源码、执行
  build/run。它不持有任何权威记录,所有事实回写 Workspace;site 上的树丢
  了可按档案重建。
- **Case = 意图边界**:project 内一个意图明确的研究线索(一份意图 + 一个
  PGen 配置族 + 它的 build/run/data 链)。参数扫描 = 一个 case 多条 run;
  意图换了才开新 case。run 的语义不变(追加式台账条目,引用 build,续跑
  引用 parent)。
- Workspace 与 Computation Site 可以在同一台机器(同一 site 同时是 dev 和
  compute 角色),也可以在不同机器。概念上永远隔离:Workspace 是可携带的
  档案,Computation Site 是可重建的执行场所。

## 3. Workspace 目录树

```text
entity-workspace/                    # 唯一工作目录,位置用户自选
├── workspace.yaml                   # workspace_id、schema 版本、创建/迁移历史
│
├── projects/                        # 人可读的树,用户日常工作的地方
│   └── <project>/
│       ├── project.yaml             # project_id、case 列表、默认 site 偏好
│       ├── source/                  # source authority(名字不限,登记在 yaml)
│       ├── docs/  scripts/  ...     # 用户既有内容原样保留,不强制结构
│       └── cases/
│           └── <case>/
│               ├── intent.md        # 意图(落成人可读文件)
│               ├── decisions.json   # pgen 参数确认卡
│               └── analysis/        # 预留槽位
│
├── sites/                           # 结构化 site 档案 = site-notes 升级版
│   └── <site>.yaml
│
└── .ledger/                         # 控制器状态(机器读写)
    ├── ledger.db                    # 从 ~/.entity-ledger 迁入
    └── snapshots/                   # 源码快照 tar(内容寻址)
```

语义:

- `projects/` 和 `sites/` 是人读人写的档案(YAML + Markdown);`.ledger/`
  是机器状态。site 档案是权威,ledger.db 的 `sites` 表由它导入/刷新;case
  的 identity 链、run 台账等高频事实留在 db。
- 不使用 git 做版本管理;Workspace 就是工作目录本身。
- **可携带性 = 目录自包含。**迁移 = rsync 整个目录 → 新机器上
  `entityctl workspace adopt <path>`(在 `~/.entity-ledger/active-workspace`
  写指针)→ 继续工作。旧机器上的 compute site 档案原样保留(描述的是远
  端,不受搬家影响)。凭证、SSH 私钥不进档案,site 档案只记 SSH alias 名。

## 4. Computation Site 文件树

```text
<site_root>/                          # 如 /lustre/.../entity-compute
├── entity-site.yaml                  # 站点标记:site_id、schema 版本、roots 清单
│                                     #   agent 找到它即知道一切(发现机制)
├── deps/                             # 共享依赖栈(site 级,跨 project 复用)
│   └── <stack_id>/                   #   按工具链签名,如 gcc11-openmpi4.1-hdf5.14
│       ├── <package>/...             #   各依赖 prefix
│       ├── env.sh
│       └── stack.yaml                #   栈清单:版本/构建配方/验证状态
│
├── checkouts/                        # 物化源码(不可变,内容寻址)
│   └── <source_hash>/                #   哈希相同即内容相同,天然去重
│
└── projects/                         # 每个 project 一棵独立子树,互不混杂
    └── <project>/
        ├── builds/<case>/<build_id>/ #   不可变
        ├── runs/<case>/<run_id>/     #   不可变;原始数据权威位置
        ├── staging/<case>/<op_id>/   #   暂存 + receipt
        └── analysis/                 #   预留槽位
```

划分逻辑:site 层只放**不可变且按内容寻址**的共享物(deps 栈、checkouts);
凡是项目专属、按时间累积的(builds、runs、staging、analysis)全部进
`projects/<project>/`。人在服务器上 `ls projects/` 即可见项目边界,删除/
归档/配额都可按子树操作。

路径段用 slug(`<project>/<case>`,可读),稳定性由档案中的 uid + 路径记
录兜底。`<project>` 子树位置默认在 `site_root` 下,档案允许 per-project 覆
盖(配额需求)。

原始数据不设独立 data_root:run 目录即数据权威位置,`record data` 的盘点
manifest 引用 run 目录内路径;取回的内容进 Workspace 的 project 区。

## 5. Site 档案(sites/<site>.yaml)

```yaml
site_id: m87
transport: { kind: ssh, alias: m87 }       # 或 { kind: local }
scheduler: { kind: slurm, default_partition: ..., default_qos: ... }
machine: { os: ..., arch: ..., gpus: ... } # site discover 探测落盘
site_root: /home/staticobserver/entity-compute
projects:                                  # 该 site 上存在哪些 project 子树
  - bh-reconnection
deps:                                      # 结构化 deps 注册表(核心新增)
  - stack_id: gcc11-openmpi4.1-hdf5.14
    status: verified                       # verified / suspect / broken
    packages: [{ name, version, prefix }, ...]
    recipe: ...                            # module 列表或源码构建配方
notes: |                                   # 自由文本节,保留人的经验
  ...
```

**deps 注册表是问题 1 的解法**:env-build 解析 `requirements.json` 时先查
对应 site 的注册表,命中且验证通过即复用;新解析/构建出的依赖栈确认后回
写注册表。`entity-deps.local.json` 仍按 case 存(构建证据),但解析来源从
"agent 临场探测"变为"注册表 + 探测补缺"。

## 6. 与现有模型的映射

| 现有概念 | 新模型中的去向 |
|---|---|
| `~/.entity-ledger/ledger.db` + `snapshots/` | `workspace/.ledger/` |
| `project-bindings.json` | 各 `project.yaml` |
| `~/Documents/<project>/` 散落工作目录 | `workspace/projects/<project>/`(整目录搬,内部不动) |
| `~/.entity-env-build/site-notes/*.md` | `workspace/sites/<site>.yaml` 的 notes 节 + 结构化各节 |
| site profile roots(5 个独立根) | `site_root` 约定树 + `entity-site.yaml` 标记 |
| Case(0.6.x,"每个模拟项目一个") | 拆为 Project(容器)+ Case(意图边界) |
| `projects` 表 root→case 1:1 绑定 | project 1:N case(store schema 升级) |
| analysis 空壳维度 | 维持预留,最后设计 |

`workspace-layout.md` 中"ledger.db 绝不放在源代码检出目录内"的契约不变:
`.ledger/` 位于 workspace 根,不在任何 source authority 内部。

## 7. 迁移策略:全面迁移,agent 驱动

旧布局不做"只约束增量"的妥协——现存 13 个 site 上的旧树(build/、
builds/ 等)和散落的项目目录全部迁入新模型,最终只存在一套布局。

**方式:先 skill,后迁移。**先把新模型、迁移原语和迁移指南开发进 skill
并投入生产,然后由 agent 在生产环境中按 skill 自主整理旧文件。分工:

- **skill 提供知识**:目标布局、移动规则、顺序与禁忌(在途 run 不动,等
  终态后迁;移动前先盘点哈希,移动后重新探测落账)、每台机器的实际情况
  如何编排节奏。
- **entityctl 提供确定性原语**:支撑"移动 + 重新登记"的安全执行——按
  新树推导目标路径、移动后重新探测证据并更新 Locator、失败零写入可重跑。
- **agent 负责编排**:哪台机器先迁、在途作业如何避开、出错如何修——这正
  是"自由探索、严格收束"原则在迁移场景的应用。

Workspace 本地部分的收编(projects 目录、ledger.db、site-notes → YAML)
是一次性本地操作,由 `workspace import` 脚本完成;远端 site 旧树的整理无
法脚本化(机器可达性、在途 run、配额各不相同),由 agent 逐 site 执行。

迁移完成标准:所有已登记资源的 Locator 指向新树路径,旧路径不再被任何
current identity 引用;旧目录由 agent 验证为空后删除。凭证永不进档案;
`workspace adopt` 后用户在新机器重新配 SSH alias。

## 8. 明确不做(本次)

- analysis 脚本/产物的管理设计(预留槽位:workspace `cases/<c>/analysis/`、
  site `projects/<p>/analysis/`、identity 链 analysis 维度)。
- run 台账级细节的全量可携带(高频事实在 ledger.db,随 workspace 走;
  远端原始数据本体永远不搬)。
- Workspace 的 git 化、多 workspace 合并。
