# GCC 构建笔记

## 已知不良版本

### GCC 12.2.0 ICE：模板代码中的 if constexpr
- **症状**：`internal compiler error: in tsubst_copy, at cp/pt.cc:17004`
- **触发**：Entity 1.4.3+ 框架代码在模板密集路径（如 `simulation.cpp`）中使用 `if constexpr` 构造。TOML11 的 `std::source_location::current()` consteval 失败也会触发。
- **受影响版本**：GCC 12.2.0（可能还有其他 12.x）。GCC 13.3+ 或 11.x 不会触发。
- **修复**：使用 GCC 13.3+ 或 GCC 11.x。Entity 构建不要使用 GCC 12.x。
- **检测**：`entity_compat.py` 会把任何 GCC 12.2.x 标记为 `compiler.version.gcc.known_bad`，状态为 WARN。

## C++ 标准支持

| GCC 版本 | C++20 | 备注 |
|-------------|-------|-------|
| 8.x | 部分 | 不受支持 |
| 10.4+ | 是 | 最低支持版本 |
| 11.x | 是 | 安全选择 |
| 12.x | 是 | **if constexpr 有已知 ICE** |
| 13.3+ | 是 | Entity >= 1.4.0 推荐 |

## SDK 兼容性

### NVCC + GCC Host
- NVCC 包装 host GCC 编译器。host GCC 必须是与 CUDA 工具包兼容的版本：
  - CUDA 12.0：默认附带 GCC 12.x 头文件；可能需要 `--allow-unsupported-compiler`
  - CUDA 12.2+：支持 GCC 12.x 与 13.x
- 使用 conda GCC 时，确保 `libstdc++` 路径在 `LD_LIBRARY_PATH` 中，以获得正确的 ABI 链接。

### Spack GCC
在 HPC 系统上获取更新 GCC 的首选方式：
```bash
spack install gcc@13.3.0
spack load gcc@13.3.0
```
在搭建环境之前，用 `spack find gcc` 发现可用版本。
