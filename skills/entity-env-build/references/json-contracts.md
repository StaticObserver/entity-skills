# JSON 契约

`requirements.json` 是用户意图加上构建站点范围。
`entity-deps.local.json` 是从该确切请求派生的站点本地依赖 checkpoint。
`env.sh` 与 `entity-build.sh` 是派生产物。

## requirements.json schema v2

```json
{
  "schema_version": 2,
  "entity": {
    "site_id": "cluster-a",
    "source_checkout": "/stage/case/source-id",
    "build_root": "/scratch/build/case/build-id",
    "deps_root": "/shared/deps/entity",
    "artifacts_root": "/shared/build-records/case/build-id",
    "source_revision": {"kind": "git", "commit": "", "tree": ""},
    "version_bucket": "1.4.0",
    "dependency_profile": "modern"
  },
  "environment": {
    "backend": "cpu",
    "gpu_arch": "",
    "output": true,
    "mpi": false,
    "gpu_aware_mpi": false,
    "dependency_policy": "reuse-existing"
  },
  "compile": {
    "pgen": "",
    "precision": "single",
    "deposit": "zigzag",
    "shape_order": "1",
    "cxx_standard": "20",
    "debug": false,
    "tests": false,
    "build_intent": "unspecified",
    "jobs": "",
    "build_dir": ""
  },
  "artifacts": {
    "entity_build_sh": "",
    "logs_dir": ""
  }
}
```

校验/构建之前必需：

- `entity.site_id`、`source_checkout`、不可变的 `source_revision`、
  `build_root` 与 `deps_root`；
- 建议提供 `entity.artifacts_root`，省略时默认为
  `<build_root>/_artifacts`；
- `compile.pgen` 与 `environment.backend`；
- 受支持的 Entity 版本/依赖 profile。

`compile.build_dir` 默认为 `entity.build_root`，并在脚本生成前回写。
所有路径都是 `entity.site_id` 上的绝对路径；它们不隐含共同的父目录。
新工作流程必须使用 v2。Schema v1 的 `checkout_root/workdir` 仅为明确的
旧版兼容而存在。

## entity-deps.local.json

checkpoint 与其请求具有相同的 schema 版本，并记录：

```json
{
  "schema_version": 2,
  "requirements": {"path": "", "embedded": {}},
  "target": {"hostname": "", "os": "", "arch": "", "shell": "", "context": "login"},
  "entity": {
    "site_id": "",
    "source_checkout": "",
    "build_root": "",
    "deps_root": "",
    "artifacts_root": "",
    "version_bucket": "",
    "dependency_profile": ""
  },
  "stack_id": "",
  "candidates": {},
  "selected": {},
  "decisions": {},
  "paths": {},
  "build_scripts": {"directory": "", "generated_at": "", "scripts": {}},
  "compatibility": {"status": "unknown", "checked_at": "", "checks": [], "issues": []},
  "env_sh": {"path": "", "status": "missing", "generated_at": "", "validation": {}},
  "status": {"checkpoint": "partial", "satisfies_requirements_json": false, "ready_for_entity_build": false, "reuse_notes": []}
}
```

`stack_id` 是可选顶层字段：仅当 checkpoint 的 `selected` 与注册表某
栈的 packages 完全一致时由 `--from-registry` 写入；`--from-discovery`
补缺或 `record-install` 改变 selected 后该字段被移除并降级为
`status.reuse_notes` 记录。

每个选定的依赖记录 provider、prefix/bin/include/lib/config 路径、版本、
编译器/MPI 签名、环境添加项、编译配置与验证。只有当内嵌的
requirements、执行站点、全部五个解析后的路径、版本 profile 与工具链
选择与当前请求匹配时，checkpoint 才可复用。

`decisions.parameters` 记录编译参数确认这一硬性门槛，由
`entity_checkpoint.py confirm` 写入：

```json
{
  "digest": "sha256:<hex>",
  "confirmed_by": "<actor>",
  "confirmed_at": "<UTC ISO timestamp>",
  "defaults": false,
  "card": {
    "schema_version": 1,
    "kind": "entity-parameter-card",
    "domain": "build",
    "fields": {"environment.backend": {"value": "cpu", "tier": 1}},
    "digest": "sha256:<hex>"
  }
}
```

`card` 是确认时从 requirements 派生的参数卡
（`entity_schema.py:parameter_card`）；`digest` 是它的摘要。当记录
缺失或摘要不再匹配当前 requirements 时，兼容性检查会使
`parameters.confirmation` 失败。

兼容性状态：

- `pass`：当前请求可用已证明的依赖构建；
- `warn`：仅剩已接受的、有文档记录的偏差；
- `fail`：至少存在一个硬性不兼容；
- `unknown`：检查器尚未验证当前状态。

override 记录用户决策，可以把一个已知检查降级为警告。它不能掩盖缺失
的路径、源码/构建站点不匹配、不受支持的 schema/版本，或缺失的可执行
文件。

## site deps 注册表与 stack_id

checkpoint 可带顶层 `stack_id`：它引用该 checkpoint 消费（或产生）的
site deps 栈。注册表由 Ledger 侧维护（workspace `sites/<site>.yaml` 的
deps 节），通过 `entityctl site deps <site> --json` 导出：

```json
{
  "site_id": "cluster-a",
  "stacks": [
    {
      "stack_id": "gcc12.3.0-kokkos5.1.0-1a2b3c4d",
      "kind": "build",
      "status": "verified",
      "signature": {"backend": "cuda", "mpi": false, "gpu_aware_mpi": false,
                    "output": true, "cxx_standard": "20",
                    "dependency_profile": "modern"},
      "packages": [{"name": "kokkos", "version": "5.1.0",
                    "prefix": "/site/deps/<stack_id>/kokkos", "provider": "module"}],
      "recipe": {"providers": {"kokkos": "module"}, "parameter_digest": "sha256:..."},
      "env_sh": "/site/deps/<stack_id>/env.sh"
    }
  ]
}
```

`entity_checkpoint.py create --from-registry <registry.json>` 时，签名
与当前 requirements 完全匹配且 `status=verified`、`kind=build`（缺省
视为 build；注册表可能混有 `kind=analysis` 的 Python 环境栈，build
消费不匹配它们）的第一个栈预填
`selected`（保留各包原始 provider，来源记 `validation.source`)，并把 `stack_id` 写进 checkpoint；
未覆盖的依赖由 `--from-discovery`/临场探测补缺。注册表条目随后与探测
条目一样接受兼容性检查。新栈在 confirm + compatibility `pass` 后用
`entityctl site deps-add <site> --from-checkpoint <entity-deps.local.json>`
回写注册表（证据不符零写入）。

## 派生产物

- `env.sh` 从 checkpoint 导出依赖/工具链路径，包括
  `ENTITY_DEPS_ROOT`；它不定义 `ENTITY_WORKDIR`。
- `entity-build.sh` 把 `entity.source_checkout` 配置到
  `entity.build_root`，并将日志写入 `entity.artifacts_root/build-logs`。
- requirements 中的 `build_result` 记录状态、时间戳、退出码、运行 ID、
  runner 日志、脚本以及预期可执行文件证据。

站点特有的 modules、前置命令与环境覆盖属于 checkpoint/站点笔记。凭据
绝不进入任何一个 JSON 文件。
