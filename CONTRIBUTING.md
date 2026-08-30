# Contributing

## Active release line

`0.8.0rc` is the release-candidate branch. The maintained runtime, schemas,
tests, and four Agent skills are under `vnext/`. The root legacy implementation
is retained for 0.7.x migration and should not receive new 0.8 behavior.

Do not create nested Git repositories or submodules inside a skill. Changes to
the runtime, schemas, skills, and tests that express one contract should land
together.

Short-lived branches may be created from `0.8.0rc` with names such as:

```text
feat/workspace-summary
fix/run-attempt-output
docs/pgen-contract
```

## Design rules

- Keep `Source + PGen -> Build -> Run` as the complete first-class model.
- Prefer standard-library code, ordinary files, and explicit JSON records.
- Do not add a database, content hashing, hidden state, mandatory preflight, or
  security machinery without a concrete product requirement.
- Preserve the small recovery rule around uncertain submissions: inspect the
  Site before creating another Attempt.
- Update the relevant `SKILL.md`, README/architecture text, examples, and tests
  when a public contract changes.

## Verification

Run before committing:

```bash
PYTHONPATH=vnext python3 -W error::ResourceWarning \
  -m unittest discover -s vnext/tests -t vnext -v
python3 -m compileall -q vnext
git diff --check
```

Validate all four `vnext/skills/*/SKILL.md` files with the Codex
`skill-creator` `quick_validate.py` helper. Also verify that:

- `vnext/entity/__init__.py` and `vnext/pyproject.toml` carry the same version;
- `vnext/bin/entity --version` reports that version;
- examples are valid JSON and referenced skill resources exist;
- a copied `vnext/` tree runs without the legacy repository.

Legacy 0.7.x tests may be run when migration compatibility is changed; they are
not the primary 0.8.0rc release suite.

## Release

After the RC suite and the separately authorized real Site canary pass, merge
`0.8.0rc` into `main`, create the final `0.8.0` tag, and publish the four skills
together. Do not publish `entity-ledger` as a 0.8 skill.
