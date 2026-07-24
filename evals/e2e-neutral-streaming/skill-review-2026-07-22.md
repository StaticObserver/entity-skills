# Skill Issue Retrospective: entity-router and related skills (S1 + Snr1)

Scope: problems exposed by **the skills themselves** (docs, scripts, implementation,
contracts) across the two e2e evaluation rounds, clearly separated from agent-behavior
problems. Evaluation-harness issues are covered in the sibling document
`harness-review-2026-07-22.md`. Evidence: S1/Snr1 archived transcripts, remote logs,
oracle reports; skill source checked against the repo's current `skills/` version.

---

## Part 1: Skill issues exposed by S1 (skills-v5)

S1 background: 72 min, 207 calls, 15 failures. The agent read the skill docs quite
proactively (the SKILL.md of router/pgen/env-build plus several references), and its
post-reading behavior was directionally correct — so the pitfalls below were stepped on
*despite* "reading the docs carefully", and the responsibility lies mainly with the
skills.

### 1. entity-router: implementation defects (by fix priority)

**R1. executor sbatch template error — burns jobs outright; still present in the repo
today.**
`entity_router_executor.py:211` generates `srun %s %s` (passing input as a positional
argument), but Entity v1.4.4 ignores positional arguments and opens the default file
"input"; it needs `-input input.toml`. The router's first submitted job (59855912)
failed because of this and forced the agent to leave the router, hand-write sbatch, and
iterate out-of-band 4 times — the origin of the later stale fingerprint and lost state.
**Fix: change the executor template to `srun entity.xc -input <file>`, and add a
regression test with a real submission.**

**R2. A failed apply leaks an active operation, with no cancel escape — driving the
agent into sqlite.**
`apply_plan` (entity_router_operation.py:403) first calls `create_operation` (sets it
active) and then runs preflight; when preflight throws because the site profile lacks
`policy.default_qos`, there is no rollback, and `complete_operation` (store.py:564)
never executes. All subsequent applies are rejected with "Case has another active
Operation", and entityctl has no cancel/reset/abort subcommand. After grepping and
confirming there was no escape, the agent could only
`sqlite3 UPDATE cases SET active_operation_id=NULL` to edit the control plane directly
— from that point on, the router's "DB is the sole authority" mechanism was hollowed
out.
**Fix: roll back / complete the operation on the apply failure path (add
complete_operation(failed) in try/except); add `entityctl operation cancel <id>`.**

**R3. Misleading error message: `run entityctl migrate`.**
store.py:162 suggests running `migrate` when the store does not exist, but that
subcommand does not exist (`invalid choice: 'migrate'`). Still the case in the repo
today.
**Fix: auto-create the store or point to `entityctl doctor`; add a test for the error
text.**

**R4. `status --live` is fragile.**
A scheduler query failure (job already dequeued, `slurm_load_jobs error: Invalid job
id`) makes the whole command exit 2 (operation.py:513) instead of degrading to the
cached state. Compounded by the agent's manual resubmission leaving the router tracking
the old job, --live is guaranteed to error.
**Fix: on live-query failure, degrade to a warning + return the store-cached state.**

**R5. Installed bundle drifts from the repo version.**
The `allocation failure: Invalid qos specification` string S1 reported does not exist in
the repo source; doctor also shows `matches_runtime: false`. The install directory was
deleted afterwards, so the difference cannot be checked. Evaluation reproducibility
suffers.
**Fix: the install flow records the bundle's commit/hash; doctor reports drift as an
error rather than a hint.**

### 2. entity-router: documentation / contract defects

**R6. No site profile documentation.** Neither SKILL.md nor references/templates has a
schema or example for the site profile; the agent was forced to read the
`validate_site_profile` source to write one, spending 3 minutes reading source.
**Fix: add site-profile.schema.json and a siyuan example to templates/.**

**R7. Recovery-semantics promise does not match the implementation.** Step 5 of SKILL.md
claims "if apply throws, just re-run the same plan; there is no recover command and none
is needed", but R2's deadlock (the fix requires editing the site profile → requires a
new plan → the new plan is stuck behind the leaked op) breaks that promise.
**Fix: after resolving this together with R2, regression-verify this path.**

**R8. No guidance for QoS/partition discovery.** SKILL.md says "Site policy supplies
safe defaults such as … QoS", but no step suggests discovering valid QoS via
sacctmgr/sinfo first; the agent burned two submissions before learning qos=debug.
**Fix: add a "discover QoS/partition" step to the site add flow, or a doctor check.**

**R9. Coverage does not match the promise.** SKILL.md presents itself as an e2e
lifecycle framework (Project→Goal→Operation→Evidence, the identity chain must be
complete), but v5 implements only the `run` Goal; pgen/build/data/analysis have no
lifecycle management (pgen preflight returns `standalone-write: locator is not
registered by Router`). In the final status, `build_id/data_id/analysis_id` are all
empty and run readiness is stuck forever at "submitted" — the identity chain is bound to
break in an e2e scenario.
**Fix: choose one — implement minimal build/data/analysis Goals, or lower SKILL.md's
promise and clearly assign each e2e stage to its owning skill.**

**R10. No submission contract.** Across all skills there is no submission.json spec (the
agent's find confirmed this); the last e2e step (deliverables, final fingerprint
recomputation) is entirely unguided. S1's stale fingerprint was a three-part stack: the
executor bug forced an out-of-band input edit (R1) → the agent edited without re-planning
(agent behavior) → it copied the old hash from plan.json instead of recomputing against
the final artifacts (no contract reminder).
**Fix: define a submission schema (see harness doc A1), and enforce in it a "fingerprint
must be recomputed against the final artifacts" check step or tool command.**

### 3. entity-pgen: three contradictions between docs and Entity v1.4.4 source — following the docs burned 3 jobs

These were the direct cause of 3 of the 5 failed submissions in S1's run phase:

**P1. Contradictory `maxnpart` type annotation.** 09-toml-config.md:84 labels it `uint
(>0)`, while the example in the same file uses `5e6` (a TOML float); the agent wrote
`524288` → `bad_cast to floating` (job 59855920 burned).
**Fix: unify to a float example and note that Entity's parser reads it as a float.**

**P2. Wrong `[boundaries]` table location.** 09-toml-config.md:109 writes boundaries as
a top-level table (the agent copied this into its first draft); Entity v1.4.4's official
input.example.toml requires `[grid.boundaries]` (job 59855932 burned).
**Fix: correct per the official example, and run the doc examples through Entity's own
validation in CI.**

**P3. `use_weights` guidance contradicts the source's enforcement logic.**
03-particle-injection.md:52/297 teaches "PGen passes false, TOML sets
`use_weights = true`", and 09-toml-config.md also says it must be true; but
particle_injector.h actually validates that **the TOML flag must equal the injector
argument, and Cartesian must be false**. The agent only passed after reading the Entity
source and changing to `use_weights = false` (job 59855960 burned).
**Fix: rewrite that section per the source semantics; this is the most severe of the
three because the docs give advice exactly opposite to the validator.**

### 4. entity-env-build: coverage gaps

**E1. No pre-staged notes for siyuan site specifics.** SKILL.md explicitly states it
does "not encode partition/account/module stack", and siyuan has no site notes, so
issues like QoS and modules being unavailable inside slurm were all discovered by agent
trial and error (`Invalid qos specification` and a missing env each burned one run).
**Fix: add site notes for siyuan (qos=debug, debuga100, module availability, PMI
configuration) — this is exactly the extension point the skill is designed for; it just
hasn't been filled yet.**

**E2. Half adoption of the scripts.** The agent scp'd the whole skill scripts directory
to the cluster but used only `entity_checkpoint.py validate/create`;
entity_compat.py, entity_generate.py env/build, and entity_run.py were never run, and
all build scripts were hand-written heredocs — including skipping the "do not compile
before env.sh is generated" rule SKILL.md explicitly states; two slurm env failures
could have been avoided by env.sh. Cause to be investigated (do the docs not show
end-to-end usage? or an agent behavior preference); recorded as a skill usability issue.

**E3. Positive case worth recording too:** `entity_checkpoint.py validate` correctly
intercepted the conflict between version_bucket 1.4.0 and CUDA — the hard gate worked.

### 5. entity-nt2py: no offline fallback for installation

**N1.** During the analysis phase `import nt2` failed; the task forbids external
network, and SKILL.md lists "install nt2py" as a responsibility with no offline install
guidance; the agent fell back to ADIOS2's bundled bpls for the checks (a reasonable
fallback), but produced only a report with no re-runnable script.
**Fix: add an offline install path to SKILL.md (pre-stage a wheel package with the
source cache on siyuan), and clarify the "degraded analysis chain when nt2py is
unavailable".**

### 6. Agent behavior issues (recorded separately, not attributed to skills)

Heredoc quoting errors, a foreground `sleep 120` timeout, a wrongly filled
version_bucket, editing the input without re-planning, copying an old hash into the
submission instead of recomputing. A tendency worth recording: **when a skill fails,
this model silently routes around it (sqlite surgery, hand-written sbatch, sed on
upstream cmake) — it does not report it, does not consult the docs**, and the trace can
only be reconstructed from the transcript afterwards. This is a hint for "skill failure
observability": the oracle's Gate A / out-of-bounds check wordlist should cover
control-plane surgery like editing router.db directly with sqlite3.

---

## Part 2: Skill issues exposed by Snr1 (skills-no-router)

Snr1 background: 134 min, 226 calls, 16 failures. Overall judgment up front: **agent
behavior problems are the primary cause (it knew the skills existed but basically never
used them); skill defects are secondary but real**. From the very start of the session
the agent saw the listing of 3 skills and even wrote in a thinking block "let me just
use the entity-env-build skill", but after a "But first let me understand the build
system" it was pulled into manual exploration and never came back — env-build and pgen
had zero invocations and zero reads the whole way; nt2py was the only skill invoked,
after the simulation finished. Out of 181 Bash commands in the whole session, skill
scripts (checkpoint/compat/generate/run, pgen_preflight, inspect_nt2_data) were hit
**0 times**.

### 1. Skill defects (gaps no amount of reading could have filled)

**G1. Siyuan's srun/PMI assembly knowledge is entirely absent (the largest gap; the root
cause of 4/7 simulation failures).** On siyuan, the ORTE layer of the system OpenMPI
4.1.9a1 is incompatible with pmi2; one must switch to the Spack module
`openmpi/4.1.1-gcc-11.2.0-cuda` + `srun --mpi=pmi2` — the agent went through mpirun
(PMIx conflict) → `srun --mpi=pmix` (no plugin) → pmi2 + system MPI (ORTE blew up) →
adding OMPI_MCA forcing (still blew up) → swapping the MPI stack before converging, plus
39 min of blind waiting (the job had already failed during SSH stutter + API stream
interruption without anyone noticing). This piece of site knowledge: env-build declares
"does not launch simulations" so it is out of scope; the router executor only generates
a bare `srun` (and the router was removed this round); site-notes contains only
`astro.md` and `pi2-v100.md` — **no siyuan.md**. By design it should have been deposited
into site-notes, but since the agent used no skills, naturally nothing was left behind —
the next round will step on it again.
**Fix: write this round's conclusions into `site-notes/siyuan.md` (qos=debug, debuga100,
Spack openmpi 4.1.1 + srun --mpi=pmi2, kokkos/adios2 version combination, login-node
restrictions), and clarify which skill owns "runtime assembly".**

**G2. kokkos.md is missing a Known Issue: GCC 11.2 ICEs on C++20 concepts; the fix is
`Kokkos_ENABLE_LAUNCH_COMPILER=OFF`.** The agent swapped 3 compiler versions at the
wrong layer (11.2→12.3→14.2), spending 50 min and 4 failures before locating the real
cause (the nvcc host compiler was pinned by launch_compiler). The docs only cover the
adjacent nvcc_wrapper propagation problem.
**Fix: add this to kokkos.md Known Issues.**

**G3. "Physics correctness judgment" has no owner — a structural blind spot for the
no-router group.** nt2py's SKILL.md explicitly draws the line: "does not prescribe
physics diagnostics or judge whether a simulation is physically correct"; criteria like
threshold awareness and first-vs-last conservation comparison belong to the router's
science-analysis domain in the v5 bundle. With the router removed, a 40% ux decay and
E² exceeding by 20× had no line of defense at the skill level, and after single-snapshot
analysis (`isel(t=-1)`) the agent wrote the result up as "consistent with drift 0.2
given thermal spread" (at T=0.001, v_th≈0.03 cannot explain a 0.08 mean shift; the
uy/uz spread of ±0.08 is itself ~25× the thermal expectation — no thinking block ever
discussed this contradiction).
**Fix (user decision needed): put a "basic physics sanity checklist" (first-vs-last
comparison, drift/energy-conservation magnitudes, E² noise awareness) into nt2py's or
pgen's deliverable requirements, or accept that this is the router's exclusive value and
state it in the scoring rubric.**

**G4. Entity 1.4.4 CMake's MPI variable quirk is undocumented, and the hard gate "do not
modify Entity core" offers no way out.** The agent got through configure only by
patching Entity's own `CMakeLists.txt` (`MPI_CXX_INCLUDE_PATH`→`MPI_CXX_INCLUDE_DIRS`) —
S1 also sed-ed upstream cmake (the ADIOS2 path). Both rounds overstepped, which shows
this is a genuine Entity 1.4.4 obstacle, while the skills only forbid without offering a
solution.
**Fix: record the quirk and the minimal patch in env-build's Known Issues, or provide a
controlled patch mechanism (patch files included in the checkpoint declaration).**

**G5. nt2py's "do not enforce artifact format" conflicts with evaluation requirements.**
SKILL.md rule 5 deliberately does not enforce report/script format, and the agent's
analysis script lived only inside a remote slurm heredoc, with zero local analysis
artifacts. This is also a harness contract issue (see A2), but the skill side should at
least make "artifacts stay somewhere reachable by the caller" a rule.
**Fix: coordinate with harness A2 on a unified artifact list.**

### 2. Skill doc bugs cross-validated across both rounds

The following issues reproduced independently in both rounds; severity upgraded:

- **The `maxnpart` type contradiction (S1-P1) burned one job in each round**: S1's
  59855920 and Snr1's 59862858 are both `bad_cast to floating`. The docs must be fixed.
- **Missing knowledge of Entity's CLI `-input` burned at least one job in each round**:
  in S1 the router executor generated a positional argument (R1); in Snr1 the agent
  hand-wrote `-i` (59862855). Entity's CLI conventions (`-input <file>`, positional
  arguments ignored) should be written into pgen's toml-config or env-build's run
  chapter — they do not belong only to the router executor.
- **No QoS discovery guidance burned one submission in each round** (S1-R8 ↔ Snr1's
  0th submission `Invalid qos specification`). The site add / site-notes flow must be
  supplemented.
- **Both rounds patched Entity's upstream cmake** (see G4).

### 3. Positive evidence of skill effectiveness

The only stage in Snr1 where a skill was read (nt2py version selection 1.5.3 + late API
usage) was the only stage without repeated trial and error; in S1, the artifacts
produced after reading docs (site profile, the pgen trio, requirements.json) were also
right on the first attempt. **Skill content itself is effective; the problems
concentrate in three points: the trigger mechanism (listing injection does not guarantee
use), doc-vs-source deviations (three places in pgen), and undeposited site knowledge
(the siyuan notes vacuum).**

### 4. Skill trigger mechanism problem (systemic)

Snr1 proves "installed ≠ used": the listing is injected at session start, the Skill tool
is available, the agent even had the intent to use them, and it was still pulled away by
manual exploration and forgot. S1 (whose task started from the router slash command)
read very proactively. The difference suggests: **the launch method determines skill
adoption**. Options: (a) task.md explicitly requires "invoke the relevant skills before
starting work" (but this would contaminate the N group's "no skills" control design, so
it can only be used for the S group); (b) accept adoption itself as a measurement
target, listing "skill invocation count/timing" as an observed metric in the scoring
rubric (the monitoring layer can already count it); (c) strengthen the "read me first,
then act" messaging in skill listing descriptions. Leaning toward (b)+(c); (a) would
break the control.

### 5. Agent behavior issues (recorded separately, not attributed to skills)

- Knew the skills existed but did not use them; even the one skill used, nt2py, was
  "hit the wall first, then read the book" (skipped the prescribed probe script
  `inspect_nt2_data.py`, gifting one analysis-job failure);
- Self-invented pgen injection pattern: looping to call `InjectUniformMaxwellian` per
  species with `{n+1,n+1}` self-pairing (the recommended pattern is one call per species
  pair), resulting in only 2048 particles/species (16 ppc) in practice — 2× off from
  design.md's claimed "PPC 32 per species", and **the agent never noticed the
  design-vs-reality deviation**;
- Violated the pgen skill's rule "do not claim physical correctness without
  verification"; single-snapshot analysis; no site-notes deposited, no local analysis
  artifacts — zero knowledge deposition;
- During the 39 min blind wait it did not proactively check job status (SSH stutter +
  API stream interruption combined; partly environmental).

---

## Part 3: Summary — skill fix priorities

| Priority | Item | Owner | Impact |
|---|---|---|---|
| 1 | Three pgen doc contradictions with v1.4.4 source (maxnpart, boundaries, use_weights) | entity-pgen | 4+ jobs burned across both rounds; following the docs is actively wrong |
| 2 | router executor sbatch `-input` bug + document Entity CLI knowledge | entity-router / pgen | one job burned in each round; the starting point of the router authority being hollowed out |
| 3 | router apply failure leaks active op + no cancel escape | entity-router | drove the agent into direct sqlite edits of the control plane |
| 4 | siyuan site-notes deposit (PMI assembly, QoS, version combination, ICE fix) | entity-env-build | Snr1 4/7 simulation failures + 50 min ICE spiral |
| 5 | Ownership of "physics correctness" criteria and a checklist | router / nt2py / scoring rubric | Snr1's physics failure misreported by the agent as a pass |
| 6 | No submission contract + mandatory final fingerprint recomputation | router / harness A1 | S1 Gate B stale fingerprint |
| 7 | Align router coverage with its promise (implement Goals or lower the promise), site profile docs, `migrate` misleading error, `status --live` degradation, bundle version drift governance | entity-router | trust and reproducibility |
| 8 | nt2py offline install fallback, keep-artifacts-local rule | entity-nt2py | S1 analysis degraded to bpls, Snr1 Gate E a total loss |
| 9 | Controlled patch mechanism for the Entity 1.4.4 cmake MPI quirk | entity-env-build | both rounds overstepped into upstream |
| 10 | Skill triggering / adoption: listing copy + adoption metrics in monitoring | systemic | "installed ≠ used" is the main cause of Snr1's efficiency gap |

**Methodological reminder for evaluation conclusions**: Snr1's "no router" control
actually mixed in the confound of "the agent used no skills at all" — it measures the
joint effect of "skill trigger failure + no router", not a clean router delta. If future
rounds want a clean router-delta estimate, the trigger problem (Part 3, item 10) must be
solved first, or the analysis should be stratified by the transcript's skill invocation
records.
