# Entity Router Development Plan (2026-07-22)

Sources: the S1/Snr1 two-round e2e evaluation retrospective
(`evals/e2e-neutral-streaming/skill-review-2026-07-22.md`), the R1–R4 fix process, and
three pieces of production feedback (missing confirmations, version naming). This
document is the baseline plan for subsequent development.

## Decisions Made

1. **Versioning starts at 0.x**. The current skill is not a production baseline; the
   first basically satisfactory version is released as 1.0.0.
2. **Confirmation gates are hard fails**, with no warn observation period.
3. Confirmation of build parameters and simulation parameters must be a **recorded
   fact**, not conversation history.

## Design Principles

Generalizing from evaluation and production evidence: drift happens entirely where
"rules are known but rely on agent self-discipline"; the agent's value shows entirely
where "rules are unknown and reasoning is needed". Work is therefore split into three
categories:

| Category | Criterion | Handling | Evidence |
|---|---|---|---|
| Deterministic convergence | Rules known; mistakes burn jobs or corrupt state | Code hard gate, no agent freedom | `-input`, fingerprints, QoS legality, ID/hash derivation |
| Constrained choice | Options enumerable, choice needs judgment | Code enumerates options, agent/user chooses, code records | QoS/partition selection, build/simulation parameter confirmation, deletion authorization |
| Free play | Rules unknown, reasoning needed | Agent free within the owner skill; router only verifies receipts at boundaries | PGen physics design, novel fault diagnosis, analysis conclusion judgment |

Three cross-cutting disciplines:

1. **The agent does not compute what code can compute, nor read what code can
   summarize** — hashes, IDs, parameter cards, and scheduler queries belong to code; the
   agent's thinking is spent only on physics and novel fault diagnosis.
2. **Confirmations and conclusions must be recorded facts** — only records in
   `decisions` carrying a digest and an attribution count; gates do not accept prose.
3. **Every release is validated by replaying the S1/Snr1 transcripts**, not by feel.

Meta-rule: **every burned job and every discovered drift converts into a hard gate or a
`needs_decision` field; converting only into documentation is not allowed.**

## Versioning Design

Two layers of versioning, each with its own job:

- **Schema version = compatibility contract** (plain integer, already exists, unchanged):
  `STORE_SCHEMA_VERSION`, plan/GoalSpec/receipt `schema_version`, env-build
  `checker_version`. Bumped only when the contract changes. All "v5" in user-visible
  strings is cleaned up and demoted to a purely technical field.
- **Product version = release management** (semver): single source
  `skills/entity-router/VERSION` (covered by `bundle_hash`; a version change
  automatically yields a new bundle identity).
  - PATCH: bug fixes, documentation corrections;
  - MINOR: backward-compatible new capabilities (new Goal kinds, new commands, new
    gates, new site profile fields);
  - MAJOR: breaking schema contract changes, gate semantics changes that invalidate
    existing checkpoints. During 0.x, MINOR carries all feature evolution and MAJOR
    semantics is suspended; strict enforcement starts at 1.0.0.
- Supporting pieces: `CHANGELOG.md` (Keep a Changelog), a git tag per release,
  `entityctl store migrate` as a real command (for now build the command shell and
  schema detection; write the first real migration when store schema 6 appears), and
  doctor distinguishing "tagged release" from "dirty development version".

## Release Roadmap

> Progress (2026-07-22): 0.1.0–0.5.0 delivered (132 tests all green). 0.5.0 landed
> status --live divergence classification (job_gone/state_mismatch/untracked_job),
> doctor hard failures (bundle drift, invalid Site profiles) + leaked Operation
> warnings, `apply --refresh` data inventory refresh, and the skill_adoption adoption
> metric in the phases report. Deviations from this document: the `analysis` Goal is
> deferred (stays in entity-nt2py; router only records it), already noted in the
> CHANGELOG Known limitations.

### 0.1.0 (baseline + Phase 0, version infrastructure)

Completed part (R1–R4 + OpenMPI gate, see CHANGELOG):
- executor sbatch `-input`; apply failure finish anomaly + `operation cancel`;
  store-missing error fix; `status --live` failure degradation; OpenMPI >= 5.0.0 gate.

Phase 0 remaining:
- `skills/entity-router/VERSION` = 0.1.0; establish `CHANGELOG.md`;
- doctor/status/install receipt report `bundle_version` + `bundle_hash`;
- clean up "Router v5" user-visible strings; `entityctl store migrate` command shell +
  schema detection.

### 0.2.0 (Phase 1, run boundary convergence)

1. `entityctl site discover <site>`: code runs `sinfo`/`sacctmgr`/`scontrol`, enumerates
   legal QoS/partitions/GRES and suggests `policy.default_*`; the choice is left to the
   agent/user. (R8, one job burned in each of the two rounds)
2. `templates/site-profile.schema.json`, eliminating the cost of "having to read the
   `validate_site_profile` source to write a profile". (R6)
3. Submission contract v1: `entityctl submission create/verify`; fingerprints are
   recomputed by the tool over the final artifacts, so the agent never touches hash
   strings in the pipeline. (R10, S1 Gate B stale fingerprint)
4. Structured mapping of executor preflight anomalies (invalid QoS → suggest
   `site discover`), with error messages carrying their own repair path.

### 0.3.0 (Phase 1.5, confirmation gates, hard fail)

Production problem: the agent does not proactively confirm build parameters and TOML
simulation parameters. Root cause: pgen has no such rule, env-build is a 14-field prose
checklist, and there is no gate anywhere in the chain.

1. env-build parameter card: `entity_checkpoint.py validate` derives a build parameter
   card + digest from requirements.json; `decisions.parameters = {digest,
   confirmed_by, confirmed_at}`; a missing or mismatched digest at validate/env.sh
   generation time → **fail**.
2. pgen parameter card: preflight derives a simulation parameter card (drift/injection,
   ppc, resolution, steps/dt, boundaries, output cadence) + digest from TOML/PGen.
3. router plan (run Goal) recomputes the TOML parameter digest; without a matching
   confirmation record → `needs_decision` with the parameter card attached — the last
   gate before the burn-a-job boundary.
4. Fields in two tiers: Tier 1 (physics and money, blocking): pgen, backend+gpu_arch,
   mpi, precision, drift/injection, ppc, resolution, steps/dt, boundaries; Tier 2
   (listed, may default): deposit, shape_order, debug/tests, dependency_policy. The
   `--confirm-defaults` bypass carries an attribution, so the audit chain stays intact.

### 0.4.0 (Phase 2, e2e coverage, R9)

- `build` Goal: router only verifies the checkpoint exists with compatibility=pass,
  derives build identity, and records artifact hashes; freedom over the build process
  itself is not reclaimed.
- `data`/`analysis`: initially only inventory identity + readiness advancement.
- SKILL.md promises aligned with implementation.

### 0.5.0 (Phase 3, observability and reconciliation)

1. `status --live` reconciliation: divergence classification
   (`job_gone`/`state_mismatch`/`untracked_job`), so out-of-band operations surface in
   status.
2. doctor upgrade: bundle drift fail (R5), leaked active operation detection with a
   cancel hint, site policy completeness.
3. Adoption metric: trace records skill script invocation counts (prerequisite for a
   clean comparison in evaluations).

### 1.0.0 Candidate Criteria (all required for release)

- 0.2.0–0.5.0 all landed;
- every S1/Snr1 failure point in transcript replay is intercepted by a gate or has a
  clear owner;
- a real SSH site (siyuan) runs the build→run→data chain end to end with an intact
  identity chain;
- at least one new e2e evaluation round with skill script hit rate > 0 and no
  sqlite-level control-plane surgery.

### Ongoing (Phase 4, knowledge precipitation loop)

- When apply ends in an anomaly and the diagnosis conclusion is known,
  `entityctl site note` writes back to the site profile / env-build site-notes (the
  OpenMPI gate is the first instance);
- every release records a "Gates added" section in the CHANGELOG.

## Explicitly Out of Scope

- No generic workflow engine; the four layers Project→Goal→Operation→Evidence are
  enough, and Phase 2 only adds Goal kinds horizontally.
- Physics-correctness criteria do not enter the router: they land in nt2py/pgen
  deliverable requirements (a first/last conservation checklist tool, interpreted by the
  agent); the router only requires that the checklist's receipt exists. **Pending the
  user's final decision.**
- Legacy compatibility paths stay untouched until the new Goals pass acceptance on a
  real SSH site.
