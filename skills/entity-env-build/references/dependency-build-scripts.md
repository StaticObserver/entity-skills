# 依赖构建脚本

当现有的系统/module/前缀依赖无法满足 `requirements.json`、必须进行本地源码构建时，使用本参考。

## 规则来源

构建脚本应遵循与 Entity 的 `dependencies.py` 及官方依赖页面相同的决策模型：

- 优先使用现有的系统/module `MPI` 与 `HDF5`（如可用）。
- 源码构建是最后手段。
- 保持编译器/工具链在 Kokkos、HDF5、ADIOS2、MPI 与 Entity 之间一致。
- 使用受支持的 Entity profile：C++20 + Kokkos 5.x + ADIOS2 2.11.x。
- 构建带 Kokkos 支持的 ADIOS2。
- 对于 CUDA 构建，在 Kokkos 安装完成后使用 Kokkos `nvcc_wrapper`。
- 生成的依赖脚本保存在执行站点的 `entity.deps_root/scripts/` 下。

官方参考：https://entity-toolkit.github.io/wiki/content/1-getting-started/2-dependencies/

## 脚本生成器的角色

使用 `scripts/entity_generate.py deps` 生成适配本技能目录布局的本地依赖构建脚本。

预期接口：

```bash
python3 scripts/entity_generate.py deps requirements.json \
  --deps kokkos,hdf5,adios2 \
  --checkpoint entity-deps.local.json
```

默认输出目录：

```text
<deps_root>/scripts/
```

生成的脚本在执行前应经过审查。它们不是事实来源；`requirements.json` 与 `entity-deps.local.json` 才是。

当前生成器范围：

- 直接生成 `kokkos`、`hdf5`、`adios2` 的源码构建脚本。
- `mpi` 会生成一个有意停止的脚本，直到加入经过审查的 OpenMPI/UCX 策略。
- 每个脚本都把 configure/build/install 日志写入 `entity.artifacts_root/build-logs` 下。
- Kokkos 与 ADIOS2 脚本包含官方基线开关，如 `CMAKE_CXX_EXTENSIONS=OFF`、位置无关代码、禁用 ADIOS2 Python/Fortran/ZeroMQ、禁用 ADIOS2 测试、禁用 ADIOS2 示例。
- 可通过 `requirements.environment.dependency_versions` 固定精确的 Kokkos/ADIOS2/HDF5 源码标签。

## 依赖顺序

只为缺失或不兼容的依赖生成脚本。

推荐顺序：

```text
MPI only if required and no compatible system/module MPI exists
Kokkos
HDF5 only if output=true
ADIOS2 only if output=true
```

## 生成脚本的要求

每个生成的脚本应当：

- 使用 `set -euo pipefail`；
- 将日志写入 `entity.artifacts_root/build-logs` 下；
- 安装到 `entity-deps.local.json` 中记录的前缀下；
- 使用来自 `entity-deps.local.json.selected.compiler` 的编译器；
- 保留 `requirements.json` 中的 MPI 开/关与后端选择；
- 避免写入 `ENTITY_CHECKOUT`；
- 具有足够的幂等性，删除其构建目录后可重新运行。

## 记录

生成脚本后，更新 `entity-deps.local.json.build_scripts`：

```json
{
  "build_scripts": {
    "directory": "/absolute/deps_root/scripts",
    "generated_at": "",
    "scripts": {
      "kokkos": {
        "path": "",
        "status": "generated",
        "source": "entity-env-build/scripts/entity_generate.py deps",
        "based_on": "Entity dependencies.py/wiki dependency generator"
      }
    }
  }
}
```

依赖构建脚本执行后，用前缀、版本（若已知）、CMake config 路径、编译器签名与验证证据更新对应的选定依赖条目。
