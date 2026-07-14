# 本地上下文与 Overlays

## 目的

把用户专属的 Entity 知识和官方上游知识分开。

## Local Overlay 类别

- StaticObserver Entity fork；
- experimental branches；
- custom pgens；
- local validation plans；
- project-specific analysis scripts；
- unpublished feature work。

## 规则

不要把 local overlay behavior 写成官方上游 Entity behavior。

每条 overlay note 应包含：

- repository path 或 URL；
- branch；
- commit；
- date observed；
- files inspected；
- 与 official upstream 的差异。

## 初始上下文

已有上下文显示，本地 Entity 相关工作可能包含 axion/external current 修改和分支特定 validation plan。在当前 checkout 验证前，把这些都视为 local overlays。

