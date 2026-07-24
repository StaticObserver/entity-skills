# Entity Source of Truth

## Official Project

- Entity repository: https://github.com/entity-toolkit/entity
- Entity wiki: https://entity-toolkit.github.io/wiki/
- nt2py: https://pypi.org/project/nt2py/

## Authoritative Rules

Run parameters are governed by the `input.example.toml` in the current checkout.

PGen hooks are governed by these files in the current checkout:

- `src/global/traits/pgen.h`;
- `pgens/*/pgen.hpp`;
- `examples/*/pgen.hpp`;
- the relevant wiki PGen pages for interpretation.

The simulation object hierarchy is governed by these files:

- `src/framework/domain/metadomain.h`;
- `src/framework/domain/domain.h`;
- `src/framework/domain/mesh.h`;
- `src/framework/containers/fields.h`;
- `src/framework/containers/particles.h`;
- the "Understanding the Code" pages in the wiki.

Engine sequencing and time/step state ownership are governed by these files:

- `src/engines/engine.hpp`;
- `src/engines/srpic/*`;
- `src/engines/grpic/*`.

Output behavior is governed by:

- the output writer source files in the current checkout;
- `input.example.toml`;
- the wiki output and visualization pages;
- the nt2py documentation and the actually installed API.

## Known Drift Areas

- TOML hierarchy;
- PGen hook signatures;
- custom output signatures;
- ADIOS2 target names and version requirements;
- Kokkos backend flags;
- local fork extensions.
