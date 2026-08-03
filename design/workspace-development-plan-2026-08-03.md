# Workspace 开发计划

日期:2026-08-03。配套设计:`design/workspace-and-computation-site-2026-08-03.md`。

实现顺序按依赖关系排:先有 Workspace 容器,再拆 Project/Case,再落 site
档案与文件树,最后接 env-build 与迁移。每个阶段独立可用、可测试。

## 阶段 1:Workspace 容器

目标:`entityctl` 认识 workspace,控制器状态位置可解析。

- `workspace.yaml` schema(workspace_id、schema_version、created_at、
  migrated_from)。
- `entityctl workspace init <path>`:创建目录树骨架(workspace.yaml、
  projects/、sites/、.ledger/)。
- `entityctl workspace adopt <path>`:写 `~/.entity-ledger/active-workspace`
  指针;`workspace where` 显示当前激活 workspace。
- store 解析顺序:显式参数 > `ENTITY_WORKSPACE` 环境变量 > active-workspace
  指针 > 旧 `~/.entity-ledger/ledger.db`(兼容期,打警告)。
- 涉及:`entity_ledger_store.py`(打开 db 的路径解析)、`entityctl.py`
  (新子命令)、`entity_ledger_common.py`。

## 阶段 2:Project / Case 拆分

目标:project 1:N case,case 有实体目录。

- store schema v3:`projects` 表改为 project 实体(project_uid、slug、
  workspace 内相对路径);`cases` 表加 `project_uid` 外键。写
  `store migrate`(旧 root→case 1:1 数据升级为每 project 一个默认 case)。
- `entityctl project init <name>`:建 `projects/<p>/`(project.yaml +
  source/ + cases/);`entityctl case init <project> <name>`:建
  `cases/<c>/`(intent.md、decisions.json)并落账。
- `record intent` 双向同步:db 为主,写时同步 `cases/<c>/intent.md`。
- status/show/dashboard 输出按 project → case 分组;就绪板/run 台账语义
  不变。
- 涉及:`entity_ledger_store.py`、`entity_ledger_record.py`、
  `entity_ledger_facts.py`、`entity_ledger_dashboard.py`、`entityctl.py`、
  `tests/test_ledger_migrate.py` 及新增测试。

## 阶段 3:Computation Site 档案与文件树

目标:site 档案结构化、权威化,site 上文件树有约定。

- `templates/site-profile.schema.json` 升级:`site_root`、`deps[]` 注册表、
  `projects[]` 列表;roots 从 5 个独立根改为派生约定(deps/checkouts/
  projects)。
- `workspace/sites/<site>.yaml` 为权威;`entityctl site sync`(档案 → db)
  与 `site list/show`(db + 档案合并视图)。
- `entityctl site init <site>`:在目标机器创建 `<site_root>` 树骨架 +
  `entity-site.yaml` 标记文件;`site discover` 扩展:探测机器档案落盘
  (machine 节)、发现既有 `entity-site.yaml`(认领旧树)。
- 路径推导改新树:render-run、record build/run/data 的 Locator 推导为
  `<site_root>/projects/<p>/{builds,runs,staging}/<case>/<id>`;旧 Locator
  在阶段 5 全面迁移前保持可引用。
- `site-notes/*.md` 转换器:散文进 notes 节,`astro-axion-site-profile.json`
  作结构化参考。
- 涉及:`entity_ledger_common.py`(Locator 推导)、`entity_ledger_remote.py`、
  `entityctl.py`、`references/workspace-layout.md`(重写)、新增
  `references/site-record.md`。

## 阶段 4:deps 注册表与 env-build 集成

目标:解决问题 1——"这台机器上以前用过什么环境"成为一次查询。

- env-build 解析 `requirements.json` 的查找顺序:site 档案 deps 注册表 →
  `entity-site.yaml` 标记 → 临场探测补缺;命中栈直接复用
  `deps/<stack_id>/env.sh`。
- 新依赖栈确认(`entity_checkpoint.py confirm` + compatibility pass)后回写
  site 档案注册表 + `deps/<stack_id>/stack.yaml`。
- `entityctl site deps <site>`:列出注册表(人读 + `--json`)。
- `record build` 的 checkpoint payload 增加 `stack_id` 引用。
- 涉及:`skills/entity-env-build/scripts/`(checkpoint/generate)、
  `skills/entity-env-build/SKILL.md` 与 `references/`、`entity_ledger_record.py`。

## 阶段 5:迁移原语与迁移 skill

目标:旧布局全面迁入新模型。方式是把迁移能力做进 skill 和原语,投产
后由 agent 在生产中按 skill 自主整理,而不是写一个一次性大迁移脚本。

- **本地收编脚本** `entityctl workspace import`(一次性,仅本地):
  整目录迁 `~/Documents/{axion-pic,bh-reconnection,polar_cap}` →
  `projects/`;迁 `~/.entity-ledger/ledger.db` + `snapshots/` →
  `.ledger/`;转 site-notes → `sites/*.yaml`;project-bindings → 各
  project.yaml。dry-run 默认,`--apply` 才动手;旧位置保留只读副本,
  doctor 校验通过后由用户手动清理。
- **迁移原语**(支撑 agent 远端整理):
  - `entityctl site plan-migration <site>`:盘点旧树上的资源(扫描旧
    roots、对照 ledger 记录),输出"旧路径 → 新路径"迁移计划(JSON),
    不执行;
  - `entityctl record relocate`:资源移动后重新探测证据(哈希/路径)
    并更新 Locator 落账,证据不符零写入;
  - 移动本身的执行(ssh/rsync/mv)由 agent 编排,不包进原语。
- **迁移指南**:`skills/entity-ledger/references/migration-guide.md`——
  目标布局、移动规则、顺序与禁忌(在途 run 不动,等 `record run-exit`
  终态后迁;先盘点哈希再移动;每步后 `doctor` 校验)、逐 site 的
  checklist 模板。
- 迁移完成标准:所有 current identity 的 Locator 指向新树;旧路径不再
  被引用;旧目录验证为空后删除。

## 阶段 6:文档与收尾

- 四个 SKILL.md 同步新模型(ledger:workspace/case 语义;env-build:注册表
  查找;pgen:preflight 目标解析;nt2py:数据根来自 run 目录约定)。
- `references/workspace-layout.md` 重写;README、CHANGELOG 更新。
- tests 全绿;新增 workspace/site-record/migrate 测试。

## 明确不在本计划内

analysis 管理设计(阶段 3/2 已留槽位);多 workspace;workspace 的 git 化。

## 验收标准

- 新 agent 会话在任一已登记 site 上:`site deps <site>` 能列出可复用环境,
  无需临场探测。
- `rsync` workspace 到本机另一路径 → `workspace adopt` → `status` 输出与
  原位置一致(除远端 live 状态)。
- 新建 project/case/build/run 全部落在新文件树。
- 迁移收官:所有 site 的旧树已按 migration-guide 整理完毕,current
  identity 的 Locator 全部指向新路径,旧目录已清空删除。
