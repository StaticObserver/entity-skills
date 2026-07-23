# Kokkos 构建笔记

## 版本策略

| Profile | Entity 版本 | Kokkos 版本 | C++ 标准 |
|---------|---------------|----------------|-------------|
| modern  | >= 1.4.0      | 5.x（默认 5.0.1） | 20 |

`1.4.0` 之前的 Entity 版本不受支持。

## CMake 选项

基线：
```
-DCMAKE_CXX_EXTENSIONS=OFF
-DCMAKE_POSITION_INDEPENDENT_CODE=TRUE
-DKokkos_ENABLE_SERIAL=ON
-DKokkos_ENABLE_PIC=ON
-DCMAKE_CXX_STANDARD=<profile_cxx_standard>
```

依后端而定：
| 后端 | 选项 |
|---------|---------|
| cpu     | `-DKokkos_ENABLE_OPENMP=ON` |
| cuda    | `-DKokkos_ENABLE_CUDA=ON -DKokkos_ARCH_<ARCH>=ON` |
| hip     | `-DKokkos_ENABLE_HIP=ON -DKokkos_ARCH_<ARCH>=ON` |

## CUDA 后端 — nvcc_wrapper

CUDA 构建必须使用 Kokkos `nvcc_wrapper` 作为 CXX。关键设置：

1. **Host 编译器**：`NVCC_WRAPPER_DEFAULT_COMPILER` 必须指向兼容的 host 编译器
2. **CUDA 工具包**：运行 cmake 之前 nvcc 必须在 PATH 中
3. **架构**：显式设置 `Kokkos_ARCH_*`（例如 A100 用 `AMPERE80`，V100 用 `VOLTA70`）

安装前缀包含 `bin/nvcc_wrapper`——这就是 selected.compiler.cxx 必须指向的目标。

## 已知问题

### GCC 版本对 Kokkos 5.x 太旧
- 症状：Kokkos configure 期间出现 C++20 特性错误
- 触发：modern profile 下 GCC < 10.4
- 修复：使用更新的 GCC（module、spack 或本地安装）。modern profile 最低要求 GCC 10.4。

### NVCC 版本对 C++20 太旧
- 症状：nvcc 无法识别 `-std=c++20`
- 触发：modern profile 下 NVCC < 12.2
- 修复：将 CUDA 工具包升级到 12.2+。检查 `nvcc --version`。

### nvcc_wrapper host 编译器传递
- 症状：nvcc_wrapper 使用了错误的 host 编译器（系统默认而非选定的）
- 触发：PATH 中有多个 GCC 安装
- 修复：在 cmake configure 之前显式设置 `NVCC_WRAPPER_DEFAULT_COMPILER`。检查生成的 nvcc_wrapper 脚本头部。

### Kokkos_ENABLE_PIC 警告
- 症状：CMake 警告 "Manually-specified variables were not used: Kokkos_ENABLE_PIC"
- 触发：Kokkos 5.x 忽略该标志（PIC 始终开启）
- 修复：忽略；该标志无害。

## 构建后验证

预期安装结构：
```
<prefix>/
├── bin/nvcc_wrapper          ← Must exist and be executable (CUDA only)
├── include/
├── lib64/
│   ├── libkokkoscore.a
│   ├── libkokkoscontainers.a
│   ├── libkokkossimd.a
│   └── cmake/Kokkos/KokkosConfig.cmake  ← Must exist
```

验证：
```bash
<prefix>/bin/nvcc_wrapper --version  # CUDA only
cmake --find-package -DNAME=Kokkos -DCOMPILER_ID=GNU -DLANGUAGE=CXX -DMODE=EXIST
```
