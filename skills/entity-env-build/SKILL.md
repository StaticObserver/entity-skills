---
name: entity-env-build
description: 在一个明确的执行站点配置、验证并执行 Entity 依赖与源码构建。适用于 requirements.json、entity-deps.local.json、兼容性检查、env.sh、entity-build.sh、依赖修复与可验证的编译。输入使用相互独立的 site_id、source_checkout、build_root、deps_root 与 artifacts_root 路径；不要假设存在共享的 ENTITY_WORKDIR。
---

# Entity 环境构建

负责构建站点的环境与 Entity 编译。本技能可以携带精确路径独立运行，也可以
配合 Ledger 使用：构建验证通过后由 `entityctl record build` 把 checkpoint
登记进 Case 台账。它不选择 PGen 物理内容、不启动模拟、
不分析输出，也不修改 Entity 核心代码。

## 必需的构建站点契约

在写入或执行任何内容之前，先为同一个逻辑站点获取以下明确的值：

```json
{
  "schema_version": 2,
  "entity": {
    "site_id": "cluster-a",
    "source_checkout": "/shared/stage/<case_uid>/<source-id>",
    "build_root": "/scratch/build/<case_uid>/<build_id>",
    "deps_root": "/shared/deps/entity",
    "artifacts_root": "/shared/records/<case_uid>/<build_id>",
    "version_bucket": "1.4.0",
    "dependency_profile": "modern"
  }
}
```

- `source_checkout` 是本构建使用的、经过验证的物化源码版本。
- `build_root` 是一个不可变构建身份的 CMake 树。
- `deps_root` 存放可复用的依赖前缀、源码以及生成的依赖脚本。
- `artifacts_root` 存放 requirements/checkpoint/env/构建脚本/日志。
- 这些路径不需要共享父目录，也不需要靠近 Ledger 控制路径、源码权威
  路径、运行路径或数据路径。
- `site_id` 在路径变化时保持稳定，并为可复用的机器笔记提供键。

Schema v1 的 `checkout_root/workdir` 仅在明确的旧版迁移时被接受。绝不从
旧的单体式约定生成新状态。

仅在调用方提供的执行 Site 与 Locator 授权路径上执行，绝不写入 Ledger
控制状态。远程 Worker 返回证据；由控制器提交状态。

## 硬性门槛

- 确认精确的源码版本/快照与构建 ID。当需要物化版本时，不要从可变的
  源码权威路径构建。
- 在环境探测之前，把所有用户构建选择记录到 `requirements.json` 中。
  不要从已安装的软件推断用户意图。
- 询问/确认：PGen、后端（`cpu/cuda/hip`）、MPI、GPU-aware MPI、输出、
  构建意图/优化、精度、deposit、shape order、debug、tests、依赖策略
  以及 jobs。对于 GPU 构建还要确认架构；对于 HIP 确认 ROCm/DTK 偏好
  与优化。用 `entity_checkpoint.py confirm <requirements.json>
  --checkpoint <entity-deps.local.json> --by <actor>` 记录确认；在
  确认摘要与当前 requirements 匹配之前，兼容性检查会使
  `parameters.confirmation` 失败，并且该失败时不得继续生成
  `env.sh` 或编译。
- 在 `requirements.json` 校验通过、兼容性为 `pass`、且 `env.sh` 是从
  当前 checkpoint 生成之前，不要编译。
- 依赖源码构建需要经过审查的计划与明确的许可。
- 不要静默弱化版本、编译器、CUDA/ROCm、MPI、HDF5、ADIOS2 或 Kokkos
  兼容性失败。
- 保留构建日志与结果证据。没有预期的可执行文件/日志证据的 shell
  退出声明不算成功。

字段细节见 `references/json-contracts.md`；选择依赖前阅读
`references/dependency-policy.md`；override 前阅读
`references/compatibility-check.md`；生成 Entity 构建前阅读
`references/entity-compile-options.md`。

## 工作流程

### 1. Requirements

在 `artifacts_root` 下编写 schema-v2 的 `requirements.json`。包含上述
五个站点/路径字段、由 Ledger 提供的源码版本身份、Entity 版本配置、
环境选择、编译选择以及期望的产物路径。校验：

```bash
python3 scripts/entity_checkpoint.py validate /artifacts/requirements.json
```

如果结果是 `partial`，解决选择冲突；生产构建不要传
`--allow-partial`。

### 2. 复用或构建依赖 checkpoint

解析 requirements.json 的依赖时按以下查找顺序，命中即用、逐层补缺：

1. **Site deps 注册表**(workspace 的 `sites/<site>.yaml` 权威):在控制
   器上导出注册表并传给 create——
   ```bash
   entityctl site deps <site_id> --json > /tmp/site-deps.json
   python3 scripts/entity_checkpoint.py create /artifacts/requirements.json \
     --from-registry /tmp/site-deps.json \
     --output /artifacts/entity-deps.local.json
   ```
   签名（backend/mpi/gpu_aware_mpi/output/cxx_standard/
   dependency_profile）与当前 requirements 完全匹配且
   `status=verified` 的栈直接预填 `selected`（保留各包的原始
   provider，来源由 `validation.source=site-registry` 承担）。注册表
   可能混有 `kind=analysis` 的 Python 环境栈——build 消费只匹配
   `kind=build`（缺省视为 build）。注册表
   里的 `env_sh` 路径仅供人读与审计——环境始终由
   `entity_generate.py env` 从当前 checkpoint 的 packages 重建。
   注册表命中不豁免任何门禁：compatibility 必须仍为 `pass` 才能编译。
2. **`entity-site.yaml` 标记**：在没有 workspace 的机器上，找
   `<site_root>/entity-site.yaml`（agent 找到它即知道 roots 清单）,
   再读 `deps/<stack_id>/stack.yaml` 了解既有栈；命中的栈可整理成
   registry JSON 走 `--from-registry`。
3. **临场探测补缺**：注册表未覆盖的依赖仍按原流程搜索 modules、系
   统软件包、已有前缀与用户管理的安装，用 `--from-discovery` 或
   `record-install` 补齐缺口。

然后检查确切的 `artifacts_root/entity-deps.local.json`（如果存在）。只有当
其内嵌的 requirements 与所有解析后的站点路径都匹配时才复用它。

```bash
python3 scripts/entity_checkpoint.py create /artifacts/requirements.json \
  --merge /artifacts/entity-deps.local.json \
  --output /artifacts/entity-deps.local.json
```

记录选定的编译器/依赖路径、版本、提供方、签名、验证结果以及必要的站
点前置命令。机器特有的修复属于站点笔记/checkpoint 数据，不属于本技能。

如果源码构建已获批准：

```bash
python3 scripts/entity_generate.py deps /artifacts/requirements.json \
  --checkpoint /artifacts/entity-deps.local.json
bash /deps/scripts/build-<dependency>.sh
```

前缀与源码下载保留在 `deps_root` 下；临时依赖构建与日志保留在
`artifacts_root` 下。按选定的依赖图确定构建顺序；ADIOS2 等待它所消费
的 Kokkos/HDF5 前缀。

**新栈回写（先验证后落账）**：一个新依赖栈走完 confirm 且兼容性
为 `pass` 后，把它登记进 site 注册表，下次解析即可直接命中：

```bash
# 在控制器上执行;env.sh 必须先存在于 <site_root>/deps/<stack_id>/env.sh
entityctl site deps-add <site_id> --from-checkpoint /artifacts/entity-deps.local.json
```

deps-add 会把栈条目（stack_id、signature、packages、recipe、
status=verified）写进 `sites/<site>.yaml` 的 deps 注册表，并在站点上生
成 `deps/<stack_id>/stack.yaml`;证据不符（checkpoint 未验证、env.sh
缺失）时零写入。

### 3. 兼容性与环境

```bash
python3 scripts/entity_compat.py /artifacts/requirements.json \
  --checkpoint /artifacts/entity-deps.local.json

python3 scripts/entity_generate.py env /artifacts/entity-deps.local.json \
  --output /artifacts/env.sh
```

兼容性必须是 `pass`。有文档记录且经用户接受的警告可以使用现有的
override 机制，但 override 不能掩盖缺失的二进制文件、错误的源码版本、
错误的执行站点路径或 ABI/工具链不匹配。

### 4. 生成并执行构建

```bash
python3 scripts/entity_generate.py build /artifacts/requirements.json \
  --env /artifacts/env.sh \
  --checkpoint /artifacts/entity-deps.local.json \
  --output /artifacts/entity-build.sh

python3 scripts/entity_run.py build /artifacts/requirements.json \
  --script /artifacts/entity-build.sh
```

生成的脚本在使用 `entity.source_checkout` 的同时配置并构建
`entity.build_root`。它将日志写入 `artifacts_root/build-logs` 下。绝不
为另一个源码版本或实质不同的编译契约复用同一个 build root；分配新的
构建 ID。

在集群上，按站点策略要求的上下文运行 configure/build。通用技能记录
scheduler 类型，但不编码分区、账户、module 栈或 SSH 凭据。

## 失败与交接

从第一个因果性错误和当前的 JSON/日志证据开始诊断。只修复构建方拥有
的状态。PGen/TOML 错误交回 `entity-pgen`；源码分歧或物化错误交回
`entity-ledger`；scheduler/运行错误交回 `entity-ledger`；未知的跨层
原因作为 `failure.triage` 证据返回。

成功需要：

- 当前 requirements 与站点路径的兼容性为 `pass`；
- 生成的 `env.sh` 与 `entity-build.sh` 绑定到当前 checkpoint；
- 构建命令退出码为零；
- 预期的可执行文件存在于不可变的 build root 内；
- 日志与构建结果标明 `site_id`、源码版本、构建 ID 以及相关的
  哈希/路径。

返回精确的产物 Locator 与验证信息，而不是复制的原始运行/数据状态。
