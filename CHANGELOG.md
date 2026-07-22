# Changelog

All notable changes to the Entity skills bundle are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The bundle is versioned with semantic versioning, starting at 0.x: the first
version considered production-satisfactory will be released as 1.0.0. Schema
versions (store, plan, GoalSpec, checkpoint, compat checker) are independent
integer compatibility contracts and are not the product version.

## [0.4.0] - 2026-07-22

### Added

- New Goal kinds `build` and `data` (Phase 2 e2e coverage):
  - `build` registers an env-build-produced build into the identity chain.
    Hard gates at plan and apply: the checkpoint must have
    `compatibility.status == "pass"` and a `decisions.parameters` confirmation
    digest. The registered build identity feeds subsequent run Goals without
    an explicit `executable`.
  - `data` inventories a run's outputs into a content-hashed
    `data-inventory.json` and advances `current.data_id` / readiness.
- Executor Step kinds `build.register.v1` and `data.inventory.v1`.
- Gates added: run Goal planning now requires a simulation-parameter
  confirmation record (`<input>.decisions.json` written by
  `pgen_preflight.py confirm`) whose `input_sha256` matches the current TOML;
  missing or stale records fail planning with `needs_decision` (Phase 1.5).

### Changed

- Plans now carry `goal_kind`; `validate_plan` checks per-kind key sets and
  Step schemas. Plans written by 0.1.0 remain valid (missing `goal_kind`
  reads as `run`) but should be re-planned.

### Known limitations

- Re-inventorying a run whose outputs changed produces the same Plan, which
  resolves to the completed Operation; a refresh path lands with the
  reconciliation work in 0.5.0.
- `analysis` Goal is not implemented yet; analysis stays with entity-nt2py
  and router records only.

## [0.3.0] - 2026-07-22

### Added

- entity-env-build: build parameter confirmation gate (Phase 1.5, hard fail).
  `entity_checkpoint.py confirm <requirements> --checkpoint <checkpoint>
  --by <actor> [--confirm-defaults]` records `decisions.parameters`
  `{digest, confirmed_by, confirmed_at, defaults, card}`; the compatibility
  check `parameters.confirmation` fails when the record is missing or the
  digest no longer matches the current requirements.
- entity-pgen: `pgen_preflight.py card <input.toml>` prints the simulation
  parameter card; `pgen_preflight.py confirm <input.toml> --by <actor>
  [--confirm-defaults]` writes `<input>.decisions.json`.

## [0.2.0] - 2026-07-22

### Added

- `entityctl site discover <site>`: enumerates Slurm partitions and QoS via
  `sinfo`/`sacctmgr` and suggests `policy.default_*` values (read-only).
- `templates/site-profile.schema.json` documenting the Site profile contract.
- `entityctl submission create/verify`: submission fingerprints are always
  recomputed by the tool from the final artifacts; `verify` reports stale and
  missing artifacts and exits non-zero on drift.
- Executor anomaly remediation: scheduler rejections (invalid QoS/partition)
  now carry the exact repair path (`entityctl site discover` + policy fix).

## [0.1.0] - 2026-07-22

First disciplined release. Baseline: the Entity Router v5 architecture lineage
(store schema 1) with the fixes below. Development plan:
`design/router-development-plan-2026-07-22.md`.

### Added

- `entityctl operation cancel <id>`: terminal escape hatch for pending/running
  Operations; releases the Case so a different Plan can proceed.
- `entityctl store migrate`: store schema migration entry point (shell; no
  schema migrations exist yet). Doctor reports the store schema version and
  points here on mismatch.
- `bundle_version` reported alongside `bundle_hash` in `entityctl doctor` and
  install receipts; single source at `skills/entity-router/VERSION`.
- entity-env-build: `mpi.openmpi_min_version` compatibility check — OpenMPI
  must be >= 5.0.0 when selected (fail below; warn when unrecorded).
- Gates added: re-applying a Plan after a failed Apply reopens the Operation
  and resumes committed Steps instead of deadlocking the Case.

### Fixed

- entity-router executor sbatch now invokes `srun <exe> -input <file>`;
  Entity ignores positional arguments and previously opened the default
  `input` file, burning the first submitted job.
- A failed Apply no longer leaks an active Operation; it finishes as
  `anomaly` and releases the Case (previously forced direct sqlite surgery).
- Missing-store error no longer points at the nonexistent `entityctl migrate`.
- `status --live` degrades to cached controller state with a warning when the
  scheduler query fails, instead of exiting 2.

### Changed

- User-facing "Router v5" strings renamed to plain "Entity Router"; v5 remains
  only as the internal architecture lineage and store schema integer.
- Doctor output keys `v5_store`/`v5_store_available` renamed to
  `store`/`store_available`.
