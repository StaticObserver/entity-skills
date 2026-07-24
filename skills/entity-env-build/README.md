# entity-env-build

Set up the Entity build environment and compile the source at one explicit
execution site. The current schema v2 uses mutually independent:

- `entity.site_id`
- `entity.source_checkout`
- `entity.build_root`
- `entity.deps_root`
- `entity.artifacts_root`

There is no requirement for a unified workspace root. See `SKILL.md` for the
full behavior protocol and `references/json-contracts.md` for the JSON fields.

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

Dependency source-build scripts go to `<deps_root>/scripts/` by default, and
install prefixes also live under `deps_root`. Logs, checkpoints, and derived
scripts live under `artifacts_root`; the CMake tree lives at the immutable
build identity's `build_root`.

Schema v1 `checkout_root/workdir` is for explicit legacy compatibility only;
new workflows must not generate v1.
