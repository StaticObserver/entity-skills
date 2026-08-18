# Contributing

## Git 边界

`entity-skills` 是四个 skill 的唯一源仓库。不要在 `skills/*` 内创建 `.git`，也不要把 skill 改为 submodule。

## 分支维护规则

- `main` 与当前已发布 release 的内容保持一致，只接受发布时的合并，不在上面直接开发。自 0.7.1 起 `main` 为英文内容，另附完整中文 README（`README.zh-CN.md`）。
- `X.Y.Zrc` 分支（例如 `0.6.0rc`）是当前正在开发的版本，日常开发都在 rc 分支上进行；从 rc 分支创建短期分支，合并回 rc。
- 开发版本全程使用中文（文档、技能说明、注释、用户可见字符串），发布时翻译进 `main`。
- `main_en` 分支已废弃（0.7.1 起英文内容直接在 `main` 上发布）。

从当前 rc 分支创建短期分支，命名使用 `<type>/<scope>-<summary>`，例如：

```text
feat/ledger-resume-flow
fix/env-build-compatibility
docs/pgen-boundary-contract
```

提交信息使用 skill scope：

```text
feat(ledger): add resume handoff
fix(env-build): reject stale compatibility state
docs(pgen): clarify TOML contract
refactor(nt2py): simplify data inventory
```

一次行为变更如果同时影响 Ledger、子 skill 和测试，应作为一个原子 pull request 提交，不要拆到不同仓库或长期分支。

## 验证

提交前运行：

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

四个 `SKILL.md` 都必须保留合法 YAML frontmatter，并通过 skill 结构校验。

## 发布

版本号作用于整个 skills package。发布前确认工作区干净、验证通过。自 0.7.1 起只发布英文版本（附中文 README），不再发布中文版 release。发布流程（以 `X.Y.Z` 为例）：

1. 将 rc 分支合并到 `main`，合并时把全部中文内容翻译为英文（代码标识符、CLI 命令、配置键、专业术语保持原样）。`README.md` 翻译为英文并在顶部放置指向中文 README 的链接；同时用 rc 分支的中文 README 生成（或更新）`README.zh-CN.md`。确认除 `README.zh-CN.md` 外全库无 CJK 字符且测试基线不变，推送。
2. 在 `main` 上创建 annotated tag 并发布 GitHub release（tag 不加语言后缀）：

   ```bash
   git tag -a X.Y.Z -m "Release X.Y.Z"
   git push origin X.Y.Z
   gh release create X.Y.Z --title "X.Y.Z" --target main
   ```

3. 将 rc 分支改名为下一开发版本（如 `0.7.1rc` → `0.7.2rc`），推送新分支并删除远端旧分支。

不再从旧的单 skill 仓库发布新版本。
