# entity-env-build Skill Evaluation

Date: 2026-06-21

## 1. Overall Conclusion

`entity-env-build` is heading in the right direction. It is no longer just a knowledge document; it is starting to form a Harness:

```text
requirements.json
  -> entity-deps.local.json
  -> compatibility
  -> env.sh
  -> entity-build.sh
```

This structure manages the current build request, dependency state, environment-loading script, and Entity build script separately, which is the correct state model.

But it cannot yet be called a mature Harness. The main problem is not a lack of knowledge, but that many key constraints still live only at the documentation layer and are not fully enforced at the script layer. In other words: the rules are written fairly clearly, but the mechanized gates are not hard enough.

## 2. Main Issues

### P1: The compatibility checker can false pass

In `skills/entity-env-build/scripts/check_compatibility.py`, `has_installed_dependency()` treats a dependency as having installed/discoverable evidence as soon as it sees a non-empty `prefix`, `cmake_config`, or `bin` field.

This lets non-existent paths pass the compatibility check.

In actual negative testing, a checkpoint was constructed with the following non-existent paths:

```text
/tmp/does-not-exist/c++
/tmp/does-not-exist/kokkos
/tmp/does-not-exist/hdf5
/tmp/does-not-exist/adios2
```

`check_compatibility.py` still returned:

```json
{
  "status": "pass",
  "issues": []
}
```

This is currently the most severe issue. It directly breaks Harness layer 5 ("evaluation and observability") and layer 6 ("constraints, validation, failure recovery").

It should at least check:

- whether the compiler path exists and is executable;
- whether the selected dependency prefix exists;
- whether `cmake_config` exists;
- whether `CMAKE_PREFIX_PATH` contains discoverable paths;
- whether a source-built dependency has actual installed evidence, rather than only a generated script;
- whether the serial/MPI modes of MPI/HDF5/ADIOS2 have real probe evidence.

### P1: The entity-build.sh generator can bypass the compatibility gate

`generate_env_sh.py` correctly refuses to generate `env.sh` when `compatibility.status != pass`.

But `generate_entity_build_sh.py` only checks that the given `env.sh` file exists; it does not confirm:

- whether `env.sh` was generated from the current `entity-deps.local.json`;
- whether the current checkpoint's compatibility is still `pass`;
- whether `requirements.json` matches the requirements recorded in the checkpoint;
- whether `env.sh` is stale;
- whether `env.sh` was handwritten or comes from an old build.

This lets a stale or handwritten env enter the Entity compile phase, violating the skill's own hard rules.

`generate_entity_build_sh.py` should explicitly read the checkpoint, or `env.sh` should record the checkpoint hash / requirements hash, verified before generating the build script.

### P2: The most fragile state construction still relies mostly on the model improvising

The current scripts cover:

- source-build script generation;
- compatibility check;
- `env.sh` generation;
- `entity-build.sh` generation.

But the following key actions still rely mainly on the Agent writing by hand or judging freely:

- generating `requirements.json` from the user request;
- probing local CMake/compiler/CUDA/HIP/MPI/Kokkos/HDF5/ADIOS2;
- repairing or merging old checkpoints;
- recording rejected candidates;
- writing source-build execution results back to the selected dependency;
- recording the build execution result.

These are precisely the parts that drift most easily. A mature Harness should fold these fragile operations into scripts or low-freedom flows.

Suggested additions:

```text
scripts/generate_requirements.py
scripts/discover_dependencies.py
scripts/repair_checkpoint.py
scripts/record_dependency_install.py
scripts/run_entity_build.py
```

### P2: The version matrix needs to be bound to verifiable sources

The current skill writes the Entity version and dependency profiles as hard rules:

```text
Entity 1.4.x and older -> C++17 + Kokkos 4.x + ADIOS2 2.10.x
Entity newer than 1.4.x -> C++20 + Kokkos 5.x + ADIOS2 2.11.x
```

This direction may be valuable, but it cannot exist only as static documentation constants. Different Entity checkouts, branches, submodule states, or `dependencies.py` rules may differ.

It is recommended to extract or confirm from the target checkout:

- `dependencies.py`;
- submodule commits;
- tag/branch;
- CMake defaults;
- a verified build matrix.

Then write the profile back into `requirements.json` and `entity-deps.local.json`, recording the evidence source.

### P2: SKILL.md is too heavy, and progressive disclosure is not clean enough

`skills/entity-env-build/SKILL.md` already exceeds 500 lines and duplicates content in `references/`.

For a Codex skill, `SKILL.md` should mainly keep:

- trigger conditions;
- task boundaries;
- hard rules;
- the execution track;
- when to read which reference;
- which scripts must be run;
- the output contract.

Detailed JSON shapes, the compatibility checklist, compile options, and dependency source-build details should live in references or scripts as much as possible.

In addition, `skills/entity-env-build/README.md` is an extra entry point for a live skill. Unless this repo explicitly needs human-readable documentation, consider deleting it or moving it into design docs.

### P2: Nested Git metadata affects the package boundary

`skills/entity-env-build/.git` contains independent Git repository metadata pointing to:

```text
https://github.com/StaticObserver/entity-env-build-skill.git
```

If `entity-skills` is to be managed as a unified skills package, the nested `.git` makes the outer repo's tracking of this skill opaque.

Choose one of:

- explicitly make `skills/entity-env-build` a submodule;
- remove the nested `.git` and let it be an ordinary directory of the outer package.

## 3. Evaluation Against the Six Harness Layers

### 3.1 Context management

Current state: right direction, but not yet mechanized enough.

Strengths:

- explicitly requires starting from the current user request;
- uses `requirements.json` to represent the current build request;
- distinguishes `ENTITY_CHECKOUT` and `ENTITY_WORKDIR`;
- does not let old checkpoints override current requirements.

Issues:

- `requirements.json` is still generated mainly by hand by the Agent;
- no schema validator;
- no requirements completeness gate;
- no hash or fingerprint linking the current request to the checkpoint.

Directions for improvement:

- add `generate_requirements.py` or a schema-driven template;
- add `validate_requirements.py`;
- record `requirements_hash`, `checkout_commit`, `workdir`, and `target_context` in the checkpoint.

### 3.2 Tool system

Current state: tool prototypes exist, but tool coverage is incomplete.

Existing tools:

- `generate_dependency_build_scripts.py`
- `check_compatibility.py`
- `generate_env_sh.py`
- `generate_entity_build_sh.py`

Issues:

- no dependency discovery tool;
- no checkpoint repair tool;
- no build execution wrapper;
- tool results have no unified result shape;
- `check_compatibility.py` lacks real probes.

Directions for improvement:

- turn probing, selection, repair, and recording execution results into scripts;
- have every script output machine-readable JSON;
- have all scripts write back to the same state model.

### 3.3 Execution orchestration

Current state: the flow is clear, but the gates are not all hardened.

Strengths:

- the documentation has an explicit order;
- distinguishes the requirement phase, environment phase, and Entity build phase;
- requires compatibility pass before generating `env.sh`;
- requires `entity-build.sh` to be generated from `requirements.json + env.sh`.

Issues:

- `entity-build.sh` generation does not enforce reading compatibility;
- the build execution result has no script custodian;
- how to update the selected dependency after a source-build still relies on manual work;
- the failure branch flow has no concrete implementation.

Directions for improvement:

- add a master script or playbook runner;
- each step only accepts the previous step's validated artifact;
- every step failure writes a remediation plan;
- build execution is uniformly recorded by a script: stdout/stderr/log/status.

### 3.4 Memory and state

Current state: this is the strongest layer of the current design.

Strengths:

- `requirements.json` as the current request;
- `entity-deps.local.json` as the local dependency checkpoint;
- `env.sh` and `entity-build.sh` are both derived artifacts;
- explicitly requires not rebuilding state from chat history or shell history.

Issues:

- state consistency is not sufficiently verified by scripts;
- the judgment of whether the checkpoint satisfies the current requirements is not deep enough;
- fields like `status.ready_for_entity_build` have no unified updater;
- the build result's pass/fail has no actual execution wrapper.

Directions for improvement:

- write a source hash into every derived artifact;
- add state transition rules;
- let scripts be responsible for updating status instead of manual Agent edits.

### 3.5 Evaluation and observability

Current state: a clear weak spot.

Strengths:

- has a compatibility result shape;
- has checks/issues;
- has a log directory concept;
- has basic script validation suggestions.

Issues:

- the compatibility checker can false pass;
- no real CMake package probe;
- no compiler version probe;
- no automatic `bash -n env.sh` validation;
- no `entity-build.sh` execution log and result recording script.

Directions for improvement:

- upgrade the compatibility check from field checking to probe-based checking;
- run `cmake --find-package` or a minimal CMake probe by default;
- record each probe's command, exit code, and stdout/stderr summary;
- have the build wrapper write `build_result.status`, `started_at`, `finished_at`, and `logs`.

### 3.6 Constraints, validation, failure recovery

Current state: many constraints written, but weak recovery mechanisms.

Strengths:

- explicitly forbids writing into the source checkout by default;
- explicitly forbids default Spack/Docker;
- explicit constraints for MPI, output, CUDA nvcc_wrapper, etc.;
- source-build MPI pauses automatic generation, which is a conservative design.

Issues:

- some constraints exist only in prose;
- no standard remediation action after a compatibility fail;
- no script for repairing stale checkpoints;
- no flow for recovering from a dependency source-build failure;
- generators lack invalidation judgments for old artifacts.

Directions for improvement:

- every failed check must give remediation;
- add checkpoint repair;
- add stale artifact detection;
- provide clean/retry/resume paths for source-build failures;
- output a user confirmation request for uncertain items instead of guessing on.

## 4. Suggested Fix Order

1. Fix the false pass in `check_compatibility.py`.
2. Make `generate_entity_build_sh.py` enforce verification of current checkpoint compatibility.
3. Add `validate_requirements.py` to at least guarantee `requirements.json` completeness.
4. Add dependency discovery / checkpoint repair scripts.
5. Add a build execution wrapper that runs `entity-build.sh` and writes back the result.
6. Slim down `SKILL.md`, moving duplicated details into references.
7. Resolve the package boundary issue of `skills/entity-env-build/.git`.

## 5. Verification Record

Completed:

```bash
python3 -m py_compile skills/entity-env-build/scripts/*.py
```

Result: passed.

Not completed:

```bash
python3 /Users/SoulDancer/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/entity-env-build
```

Result: the current Python3 environment lacks the `yaml` module, so quick validate could not run.

Note: in the current shell, `python` points to Python 2.7, and running these Python 3 scripts with it produces syntax errors. Use `python3`, or write `python3` uniformly in the skill docs and script examples.

## 6. External Basis

The official Entity wiki currently states:

- compilation requires CMake and a C++ compiler, with CUDA/HIP/MPI enabled as needed;
- Kokkos and ADIOS2 can be built in-tree with the code, but an external ADIOS2 install is usually faster;
- when the system already has MPI/HDF5, the official recommendation is to prefer reusing them;
- `dependencies.py` is the officially recommended entry point for dependency script generation;
- Entity compiles with `cmake -B build -D pgen=<...>`, with boolean options using `ON/OFF`;
- `pgen`, `pgens`, `precision`, `deposit`, `shape_order`, `output`, `mpi`, `gpu_aware_mpi`, `DEBUG`, and `TESTS` are the main compile options listed on the official page.

Therefore, `entity-env-build`'s current direction of "local/system reuse first, source-build as last resort, requirements/checkpoint/env/build-script layering" is sound, but the version profiles and compatibility pass must obtain evidence from the target checkout and real probes.
