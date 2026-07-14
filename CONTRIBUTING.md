# Contributing

## Git 边界

`entity-skills` 是四个 skill 的唯一源仓库。不要在 `skills/*` 内创建 `.git`，也不要把 skill 改为 submodule。

从 `main` 创建短期分支，命名使用 `<type>/<scope>-<summary>`，例如：

```text
feat/router-resume-flow
fix/env-build-compatibility
docs/pgen-boundary-contract
```

提交信息使用 skill scope：

```text
feat(router): add resume handoff
fix(env-build): reject stale compatibility state
docs(pgen): clarify TOML contract
refactor(nt2py): simplify data inventory
```

一次行为变更如果同时影响 Router、子 skill 和测试，应作为一个原子 pull request 提交，不要拆到不同仓库或长期分支。

## 验证

提交前运行：

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s skills/entity-env-build/tests -v
python3 -m py_compile \
  skills/entity-router/scripts/*.py \
  skills/entity-env-build/scripts/*.py \
  skills/entity-nt2py/scripts/*.py
```

四个 `SKILL.md` 都必须保留合法 YAML frontmatter，并通过 skill 结构校验。

## 发布

版本号作用于整个 skills package。发布前确认工作区干净、CI 通过，然后在 `main` 上创建 annotated tag：

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin main --follow-tags
```

不再从旧的单 skill 仓库发布新版本。
