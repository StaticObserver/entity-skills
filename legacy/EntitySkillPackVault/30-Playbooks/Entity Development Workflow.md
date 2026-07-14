# Entity 开发工作流

## 目标

安全地修改 Entity 源码，并验证行为。

## 步骤

1. 探测 Git root、branch、commit 和 dirty state。
2. 确认目标 subsystem。
3. 用 `rg` 搜索当前代码。
4. 读取相关 headers 和 call path。
5. 写下已验证事实。
6. 起草最小设计。
7. 实施窄范围修改。
8. 运行 focused tests 或 compile checks。
9. 相关时运行小型 simulation smoke test。
10. 记录 remaining risks。

## 设计规则

不要把 repo facts 和 proposed behavior 混在一起。development note 中应分开写。

