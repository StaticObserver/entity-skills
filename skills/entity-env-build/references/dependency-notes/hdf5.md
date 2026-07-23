# HDF5 构建笔记

## 版本策略

所有 profile 的 HDF5 版本都是 **1.14.6**。可通过 `requirements.environment.dependency_versions.hdf5` 覆盖。

## CMake 选项

```
-DCMAKE_INSTALL_PREFIX="$PREFIX"
-DHDF5_BUILD_CPP_LIB=ON
-DHDF5_ENABLE_PARALLEL=ON     # only when MPI=ON
-DHDF5_ENABLE_PARALLEL=OFF    # when MPI=OFF
```

HDF5 是三个源码构建依赖中最简单的。很少出问题。

## 已知问题

### MPI/串行模式不匹配
- 症状：ADIOS2 期望 MPI HDF5 但 HDF5 是串行构建时的链接错误
- 触发：HDF5 构建之后 `requirements.environment.mpi` 发生了变化
- 修复：用正确的 `HDF5_ENABLE_PARALLEL` 设置重新构建 HDF5。HDF5 不重新构建就无法切换 MPI 模式。

### HDF5 版本标签格式
- 症状：git clone 失败，报 "branch not found"
- 触发：HDF5 使用 `hdf5_X.Y.Z` 标签格式（如 `hdf5_1.14.6`）
- 修复：生成的构建脚本已经处理了这一点。

## 构建后验证

预期安装结构：
```
<prefix>/
├── bin/
├── include/hdf5.h
├── lib/
│   ├── libhdf5.a (or .so)
│   └── libhdf5_cpp.a (or .so)
└── cmake/hdf5-config.cmake     ← Must exist
```

验证：
```bash
ls <prefix>/cmake/hdf5-config.cmake
ls <prefix>/include/hdf5.h
```
