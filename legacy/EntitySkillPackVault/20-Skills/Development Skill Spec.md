# Development Skill 规范

## 使命

以源码事实为基础，帮助开发 Entity 功能。

这个 skill 比 simulation operation 更深。在读取当前 checkout 后，它可以修改 Entity 源码。

## 必做 Preflight

提出方案或编辑代码前运行：

```bash
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse --short HEAD
git describe --tags --always
```

然后检查相关源码文件。不要只依赖 skill-pack 摘要。

## 源码边界

常见子系统：

- `src/framework`：domain、mesh、parameters、containers；
- `src/engines`：算法调度和 engine-owned state；
- `src/kernels`：device numerical kernels；
- `src/output`：ADIOS2/HDF5/stats/checkpoint 写出；
- `src/global/traits`：编译期 hook 检测；
- `pgens` 和 `examples`：面向用户的 customization patterns；
- `tests`：unit 和 integration tests。

## 工作流

1. 明确 feature goal 和 expected behavior。
2. 确认目标 subsystem 和 owner boundary。
3. 追踪当前 call path。
4. 分离“已验证 repo fact”和“拟议设计”。
5. 起草最小实现方案。
6. 窄范围编辑。
7. 运行可用 compile/tests/smoke checks。
8. 记录兼容性和风险。

## 工程规则

- 在实际可行时保持 backwards compatibility。
- 明确 host/device 边界。
- 不要把属于 `Engine` 的状态强行放进 `Domain`。
- 添加新的 PGen hook 假设前先检查 traits。
- 某些验证任务中，普通 particle output 不足以作为精确 oracle；需要 checkpoint/raw state。

## 必要输出

使用 [[90-Templates/Development Design Note Template|Development Design Note 模板]]。

包含：

- 已检查源码路径；
- 已验证当前行为；
- 拟议行为；
- changed files；
- tests run；
- tests not run；
- remaining risks。

