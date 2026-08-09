# Ledger 运行时参考

这是一份内部/调试参考。正常工作使用 `SKILL.md` 中记录的
`entityctl status`、`record` 原语和 `show`。

## 控制器

`ledger.db` 是唯一的结构化权威。schema v3 在 SQLite 中存储 Site、
Project（project_uid + slug + root,1:N Case）、Case（带 project_uid
外键）、identity、紧凑证据和事件（events 为被动审计）。大型
产物和日志保留在其 owner Site。并发控制是 `BEGIN IMMEDIATE`
文件锁；旧 plan/apply 协议的 Operation/Step 记录已随 v1→v2 迁移
归档到 `<ledger_home>/archive/`。

控制器 home（ledger.db 所在目录）的解析顺序：显式参数
（`--ledger-home` 或 `ENTITY_LEDGER_HOME`）> `ENTITY_WORKSPACE`
环境变量（`<workspace>/.ledger`）>
`~/.entity-ledger/active-workspace` 指针 > 旧 `~/.entity-ledger`
（兼容回退，stderr 打一次 deprecation 警告）。snapshots 目录随 db
解析到同一 home 下。

在不改变控制器状态的情况下导出：

```bash
python3 scripts/entityctl.py export --output /absolute/ledger-export.json
```

## record 落账与 receipt

每个 record 原语先在控制器本地推导 identity（内容寻址哈希），再经
`ExecutorClient` 把结构化 envelope 交给执行 Site 上的执行器。写入类
原语自带证据探测：执行器重新读取并验证 receipt/输出 fingerprint，
全部通过后原语才在一个 SQLite 事务中落账 identity、current 投影和
审计事件。任何一步失败都是零写入，修复原因后重跑同一条原语即可。

提交作业（`record run-launch`）是不可盲目重放的外部效果，执行器内部
按 `intent_written → effect_observed → outputs_verified` 推进 receipt：
重复执行命中已验证的 receipt 直接短路；进程在提交后、验证前中断时，
按 launch comment 在 scheduler/进程表中找回唯一匹配的已提交效果并
认领，绝不二次提交。多个匹配属于异常——采纳其中任何一个都不安全。

## 改名与存储迁移边界

entity-router → entity-ledger 改名带来三处兼容边界：

- **存储目录与数据库**：首次解析 Ledger home 时自动把
  `~/.entity-router` 迁移为 `~/.entity-ledger`（home 内的
  `router.db` 随之改名为 `ledger.db`）。迁移是惰性的，只在
  命令真正解析 home 时发生，不会在 `--help` 等 parser 构建阶段
  触发。`ENTITY_ROUTER_HOME` 环境变量仍被识别（在
  `ENTITY_LEDGER_HOME` 未设置时）。
- **receipt 身份**：改名前已 prepare/inventory 的 run，其 staging
  receipts 里的 receipt 记录着旧的 `plan_hash`（其中嵌有旧 kind
  字符串）。对同一个 run 重跑 prepare/data 会命中 "existing receipt
  belongs to another Step"。修复办法：删除该 run 在
  `<staging_root>/<case_uid>/<operation_id>/receipts/` 下的旧
  receipt 后重跑原语。
- **在途作业恢复**：改名前提交的在途作业带有
  `entity-router:` 前缀的 launch comment。恢复匹配（Slurm 的
  squeue/sacct 扫描与 direct 的 pgrep 扫描）同时接受
  `entity-ledger:` 和 `entity-router:` 两种前缀，旧作业会被认领
  而不是重复提交；新提交一律使用 `entity-ledger:` 前缀。

## 执行器 transport

本地和 SSH 执行的是同一个 `entity_ledger_executor.py` 的 validate/execute/verify
逻辑和同一份请求 envelope 协议，但调用方式不同：本地 Site 由
`ExecutorClient` 在进程内直接调用（receipt 落盘与 allowed_roots 校验完全
相同，省掉脚本拷贝、请求文件和子进程）;SSH Site 把内容寻址的执行器副本
部署到远端后按子进程调用：

```text
<staging_root>/.entity-ledger-executor/<sha256>/entity_ledger_executor.py
```

SSH transport 只负责暂存精确的 payload/请求 JSON、调用白名单内的动作、
并返回结构化结果。run 提交接受经过校验的 `run_spec`；
执行器渲染由 Site profile 的 `scheduler.kind` 选定的提交
脚本——`slurm` 对应 sbatch 脚本,`direct` 对应自包含的 `run.sh`。
调用方提供的 shell、命令、前置命令或脚本文本都会被拒绝。

launch 的 effect identity 因后端而异。Slurm 记录
`{"scheduler": "slurm", "job_id": ..., "comment": ...}`；direct 后端
（无 scheduler 的 Site）记录分离的进程：

```json
{"scheduler": "direct", "pid": 418795, "pgid": 418795,
 "run_root": "...", "log": "<run_root>/run.log",
 "exit_file": "<run_root>/.entity-exit-code", "comment": "entity-ledger:..."}
```

被启动的进程是会话首进程（`pid == pgid`）；walltime 由
`run.sh` 内部的 `timeout`（或内嵌的 bash 等价物）强制执行，
退出码——包括超时时的 124——被写入退出文件。
恢复时通过 `pgrep -f` 扫描 launch comment 并匹配进程工作目录
来认领一次被中断的 launch，且只采纳唯一匹配。

## Site profile

site 信息的权威是 workspace 的 `sites/<site>.yaml` 档案（transport、
scheduler、machine、site_root、projects、deps 注册表、notes）;
`entityctl site sync` 把档案刷新进 store,`site list/show` 给出
db + 档案的合并视图。旧流程的 `site add` 仍可直接写 db（在合并视图中
标注 db-only)。

```bash
python3 scripts/entityctl.py site sync
python3 scripts/entityctl.py site list
```

profile 带 `site_root` 时，新 build/run/staging 落在
`<site_root>/projects/<project>/{builds,runs,staging}/<case>/<id>`
（layout `site-tree`)；没有 `site_root` 的旧 profile 需要
`build_root`、`run_root` 和 `staging_root` 三个独立根（layout
`legacy-roots`)，旧 Locator 保持可引用。run
Site 还要声明 transport 和 scheduler（`slurm`，或对无
scheduler 的 Site 使用 `none`）。策略可以提供 `default_cpus_per_gpu`、
`default_partition`、`default_qos`、`default_submit_user`、
`default_gres`（Slurm gres 规格 `gpu[:type]:count`，如
`gpu:V100:1`，用于同分区多 GPU 类型时钉住类型）和
`max_cpu_per_gpu`。run 的 gres 解析顺序：显式 `--gres` >
policy `default_gres` > 通用 `gpu:<N>`；解析结果记入 run identity
的 compute。direct 后端忽略 `default_partition` 和
`default_qos`（它们归一化为空字符串），gres 同样忽略（归一化为
""），并将提交用户默认为当前用户。密钥和集群修复命令绝不应出现在
profile 或档案中。

## live status 探测

默认 status 是控制器本地的，且绝不写状态；只有 `--live` 才接触
执行 Site，且最多做三次有界的后端查询。在 Slurm Site 上：作业状态、
作业离开队列后的 `sacct` 兜底查询，以及对 Case run root 的未跟踪
作业扫描。在无 scheduler 的 Site 上：退出文件、`kill -0` 存活探测，
以及外来进程扫描——当 Site 拒绝该扫描时降级为 `unknown`（绝不视为
失败）。`--live` 还会报告 `divergences`，对带外变更分类：
`job_gone`（后端对已记录的作业或进程没有记录）、`state_mismatch`
（作业到达了 Ledger 从未观测到的终态），以及 `untracked_job`
（一个外来的 scheduler 作业或进程正在 Case run root 中运行——
这是绕过记录原语的证据）。
