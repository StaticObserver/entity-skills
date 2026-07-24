# entity-env-build Optimization Plan

Date: 2026-06-22

Basis: `design/entity-env-build-harness-review-2026-06-22.md`

Goal: narrow `entity-env-build` from "a usable Harness prototype with an overly wide control surface" into "a small, hard, simple, elegant, recoverable" build harness. The optimization focus is not piling on new capabilities, but reducing branches, unifying state, and making the main chain more trustworthy.

## 1. Current Baseline

The main chain that has stabilized is:

```text
requirements.json
  -> entity-deps.local.json
  -> entity_compat.py
  -> env.sh
  -> entity-build.sh
  -> entity_run.py build result
```

Completed and to be kept:

- `entity_checkpoint.py validate` blocks invalid/partial requirements by default.
- `entity_generate.py env/build` only accepts `compatibility.status=pass` by default.
- `entity_checkpoint.py record-install` can already record dependency install evidence in a structured way.
- `entity_run.py build` can already execute the generated script and write back `requirements.json.build_result`.
- `tests/test_hard_gates.py` already covers hard gates, the warn gate, stale env, record-install, requirements drift, and runner success/failure.

What truly needs optimization now is not more corner features, but:

- `SKILL.md` is heavy, mixing the main flow with long diagnostic material.
- The location and initialization of `.entity-session.json` are not unified.
- session/log/compat archive/site notes helpers exist, but have not formed a clean state model.
- The source-build sub-agent permission description contradicts the actual build actions.
- The coverage of a compat pass has not been explicitly modeled.
- Cluster configure/build policy needs to be more precise, but must not grow into a remote orchestration framework.

## 2. Design Principles

### 2.1 Subtract first, then harden

Do not evolve with a "one patch per problem" approach. Every future change must satisfy at least one of these conditions:

- removes a conceptual branch;
- unifies a class of state transitions;
- turns manual judgment into a deterministic artifact;
- makes the meaning of `pass/fail` more trustworthy.

Features that satisfy none of these are deferred.

### 2.2 The main chain has only a few core artifacts

Core artifacts are limited to:

```text
requirements.json
entity-deps.local.json
env.sh
entity-build.sh
requirements.json.build_result
```

Auxiliary artifacts may exist, but do not enter the completion criteria:

```text
.entity-session.json
~/.entity-env-build/run.log
~/.entity-env-build/compat/<run_id>.json
~/.entity-env-build/site-notes/<hostname>.md
```

Auxiliary artifacts may only become hard requirements once they are maintained by the unified state layer.

### 2.3 Few entry points, unified state

Keep a few core entry points:

```text
entity_checkpoint.py validate/create/record-install
entity_compat.py
entity_generate.py deps/env/build
entity_run.py build
```

Do not bolt a one-off session/log/report mechanism onto each script. When state is needed, first extract a small shared state-transition layer.

## 3. Target Shape

The target is not a large orchestrator, but a clear minimal pipeline:

```text
validate requirements
  -> create/update checkpoint
  -> check compatibility
  -> generate env
  -> generate build script
  -> run build
  -> record result
```

Each step should satisfy:

- its input is the previous step's validated artifact;
- its output is a deterministic file or structured JSON field;
- failure returns a non-zero exit code;
- the user/Agent can tell from the artifacts what the next step is.

## 4. Phase Plan

## Phase 0: Documentation subtraction and boundary narrowing

Goal: reduce Agent entry complexity first, without changing the main code.

Changes:

1. Slim the `SKILL.md` body to keep only:
   - mission;
   - boundaries;
   - hard rules;
   - the minimal phase workflow;
   - which script to run at each step;
   - completion criteria;
   - reference routing.

2. Move down or demote:
   - long failure diagnosis -> references;
   - network-unavailable scenarios -> references;
   - remote/sub-agent prompt details -> references;
   - site-notes automatic maintenance -> optional;
   - compat archive -> optional;
   - session state -> optional until ownership is fixed.

3. README/CLAUDE keep only an entry index and do not restate policy independently.

Acceptance:

- The `SKILL.md` main flow can be read within 150-220 lines.
- `SKILL.md` no longer requires running the currently non-runnable `python3 -c` session initialization snippet.
- Capabilities not custodied by scripts are no longer written as hard requirements.

## Phase 1: Unify artifact ownership

Goal: resolve the boundary confusion between `.entity-session.json` and the artifact paths.

Decision:

Prefer a pgen/build-run-level session:

```text
$PGEN_DIR/_build/.entity-session.json
```

Rationale:

- One Entity build actually binds one pgen/backend/dependency set.
- `requirements.json`, `entity-deps.local.json`, `env.sh`, and `entity-build.sh` all most naturally live under `_build/`.
- A root-level session easily mixes multiple pgen states, making recovery boundaries unclear.

Changes:

- `references/json-contracts.md` clarifies artifact ownership.
- `SKILL.md` examples uniformly point to `$PGEN_DIR/_build/`.
- If the root-level `$ENTITY_WORKDIR/.entity-session.json` is kept, it can only serve as a workspace index, not as build-run state.

Acceptance:

- Only one build-run session location appears in the docs.
- All artifact path examples match the default paths of `entity_generate.py`.
- Recovery instructions do not rely on chat history.

## Phase 2: Extract a minimal state-transition layer

Goal: avoid patching CLIs everywhere; use one small interface to uniformly record main-chain progress.

Add or refactor:

```text
scripts/entity_state.py
```

Suggested interface:

```python
record_step(artifacts_dir, step, status, inputs=None, outputs=None, run_id=None, message="")
load_state(artifacts_dir)
```

Record only the key main-chain states:

```text
requirements_validated
checkpoint_updated
compatibility_checked
env_generated
build_script_generated
build_executed
```

Do not wire in site-notes, remote, or multi-machine memory in the first version.

Integration order:

1. `entity_checkpoint.py validate/create/record-install`
2. `entity_compat.py`
3. `entity_generate.py env/build`
4. `entity_run.py build`
5. `entity_generate.py deps`

Acceptance:

- After each main-chain CLI succeeds, `.entity-session.json` has the corresponding step.
- Failures do not corrupt existing state.
- Tests verify only a few steps and do not replicate each script's internal details.

## Phase 3: Fix the sub-agent contract

Goal: make the source-build sub-agent contract consistent with actual write behavior.

Changes:

- Change `Read only — no write access` to:
  - may write to the designated build tree, install prefix, and log dir;
  - forbidden to modify `requirements.json`;
  - forbidden to modify `entity-deps.local.json`;
  - may only return a structured result.
- Both `SKILL.md` and the source-build prompt state the allowed write directories.
- The main Agent writes back to the checkpoint only via `entity_checkpoint.py record-install`.

Acceptance:

- The docs no longer contain the contradiction between "execute the build script" and "no write access."
- The only checkpoint write entry for a source-build result handoff is `record-install`.

## Phase 4: Make compatibility coverage explicit

Goal: make the meaning of `compatibility.status=pass` consistent with the implemented scope.

Changes:

Add coverage metadata to the `entity_compat.py` output:

```json
{
  "compatibility": {
    "status": "pass",
    "checker_version": 1,
    "coverage": {
      "requirements_checkpoint_match": "implemented",
      "dependency_path_existence": "implemented",
      "compiler_signature": "partial",
      "path_list_existence": "not_implemented",
      "cmake_package_probe": "not_implemented",
      "mpi_output_mode": "partial"
    }
  }
}
```

Rules:

- `not_implemented` must not silently count toward the full pass contract.
- If an item is required for the current build but not yet implemented, it should yield `warn` or `fail`, blocked by the default gate.
- Coverage is a means of explaining pass credibility, not a new approval path.

Priority checks to fill in:

1. Compiler signature: realpath, family, version, wrapper relation.
2. `PATH` / `CMAKE_PREFIX_PATH` / `LD_LIBRARY_PATH` existence.
3. Whether the prefix owning `cmake_config` enters `CMAKE_PREFIX_PATH`.
4. A minimal CMake package probe.
5. MPI on/off and ADIOS2/HDF5 serial/MPI mode consistency.

Acceptance:

- Coverage metadata appears in the compat result.
- Uncovered required checks are not mistaken for a complete pass.
- Existing hard gate tests keep passing.

## Phase 5: Make cluster policy precise without growing into a remote framework

Goal: resolve the login node / compute node rule ambiguity while keeping the implementation lightweight.

The documentation splits actions into four classes:

| Action | login node | compute node | Notes |
| --- | --- | --- | --- |
| download/materialize | may allow | may allow | depends on the network; record the source |
| configure | may allow under specific conditions | recommended | be careful with GPU/tool-linked configure |
| compile/link | forbidden by default | recommended/required | goes through the scheduler by default on clusters |
| run/test | forbidden by default | recommended/required | depends on the GPU/MPI runtime |

The first version only does documentation and a build-plan field; no automatic scheduler abstraction.

Optional artifact:

```json
{
  "execution_plan": {
    "configure_context": "login|compute",
    "build_context": "compute",
    "scheduler": "slurm|pbs|manual",
    "notes": []
  }
}
```

Acceptance:

- `SKILL.md` no longer gives both the vague "NEVER compile on login nodes" and an undefined login configure exception.
- No automatic remote execution framework is introduced.

## Phase 6: Clean up prompt and remote semantics

Goal: make independent verification actually verify the current artifact.

Changes:

- The compat sub-agent prompt is based primarily on file paths and hashes.
- Inline JSON serves only as a summary, not as the object of verification.
- The remote prompt is labeled experimental.
- Remote verification requires script version consistency: the same commit/hash, or explicitly uploading this session's scripts.

Acceptance:

- Prompts no longer say "no file reads needed."
- Sub-agent verdicts record the requirements/checkpoint hashes.
- Remote is not a completion condition of the main chain.

## 5. Minimal Test Matrix

Run at least the following for every code optimization:

```bash
python3 -m py_compile scripts/*.py
python3 -m unittest tests/test_hard_gates.py
```

Add new tests phase by phase, not all at once:

| Phase | Test | Expected |
| --- | --- | --- |
| Phase 1 | artifact/session path examples align with generated defaults | no duplicate build-run state location |
| Phase 2 | CLI success records one state step | `.entity-session.json` updated |
| Phase 2 | CLI failure does not erase prior state | previous state preserved |
| Phase 3 | source-build contract forbids JSON writes but allows build dir writes | docs/prompt consistent |
| Phase 4 | compat result includes coverage metadata | coverage keys present |
| Phase 4 | missing required path list entry | fail or blocking warn |
| Phase 4 | compiler same class but different version/path | warn/fail unless accepted |
| Phase 5 | cluster plan separates configure/build context | execution_plan explicit |
| Phase 6 | compat prompt includes file hashes | no stale inline-only validation |

## 6. Recommended Execution Order

Ordered by benefit and complexity:

1. Phase 0: documentation subtraction. First separate hard requirements from optional notes.
2. Phase 1: unify artifact ownership. Without this, the state layer stays chaotic.
3. Phase 3: fix the source-build sub-agent contract. Low cost, removes a direct contradiction.
4. Phase 6: fix compat prompt fresh-read semantics. Low cost, improves verification credibility.
5. Phase 4: add compatibility coverage metadata, then gradually fill in high-value checks.
6. Phase 2: extract the minimal state-transition layer. Wire it into the main CLIs after artifact ownership stabilizes.
7. Phase 5: make cluster policy precise. Document it first; do not build a remote framework.

Note: Phase 2 must not turn into a big orchestrator. It only records main-chain state uniformly; it does not make all decisions for the Agent.

## 7. Deferred Items

Not done in the short term:

- full automatic dependency discovery coverage;
- automatic remote build orchestration;
- automatic scheduler submission abstraction;
- parallel multi-sub-agent builds;
- automatic site-notes summarization;
- a complete machine memory database;
- GUI/dashboard;
- a large `entity_env_build.py run-all` master command.

All of these may have value, but they would push the project back toward a complex control surface. The current goal is to make the minimal main chain stable and trustworthy.

## 8. Completion Criteria

After the optimization, it should be possible to answer three questions:

1. If a CLI returns success, can its output artifact really be trusted for the next step?
2. If it fails, can you see from the JSON/state/log which step failed, instead of digging through chat history?
3. If the Agent is interrupted, can you recover from the artifact chain under `_build/`?

If all answers are "yes," the skill is already good enough. Further optimization should prioritize deleting complexity over expanding the feature surface.
