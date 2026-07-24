# Entity Case Skill Spec

## Mission

Maintain the consistency of an Entity simulation case.

A case is not a standalone TOML, nor a standalone `pgen.hpp`, but:

```text
TOML + pgen.hpp + setup parameters + species + boundaries + output requests
```

The first responsibility of this skill is to help the agent understand the structure and API of a PGen, then check whether the TOML and the PGen are consistent.

## Out of Scope

This skill does not handle:

- building the Kokkos/ADIOS2/MPI/HDF5 environment;
- choosing the CMake backend;
- modifying Entity `src/` core code;
- drawing physics conclusions from output data;
- writing long-term handover documentation.

Those go to env-build, core-dev, analysis, and docs respectively.

## PGen Source of Truth

The PGen API is highly version-sensitive. Before use, verify against the target Entity checkout:

- `src/global/traits/pgen.h`;
- `pgens/*/pgen.hpp`;
- `examples/*/pgen.hpp`;
- the PGen hooks reported in `src/engines/reporter.*`;
- `src/engines/*/fields_bcs.*`;
- `src/engines/*/fieldsolvers.*`;
- where PGen hooks are invoked in `src/engines/engine.hpp`.

API summaries in the skill are only for navigation; they cannot replace the current checkout.

## PGen File Structure

Typical case directory:

```text
pgens/<name>/
├── pgen.hpp       # required, selected at compile time
├── <name>.toml    # recommended, reference input
└── <name>.py      # optional, visualization or analysis script
```

Entity selects the PGen via a CMake option:

```bash
cmake -B build/<name> -D pgen=<name>
```

If `pgen.hpp` is modified, Entity usually needs to be rebuilt.

## PGen Top-Level Structure

A PGen must live in `namespace user`. A typical structure:

```cpp
namespace user {
  using namespace ntt;

  template <SimEngine::type S, class M>
  struct PGen {
    static constexpr auto D { M::Dim };

    static constexpr auto engines {
      ::traits::pgen::compatible_with<SimEngine::SRPIC> {}
    };
    static constexpr auto metrics {
      ::traits::pgen::compatible_with<Metric::Minkowski> {}
    };
    static constexpr auto dimensions {
      ::traits::pgen::compatible_with<Dim::_2D, Dim::_3D> {}
    };

    const SimulationParams& params;
    Metadomain<S, M>& metadomain;

    PGen(const SimulationParams& p, Metadomain<S, M>& m)
      : params { p }
      , metadomain { m } {}
  };
}
```

Note: older material may show forms like `static constexpr auto engines = { SimEngine::SRPIC }`. Whether the current checkout supports that must be determined from `src/global/traits/pgen.h` and the existing pgens. The common 1.4.x form is `traits::pgen::compatible_with<...>{}`.

## Compatibility Traits

A PGen should declare the supported:

- engines;
- metrics;
- dimensions.

Common engines:

- `SimEngine::SRPIC`;
- `SimEngine::GRPIC`.

Common metrics:

- `Metric::Minkowski`;
- `Metric::Spherical`;
- `Metric::QSpherical`;
- `Metric::Kerr_Schild`;
- `Metric::QKerr_Schild`;
- `Metric::Kerr_Schild_0`.

Common dimensions:

- `Dim::_1D`;
- `Dim::_2D`;
- `Dim::_3D`.

The TOML `simulation.engine`, `grid.metric.metric`, and the dimension implied by `grid.resolution` must be consistent with the PGen traits.

## Parameter Reading

A PGen usually reads TOML parameters from `SimulationParams`:

```cpp
const auto value = params.template get<real_t>("setup.value", 1.0);
const auto required = params.template get<real_t>("setup.required");
```

Conventions:

- PGen custom parameters should live under `[setup]`;
- parameters with defaults should document their defaults;
- required parameters should be stated explicitly in the reference TOML or case note;
- parameter paths must match the TOML hierarchy.

## Field Initialization: `init_flds`

If the PGen provides initial fields, it usually defines a field initializer and places a member named `init_flds` in the PGen.

```cpp
template <Dimension D>
struct InitFields {
  Inline auto ex1(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
  Inline auto ex2(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
  Inline auto ex3(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }

  Inline auto bx1(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
  Inline auto bx2(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
  Inline auto bx3(const coord_t<D>& x_Ph) const -> real_t { return ZERO; }
};

InitFields<D> init_flds;
```

Rules:

- the member name must usually be `init_flds`;
- method names follow `ex1/ex2/ex3`, `bx1/bx2/bx3`;
- arguments are usually physical coordinates;
- SRPIC usually specifies fields in the local tetrad/orthonormal basis;
- GRPIC field basis and coordinate conventions must be verified against the current checkout/wiki;
- the code handles staggering and internal conversions, but code units and physical units must not be mixed.

## Particle Initialization: `InitPrtls`

`InitPrtls` initializes particles for each local domain at simulation start:

```cpp
void InitPrtls(Domain<S, M>& local_domain) {
  // inject particles
}
```

Common responsibilities:

- initialize electrons, ions, positrons, photons, etc. according to the TOML species;
- use built-in energy/spatial distributions;
- use `arch::InjectUniform...` or `arch::InjectNonUniform...`;
- read density, temperature, drift velocity, layer width, and similar parameters from `[setup]`;
- pay attention to the consistency between species index and TOML `[[particles.species]]`.

Note:

- species index in Entity code is often 1-indexed;
- C++ container access is often 0-indexed;
- the agent must confirm this against the current API and call sites, and must not mix them by intuition.

## Spatial and Energy Distributions

A PGen can define custom spatial distributions and energy/velocity distributions.

Typical use cases:

- current sheet;
- shock;
- turbulence;
- localized injection;
- atmosphere;
- beam / streaming setup.

Design requirements:

- distribution functions should state explicitly whether input coordinates are physical coordinates or code coordinates;
- the velocity/momentum basis must be explicit;
- random number pool usage must satisfy Kokkos/device constraints;
- distribution parameters should come from `[setup]` or the PGen constructor.

## Boundary Hooks

A PGen can provide field boundary behavior.

Common hooks:

```cpp
auto MatchFields(simtime_t time) const -> FieldProvider;
auto MatchFieldsInX1(simtime_t time) const -> FieldProvider;
auto MatchFieldsInX2(simtime_t time) const -> FieldProvider;
auto MatchFieldsInX3(simtime_t time) const -> FieldProvider;
```

And fixed-field behavior:

```cpp
auto FixFieldsConst(simtime_t time, const bc_in& bc, em comp) const
  -> std::pair<real_t, bool>;
```

Note:

- exact signatures change across versions; defer to `fields_bcs` and `traits/pgen.h`;
- if the TOML boundary uses `MATCH`, `FIXED`, or `CUSTOM`, the PGen must provide the corresponding logic;
- spherical/GR boundaries may be partially set automatically by the framework; cartesian logic must not be copied over blindly.

## Runtime Hook: `CustomPostStep`

`CustomPostStep` is called at the end of each timestep:

```cpp
void CustomPostStep(timestep_t step, simtime_t time, Domain<S, M>& domain) {
  // custom injection, boundary changes, diagnostics support, etc.
}
```

Common uses:

- runtime particle injection;
- changing boundary conditions;
- maintaining custom buffers;
- executing case-specific physics.

Risks:

- raw quantities inside `Domain` are often in code units;
- deleting charged particles may break charge conservation;
- implementing an external source here may bypass the proper field solver/source path;
- if a feature belongs to the core algorithm, it should be routed to core-dev rather than stuffed into the PGen.

## External Force: `ext_force`

A PGen can define a member named `ext_force` to provide an external force for specified species.

Typical form:

```cpp
struct ExtForce {
  std::vector<int> species;

  Inline auto fx1(spidx_t sp, simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
  Inline auto fx2(spidx_t sp, simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
  Inline auto fx3(spidx_t sp, simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
};

ExtForce ext_force;
```

Note:

- the signature must be verified against the current checkout;
- the species list must be consistent with the TOML species;
- force basis and units must be explicit;
- some methods may be optional, detected via traits.

## External Current: `ext_current`

A PGen can define a member named `ext_current` to provide an external current source for Ampere's law.

Typical form:

```cpp
struct ExtCurrent {
  Inline auto jx1(simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
  Inline auto jx2(simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
  Inline auto jx3(simtime_t time, const coord_t<D>& x_Ph) const -> real_t;
};

ExtCurrent ext_current;
```

Note:

- official upstream may restrict `ext_current` to the Minkowski/SRPIC path;
- a local fork may have extended it, but that must be marked as a local overlay;
- time staggering, source time, and field solver call sites are high-risk points;
- any change involving `src/kernels/ampere*` or engine time ownership should be routed to core-dev.

## Custom Field Output

Custom field output can be requested in the TOML:

```toml
[output.fields]
custom = ["my_field"]
```

The PGen needs to provide the corresponding hook, for example:

```cpp
void CustomFieldOutput(
    const std::string& name,
    array_t<real_t*>& buffer,
    std::size_t index,
    timestep_t step,
    simtime_t time,
    Domain<S, M>& domain) {
  if (name == "my_field") {
    // fill buffer
  }
}
```

Note:

- the exact buffer type and signature must defer to the current checkout;
- custom field names must match the TOML `custom` list;
- output quantities should be as resolution-independent as possible;
- if a quantity must be re-deposited from particles, the oracle and numerical error must be documented.

## Custom Stats

Custom scalar stats can be requested in the TOML:

```toml
[output.stats]
custom = ["my_stat"]
```

The PGen needs to provide the corresponding hook. The common 1.4.x signature includes `name`, `step`, `time`, `domain`, but defer to the checkout:

```cpp
real_t CustomStat(
    const std::string& name,
    timestep_t step,
    simtime_t time,
    const Domain<S, M>& domain) const;
```

Note:

- stats are usually reduced across local domains;
- the return value should state whether it is a sum, an average, or a local quantity;
- the name must match the TOML `custom` list.

## Custom Particle Update

Entity supports a case-specific particle update hook for customizing particle push or boundary response.

The typical pattern is that the PGen returns a functor:

```cpp
template <class D>
auto CustomParticleUpdate(simtime_t time, spidx_t sp, D& domain) const
  -> CustomPrtlUpdate;
```

The functor runs in a device/kernel context and must satisfy Kokkos constraints.

Uses:

- special reflecting boundaries;
- velocity resampling;
- case-specific particle update;
- payload updates.

Risks:

- host/device capture errors;
- species index mix-ups;
- incorrect use of position coordinates and metric transforms;
- complex interactions with the standard pusher, boundary conditions, or charge conservation.

## PGen API Checklist

When reading or writing a PGen, the agent checks at least:

- whether `namespace user` is correct;
- whether the `PGen` template parameters match the current version;
- whether compatibility traits match the TOML;
- whether the constructor stores `params` and the necessary `metadomain`;
- whether `init_flds` exists and is named correctly;
- whether `InitPrtls` uses the correct species;
- whether all `[setup]` parameters are documented in the TOML;
- whether boundaries require corresponding hooks;
- whether custom output/stat names match the TOML;
- whether `CustomPostStep` misuses code units/physical units;
- whether ext_force/ext_current are subject to engine/metric restrictions;
- whether a rebuild reminder is given after modifying the PGen.

## TOML-PGen Contract

TOML and PGen are the two halves of the same case. The agent must not check only one of them.

TOML provides:

- engine, metric, dimension;
- grid, boundaries, scales;
- species definitions;
- output requests;
- PGen custom `[setup]` parameters.

PGen provides:

- compile-time compatibility with engine/metric/dimension;
- initial fields;
- initial particles;
- custom boundaries, external forces, currents, outputs, and runtime hooks;
- interpretation of the `[setup]` parameters.

## Contract 1: Engine / Metric / Dimension

These TOML fields must be consistent with the PGen traits:

```toml
[simulation]
engine = "SRPIC"  # or "GRPIC"

[grid]
resolution = [nx, ny, nz]  # length determines the dimension

[grid.metric]
metric = "Minkowski"
```

Check rules:

- `simulation.engine` must be in the PGen `engines` traits;
- `grid.metric.metric` must be in the PGen `metrics` traits;
- the dimension implied by `grid.resolution` must be in the PGen `dimensions` traits;
- a GRPIC case must not misuse a PGen that only supports SRPIC;
- boundary and coordinate rules for spherical/GR metrics must not be copied from a Minkowski/cartesian case.

If these three are inconsistent, the case is invalid; fix the TOML or the PGen traits first.

## Contract 2: Species

`[[particles.species]]` in the TOML defines the order, label, mass, charge, pusher, and capacity of species:

```toml
[particles]
ppc0 = 16

[[particles.species]]
label = "electrons"
mass = 1.0
charge = -1.0
maxnpart = 1000000

[[particles.species]]
label = "positrons"
mass = 1.0
charge = 1.0
maxnpart = 1000000
```

Common PGen usage:

- `InitPrtls` injects particles by species index;
- `ext_force.species` specifies which species feel the force;
- custom output/stats may accumulate moments per species;
- `CustomParticleUpdate` usually branches on `spidx_t sp`.

Check rules:

- whether the species indices used by the PGen exist;
- whether the species labels used by the PGen match the TOML;
- whether 1-indexed API and 0-indexed container access are correctly distinguished;
- whether massless species use an appropriate pusher;
- whether photon/emission species are defined in the TOML;
- whether `maxnpart` covers initial injection and runtime injection;
- whether `tracking` and payload counts satisfy PGen usage.

## Contract 3: `[setup]` Parameters

`[setup]` is the PGen custom parameter space.

TOML:

```toml
[setup]
bg_B = 1.0
temperature = 1e-3
cs_width = 0.1
```

PGen:

```cpp
bg_B { params.template get<real_t>("setup.bg_B", 1.0) }
cs_width { params.template get<real_t>("setup.cs_width") }
```

Check rules:

- all `params.get("setup.*")` in the PGen should be listed in the case note;
- `setup.*` parameters without defaults must appear in the TOML;
- parameters with defaults should also document the default value;
- parameter units must be explicit: code units, physical units, `m0 c^2`, `n0`, `B0`, etc.;
- parameter names must not be confused with leftovers from old pgens or old branches;
- if the PGen renames a `[setup]` parameter, the corresponding TOML must be updated in sync.

## Contract 4: Scales and PGen Physical Quantities

The TOML `[scales]` section gives normalization scales, which the PGen reads or uses implicitly.

Common fields include:

- `larmor0`;
- `skindepth0`;
- derived `B0`, `n0`, `q0`, `sigma0`, `omegaB0`.

Check rules:

- where the PGen reads `scales.*` must be consistent with the TOML;
- whether initial field strengths, temperatures, densities, drift velocities, etc. use the same normalization;
- do not mix physical coordinates in `InitPrtls` with code units inside `Domain`;
- raw `domain` quantities in `CustomPostStep` are usually in code units; compare them cautiously.

## Contract 5: Boundaries and PGen Hooks

The TOML boundary determines how the framework treats boundaries:

```toml
[grid.boundaries]
fields = [["MATCH"], ["PERIODIC"]]
particles = [["ABSORB"], ["PERIODIC"]]
```

If the TOML uses:

- `MATCH`: the PGen may need `MatchFields` or `MatchFieldsInX*`;
- `FIXED`: the PGen may need `FixFieldsConst`;
- `CUSTOM`: the PGen must provide the corresponding custom behavior;
- `ATMOSPHERE`: the TOML needs atmosphere parameters, and the PGen may also assume specific species;
- runtime boundary change: the PGen may call `metadomain.setFldsBC` or `setPrtlBC` in `CustomPostStep`.

Check rules:

- whether the TOML boundary type is supported by the current engine/metric;
- whether the PGen provides the required hook;
- whether the hook covers the corresponding direction;
- whether spherical/GR automatic boundaries are mistakenly specified manually;
- whether particle boundaries and field boundaries are physically consistent;
- whether runtime boundary changes have a clear trigger time and risk notes.

## Contract 6: Output Requests and PGen Custom Hooks

Standard output in the TOML does not necessarily need a PGen hook:

```toml
[output.fields]
quantities = ["E", "B", "Rho", "N"]
```

But custom output must align with the PGen:

```toml
[output.fields]
custom = ["my_field"]

[output.stats]
custom = ["my_stat"]
```

Check rules:

- whether every name in `output.fields.custom` is handled by `CustomFieldOutput`;
- whether every name in `output.stats.custom` is handled by `CustomStat`;
- whether custom names match exactly, including case;
- whether custom quantity units, basis, and staggering are explicit;
- if the PGen precomputes an output buffer in `CustomPostStep`, check the update timing;
- if the output depends on particle moments, document smoothing and species selection.

## Contract 7: Radiation / Emission / Payloads

If TOML species use:

- `radiative_drag`;
- `emission`;
- `n_payloads_real`;
- `n_payloads_int`;
- `tracking`.

The PGen must cooperate by:

- defining photon species;
- correctly referencing emission species indices;
- not overwriting reserved payloads;
- correctly maintaining payloads in custom particle update;
- documenting payload semantics in output/analysis.

## Contract 8: Checkpoint and Restart

Checkpointing is mainly a run-reliability concern and is not part of the PGen API core. But case design should still note:

- whether runtime state in `CustomPostStep` can be restored from a checkpoint;
- whether random initialization in the PGen constructor is stable after a restart;
- whether custom buffers or local flags need checkpoint support;
- whether runtime boundary changes depend on `time`/`step`, and whether they re-trigger after a restart.

If a case has non-checkpointable runtime state, it must be recorded in the run manifest.

## Contract 9: Modification Boundaries and Rebuilds

Modifying only the TOML usually does not require a rebuild.

Changes that require a rebuild:

- modifying `pgen.hpp`;
- adding or removing a PGen hook;
- modifying compatibility traits;
- modifying compile-time CMake options;
- switching the CMake `pgen`;
- modifying Entity `src/`.

Changes that only require a rerun:

- modifying `[setup]` values without changing PGen parameter names;
- modifying runtime, resolution, extent, output interval;
- modifying standard output quantities;
- modifying checkpoint policy.

Gray areas:

- changing a custom output name requires confirming the PGen already supports it;
- changing the number or order of species requires confirming the PGen indices are still correct;
- changing metric/dimension may require modifying and rebuilding the PGen even without PGen edits, because traits may not support it.

## Case Consistency Check Order

The agent should check a case in this order:

1. Confirm the Entity checkout and version bucket.
2. Read the current `input.example.toml` and confirm the TOML hierarchy.
3. Read the target TOML.
4. Read the target `pgen.hpp`.
5. Extract traits from the PGen.
6. Align engine/metric/dimension.
7. Align species index, label, mass, charge, pusher, payload.
8. List the `[setup]` parameters the PGen reads, and align them with the TOML.
9. Align boundaries with PGen boundary hooks.
10. Align custom fields/stats with PGen output hooks.
11. Check units, basis, and coordinate conventions.
12. Decide whether a rebuild is needed.
13. Output the case consistency report.

## Output Contract

When this skill outputs PGen-related conclusions, it should include:

```yaml
pgen:
  path:
  entity_version_bucket:
  supported_engines:
  supported_metrics:
  supported_dimensions:
  hooks_detected:
    init_flds:
    InitPrtls:
    MatchFields:
    FixFieldsConst:
    CustomPostStep:
    ext_force:
    ext_current:
    CustomFieldOutput:
    CustomStat:
    CustomParticleUpdate:
  setup_parameters:
    required:
    optional:
  toml_contract:
    toml_path:
    engine:
    metric:
    dimension:
    species:
    setup_parameters:
    scales:
    boundaries:
    output_custom_fields:
    output_custom_stats:
    checkpoint_restart_risks:
    needs_rebuild:
  risks:
    -
```
