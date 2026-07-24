# E2E Evaluation Revision: Resource Self-Discovery Task Contract and Run-Process Monitoring

Date: 2026-07-21
Status: task/fixtures/source-cache/collector implemented (2026-07-21); probe gate and pilot pending
Predecessor: `design/e2e-skill-evaluation-project-2026-07-19.md` (project principles unchanged; this document revises the task contract and process monitoring parts)

## 1. New task contract

### 1.1 The evaluation provides only two things

- `task.md`: the task goal, deliverable contract, site boundaries, resource ceilings, and safety constraints;
- `physics-spec.json`: the frozen physics semantics (identical to §3.2 of the 07-19 document, unchanged).

Source paths, dependency cache paths, writable roots, job naming, and the like never appear in the task input.

### 1.2 What task.md must contain

task.md needs to describe the task clearly and state the following **site usage boundaries** (these are constraints, not resource locations):

1. Computation must happen on the **siyuan cluster**; no other site may be used (siyuan and pi2 are two different clusters and must not be mixed);
2. **Compiling on login nodes is forbidden**; compilation must happen on compute resources (interactive or job-based, at the agent's discretion);
3. Jobs are submitted to the **debuga100 partition** (GPU resources), subject to the resource ceiling;
4. **Data analysis uses CPU resources**; GPU nodes must not be occupied for analysis;
5. Resource ceiling: 1 node / **2 GPUs (MPI, 2 tasks)** / 10 min walltime;
6. Safety constraints unchanged: no public network, no credentials in artifacts, no modification of shared read-only content, and when a key decision is missing, stop and report rather than assume.

task.md **must not contain**: the Entity source location, dependency cache location, concrete writable paths, internal site usernames, or any wording like "already provided by the evaluation runtime". The agent must locate these resources itself through environment probing (ssh configuration, publicly readable caches on the cluster, existing software stacks).

### 1.3 Local source cache (pre-provisioned by the maintainer)

Before the evaluation run, the maintainer prepares a **read-only source cache** on siyuan containing:

| Component | Version | Notes |
|---|---|---|
| Entity | v1.4.4 (tag) | Frozen version, consistent with physics-spec |
| Kokkos | 5.0.1 | modern profile default (entity-env-build version policy) |
| ADIOS2 | 2.11.x | modern profile |
| OpenMPI | 4.1.6 | Required for MPI=ON; the agent may also choose the site's existing MPI |
| HDF5 | 1.14.6 (tag `hdf5_1.14.6`) | ADIOS2 dependency |

Constraints:

- cache contents and version fingerprints (sha256) are recorded in the evaluation manifest and may be committed to the repository;
- the cache is placed at a read-only location the agent can reasonably discover, but **the path does not appear in task.md** (the §1.5 probe gate verifies discoverability);
- providing sources does not force a source build: the agent may still choose equivalent dependencies already on the site, but must pass compatibility convergence and give the identity and fingerprint in the submission.

### 1.4 Deliverable contract unchanged

The `submission.json` schema follows the existing version. It is the judging interface, not a resource hint; it applies to the no-skill group equally and does not require mimicking Router internal objects.

### 1.5 Discoverability precondition (probe gate)

"Discoverable but undeclared" must be verified; otherwise what is measured is environment setup rather than agent capability. Before the formal run, the maintainer executes one probe:

- confirm that the source cache (§1.3) and the site software stack exist on the siyuan cluster in a way the agent can reasonably discover;
- confirm that the discovery path does not depend on private knowledge of this evaluation repository;
- the probe conclusion is written into the experiment manifest. If the probe fails, fix the environment first; do not start the run.

### 1.6 New task.md draft

```markdown
# End-to-end Entity simulation task

Run the controlled Entity simulation described by the supplied
`physics-spec.json` on the siyuan cluster.

Complete the full lifecycle:

1. create a consistent `docs/design.md`, `pgen.hpp`, and Entity TOML input;
2. discover and converge a CUDA + MPI build environment for this PGen;
3. perform a clean Entity build (MPI enabled);
4. submit exactly one Slurm job within the stated resource budget and wait for
   its terminal result;
5. inspect the produced data with nt2py and perform the requested field and
   particle analysis;
6. write all required artifacts and a final `submission.json` that conforms to
   the supplied schema.

Site rules:

- All computation happens on the siyuan cluster. Do not use any other site.
- Do not compile on login nodes.
- Submit the GPU job to the `debuga100` partition, within the resource budget:
  1 node, 2 GPUs, 2 MPI tasks, 10 minutes walltime.
- Use CPU resources for data analysis; do not occupy GPU nodes for analysis.

Resource locations are intentionally not specified. Discover the available
Entity source, dependency sources, and writable roots yourself. Do not use the
public network. Do not modify shared read-only content. Do not expose
credentials in source files, logs, or results. Keep analysis artifacts
outside the raw-data root.

If a required scientific or resource decision is genuinely missing, report it
precisely and stop before creating external effects. Do not silently change
the physics specification or resource ceiling.
```

## 2. Run-process monitoring (observability v2)

### 2.1 Independence and switchability (hard requirements)

Monitoring is an independent layer outside the system under test, satisfying three conditions:

1. **Zero intrusion**: no modification of any skill's SKILL.md, scripts, or Router code; no hooks or probes installed inside the skill directories of the workspace under test. The skills themselves do not know whether monitoring exists.
2. **Fully switchable**: controlled by one switch of the evaluation harness (such as `OBSERVE=on|off` or an `--observe` flag). When off, the agent runs exactly as it would without monitoring — same command line, same settings, same environment.
3. **Overhead out of band**: collection and parsing happen outside the process under test or after it finishes; no synchronous wait is added to the agent's tool-call path, and the agent's context window is not consumed. Token and duration readings reflect the agent's native behavior, excluding the monitoring's own cost.

### 2.2 Evidence grading

The declared / observed / verified three-way split is kept: the agent's report is declared, the collection stream is observed, and independent oracle re-checking is verified. Monitoring only adds observed evidence; it does not change oracle judgment logic.

### 2.3 Three collection channels

**Channel 1: structured event stream (main trace)**
The Claude Code under test runs headless, with the harness wrapping the command line:

```bash
claude -p "$(cat task.md)" --output-format stream-json --verbose ...
```

With the switch off it is the same command without output redirection. JSONL events contain each assistant message's `usage` (input / output / cache_read / cache_creation tokens), every tool_use / tool_result, and the final result (total duration, total tokens). Tokens are accumulated per message from usage. All parsing happens offline after the run ends.

**Channel 2: hooks side channel (independent action timeline)**
The evaluation harness injects an independent settings file (separate from the agent's own configuration), configuring `PreToolUse` / `PostToolUse` hooks that asynchronously append JSONL: timestamp, tool name, command fingerprint (redacted), exit status. With the switch off, this settings file is not injected. The hook script only appends; it does not block and returns no decisions, so its effect on the tool-call path is negligible. This stream is independent of the transcript: even if the main trace is corrupted, an important action log with precise timestamps survives, and it serves as the audit basis for external side effects such as ssh / sbatch.

**Channel 3: external facts (existing)**
Scheduler snapshots, receipts, artifact hashes — the existing oracle system is unchanged and was never on the path under test.

### 2.4 Deterministic phase segmentation

The agent is not asked to emit phase markers. Post-processing cuts the trace into ordered phases by tool-call patterns:

| phase | Segmentation signal (first matching tool-call pattern) |
|---|---|
| discover | exploratory ssh / ls / find / environment probing, until site and source are determined |
| pgen | writing `pgen.hpp` / `design.md`, PGen preflight |
| env-build | cmake / make / entity-build related calls |
| run | `entityctl plan/apply` or `sbatch` |
| analysis | `import nt2` / analysis script execution |
| submission | writing `submission.json` (trace termination signal) |

The segmentation rules live in the collector configuration and can be iterated against the phase signal table, but are not adjusted based on individual results.

### 2.5 Output: `phases.json`

Each assistant message is assigned to its segment by timestamp, accumulating per segment:

- wall time (start/end timestamps; Slurm queueing waits are marked separately and not counted toward agent efficiency, same as 07-19 §5.3);
- tokens: input / output / cache_read / cache_creation **listed separately** (the two cache items must be separate, to answer "whether the skills' context cost is worth it");
- tool call count, failed call count, SSH round trip count.

What cannot be assigned goes into `unclassified`; if its token share is too high (threshold tentatively 10%), the segmentation rules have failed — mark this round's trace as non-comparable, fix the rules before running.

### 2.6 Where it lands

Extend the existing `tools/skill_observability`:

1. add a CC stream-json transcript parser (offline);
2. add a phase segmenter (rule-table driven, offline);
3. add `phases[]` to the trace schema;
4. add a monitoring switch to the harness, controlling output redirection and hook settings injection;
5. the summary report reads `phases.json` directly to fill the "execution cost" dimension of §8 in the 07-19 document.

## 3. Fairness impact

- Both S/N groups receive exactly the same new task.md; the discovery phase is tested equally for both, so comparison fairness is unchanged;
- discovery-phase time and tokens count toward the comparison, but queueing time is still reported separately;
- if a group fails in the discover phase, it counts toward autonomous completion as "number of phases completed" (07-19 §8 item 2), with no efficiency compensation.

### 3.1 How the no-skill group (N) is observed

The monitoring instrumentation is independent of the condition under test: it observes the agent's observable behavior (tool calls, tokens, timestamps), not the skills themselves. It is therefore fully isomorphic for the N group:

- stream-json collection, hooks side channel, and transcript import are all done out of band by the harness, identically for both groups;
- the phase segmentation rules match **task deliverables**, not skill interfaces — `pgen.hpp`, `design.md`, `cmake/make`, `sbatch/squeue`, `import nt2`, and `submission.json` are all artifacts mandated by task.md and produced by the N group too; S-specific signals like `entityctl` are only one of the run-phase rules, and the N group hitting `sbatch` directly matches as well;
- the N group's `start` carries no `--skill`, so `resource_matches` is naturally empty — no error, no missing data.

The only S-only observation is the skill evidence validators (router-operation, pgen-preflight, env-build, nt2py-inventory). They are not the judging interface: the common judge for both groups is oracle Gates A–E, which read external facts such as the scheduler, raw data, and submission. The N group's phases.json has exactly the same structure as the S group's and can enter the same summary comparison directly (already covered by segmentation tests on N-group-style transcripts).

## 4. Implementation order

1. prepare the local source cache (§1.3) and record the version fingerprint manifest;
2. land the new `task.md` per §1.6 and update the `evals/e2e-neutral-streaming/` fixtures (including the physics-spec's MPI and 2-GPU resource ceiling);
3. execute the §1.5 probe gate to confirm resources are discoverable;
4. implement the collector's parser + segmenter + `phases.json` and the monitoring switch (§2.6), regression-testing the segmentation rules against existing gold-run traces;
5. pilot: one run each of S/N, verifying the discovery phase is observable, monitoring data is complete, and behavior with the switch off matches a bare run;
6. start the formal pairs only after this passes (following the 07-19 §5.3 order).
