# entity-env-build

在一个明确的 execution site 上构造 Entity build 环境并编译源码。当前
schema v2 使用彼此独立的：

- `entity.site_id`
- `entity.source_checkout`
- `entity.build_root`
- `entity.deps_root`
- `entity.artifacts_root`

不存在统一 workspace 根目录的要求。完整行为协议见 `SKILL.md`，JSON 字段
见 `references/json-contracts.md`。

```bash
REQ=/absolute/artifacts/requirements.json
CP=/absolute/artifacts/entity-deps.local.json
ENV=/absolute/artifacts/env.sh
BUILD=/absolute/artifacts/entity-build.sh

python3 scripts/entity_checkpoint.py validate "$REQ"
python3 scripts/entity_checkpoint.py create "$REQ" --output "$CP"
python3 scripts/entity_compat.py "$REQ" --checkpoint "$CP"
python3 scripts/entity_generate.py env "$CP" --output "$ENV"
python3 scripts/entity_generate.py build "$REQ" \
  --env "$ENV" --checkpoint "$CP" --output "$BUILD"
python3 scripts/entity_run.py build "$REQ" --script "$BUILD"
```

依赖源码构建脚本默认进入 `<deps_root>/scripts/`，安装 prefix 也位于
`deps_root`。日志、checkpoint 和派生脚本位于 `artifacts_root`，CMake tree
位于不可变 build identity 的 `build_root`。

Schema v1 `checkout_root/workdir` 仅用于显式 legacy 兼容，新 workflow 不应
生成 v1。
