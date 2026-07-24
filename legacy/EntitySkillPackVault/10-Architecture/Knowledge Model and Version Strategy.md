# Knowledge Model and Version Strategy

## Principle

The current Entity checkout is more authoritative than the skill pack.

The skill pack should store:

- where to look;
- what to look for;
- how to interpret what is found;
- which workflows to follow.

Unless a version range is explicitly marked, do not store large copied parameter tables or API signatures in the skill pack.

## Information Source Priority

Every Entity task follows this priority order:

1. The current local checkout.
2. The current upstream repository, when needed or requested by the user.
3. The official wiki, for conceptual explanations.
4. Skill pack notes, for workflows and orientation.
5. Local overlays, for user fork or experimental branch behavior.

## Mandatory Checkout Probe

Before simulation or development, collect:

```bash
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse --short HEAD
git describe --tags --always
```

If it is not a Git checkout, record the absolute path and whatever version information is available.

## Official Authoritative Files

Check these files before trusting skill-pack summaries:

- `input.example.toml`: run parameters and TOML hierarchy.
- `pgens/*/pgen.hpp` and `examples/*/pgen.hpp`: current PGen style.
- `src/global/traits/pgen.h`: PGen hook detection and signatures.
- `src/engines/*`: engine scheduling order and ownership of time/step state.
- `src/kernels/*`: device kernels and numerical operations.
- `src/framework/domain/*`: `Metadomain`, `Domain`, `Mesh`, and local domain behavior.
- `src/output/*` and ADIOS2-related code: output semantics.

## Version Buckets

Track at least these version buckets:

- `official-v1.4.x`: the current upstream release series.
- `official-master`: the latest upstream development state.
- `legacy-v1.3.3`: the old branch series still relevant to existing local work.
- `local-staticobserver`: user fork behavior.
- `local-experimental`: task branches and unpublished changes.

Any note describing behavior should state which version bucket it applies to.

## Dependency Version Matrix

The Entity build environment must select dependency families according to the Entity major version; they must not be mixed arbitrarily:

| Entity version bucket | Kokkos | ADIOS2 | Key notes |
| --- | --- | --- | --- |
| `official-v1.4.x` | Kokkos 5.x | ADIOS2 2.11.x | ADIOS2 must be built with the Kokkos dependency. |
| `legacy-v1.3.x` | Kokkos 4.x | ADIOS2 2.10.x | Do not apply the 1.4.x ADIOS2/Kokkos combination here. |

If the current checkout cannot be clearly assigned to one of these version buckets, the agent must first read the repository's `README.md`, `dependencies.py`, `cmake/`, and the official wiki before giving dependency advice.

## High Drift Risk

Content prone to change:

- TOML hierarchy and default values;
- PGen hook signatures;
- output quantity names;
- custom particle update hooks;
- Kokkos and ADIOS2 version requirements;
- whether ADIOS2 requires the Kokkos dependency;
- branch-specific features.

Relatively stable content:

- the workflow boundary between simulation and development;
- the necessity of the run manifest;
- the `Metadomain -> Domain -> Mesh -> Fields/Particles` concept hierarchy;
- the distinction between code units, physical coordinates, tetrad basis, and coordinate basis.

## Local Overlay Rules

Local extensions must not be written as upstream facts.

Example:

- Official upstream may state that `ext_current` is Minkowski-only.
- A local fork may have extended `ext_current` with a time-aware context or other behavior.

The skill pack must label the latter as a local overlay and require checking the current checkout before use.
