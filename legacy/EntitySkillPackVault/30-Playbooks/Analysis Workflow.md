# 分析工作流

## 目标

把 simulation output 转换成诊断证据。

## 步骤

1. 定位 output path 和 metadata。
2. 如果存在 `.err`，先读 `.err`。
3. 读取 `.info` 和 stats CSV。
4. 用 nt2py lazy load。
5. 加载数组前先按 time/space/species 选择。
6. 生成所需 plots 和 numeric diagnostics。
7. 可行时与 expectation 或 previous run 比较。
8. 标记证据强度。
9. 保存 script/notebook 和 report。

## 证据标签

- visual；
- numerical；
- regression；
- unresolved。

