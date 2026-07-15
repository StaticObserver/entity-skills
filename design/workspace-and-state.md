# Entity 多端点 Workspace 与 Case v3

日期：2026-07-14
状态：当前实现基准

## 1. 原则

Case 是逻辑资源图，不是包含源码、依赖、build、run 和 data 的大目录。
Agent 所在控制端与代码执行端可以不同；每个资源用
`Locator = {site_id, path}` 标识。JSON 只保存结构化 Locator，CLI 使用
`site_id:/absolute/path`。

Router 状态由控制端单写。源码、build、run、raw data 和 analysis 可以
分别位于不同 site，目录不要求共同父目录。

## 2. 控制端

默认 `ENTITY_ROUTER_HOME=~/.entity-router`：

```text
~/.entity-router/
├── registry.json
├── sites/<site_id>.json
└── cases/<case_uid>-<label>/
    ├── case.json
    ├── events.jsonl
    ├── actions/<action_id>/{request.json,result.json}
    ├── history/
    └── evidence/
```

`registry.json` 是可重建索引；`case.json` 是控制快照；owner 文件仍是各
领域事实源。自定义 control root 可以注册。控制状态不得放入源码 checkout，
远端 Worker 不得修改控制状态。

## 3. Site

Site profile 记录稳定 `site_id`、local/SSH transport、SSH alias、scheduler
kind 和独立 roots：`source_root/build_root/run_root/deps_root/staging_root/
analysis_root`。凭据不进入 profile。HPC 登录节点、scheduler、计算节点和
共享文件系统构成一个逻辑 site。

推荐但不强制：

```text
<build_root>/<case_uid>/<build_id>
<run_root>/<case_uid>/<run_id>
<staging_root>/<case_uid>/<snapshot_id>
```

某 root 只在当前 phase 需要时成为门禁；orient 不因未来 phase 的 root
尚未配置而阻塞。

## 4. Source

每个 Case 只有一个可编辑 authority，默认控制端本地，也可为远端。
PGen/TOML/design 必须位于 authority root 内；replica 默认不可编辑。

支持：

- `git-ref`：精确 commit checkout，正式 build/run 默认；
- `snapshot`：dirty/untracked 文件进入 manifest，按内容哈希命名并逐文件复核；
- `shared`：声明共享映射后验证 Git tree/文件 hash；
- `external`：用户管理副本，只有 revision/hash 一致才接受。

普通可变 rsync/tar 只是传输实现，不是 source identity。snapshot 目录不可
覆盖。Authority 切换是 `source.transfer-authority` Action：先证明两端
clean commit/tree 一致，再原子切换 authority 和 PGen locators；禁止双端
同时可编辑。

## 5. Build、run、data、analysis

Build request schema v2 显式记录 `site_id/source_checkout/build_root/
deps_root/artifacts_root`，不再使用含混 `entity.workdir`。每个 build ID 引用
一个 SourceRevision；每个 run ID 引用一个 build ID。参数或 checkpoint 变化
创建新 run identity，历史路径不覆盖。

Raw data 在 data site 权威保存。`data.inspect`/`analysis.run` 默认靠近数据
执行，只拉取 inventory、日志、图像、报告或用户明确选择的数据子集。

## 6. Evidence 与恢复

Evidence 至少包含 Locator、kind、fingerprint、observed time 和 observer
site。远端 request 是 staging root 中的不可变副本；Worker 结果只是声明，
Router 完成 Action 前必须重新 probe 文件、Git、scheduler 或数据。

远端不可达时，旧 observation 不作为当前事实；Action 进入 blocked/suspended，
恢复后重新 probe。Source 变化使 build/run stale；build 变化使未启动 run
stale；data 变化使相关 analysis stale。

## 7. 迁移

`migrate-case --dry-run` 只展示 v2 到 Locator 的映射；`--commit` 创建新的
v3 control Case，将旧路径映射到 `legacy-local` site，并复制旧控制记录。
它不移动或删除源码、build、run 或 raw data。新状态验证完成后才 suspend
旧控制面，并保留 migration backup，防止双控制。

PGen preflight 通过 registry + Locator 判断 managed 状态；不再沿祖先目录
寻找 `_case/case.json`。
