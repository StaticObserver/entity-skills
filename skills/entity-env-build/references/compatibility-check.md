# 兼容性检查

在 `entity-deps.local.json` 被写入或修复之后、生成 `env.sh` 之前使用本参考。

该检查回答一个问题：这对确切的 `requirements.json + entity-deps.local.json` 能否安全地为所请求的 Entity 构建生成环境？

每个结果都包含 `checker_version` 和 `coverage`。覆盖度取值含义明确：
`implemented` 表示已做机械检查，`partial` 表示只检查了契约的一部分，
`not_implemented` 表示 pass 结果绝不能被解读为对该项的证明。

优先使用随附的检查器：

```bash
python3 scripts/entity_compat.py requirements.json --checkpoint entity-deps.local.json
```

如果检查器无法评估某个站点特有的条件，请手动把证据补充到相同的结果结构中，而不是绕过检查。

## 必需的结果结构

将结果写入 `entity-deps.local.json.compatibility`：

```json
{
  "status": "pass|fail|partial",
  "checker_version": 1,
  "checked_at": "",
  "coverage": {
    "requirements_checkpoint_match": "implemented",
    "compiler_signature": "partial",
    "cmake_package_probe": "not_implemented"
  },
  "checks": [
    {
      "id": "",
      "status": "pass|fail|warn|skip",
      "summary": "",
      "evidence": {},
      "remediation": ""
    }
  ],
  "issues": []
}
```

只有 `status=pass` 才能继续生成 `env.sh`。

## 1. 请求与 checkpoint 一致性

> **实现状态：大部分已实现** — `entity_compat.py` 检查 schema 版本、执行 `site_id` 与独立的源码/构建/依赖/产物路径不匹配、`requirements.path` 存在性，以及可复用内嵌请求在 backend、MPI、output、profile 和编译选项上的漂移。

检查：

- `entity-deps.local.json.requirements` 指向或内嵌当前的 `requirements.json`。
- `requirements.schema_version` 与 checkpoint 的 `schema_version` 是受支持的。
- 执行站点与所有解析后的 schema-v2 Entity 路径等于当前 requirements；
- schema-v1 的 `checkout_root/workdir` 比较仅为旧版兼容。
- 请求的 backend、MPI、output、依赖 profile 与编译选项与 checkpoint 中的选择一致。
- `decisions.parameters` 持有一条确认记录，其摘要与当前 requirements
  的参数卡匹配（`parameters.confirmation` 检查）。记录缺失或过期则
  失败；在生成 `env.sh` 之前用
  `entity_checkpoint.py confirm <requirements> --checkpoint <checkpoint>
  --by <actor>` 重新确认。显式的
  `decisions.parameters_confirmation_override` 会像其他已记录的
  override 一样把该检查降级为警告。

如果 checkpoint 是为不同的 Entity checkout、workdir、backend、MPI 模式、output 模式或依赖 profile 生成的，则失败。

## 2. Entity 版本 profile

> **实现状态：已实现** — `entity_compat.py` 验证 profile 检测、C++ 标准、Kokkos/ADIOS2 版本族匹配，以及 ADIOS2 的 Kokkos 支持模式。

拒绝 `1.4.0` 之前的 Entity 版本。`requirements.entity.dependency_profile` 若存在，必须是 `modern`。

检查：

- Entity `1.4.0` 及更新版本使用 `C++20`、Kokkos `5.x`、ADIOS2 `2.11.x`，且 ADIOS2 Kokkos 支持为 `ON`。
- CUDA 构建要求 Entity `1.4.3` 或更新；Entity `1.4.0`–`1.4.2` 仅支持 CPU。
- `requirements.compile.cxx_standard` 与 profile 匹配。
- 选定的 Kokkos 与 ADIOS2 版本与 profile 版本族匹配。
- ADIOS2 的 `compile_config` 或生成脚本元数据记录了预期的 Kokkos 支持模式。

不支持的 Entity 版本或依赖族不匹配则失败。

## 3. 工具链一致性

> **实现状态：部分实现** — `entity_compat.py` 验证 `compiler.cxx`/`cc` 路径存在且可执行。跨依赖的签名一致性尚未自动比较。

检查：

- 选定的 `cmake`、`compiler.cc`、`compiler.cxx` 存在且可执行。
- 编译器能报告版本。
- 编译器支持所需的 C++ 标准。
- 所有选定的源码构建或前缀依赖记录相同的编译器签名，或记录一个明确接受的兼容 wrapper 关系。
- 当 `compiler.cxx` 是 Kokkos `nvcc_wrapper` 时，记录 `compiler.host_cxx`。
- 当选定的 MPI 是 OpenMPI 时，其记录的版本满足
  `entity_schema.py:MIN_OPENMPI_VERSION`（>= 5.0.0）。

证据应包含可执行文件路径、版本输出以及编译器签名字符串。

## 4. 后端检查

> **实现状态：部分实现** — 已检查 CUDA nvcc_wrapper 与 ADIOS2 标志冲突。已检查 HIP 工具包前缀存在性。CPU 后端检查与 GPU 架构验证尚未自动化。

对于 `backend=cpu`：

- CPU 编译器支持所需的 C++ 标准。
- 选定的 Kokkos 启用了 Serial/OpenMP 之类的 CPU 后端。

对于 `backend=cuda`：

- CUDA 工具包与 `nvcc` 存在。
- 选定的 C++ 编译器是 Kokkos `nvcc_wrapper`。
- `NVCC_WRAPPER_DEFAULT_COMPILER` 或 `compiler.host_cxx` 有效。
- CUDA 编译器与 host 编译器版本互相合理。
- `requirements.environment.gpu_arch` 已设置，或记录了安全的默认/自动检测决策。
- 选定的 Kokkos 是以 CUDA 和所请求架构构建的。

对于 `backend=hip`：

- ROCm/HIP 工具存在，例如 `hipcc`。
- 选定的 Kokkos 启用了 HIP。
- 记录了所请求的 AMD GPU 架构。
- ROCm 前缀可通过 `CMAKE_PREFIX_PATH` 或等价环境变量发现。

## 5. MPI 检查

> **实现状态：部分实现** — 已检查 MPI 选择的存在性，但 MPI wrapper 输出、编译器族兼容性以及 ADIOS2/HDF5 串行/MPI 一致性尚未验证。

当 `requirements.environment.mpi=false` 时：

- Entity 构建将使用 `mpi=OFF`。
- ADIOS2 与 HDF5 选择与串行兼容。
- 没有意外选中仅 MPI 的 ADIOS2/HDF5 目标。

当 `requirements.environment.mpi=true` 时：

- `mpicxx` 与 `mpirun` 存在且可执行。
- 记录了 `mpicxx --show` 或等价的 wrapper 输出。
- MPI wrapper 使用选定的编译器族，或使用用户确认的兼容编译器。
- ADIOS2 与 HDF5 启用了 MPI。
- Kokkos/ADIOS2/HDF5/Entity 将在同一个编译器/MPI 上下文中构建。
- `gpu_aware_mpi=true` 有证据或明确的风险接受。

## 6. 依赖存在性与发现

> **实现状态：已实现** — `entity_compat.py` 验证 `prefix`、`cmake_config`、`bin` 路径在磁盘上存在。结构完整性（非空字段）单独检查。

对每个必需的依赖，同时检查文件与 CMake 发现。

始终必需：

- CMake 可执行文件。
- 选定的 C/C++ 编译器。
- Kokkos 前缀或源码构建结果。
- Kokkos `KokkosConfig.cmake`。

当 `output=true` 时必需：

- HDF5 前缀或源码构建结果。
- HDF5 CMake config，通常是 `hdf5-config.cmake` 或 `HDF5Config.cmake`。
- ADIOS2 前缀或源码构建结果。
- ADIOS2 `ADIOS2Config.cmake`。

可行时运行或模拟一次 CMake 包查找：

```bash
cmake -S <probe-src> -B <probe-build> -DCMAKE_PREFIX_PATH="<paths>"
```

至少验证每个记录的 `cmake_config` 路径存在，且其前缀包含在 `paths.CMAKE_PREFIX_PATH` 中。

## 7. ADIOS2、HDF5 与 Kokkos 模式兼容性

> **实现状态：部分实现** — 已检查 ADIOS2 Kokkos 支持模式与 profile 的关系。已检测 ADIOS2_USE_Kokkos + CUDA 冲突。串行/MPI 模式一致性尚未自动化。

检查：

- ADIOS2/HDF5 串行与 MPI 模式匹配 `requirements.environment.mpi`。
- ADIOS2 Kokkos 支持仅对 `modern` profile 为 `ON`，除非显式 override。
- ADIOS2 不得同时启用 `ADIOS2_USE_Kokkos=ON` 与 `ADIOS2_USE_CUDA=ON`。
- 如果 ADIOS2 Kokkos 支持为 `ON`，Kokkos 前缀在 `CMAKE_PREFIX_PATH` 中必须先于 ADIOS2 可发现。
- ADIOS2 与 HDF5 是以兼容的编译器签名构建的。
- HDF5 C 与 C++ 库可用性与 ADIOS2 构建匹配。

## 8. 运行时加载器路径

> **实现状态：尚未实现** — 记录在 `paths.*` 中的路径条目尚未验证存在性。

检查：

- checkpoint 中记录的每个 `PATH`、`CMAKE_PREFIX_PATH`、`LD_LIBRARY_PATH`、`DYLD_LIBRARY_PATH` 条目都存在，除非它在当前 OS 上有意缺失。
- 使用动态库时，所选依赖的库目录已包含在内。
- 除非显式记录，否则不需要源码 checkout 的构建目录作为运行时库路径。

在 macOS 上检查 `DYLD_LIBRARY_PATH`；在 Linux 上检查 `LD_LIBRARY_PATH`。

## 9. 源码构建脚本就绪性

> **实现状态：部分实现** — 会标记 `status=generated` 且没有安装证据的源码构建脚本。单个脚本选项验证尚未自动化。

当选定依赖的 provider 为 `source-build` 时：

- 生成的脚本路径存在且可执行。
- 脚本来源记录在 `build_scripts` 中。
- 生成的版本 profile 与 C++ 标准匹配 `requirements`。
- 脚本安装前缀与选定依赖前缀匹配。
- 执行后构建日志存在，或者状态仍为 `generated` 且兼容性必须保持 `partial`/`fail`。

对于只有生成脚本而没有完成安装证据的依赖，不要把兼容性标记为 `pass`。

## 10. Entity 构建就绪性

> **实现状态：尚未实现** — 由 `generate_entity_build_sh.py` 隐式执行（pgen 要求、CMake 选项推导）。不是 `entity_compat.py` 中的独立检查。

检查：

- `requirements.compile.pgen` 已设置。
- 选定的依赖路径能够产出 `entity-build.sh` 所需的 CMake 选项。
- `requirements.compile.cxx_standard`、backend、MPI、output、debug、tests、precision、deposit 与 shape order 内部一致。
- 预期构建目录等于不可变的 `entity.build_root`，除非用户显式记录了另一个构建身份路径。

该检查不编译 Entity。它只决定生成 `env.sh` 再生成 `entity-build.sh` 是否安全。

## 状态规则

当必需依赖、必需路径、版本族、编译器模式、后端模式或 MPI/output 模式不兼容时，使用 `fail`。

仅当缺失项预期接下来会被创建，且在重新检查之前不会启动任何 Entity 构建时，才使用 `partial`；例如已生成但尚未运行的源码构建脚本。

仅当所有必需的选定依赖都已安装/可发现，且每个请求的模式都有证据时，才使用 `pass`。
