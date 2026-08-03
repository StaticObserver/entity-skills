# 迁移指南:旧布局全面迁入 Workspace / Computation Site 模型

目标布局见 `references/workspace-layout.md` 与设计文档
`design/workspace-and-computation-site-2026-08-03.md`。最终只存在一套布
局:所有已登记资源的 Locator 指向新树,旧路径不再被任何 current
identity 引用,旧目录验证为空后删除。

迁移是 **agent 驱动** 的:entityctl 提供确定性原语(计划、落账),移动
本身(ssh/rsync/mv)由 agent 编排。原则不变——自由探索、严格收束:
agent 决定顺序与节奏,原语保证每一步可验证、可重跑、失败零写入。

## 顺序与禁忌

- **在途 run 不动。**没有终态的 run(prepared/submitted/running)原地留
  置,等 `entityctl record run-exit` 落出终态后再迁。
- **先盘点哈希再移动。**移动前以 `site plan-migration` 的计划为准;
  移动后 `record relocate` 会重新探测证据,证据不符零写入——所以绝不
  要先删旧路径再落账。
- **每步后校验。**每完成一个 site 的一个批次,跑 `entityctl doctor`
  与 `status`,确认 current identity 的 Locator 已指向新树。
- **凭证永不进档案。**site 档案只记 SSH alias 名;密码、令牌、私钥不
  进 workspace 的任何文件。
- 旧位置在 doctor 校验通过、agent 验证为空之前**只读保留**,由用户手
  动清理。

## 第 0 步:本地收编(一次性,仅本地)

把散落的项目目录、旧控制器和 site-notes 收进一个 workspace:

```bash
entityctl workspace init <workspace>
entityctl workspace import <workspace> \
  --projects-dir ~/Documents \
  --from-ledger-home ~/.entity-ledger \
  --site-notes ~/.entity-env-build/site-notes          # dry-run,先看计划
entityctl workspace import <workspace> ... --apply     # 确认后执行
entityctl workspace adopt <workspace>
```

- dry-run 输出每一步计划(project 复制、ledger.db、snapshots、
  site-notes 转换);冲突(目标已存在且内容不同)只报告、跳过,绝不覆
  盖。已初始化的空 `.ledger/ledger.db` 会被备份后替换;非空库冲突跳过。
- `--apply` 复制旧 `ledger.db` 到 `.ledger/` 并自动完成 store schema
  迁移(v1→v2→v3),旧 project 绑定会登记成各 `project.yaml`;
  site-notes 复用 `site import-notes` 转换器(散文进 notes 节,结构化
  JSON 进对应节)。已存在的档案跳过。
- 收编后:`entityctl site sync` 把档案刷进 db,`entityctl doctor` 校验。

## 第 1 步:site 档案与骨架

每个旧 site:

1. 确认 `sites/<site>.yaml` 已有 `site_root`(import-notes 已带入旧
   roots;新 site_root 按约定选,如 `/home/<user>/entity-compute`)。
2. `entityctl site sync <site>` 刷新 db。
3. `entityctl site init <site>` 在目标机器建 `<site_root>/{deps,
   checkouts,projects}` 骨架和 `entity-site.yaml` 标记。若目标机上已存
   在标记,`site discover` 会报告认领信息——核对后再决定是否沿用。
4. 依赖栈:`entityctl site deps-add <site> --from-checkpoint
   <entity-deps.local.json>` 把已验证的栈登记进注册表(证据不符零写
   入),并在 site 上生成 `deps/<stack_id>/stack.yaml`。

## 第 2 步:逐 site 迁移旧树

```bash
entityctl site plan-migration <site>     # 只读:旧路径 → 新路径计划
```

计划 JSON 逐项给出 identity 维度(build/run)、旧 Locator、新 Locator
(`<site_root>/projects/<project>/{builds,runs}/<case>/<id>`)、磁盘存
在性,并把在途 run 标记为 `skip`;旧 roots 下未落账的目录列入
`untracked` 供人工核对。

然后对每一项 `move`:

1. **agent 执行移动**(本指南不替你做):`mv`、`rsync --remove-source-files`
   或 ssh 远端移动。保持目录内容逐字节一致。
2. **落账**:

   ```bash
   entityctl record relocate --project-root <project> [--case <slug>] \
     --dimension <build|run|data> --identity-id <id> --to <新绝对路径>
   ```

   relocate 在新路径重新探测证据(run 的 `run-manifest.json`、build 的
   可执行文件 sha256、data 的 `data-inventory.json`),证据一致才更新
   Locator 并写 `record.relocate` 审计事件;不符零写入。在途 run 被拒
   绝。
3. **校验**:`entityctl status --project-root <project>` 确认就绪板与
   run 台账正常;`entityctl doctor` 无 failure。
4. 全部项完成后,agent 验证旧目录为空(`find <old_root> -type f` 应为
   空;`untracked` 项已人工处置),由用户手动删除旧目录。

新发生的 build/run 自动落新树(profile 带 `site_root` 时路径推导即新
布局);旧树只减不增。

## 逐 site checklist 模板

```text
site: <site_id>
[ ] sites/<site>.yaml 有 site_root;site sync 已刷 db
[ ] site init 骨架已建(或认领既有 entity-site.yaml)
[ ] deps 注册表:既有已验证栈已 deps-add
[ ] plan-migration 计划已审阅;moves=N skips=M(在途)
[ ] 逐项:移动 → record relocate → status 校验
[ ] 在途 run:record run-exit 终态后补齐迁移
[ ] untracked 目录已人工核对处置
[ ] 旧目录验证为空,用户已手动删除
[ ] doctor 无 failure;current identity Locator 全部指向新树
```

## 迁移完成标准

- 所有 current identity 的 Locator 指向新树;
- 旧路径不再被任何 current identity 引用;
- 旧目录验证为空后删除;`entityctl doctor` 全绿。
