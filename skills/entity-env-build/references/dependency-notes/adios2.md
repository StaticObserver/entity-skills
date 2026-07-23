# ADIOS2 构建笔记

ADIOS2 是最复杂的依赖，因为它有多库依赖链（Kokkos + HDF5）以及
GPU-aware 编译。

## 版本策略

| Profile | ADIOS2 版本 | Kokkos 支持 | CUDA 经由 |
|---------|---------------|----------------|----------|
| modern  | 2.11.x        | ON             | 仅 Kokkos |

## CMake 选项

基线：
```
-DCMAKE_CXX_EXTENSIONS=OFF
-DCMAKE_POSITION_INDEPENDENT_CODE=TRUE
-DBUILD_SHARED_LIBS=ON
-DADIOS2_USE_Python=OFF
-DADIOS2_USE_Fortran=OFF
-DADIOS2_USE_ZeroMQ=OFF
-DBUILD_TESTING=OFF
-DADIOS2_BUILD_EXAMPLES=OFF
-DADIOS2_USE_HDF5=ON
-DADIOS2_BUILD_TOOLS=OFF
```

依 profile/后端而定：
| 条件 | 选项 |
|-----------|---------|
| MPI=ON     | `-DADIOS2_USE_MPI=ON -DADIOS2_HAVE_HDF5_VOL=ON` |
| MPI=OFF    | `-DADIOS2_USE_MPI=OFF -DADIOS2_HAVE_HDF5_VOL=OFF` |
| 所有受支持的构建 | `-DADIOS2_USE_Kokkos=ON` |
| CUDA | `-DADIOS2_USE_CUDA=OFF`（CUDA 经由 Kokkos） |

CUDA 额外要求：
```
-DCMAKE_CUDA_COMPILER=<cuda_prefix>/bin/nvcc
-DCMAKE_CUDA_ARCHITECTURES=<arch_number>
```
这些是必需的，因为 ADIOS2+Kokkos 会触发 CMake 的 `enable_language(CUDA)`。

CMAKE_PREFIX_PATH 必须在 ADIOS2 configure 之前同时包含 Kokkos 与 HDF5
前缀，且 Kokkos 在前（这样 ADIOS2 会先于回退到非 Kokkos 路径之前找到
KokkosConfig.cmake）。

## 已知问题

### 需要 CUDA GPU 动态库
- 症状：链接错误 `cannot find -l cuda`、`libcuda.so not found`，或缺少 `libcudart.so`
- 触发：带 Kokkos CUDA 后端的 ADIOS2 2.11.x 会链接 CUDA 运行时库
- 修复：把 stubs 与真实库路径都加入链接器标志。stubs 在前（登录节点为非 GPU 符号更偏好它们），然后是真实库路径（GPU 节点需要 libcuda.so 与 libcudart.so）：
  ```bash
  STUBS="<cuda_prefix>/targets/x86_64-linux/lib/stubs"
  CUDA_LIB="<cuda_prefix>/targets/x86_64-linux/lib"
  export LDFLAGS="-L$STUBS -L$CUDA_LIB ${LDFLAGS:-}"
  export CMAKE_EXE_LINKER_FLAGS="-L$STUBS -L$CUDA_LIB ${CMAKE_EXE_LINKER_FLAGS:-}"
  export CMAKE_SHARED_LINKER_FLAGS="-L$STUBS -L$CUDA_LIB ${CMAKE_SHARED_LINKER_FLAGS:-}"
  ```
  stubs 提供足够的符号让 ADIOS2 能在登录节点上链接；
  真实库路径在 GPU 节点的链接期与运行期都需要。
  生成的构建脚本会自动添加这两个路径。

### 缺少必需变量的 enable_language(CUDA)
- 症状：CMake 错误 "No CMAKE_CUDA_COMPILER could be found"
- 触发：带 Kokkos CUDA 后端的 ADIOS2 触发 CUDA 语言支持
- 修复：在 cmake configure 中显式设置 `-DCMAKE_CUDA_COMPILER=<cuda_prefix>/bin/nvcc`

### 不完整的 cmake --install（缺少 targets 文件）
- 症状：Entity cmake configure 失败并报 "adios2 targets not found"，或 `cmake --install` 以非零退出
- 触发：ADIOS2 的 `cmake --install` 尝试安装所有目标，包括工具（`adios2_remote_server`、`bpls` 等）。在没有 `libcuda.so.1` 的登录节点上，工具目标链接失败，而安装步骤是全有或全无的。
- 修复：生成的构建脚本现在传 `-DADIOS2_BUILD_TOOLS=OFF` 以完全跳过工具。Entity 只需要库（libadios2_core.so、libadios2_c.so、libadios2_cxx.so），不需要 CLI 工具。

### GCC libstdc++ ABI 版本不匹配
- 症状：ADIOS2 链接期间出现 `undefined reference to std::__cxx11::...`
- 触发：混用 GCC 版本（旧系统 GCC 的 libstdc++ 与新编译器）
- 修复：确保 LD_LIBRARY_PATH 包含所选编译器的 lib64 目录。
  这由 env.sh 生成处理。

### nvcc_wrapper 使用了错误的 host 编译器
- 症状：ADIOS2 configure 检测到错误的 host 编译器
- 触发：Kokkos nvcc_wrapper 脚本带有过期的 NVCC_WRAPPER_DEFAULT_COMPILER
- 修复：修补 nvcc_wrapper，或创建一个先设置该变量的 wrapper 脚本：
  ```bash
  #!/bin/bash
  export NVCC_WRAPPER_DEFAULT_COMPILER=/path/to/g++
  exec /path/to/kokkos/bin/nvcc_wrapper "$@"
  ```

## 构建后验证

预期安装结构：
```
<prefix>/
├── bin/
├── include/
├── lib64/
│   ├── libadios2_c.so
│   ├── libadios2.so
│   └── cmake/adios2/
│       ├── adios2-config.cmake
│       ├── adios2-config-version.cmake
│       ├── adios2-targets.cmake
│       ├── adios2-targets-release.cmake
│       ├── adios2-c-targets.cmake
│       ├── adios2-c-targets-release.cmake
│       ├── adios2-cxx-targets.cmake
│       └── adios2-cxx-targets-release.cmake
```

验证：
```bash
# CMake config
ls <prefix>/lib64/cmake/adios2/adios2-config.cmake

# Targets files (all 6 must exist)
ls <prefix>/lib64/cmake/adios2/adios2-targets*.cmake \
   <prefix>/lib64/cmake/adios2/adios2-c-targets*.cmake \
   <prefix>/lib64/cmake/adios2/adios2-cxx-targets*.cmake

# Libraries
ls <prefix>/lib64/libadios2_c.so <prefix>/lib64/libadios2.so
```
