# entity-env-build Harness Review

Date: 2026-06-22

Review scope: the current live skill surface of `skills/entity-env-build/`, including `SKILL.md`, `README.md`, `CLAUDE.md`, `scripts/`, `references/`, and `tests/`. The outer `test-wtih-cc/` serves only as practice-record background, not as part of the shared skill itself.

## Overall Assessment

`entity-env-build` is already a usable build harness, not a purely knowledge-based skill. Its core chain is clear:

```text
requirements.json
  -> entity-deps.local.json
  -> compatibility
  -> env.sh
  -> entity-build.sh
  -> entity_run.py build result
```

Compared with the 2026-06-21 version, the current version has fixed several early hard problems:

- `entity_checkpoint.py validate` blocks `partial` by default; only `--allow-partial` exits 0.
- `entity_generate.py env/build` only accepts `compatibility.status=pass` by default; `warn` requires `--allow-warnings` plus structured user confirmation.
- `entity_checkpoint.py record-install` exists, verifies real paths, and invalidates compatibility.
- `entity_run.py build` exists, custodies execution of the generated script, and writes back `requirements.json.build_result`.
- Tests cover the hard gates, warn gate, stale env gate, record-install, requirements snapshot drift, and build runner success/failure recording.

Therefore, the main problem is no longer "no tools" or "hard gates completely broken," but that the closed loop of a mature Harness is still not fully mechanized: state initialization paths are inconsistent, the session/compat/site notes helpers are not wired into most CLIs, some documentation promises still exceed actual script capabilities, and the remote/sub-agent orchestration contract contains contradictions.

## Design Principle Addendum: Don't Patch Everywhere

Future optimization should not become "every hole found gets a special case in some script." That makes the skill ever more complex, until the Agent faces a pile of branches, flags, and exceptions instead of one reliable track.

A better direction:

- A few core artifacts: `requirements.json`, `entity-deps.local.json`, `env.sh`, `entity-build.sh`, `build_result`.
- A few core entry points: validate, checkpoint/update, compat, generate, run.
- One unified state-transition function, instead of hand-writing session/log update logic in every script.
- Documentation describes only execution paths that really exist; capabilities not yet custodied by scripts are demoted to optional notes, not written as hard requirements.
- Fixes should prioritize reducing concepts and branches over adding new commands, new flags, and new special cases.

In other words, the goal is not to wire every helper into every place, but to narrow the main chain to "short, hard, verifiable." An elegant Harness should let the Agent judge less, not teach the Agent more patch rules.

## P1 Findings

### P1.1 The session initialization example cannot run directly, and the state file location conflicts with the artifact layout

Locations:

- `skills/entity-env-build/SKILL.md:130-139`
- `skills/entity-env-build/SKILL.md:141-153`
- `skills/entity-env-build/scripts/_json_io.py:247-284`

Problem:

`SKILL.md` requires initializing session state after confirming paths:

```bash
python3 -c "
from _json_io import init_session_state
init_session_state(Path('$ENTITY_WORKDIR'))
"
```

This snippet has two immediate problems:

- When run from the skill root, `_json_io.py` lives under `scripts/` and is not on the default import path.
- Even with `PYTHONPATH=scripts` set, the snippet lacks `from pathlib import Path` and raises `NameError`.

Probe from this review:

```bash
ENTITY_WORKDIR="$tmp" python3 -c "from _json_io import init_session_state; init_session_state(Path('$tmp'))"
```

Result: `ModuleNotFoundError: No module named '_json_io'`.

```bash
ENTITY_WORKDIR="$tmp" PYTHONPATH=scripts python3 -c "from _json_io import init_session_state; init_session_state(Path('$tmp'))"
```

Result: `NameError: name 'Path' is not defined`.

Even after fixing the imports:

```bash
PYTHONPATH=scripts python3 -c "from pathlib import Path; from _json_io import init_session_state; init_session_state(Path('$tmp'))"
```

What actually gets written is:

```text
$ENTITY_WORKDIR/.entity-session.json
```

But `SKILL.md`'s default artifact layout places `.entity-session.json` at the pgen level:

```text
$PGEN_DIR/_build/.entity-session.json
```

Harness impact:

This is the entry to layer 4, "memory and state." An entry command that cannot run pushes the Agent back to chat context; an inconsistent state file location means recovery doesn't know whether the root session or the pgen session is authoritative.

Suggestions:

- Add a proper CLI, e.g. `scripts/entity_checkpoint.py session-init --workdir ... --artifacts-dir ...` or `scripts/entity_session.py init`.
- Clarify session state ownership: if one build binds one pgen, it should live at `$PGEN_DIR/_build/.entity-session.json`; if a root-level session is responsible for multiple pgens, the pgen/build artifact paths should be explicitly recorded in it.
- Change all documentation examples to directly runnable script commands; do not use bare `python3 -c` imports of internal modules.

### P1.2 The dependency source-build sub-agent permission contract contradicts itself

Locations:

- `skills/entity-env-build/SKILL.md:402-453`
- `skills/entity-env-build/scripts/entity_generate.py:183-481`

Problem:

`SKILL.md` requires the source-build sub-agent to execute the generated dependency build script and return `prefix/cmake_config/version/compiler_signature/issues[]`. But the same section also says:

```text
Sub-agent permissions: Bash(bash build-<dep>.sh) and Read only — no write access.
```

The whole purpose of a dependency build script is to write the build tree, install prefix, and logs. What should really be forbidden is "hand-editing JSON," not all write operations.

Harness impact:

This is a contract error in layer 2 ("tool system") and layer 3 ("execution orchestration"). Executed literally, the sub-agent cannot complete the build; executed loosely, it violates the documented permission constraints. In a high-risk HPC environment, the Agent won't know which rule to follow.

Suggestions:

- Change the permissions to: allow writes to restricted build/install/log directories; forbid modifying `requirements.json` and `entity-deps.local.json`.
- When generating the build script, write the allowed write directories into the prompt and the script header.
- Sub-agent output must enter the checkpoint only through `entity_checkpoint.py record-install`.

## P2 Findings

### P2.1 The session state, compat report, and site notes helpers are still not wired into the main CLI loop

Locations:

- `skills/entity-env-build/scripts/_json_io.py:149-189`
- `skills/entity-env-build/scripts/_json_io.py:247-348`
- `skills/entity-env-build/scripts/entity_checkpoint.py:142-167`
- `skills/entity-env-build/scripts/entity_checkpoint.py:333-407`
- `skills/entity-env-build/scripts/entity_compat.py:1069-1115`
- `skills/entity-env-build/scripts/entity_generate.py`
- `skills/entity-env-build/scripts/entity_run.py:45-122`

Implemented:

- `_json_io.py` has `log_event()`, `save_compat_report()`, `init_session_state()`, `update_session_state()`, and site-notes helpers.
- `entity_run.py build` calls `ensure_harness_home()` and `log_event()`, and writes back the build result.

Gaps:

- `entity_checkpoint.py validate/create/record-install` does not update `.entity-session.json`.
- `entity_compat.py` does not call `save_compat_report()`, and has no `--run-id` / `--save-report`.
- `entity_generate.py env/build/deps` does not call `update_session_state()`, nor does it write the run log.
- Site notes are still updated by Agent prose, not by a script-custodied structured action.

Harness impact:

The state layer is currently "usable parts," not an execution track. After a task interruption, the Agent may still rely on chat history to judge which step it reached; compat evidence may also lack a traceable independent report.

Suggestions:

- Do not scatter patches across every CLI. First define a minimal `run_context` / `state_transition` helper, called uniformly by a few entry points.
- The main chain only needs to record key states: requirements valid, checkpoint updated, compat checked, env generated, build script generated, build executed.
- Whether the `compat` report is archived should be part of that unified state transition, not a separate logic tree growing next to `entity_compat.py`.
- Demote site notes to an optional reference for now; once the main chain is stable, wire them in with a structured append tool.

### P2.2 A compatibility `pass` is still smaller than the pass promised by the docs

Locations:

- `skills/entity-env-build/references/compatibility-check.md:70-181`
- `skills/entity-env-build/scripts/entity_compat.py:96-157`
- `skills/entity-env-build/scripts/entity_compat.py:297-379`
- `skills/entity-env-build/scripts/entity_compat.py:1000-1066`

Improved:

`entity_compat.py` already verifies schema version, requirements snapshot drift, compiler path, dependency paths, parts of the version profile, ADIOS2/Kokkos/CUDA conflicts, and source-build install evidence, and it updates the checkpoint status.

Remaining gaps:

- Compiler consistency is judged mainly by basename/toolchain class; host compilers of the same class but different paths/versions may still be treated as pass.
- `paths.PATH`, `CMAKE_PREFIX_PATH`, and `LD_LIBRARY_PATH` entry existence is not systematically verified.
- A minimal CMake package probe is not yet implemented.
- MPI wrapper output and ADIOS2/HDF5 serial-vs-MPI mode consistency are not mechanized.
- Matching of GPU architecture against Kokkos enabled arch is still incomplete.
- `compatibility-check.md` marks several items as Partial, but the generators only look at the final `pass` and don't know the coverage of that pass.

Harness impact:

This is a credibility issue in layer 5, "evaluation and observability." The current `pass` means "passed the implemented checks," not yet "satisfies the full documented contract." For HPC builds, this disguises uncovered risk as a deliverable state.

Suggestions:

- Add `coverage` / `implemented_checks_version` / `unimplemented_required_checks` to the compatibility result.
- For required checks still marked Partial in the docs, either implement them or explicitly demote them to `warn` in the result.
- Prioritize implementing compiler signature, path list existence, CMake package probe, and MPI/output mode consistency.

### P2.3 The remote compat prompt conflicts with SKILL.md's fresh-read semantics

Locations:

- `skills/entity-env-build/SKILL.md:455-487`
- `skills/entity-env-build/scripts/entity_generate.py:761-808`

Problem:

`SKILL.md` requires the compat sub-agent to:

```text
Read both files from scratch.
```

But the prompt generated by `_compat_prompt()` says:

```text
Read BOTH JSONs above — they are already in your context, no file reads needed.
```

The remote example also contains a placeholder path:

```text
ssh <remote> 'python3 /path/to/scripts/entity_compat.py ...'
```

without making how the skill scripts are synced/located an input.

Harness impact:

The value of an independent compat sub-agent lies in re-reading from on-disk evidence, not reusing the main Agent's inline stale snapshot. Otherwise, if the files are modified after the prompt is generated, the sub-agent is not verifying the current artifact.

Suggestions:

- Base the compat prompt on file paths and hashes; inline JSON serves only as a summary.
- Sub-agent verdicts must record the hashes of `requirements.json` and the checkpoint.
- Remote mode must specify how scripts are synced, or require that the remote already has skill scripts at the same commit/hash.

### P2.4 Cluster policy is not precise enough about the configure/build boundary

Locations:

- `skills/entity-env-build/SKILL.md:65`
- `skills/entity-env-build/SKILL.md:525-533`
- `skills/entity-env-build/SKILL.md:579-582`

Problem:

The hard rules say "NEVER compile on login nodes" on clusters and require showing a login-vs-compute difference table; but the current `SKILL.md` has no such table. A later section also suggests, for Entity's `plog` FetchContent scenario:

```text
Run cmake configure on a login node (with internet) first
```

This may be a reasonable strategy, but it needs to distinguish:

- dependency configure;
- Entity configure;
- actual compilation/linking;
- FetchContent download/materialization;
- whether GPU-tool-linked tools trigger during the configure phase.

Harness impact:

This is a rule ambiguity in layer 6, "constraints, validation, failure recovery." The Agent may be overly conservative and unable to use login-node networking, or may mistakenly treat configure as an allowed build operation.

Suggestions:

- Split cluster execution policy into four action classes: `download/materialize`, `configure`, `compile/link`, `run/test`.
- Add the login-vs-compute difference table promised in the docs.
- Let the generators support a split execution plan: login-node configure only + compute-node build, recorded into requirements/build plan.

## P3 Findings

### P3.1 SKILL.md is still heavy, mixing entry rules with a diagnostic manual

Locations:

- `skills/entity-env-build/SKILL.md`
- `skills/entity-env-build/references/*`

Problem:

`SKILL.md` contains task boundaries, hard rules, and the three-phase flow, but also fault trees, network failure strategies, site notes maintenance details, cluster special cases, and the output contract. It is readable, but still heavy as an Agent entry point.

Suggestions:

- `SKILL.md` keeps trigger conditions, inviolable gates, phase runner order, and the state transition table.
- Fault trees, cluster policy, network fallback, and dependency notes continue to move down into references.
- Each phase should center on "which CLI must be run, which artifact should be written, and what state allows continuing."

### P3.2 README/CLAUDE still have slight policy dependencies on live scripts

Locations:

- `skills/entity-env-build/README.md`
- `skills/entity-env-build/CLAUDE.md`
- `skills/entity-env-build/SKILL.md`
- `skills/entity-env-build/scripts/entity_schema.py`

Problem:

README and CLAUDE have been updated to mention `record-install`, `entity_run.py`, and the strict gate, but they still restate a lot of policy. As soon as `SKILL.md` or `entity_schema.py` changes again, these summaries easily drift again.

Suggestions:

- Clarify the policy source of truth: `SKILL.md` owns flow and hard rules; `entity_schema.py` owns schema/default/profile; references own extended explanations.
- README/CLAUDE should keep only a short entry and command index.

## Six-Layer Harness Scores

| Layer | Current state | Score | Notes |
| --- | --- | --- | --- |
| Context management | fairly strong | 7/10 | `requirements.json` as the current request boundary is the right direction; but the session location and initialization example still pollute the recovery boundary. |
| Tool system | fairly strong | 8/10 | checkpoint, compat, generate, run, and record-install are all in shape; unified CLI integration for session/site-notes/compat-report is missing. |
| Execution orchestration | moderately strong | 7/10 | three phases and hard gates are clear, tests cover the key gates; cluster split execution and the sub-agent contract are still not hard enough. |
| Memory and state | medium | 6/10 | the JSON artifact chain is correct and helpers exist; session state has not become the source of truth for every CLI. |
| Evaluation and observability | moderately strong | 7/10 | negative gates and runner tests are significantly stronger; compat pass coverage still needs explicit modeling. |
| Constraints, validation, failure recovery | medium | 6/10 | `record-install`, runner, and warn gate have improved; remote verification, site notes, and cluster recovery still rely on prose. |

Overall: `6.8/10`. The skill has moved past the "documentation-style skill" stage into an executable Harness prototype; the gap to a mature Harness lies mainly in the state closed loop, verification coverage declarations, the remote/sub-agent contract, and mechanization of cluster execution policy.

## Suggested Fix Order

1. Subtract first: compress the `SKILL.md` main flow back to a minimal closed loop, and demote non-scripted session/site-notes/remote capabilities to optional.
2. Unify artifact ownership: clarify whether `.entity-session.json` belongs to the root run or the pgen `_build/`; do not keep both locations.
3. Extract a small state-transition layer instead of scattering `update_session_state()`, `log_event()`, and `save_compat_report()` patches across every script.
4. Fix the source-build sub-agent permission description: allow writes to designated directories, forbid JSON writes.
5. Rewrite the compat sub-agent prompt: use file paths/hashes as evidence, not inline JSON as the fresh-read input.
6. Add coverage/implemented checks to the compatibility result; implement unimplemented required checks or explicitly demote them.
7. Fill in only the checks that most affect pass credibility: compiler signature, path list existence, CMake package probe, MPI/output mode consistency.
8. Split the cluster policy, but do not introduce a complex remote framework; first state the minimal plan for login configure / compute build clearly.

## Verification in This Review

Ran:

```bash
python3 -m py_compile scripts/*.py
python3 -m unittest tests/test_hard_gates.py
```

Result: passed, all `12` tests passed.

Also ran the state initialization negative probes:

- The original doc snippet fails when run from the skill root: `ModuleNotFoundError: No module named '_json_io'`.
- With `PYTHONPATH=scripts` it still fails: `NameError: name 'Path' is not defined`.
- After fixing the imports, it actually writes `$ENTITY_WORKDIR/.entity-session.json`, which is inconsistent with the documented pgen `_build/.entity-session.json` layout.
