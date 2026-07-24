# Contributing

## Git Boundaries

`entity-skills` is the single source repository for the four skills. Do not create a `.git` inside `skills/*`, and do not turn a skill into a submodule.

Create short-lived branches from `main`, named `<type>/<scope>-<summary>`, for example:

```text
feat/ledger-resume-flow
fix/env-build-compatibility
docs/pgen-boundary-contract
```

Commit messages use the skill scope:

```text
feat(ledger): add resume handoff
fix(env-build): reject stale compatibility state
docs(pgen): clarify TOML contract
refactor(nt2py): simplify data inventory
```

A behavioral change that affects the Ledger, sub-skills, and tests at the same time should be submitted as a single atomic pull request — do not split it across different repositories or long-lived branches.

## Verification

Run before committing:

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s skills/entity-pgen/tests -v
python3 -m unittest discover -s skills/entity-env-build/tests -v
python3 -m py_compile \
  tools/skill_observability/*.py \
  tools/skill_observability/adapters/*.py \
  skills/entity-ledger/scripts/*.py \
  skills/entity-pgen/scripts/*.py \
  skills/entity-env-build/scripts/*.py \
  skills/entity-nt2py/scripts/*.py

for schema in tools/skill_observability/schemas/*.json; do
  python3 -m json.tool "$schema" >/dev/null
done
```

All four `SKILL.md` files must keep valid YAML frontmatter and pass skill structure validation.

## Release

Version numbers apply to the whole skills package. Before releasing, confirm the working tree is clean and CI passes, then create an annotated tag on `main`:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin main --follow-tags
```

New versions are no longer released from the old single-skill repositories.
