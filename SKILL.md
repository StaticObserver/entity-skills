---
name: entity-pgen
description: Design, write, and debug Entity problem generators (pgen.hpp + TOML). Use when the user needs to create a new PGen, modify existing PGen code, write matching TOML configs, debug compile/runtime/physics errors in PGen code, or understand Entity's API and normalization conventions for PGen development.
---

# Entity-PGen

## Mission

Help the Agent translate the user's physics requirements into a correct, compilable Entity Problem Generator (pgen.hpp + TOML config). This skill breaks down each PGen development capability into an independent reference, which the Agent matches and combines on demand.

Core workflow:

```
Requirement Clarification → Requirements Document → Match References → Design Document → User Confirmation → Build Code + TOML → Three-Way Audit → Fix → Deliver
```

## Boundaries

**Handle**: Requirement elicitation, PGen code writing, TOML configuration, normalization conventions, structural integrity checks, code-TOML consistency audit.

**Route to other skills**:
- Build environment, CMake configuration, compilation execution → `entity-env-build`
- Entity engine source modifications (Ampere kernel, Context extensions, etc.) → `entity-core-dev`
- Data analysis/visualization → `entity-analysis` or `nt2py`

## Hard Rules

1. **Normalization**: Field values returned by InitFields are in code normalized units and can be written directly into EM arrays; no additional normalization coefficients are needed. ext_current must be multiplied by skindepth0²/larmor0 as compensation (see `references/00-normalization.md` for details)
2. **Coordinate Basis**: SRPIC → local tetrad (orthonormal) basis. GRPIC → coordinate basis. Do not mix them
3. **Unit Domain**: InitPrtls = physical units. CustomPostStep / ext_current = code units
4. **Instance Name Enforced**: The names `init_flds`, `ext_force`, `ext_current` are detected by C++20 concepts and must not be changed
5. **Confirmation Gate Before Writing Code**: After Step 2 produces design.md, explicit user confirmation must be obtained
6. **Audit Before Delivery**: The three-way audit in Steps 5-6 must pass; it cannot be skipped
7. **species index is 1-based**: The species parameter of arch::InjectUniform* starts from 1

## Reference Index

> All references are written based on **Entity v1.4.4**.

### Background Knowledge (Loaded in Step 1)

| Reference | Summary |
|-----------|---------|
| `00-normalization.md` | Normalization conventions, code normalized unit system, numerical specifications for InitFields/ext_current |
| `01-skeleton.md` | PGen skeleton template, minimal runnable PGen, traits declaration, parameter reading, required includes |

### Load by Functionality (Matched to User Needs)

> `09-toml-config.md` is loaded when building the TOML (Step 4). `pgens-index.md` is loaded when API usage is uncertain or a reference implementation is needed.

| Reference | When Needed | Trigger Keywords |
|-----------|-------------|------------------|
| `02-init-fields.md` | Initial EM fields needed | magnetic field, electric field, Bx/By/Bz, Ex/Ey/Ez, Wald, dipole, Harris sheet |
| `03-particle-injection.md` | Particles needed | plasma, particle, electron, ion, injection, Maxwellian, density distribution, pair plasma |
| `04-ext-current.md` | Ampere source term (Minkowski only) | external current, antenna, axion current, J_ext, source term |
| `05-ext-force.md` | External force on particles | external force, external acceleration, radiation force, external B/E field |
| `06-boundary.md` | Non-PERIODIC boundaries | open boundary, absorbing boundary, fixed boundary, atmosphere, conductor |
| `07-custom-output.md` | Custom diagnostic quantities | custom output, extra diagnostics, derived field |
| `08-custom-post-step.md` | Timestep hooks | replenish injection, moving window, dynamic boundary, piston, periodic injection |
| `09-toml-config.md` | Generate/validate TOML config | write TOML, config parameters, section syntax, TOML skeleton |
| `10-higher-order.md` | Custom field stencil or high-order shape | stencil, Cherenkov, numerical dispersion, high-order shape, shape_order, esirkepov, delta_x, beta_xy |
| `pgens-index.md` | Uncertain about API usage or implementation patterns | reference implementation, official examples, Entity built-in pgen, template reference |

## Development Workflow (7 Steps)

### Step 1: Requirement Clarification → user_requirements.md

Load `00-normalization.md` and `01-skeleton.md` as background knowledge.

Collect requirements from the user in **3 rounds**. After each round, present intermediate results. Poll in order; do not jump to the next round.

**Round 1 — Basic Information**:

| # | Question | Options/Notes | Default |
|---|----------|---------------|---------|
| 1 | PGen name | Lowercase English + underscores | **Required** |
| 2 | Physics problem description | Free text: what phenomenon is being simulated? | **Required** |
| 3 | Simulation engine | `SRPIC` / `GRPIC` | `SRPIC` |
| 4 | Metric | `Minkowski` / `Spherical` / `QSpherical` / `Kerr_Schild` / `QKerr_Schild` / `Kerr_Schild_0` | `Minkowski` |
| 5 | Spatial dimensions | 1D / 2D / 3D | Inferred from the problem |
| 6 | Grid resolution + physical extent | Per dimension [N, extent_min, extent_max] | **Required** |

**Round 2 — Physics Configuration**:

| # | Question | Options/Notes | Default |
|---|----------|---------------|---------|
| 7 | Initial field configuration | B field? E field? Spatial distribution? Uniform/non-uniform? | None (vacuum) |
| 8 | Number of particle species + label/mass/charge per species | List | No particles |
| 9 | Initial particle distribution | Uniform / NonUniform? Temperature? Drift velocity? Density? | — |
| 10 | Boundary conditions | PERIODIC / MATCH / FIXED / ABSORB / ... | PERIODIC |

**Round 3 — Advanced Features + Runtime**:

| # | Question | Options/Notes | Default |
|---|----------|---------------|---------|
| 11 | External current/force needed? | Describe the physical mechanism | None |
| 12 | Timestep hooks needed? | Replenish injection / moving window / dynamic boundary / ... | None |
| 13 | Custom output needed? | Extra fields / statistics | None |
| 14 | Fiducial scales | larmor0, skindepth0 | larmor0=1.0, skindepth0=1.0 |
| 15 | Runtime parameters | `runtime`, `ppc0`, `CFL`, `output interval` | runtime=100.0, ppc0=32, CFL=0.45 |

After all three rounds are complete, write the results to `user_requirements.md` (keep `<description>` placeholders, do not fill in example data):

```markdown
# User Requirements — <pgen_name>

## Physics Problem
<description>

## Simulation Parameters
| Parameter | Value |
|-----------|-------|
| Engine | ... |
| Metric | ... |
| Dimensions | ... |
| Resolution | ... |
| Extent | ... |
| Boundaries | ... |
| Runtime | ... |
| larmor0 | ... |
| skindepth0 | ... |
| CFL | ... |

## Field Configuration
<describe initial E/B fields>

## Species List
| # | Label | Mass | Charge | Pusher | maxnpart |
|---|-------|------|--------|--------|----------|

## Initial Particle Distribution
<temperature, drift velocity, density, distribution type>

## External Current/Force
<if applicable>

## Timestep Hooks
<if applicable>

## Custom Output
<if applicable>

## Special Considerations
<constraints specifically mentioned by the user>
```

Present `user_requirements.md` to the user. After confirmation, proceed to Step 2.

### Step 2: Match References → Design Document → design.md

**design.md documents HOW**: Based on user requirements, provide a concrete code implementation plan — PGen structure, InitFields formulas, injection archetype selection, TOML parameter table, etc. This is the translation from physics requirements to code design.

**Sub-step 2a: Match references**

Cross-reference the "Load by Functionality" index table above and match the corresponding reference files based on user_requirements.md. Additional rules:
- Always load `00-normalization.md`, `01-skeleton.md`
- When particle injection is present, replenish depends on `03` + `08`
- When API usage is uncertain, load `pgens-index.md`
- `09-toml-config.md` is loaded in Step 4

After loading the matched references, carefully read the API signatures, constraints, and pitfalls.

**Sub-step 2b: Write design.md**

Based on the requirements document and references, write the design document:

```markdown
# Design — <pgen_name>

## Referenced References
- 00-normalization.md
- 01-skeleton.md
- 02-init-fields.md  ← initial B field needed
- 03-particle-injection.md  ← particle injection needed
- 09-toml-config.md

## PGen Structure
### Traits Declaration
- engines: { SRPIC }
- metrics: { Minkowski }
- dimensions: { _2D }

### Member List
| Member | Type | Source Reference |
|--------|------|------------------|
| params | const SimulationParams& | skeleton |
| metadomain | Metadomain<S,M>& | skeleton |
| init_flds | InitFields<D> | 02-init-fields |
| B0, theta | real_t (from [setup]) | 02-init-fields |

### Defined Methods
| Method | Purpose | Source Reference |
|--------|--------|------------------|
| PGen(...) | Constructor, reads parameters from TOML | skeleton |
| InitPrtls(...) | Initial particle injection | 03-particle-injection |

## InitFields Design
<describe the InitFields struct structure and return value formulas for each method>

## InitPrtls Design
<describe the injection method, archetype used, parameter values>

## TOML [setup] Parameters
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| B0 | real_t | 1.0 | Magnetic field strength |
| temperature | real_t | 0.01 | Plasma temperature |

## Boundary Conditions
- Fields: PERIODIC × 2
- Particles: PERIODIC × 2

## Normalization Checklist
- [ ] InitFields field values are in code normalized units, no extra coefficients needed
- [ ] ext_current multiplied by skindepth0²/larmor0 (if applicable)
- [ ] InitPrtls uses physical units
- [ ] CustomPostStep uses code units (if applicable)
```

### Step 3: User Confirms Design

Present design.md in full to the user. **Must wait for explicit user confirmation** before proceeding to Step 4.

If the user proposes modifications, return to Step 2 to revise the design document and re-confirm.

Confirmation prompt: "Above is the complete design. After confirmation, I will begin writing the code and TOML. Any adjustments needed?"

### Step 4: Build Code

Based on design.md, generate two files:

**4a. Generate `pgen.hpp`**

Assemble in the following order:
1. Include guards + headers (from 01-skeleton)
2. namespace + using (from 01-skeleton)
3. InitFields struct (from 02-init-fields, if needed by design)
4. ext_current struct (from 04, if needed by design)
5. ext_force struct / ExtFields (from 05, if needed by design. ext_force and ExternalFields method are mutually exclusive — pick one)
6. PGen struct (from 01-skeleton):
   - traits declaration
   - member variables
   - constructor (params.get reads [setup] parameters)
   - InitPrtls() (from 03, if needed by design)
   - MatchFields / FixFieldsConst / AtmFields (from 06, if needed by design)
   - ExternalFields() (from 05, if needed by design. Returns ExtFields functor)
   - CustomPostStep() (from 08, if needed by design)
   - CustomParticleUpdate() (from 08, if needed by design. Returns UpdateFunctor)
   - CustomFieldOutput() / CustomStat() (from 07, if needed by design)

Add comments on each method indicating whether physical units or code units are used.

**4b. Generate `<name>.toml`**

Based on 09-toml-config.md and the parameters in design.md:
1. Fill in user-confirmed simulation, grid, metric, boundaries
2. Fill in scales (larmor0, skindepth0)
3. Fill in particles + species (if particles present)
4. Fill in [setup] section (PGen-specific parameters)
5. Fill in output configuration
6. Set `current_filters = 0`

### Step 5: Three-Way Audit

**Launch 3 audit sub-Agents in parallel** (all using `general-purpose` type, `subagent_type`="general-purpose"). Each Agent first reads the corresponding files under `references/`, then reads the generated pgen.hpp, TOML, user_requirements.md, and design.md to perform the audit. If an Agent fails/times out, fall back to the main Agent completing that audit serially.

**Agent 1 — Code Correctness**: Check syntax, traits matching, API signatures (against references), unit annotations, normalization conventions, common pitfalls (1-based/0-based indexing, forgotten CommunicateFields, dead particle charge conservation), performance issues. Output a list of critical/warning issues + fix suggestions.

**Agent 2 — Requirements Satisfaction**: Check item by item against user_requirements.md: field configuration, particle species + injection, boundary conditions + corresponding methods, [setup] parameters, custom output. Output a ✓/✗/⚠ checklist.

**Agent 3 — Code-TOML Consistency**: Check bidirectional matching of params.get and TOML [setup], species index consistency, traits × TOML compatibility, BC method correspondence, custom output name matching. Output a list of inconsistencies.

Conflict resolution priority: Code Correctness > Requirements Satisfaction > Consistency.

### Step 6: Collect Audit Results and Fix

1. Aggregate the three audit reports, sort all discovered issues by severity
2. Fix one by one, marking each as fixed ✓ in the report
3. For issues requiring user trade-off decisions (e.g., performance vs. precision), list the options and ask the user
4. After fixes are complete, if changes are substantial (≥3 modifications), re-run audit Agent 1 for regression check
5. If the audit still does not pass after 2 consecutive rounds of fixes, fall back to Step 2 to redesign (do not modify the original user_requirements.md)
6. On compilation failure: first self-diagnose syntax/include errors; if unresolvable, fall back to Step 4 to regenerate

Audit result summary format:

```markdown
# Audit Summary — <pgen_name>

## Agent 1: Code Correctness
- [ ] Issue 1 (Critical/Warning): <description> → Fixed ✓
- [ ] Issue 2 (Warning): <description> → Needs user confirmation...

## Agent 2: Requirements Satisfaction
| Requirement Item | Status | Notes |
|------------------|--------|-------|
| Initial B field | ✓ | |
| e-/e+ injection | ✓ | |
| ... | | |

## Agent 3: Code-TOML Consistency
- [ ] Inconsistency 1: <description> → Fixed ✓
- [ ] Inconsistency 2: <description> → Fixed ✓
```

### Step 7: Deliver

Final checks before delivery:
- [ ] pgen.hpp has passed audit
- [ ] `<name>.toml` has passed audit
- [ ] Normalization conventions verified (refer to 00-normalization.md)
- [ ] Code comments annotate the unit system

Deliverables:
```
pgens/<name>/
├── pgen.hpp              # Final code
├── <name>.toml           # Final TOML
├── design.md             # Design document (for future reference)
├── user_requirements.md  # Requirements document (for future reference)
└── audit_summary.md      # Audit report
```

Report the deliverable list to the user, and prompt:
- "Code is ready. Next step: use the entity-env-build skill to compile and run."
- "Compile command: `cmake -B build -D pgen=<name>`"

## Reference Decision Table

Some references have mutual exclusion or prerequisite dependencies:

| Scenario | Decision |
|----------|----------|
| ext_current is Minkowski-only | GR users do not need 04. GR + current source → engine modification needed |
| GR init-fields | Requires dx1/dx2/dx3 + potential method. See the GR section of 02 |
| ExternalFields vs ext_force | Pick one. ExternalFields is the superset. Simple force → ext_force |
| Replenish dependency | Requires 03 (ComputeMomentWithSpecies) + 08 (CustomPostStep) |
| Moving Injector | Requires 03 (injection) + 02 (field reset) + 08 (CustomPostStep) |
| Dynamic BC | PGen needs non-const Metadomain. Compatible with MovingWindow |
| PGen without init_flds | Vacuum simulation. Fields remain zero |

## Common Agent Operations

### Updating an Existing PGen

When the user asks to modify an existing PGen:
1. Read the existing pgen.hpp + TOML + design.md (if available)
2. Modify user_requirements.md (mark changed items)
3. Enter Step 2 → only load references corresponding to new functionality
4. Subsequent flow follows the standard workflow

### Debugging an Existing PGen

When the user reports a bug/error:
1. Load the corresponding functionality reference, check the "Common Pitfalls" section
2. Load `00-normalization.md` (the most subtle source of bugs)
3. If TOML-related, load `09-toml-config.md` to validate parameters
4. Launch audit Agent 1 (Code Correctness) for targeted auditing
5. Output a diagnostic report + fix suggestions
