# Entity Router v3 控制协议

日期：2026-07-14
状态：当前实现基准

## 控制对象

```text
Case -> Workflow -> Action -> Worker
```

Case 用不可变 `case_uid` 标识，`case_id/name` 只是标签。控制端每个 Case
同时最多一个 active mutating Action。Worker 绑定 `(case_uid,
execution_domain)`，runtime Agent ID 不持久化。

## Action Contract v2

Request 包含 Case revision/UID、owner/domain、`execution_site_id`、Locator
inputs/read roots/write roots/protected paths、约束、预期输出和验收检查。
owner envelope 同时校验 site 与 path，并永远保护 controller Case root。

远端 Worker 只读 staging root 中的不可变 request；不能写 controller。
Result 记录 terminal status、输出 Evidence、verification、blocker、diagnosis
和 suggested owner。Router 重新 probe 后才写 result 并推进 state revision。

固定路由：

| Prefix | Owner | Domain |
|---|---|---|
| `pgen` | `entity-pgen` | `entity-pgen` |
| `source` | `router` | `playbook-sync` |
| `build` | `entity-env-build` | `entity-env-build` |
| `run` | `playbook-run` | `playbook-run` |
| `data` | `entity-nt2py` | `entity-nt2py` |
| `analysis` | `playbook-analysis` | `playbook-analysis` |
| `failure` | `failure-triage` | `failure-triage` |

## 标准循环

1. Orient：精确选择 Case/source authority/sites/当前 phase roots；
2. Recover：读取 Case 并重新 probe 外部事实；
3. Decide：只从 allowed actions 选择；
4. Start：原子写 controller request，必要时 stage 到远端；
5. Dispatch：Worker 只加载 owner skill/playbook 和 request；
6. Verify：检查输出 Locator、hash、Git、scheduler/data evidence；
7. Commit：写 result/event/state，传播 stale；
8. Continue/suspend/complete。

Action 启动后不可改变 owner、site、输入或 envelope；改变时关闭旧 Action
并创建新 Action。Revision 冲突必须重读，不得盲重试。

## 行为限制

- bounded read-only 或真正 standalone owner edit 可以直接调用 task skill；
- registered source 写入必须有匹配的 active Action；
- PGen 只在 source authority site 修改 PGen/TOML/design；
- build 只写 build site envelope，run 只写 run identity；
- source authority transfer 必须独立 Action；
- 不猜“最新” checkout/build/run；
- 不把 Worker 总结当证据；
- 不复制完整 raw data 作为默认分析流程；
- offline site 的缓存 observation 不推进状态。

状态工具 `entity_router_state.py` 管 Case/Action/revision/migration；
`entity_router_site.py` 管 site/profile/probe/materialization。通用核心不保存
SSH 凭据、partition/account/module 修复等 site-specific 内容。
