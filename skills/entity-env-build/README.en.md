# entity-env-build

Configure and compile Entity at one explicit execution site. Schema v2 uses
independent `site_id`, `source_checkout`, `build_root`, `deps_root`, and
`artifacts_root` values; no common workspace parent is required.

See `SKILL.md` for behavior and `references/json-contracts.md` for fields.

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

Dependency scripts and prefixes live under `deps_root`; checkpoints, generated
scripts, and logs live under `artifacts_root`; the CMake tree lives at the
immutable build identity's `build_root`. Schema v1 `checkout_root/workdir` is
legacy compatibility only.
