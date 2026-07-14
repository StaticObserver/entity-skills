# Entity 权威信息源

## 官方项目

- Entity repository: https://github.com/entity-toolkit/entity
- Entity wiki: https://entity-toolkit.github.io/wiki/
- nt2py: https://pypi.org/project/nt2py/

## 权威规则

运行参数以当前 checkout 的 `input.example.toml` 为准。

PGen hooks 以当前 checkout 的这些内容为准：

- `src/global/traits/pgen.h`；
- `pgens/*/pgen.hpp`；
- `examples/*/pgen.hpp`；
- 相关 wiki PGen 页面用于解释。

Simulation object hierarchy 以这些文件为准：

- `src/framework/domain/metadomain.h`；
- `src/framework/domain/domain.h`；
- `src/framework/domain/mesh.h`；
- `src/framework/containers/fields.h`；
- `src/framework/containers/particles.h`；
- wiki 中 "Understanding the Code" 相关页面。

Engine sequencing 以及 time/step state ownership 以这些文件为准：

- `src/engines/engine.hpp`；
- `src/engines/srpic/*`；
- `src/engines/grpic/*`。

输出行为以这些内容为准：

- 当前 checkout 中的 output writer source files；
- `input.example.toml`；
- wiki 的 output and visualization 页面；
- nt2py 文档和实际安装的 API。

## 已知漂移区域

- TOML hierarchy；
- PGen hook signatures；
- custom output signatures；
- ADIOS2 target names 和 version requirements；
- Kokkos backend flags；
- local fork extensions。
