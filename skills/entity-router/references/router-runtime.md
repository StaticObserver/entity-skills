# Router 运行时参考

这是一份内部/调试参考。正常工作使用 `SKILL.md` 中记录的
`entityctl status`、`record` 原语和 `show`。

## 控制器

`$ENTITY_ROUTER_HOME/router.db`（默认 `~/.entity-router/router.db`）是
唯一的结构化权威。它在 SQLite 中存储 Site、Case、项目绑定、
identity、Operation、Step、紧凑证据和事件。大型
产物和日志保留在其 owner Site。

在不改变控制器状态的情况下导出：

```bash
python3 scripts/entityctl.py export --output /absolute/router-export.json
```

## Operation 日志

> 注意：本节描述的 plan/apply 协议（GoalSpec、Operation Plan、Step
> 推进与重新 Apply 恢复）已退役，仅用于解读旧 store 中导出的
> Operation 记录。当前写入路径是 `entityctl record` 原语。

每个 Operation 都有不可变的 Goal 和 Plan 哈希。内部 Step 依次推进：

```text
pending → intent_written → effect_observed → verified → committed
```

执行 Site 为每个 Step 持有一份 receipt。Apply 记录控制器
intent，调用内容寻址执行器，让执行器重新读取并
验证 receipt/输出 fingerprint，然后在一个 SQLite 事务中
提交该 Step 以及 identity 和当前投影。

进程丢失、网络中断或控制器瞬时错误都会留下可恢复的
receipt/日志。用同一个 Plan 重新运行 Apply 即可。匹配同一次
launch intent 的 scheduler 作业或进程出现多个时，属于终态
`anomaly`，因为采纳其中任何一个都是不安全的。

## 执行器 transport

本地和 SSH 使用相同的 `entity_router_executor.py` 内容和 StepSpec。
远端副本位于：

```text
<staging_root>/.entity-router-executor/<sha256>/entity_router_executor.py
```

Transport 只负责暂存精确的 payload/请求 JSON、调用白名单内的 Step、
并返回结构化结果。run 提交接受经过校验的 `run_spec`；
执行器渲染由 Plan 的 `scheduler` 字段选定的提交
脚本——`slurm` 对应 sbatch 脚本，`direct` 对应自包含的 `run.sh`。
调用方提供的 shell、命令、前置命令或脚本文本都会被拒绝。

launch 的 effect identity 因后端而异。Slurm 记录
`{"scheduler": "slurm", "job_id": ..., "comment": ...}`；direct 后端
（无 scheduler 的 Site）记录分离的进程：

```json
{"scheduler": "direct", "pid": 418795, "pgid": 418795,
 "run_root": "...", "log": "<run_root>/run.log",
 "exit_file": "<run_root>/.entity-exit-code", "comment": "entity-router:..."}
```

被启动的进程是会话首进程（`pid == pgid`）；walltime 由
`run.sh` 内部的 `timeout`（或内嵌的 bash 等价物）强制执行，
退出码——包括超时时的 124——被写入退出文件。
恢复时通过 `pgrep -f` 扫描 launch comment 并匹配进程工作目录
来认领一次被中断的 launch，且只采纳唯一匹配。

## Site profile

Site 直接注册进 store：

```bash
python3 scripts/entityctl.py site add --profile /absolute/site-profile.json
python3 scripts/entityctl.py site list
```

必需的运行根目录是 `build_root`、`run_root` 和 `staging_root`；run
Site 还要声明 transport 和 scheduler（`slurm`，或对无
scheduler 的 Site 使用 `none`）。策略可以提供 `default_cpus_per_gpu`、
`default_partition`、`default_qos`、`default_submit_user` 和
`max_cpu_per_gpu`。direct 后端忽略 `default_partition` 和
`default_qos`（它们归一化为空字符串），并将提交用户
默认为当前用户。密钥和集群修复命令绝不应出现在
profile 中。
