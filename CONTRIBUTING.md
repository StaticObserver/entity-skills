# Contributing

## Git Boundaries

`entity-skills` is the single source repository for the four skills. Do not create a `.git` inside `skills/*`, and do not turn a skill into a submodule.

## Branch Maintenance Rules

- `main` mirrors the currently published release; it only accepts merges at release time, no direct development. Since 0.7.1, `main` carries the English content, accompanied by a full Chinese README (`README.zh-CN.md`).
- The `X.Y.Zrc` branch (e.g. `0.6.0rc`) is the version under development; day-to-day development happens on the rc branch. Create short-lived branches from the rc branch and merge them back into it.
- Development versions use Chinese throughout (docs, skill descriptions, comments, user-visible strings); they are translated into `main` at release time.
- The `main_en` branch is retired (since 0.7.1, English content is published directly on `main`).

Create short-lived branches from the current rc branch, named `<type>/<scope>-<summary>`, for example:

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

Version numbers apply to the whole skills package. Before releasing, confirm the working tree is clean and verification passes. Since 0.7.1, only the English version is published (with a Chinese README attached); the Chinese release is no longer published. Release process (using `X.Y.Z` as the example):

1. Merge the rc branch into `main`, translating all Chinese content to English as part of the merge (code identifiers, CLI commands, config keys, and technical terms stay as-is). `README.md` is translated to English with a link to the Chinese README at the top; at the same time, generate (or update) `README.zh-CN.md` from the rc branch's Chinese README. Confirm the repo has no CJK characters outside `README.zh-CN.md` and the test baseline is unchanged, then push.
2. Create an annotated tag on `main` and publish the GitHub release (no language suffix on the tag):

   ```bash
   git tag -a X.Y.Z -m "Release X.Y.Z"
   git push origin X.Y.Z
   gh release create X.Y.Z --title "X.Y.Z" --target main
   ```

3. Rename the rc branch to the next development version (e.g. `0.7.1rc` → `0.7.2rc`), push the new branch and delete the old remote branch.

New versions are no longer released from the old single-skill repositories.
