# Playbook：开发 PGen（develop-pgen）

## 收益

PGen/TOML/design 的一致性有专项检查；参数确认记录让"这份 run 跑的是
什么"永远可核对——TOML 改过一个字节，就绪板的 pgen 格就会自动变回
未确认。

## 产物

- `pgen.hpp` + `<pgen>.toml` + `docs/design.md`（项目 Git 权威）；
- 参数确认记录 `<input>.decisions.json`（`record run-prepare` 的门禁）。

## 步骤

1. PGen/TOML/design 的编写和修改全部交给 **entity-pgen** skill。
   修改 PGen 或 TOML 后，受影响的契约面（traits、`params.get`、
   species、boundary、custom output）要重新核对。
2. 模拟参数确定后，把参数卡片展示给用户，然后：
   ```bash
   python3 scripts/pgen_preflight.py confirm <input.toml> --by <actor>
   ```
   （在 entity-pgen skill 目录下）写入 `<input>.decisions.json`。
3. 之后改了 TOML，确认记录自动失效，跑 run 前重新 confirm。

## 状态记在哪

就绪板的 pgen 格：`confirmed`（TOML 与确认记录字节匹配）/
`unconfirmed` / `partial`。Router 不存设计内容——科学判断和设计依据
属于项目 Git 里的 design.md。

## 转引

`entity-pgen` SKILL：PGen 骨架、normalization、注入、边界、custom
output、TOML 契约、高阶方法。
