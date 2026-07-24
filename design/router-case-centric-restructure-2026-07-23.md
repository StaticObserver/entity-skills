# Entity Router Restructuring Design: Case-Centric Fact Recording and Deterministic Execution

Date: 2026-07-23
Status: discussion draft

This document defines the target architecture of the entity-router restructuring. The
restructuring does not change the safety capabilities already implemented at the
underlying layer (identity chain, allowlisted executor, receipts, evidence re-probing);
what changes is:
**what the agent sees, what it has to assemble, and how many tokens it spends per
turn.**

## 1. Problem Diagnosis

### 1.1 Measured Evidence

Two rounds of manual testing on 2026-07-23 (S1/S2, m87 without Slurm or MPI; evidence
in `~/entity-eval-traces/2026-07-23-S{1,2}/`, analysis in
`evals/e2e-neutral-streaming/findings-2026-07-23.md`) showed: in both rounds the agent
used the router only as a site registry, with zero plan/apply executions — even though
the direct backend was already in place. The entry boundary is a motivation problem, not
a capability problem.

### 1.2 Three Misalignments

1. **Narrative subject misalignment**: SKILL.md narrates throughout how to comply with
   control-plane rules (identity chain, receipts, leases, allowlists) without ever
   saying what those rules are for. The skill's purpose is to help users do plasma
   simulation research with Entity: set up environments, write PGens, run simulations,
   modify code, analyze results. This workflow never appears in the document from start
   to finish.
2. **Three layers of determinism flattened**: deterministic things (build environment,
   build configuration), semi-deterministic things (simulation parameters, frequently
   modified), and fully undetermined things (which parameters to pick, how long to run,
   how to design the PGen) are all crammed into the same "managed write transaction"
   mechanism. The middle layer is too heavy (changing a parameter feels like going
   through an approval process), and the top layer has no anchor (exploration leaves no
   settled foothold).
3. **State positioning misalignment**: `router.db` is a "compliance ledger" answering
   "was this write legal"; the design goal is a "project map" answering "where is the
   project now, what is done, what remains".

### 1.3 Efficiency Problem

For every Action the agent has to assemble and validate too many control-plane fields
(revision, lease, target hash, Action history, owner/domain, path envelope) — high token
cost, low efficiency. Root cause: protocol fields are assembled by the agent and
validation is nested layer upon layer, instead of code providing simple deterministic
tools.

## 2. Design Principles

1. **Three layers of determinism, three treatments.**
   - Deterministic layer (environment, build configuration, site topology, source
     version): established once, files authoritative, rarely changed.
   - Semi-deterministic layer (simulation parameters, resource amounts): the agent
     edits freely, with a lightweight confirmation afterwards; the parameter card is the
     "meaning anchor of this run", not a compliance gate.
   - Undetermined layer (scientific judgment, parameter exploration, PGen design): the
     router does not intervene in the process; it only records conclusions and evidence
     after convergence.
2. **The agent plans the flow; code does the deterministic work.** The agent is
   responsible for conversing with the user, scientific judgment, and orchestrating the
   simulation flow (what first, what next, what to do on errors); the CLI is the agent's
   auxiliary tool, responsible for reading and generating deterministic records,
   generating deterministic scripts, and probing/validating. Deterministic work is
   executed by code, but the large flow is not wrapped into code.
3. **Store only facts that cannot be derived.** "What to do next" can almost always be
   derived from artifact readiness; storing a derivable pointer creates a second source
   of truth that inevitably drifts. Anything derivable is computed.
4. **State advances only on evidence.** Behind every state change there must be
   re-probed evidence (files, hashes, exit codes); narratives from agents or workers do
   not count.
5. **Minimal action, persist on demand.** (Inherited from
   `legacy/docs/entity-case-design-2026-07-11.md`) User goal + state snapshot → pick the
   minimal action, do not expand a local request into a full lifecycle; only facts that
   actually happened are persisted.

## 3. Target Architecture

### 3.1 Case: Center of Facts

One Case per simulation project, recording all facts needed. It inherits the Locator
and identity model of Case v3 (`design/workspace-and-state.md`); the underlying layer
stays untouched:

- **Intent**: the current research goal (the only stored "pointer", because it is not
  derivable — all-green artifacts do not mean the work is done).
- **Source identity**: Entity checkout, commit/version, editable authority location,
  PGen identity.
- **Build records**: on which machine, with which environment checkpoint, producing
  which executable; referencing the source revision.
- **Parameter cards**: human-readable simulation parameters + hash; confirmed before a
  run, re-confirmed after changes.
- **Run ledger**: an append-only list; each entry = parameter card hash, site,
  resources, status, exit evidence, data Locator, inventory status; reruns reference
  their parent instead of overwriting. **The run sequence is the research trajectory.**
- **Decision state**: two sets, `clear / open / blocked` — confirmed decisions and open
  questions; only information needed to complete the current request is judged.
- **Evidence references**: Locators of receipts, manifests, inventory hashes.

### 3.2 State Presentation: Readiness Board + Deriver

No state machine (explicitly abandoned). State presentation has two layers:

- **Readiness board (stored)**: the dependency chain source → pgen → build → run →
  data → analysis, each cell with a status vocabulary (e.g. `missing / established /
  stale / running / failed`) + evidence + last-verified time. It is a vector, not a
  scalar, naturally allowing "run executing on m87 while data is being analyzed". Stale
  propagates along the chain: source changes → build/run stale; parameter card changes
  → unstarted runs stale; data changes → analysis stale.
- **Deriver (computed, not stored)**: a piece of deterministic code inside the router,
  `f(readiness board, intent) → suggested next step`. The old state machine's
  transition knowledge ("build failed → fix the build", "run terminal → inventory the
  data") becomes derivable rules, testable. The "current phase" shown on the dashboard
  is a computed view, always consistent with reality.

Debug is not a state: it is simply "some stage has failure evidence attached", and the
deriver naturally routes the next step to the stage that owns the fix.

### 3.3 Interface: Deterministic Primitives, Not Large-Flow Wrappers

The CLI is positioned as the agent's auxiliary tool. Each command does one
deterministic thing and does not wrap large flows. Orchestration — what first, what
next, what to do on errors — is the agent's responsibility; this is exactly where debug
and unexpected situations require the agent's presence.

Four classes of primitives:

- **Read**: `status` (readiness board + intent + ledger + derived next-step
  suggestion), `show` (Case fact details);
- **Generate**: source snapshots, build scripts, run scripts, parameter cards —
  deterministic text and records are generated by code, not handwritten by the agent;
- **Record**: register a build (code probes the executable and env checkpoint before
  writing the identity), register run launch/terminal state (probing receipts and exit
  codes), data inventory (generating a manifest with hashes);
- **Probe**: live run status, file hashes, path and site validation.

Write-class primitives carry their own evidence probing: recording is not "registering
what the agent says" but "code verifies, then posts to the ledger" — the agent cannot
advance any state by narrative alone (this is how Principle 4 is implemented).

A build, from the agent's point of view, is: read `status` → decide to build → CLI
generates the build script → execute the script (long tasks may spin up a sub-agent to
isolate context) → CLI records the build (code verifies, then posts to the ledger).
Every step is a simple tool call with no protocol fields to assemble; when script
execution fails the agent is right there, reading logs, changing configuration,
rerunning — no recovery protocol needed.

All normal output stays compact (status and command results each within roughly 4 KiB).

### 3.4 Validation System: Only Two Mechanisms Remain

1. **Content hashes** — the sole means of identity and stale detection. Covers the
   entire derivation need of "what is done, what remains".
2. **Re-probing after execution** — the sole means of effect verification. Files, exit
   codes, and hashes are self-checked by code; no narrative is trusted.

Two special cases remain but are hidden inside the code, never visible to the agent:

- Non-replayable side effects such as job submission and data deletion: still go
  through the intent → effect → verified receipt logic to prevent duplicate submission;
- Raw data deletion: still requires explicit user authorization + manifest (the
  existing purge mechanism is retained).

Concurrency control degrades to a single-writer file lock. Actor provenance degrades to
a passively recorded environment variable, for audit only, not a gate.

### 3.5 Sub-Agent Usage Boundaries

- Deterministic work is done by "CLI primitives + agent driving", without wrapping
  large flows. Long tasks (e.g. a full build) may spin up a sub-agent to execute the
  generated script, purely for context isolation — the script is generated by code, the
  result verified by code, and the sub-agent records nothing.
- Work requiring judgment (modifying PGens, doing analysis) continues to use the model
  Worker envelope mechanism (`design/model-efficient-router-flow.md`): only the goal,
  precise read/write boundaries, and acceptance criteria are given, with no
  conversation history; results are not trusted and are posted to the ledger only after
  code re-probes them.

### 3.6 SKILL.md and Playbook Structure

SKILL.md stays thin. The first screen answers the purpose: this skill maintains a
deterministic record for your Entity simulation project, so that any session (machine
switch, agent switch, mid-way crash) can know where the project is and what the next
step is. Then it covers only two things: how to read Case state (status / readiness
board), and which classes of deterministic primitives are available.

It does not prescribe a linear flow. Each activity is written as an independent
playbook for the agent's reference; flow order and combination are customized by the
agent according to the user's goals:

- `playbooks/setup-env.md`: establishing dependencies and build environment; the
  product is an env checkpoint (delegates to entity-env-build);
- `playbooks/develop-pgen.md`: consistent PGen/TOML/design development (delegates to
  entity-pgen);
- `playbooks/build.md`: from generating the build script to recording build identity;
- `playbooks/run-simulation.md`: parameter card confirmation, run script generation,
  submission, monitoring, terminal-state registration;
- `playbooks/analyze-data.md`: data inventory and nt2py analysis (delegates to
  entity-nt2py);
- `playbooks/debug.md`: locate the stage by failure evidence, return to the
  corresponding activity after fixing.

Each playbook writes only orchestration logic: what file this activity produces, which
primitives to use, where state is recorded, what to post to the ledger when done — not
long stretches of domain knowledge (that is the job of owner skill references), and it
**states the payoff before the procedure** (checkpoints save you from re-figuring build
options; run records let you adopt the original job after a crash instead of
resubmitting). A playbook is a reference, not a rail: the agent may skip, merge, or
reorder; the only hard constraint is Principle 4 — state advances only through record
primitives on evidence. Control-plane concepts all retreat into internal reference
documents.

## 4. Inherited and Dropped from Historical Versions

| Concept | Source | Disposition |
|---|---|---|
| Case fact center, Locator, identity chain, stale propagation | `design/workspace-and-state.md` (v3) | Inherited; underlying layer untouched |
| model Worker envelope, context isolation, result re-probing | `design/model-efficient-router-flow.md` | Inherited, only for judgment-requiring subtasks |
| Independent state dimensions, minimal action, three-state decisions, persist on demand | `legacy/docs/entity-case-design-2026-07-11.md` | Revive its spirit, written into SKILL.md behavioral principles |
| Multi-agent handoff contract | `legacy/EntitySkillPackVault/10-Architecture/Agent Collaboration Model.md` | Archived; does not enter the new architecture |
| run-manifest (new record per rerun, parent reference) | `legacy/.../Run Manifest Template.md` | Merged into the run ledger |
| playbooks (orchestration logic only, composing cross-skill workflows) | `legacy/docs/architecture-v1-2026-06-20.md` §6 | Revived, split by activity, see §3.6 |

## 5. Deletion List

The following agent-visible concepts and gates are deleted wholesale (the main body of
token consumption):

- The GoalSpec JSON protocol, the three Goal types (run/build/data), and the
  `needs_decision` planning gate (parameter confirmation becomes a lightweight card
  confirmation; build/run/data are replaced by record primitives);
- The plan review loop (agent reads plan then applies);
- writer lease, handoff, revision concurrency gates;
- flow request assembly (step, Action ID, owner/domain, binding, acceptance
  conditions);
- Worker staging for deterministic steps;
- multi-step gates such as owner/domain matching and Action history continuity;
- verb commands that wrap large flows (swallow-whole build/run/data transactions).

Kept as internal implementation or downgraded: identity chain, allowlisted executor,
receipts (internal to non-replayable side effects only), purge authorization, passive
actor auditing. The plan/apply engine is retired after being dismantled into
primitives.

## 6. Migration Steps

The detailed migration plan (parts inventory, primitive command surface, test matrix,
risks) is in `design/router-restructure-migration-2026-07-23.md`. Phase summary:

1. **P1 status dashboard-ification**: `entityctl status` output restructured into
   readiness board + intent + ledger + derived next step; human-readable, compact.
2. **P2 primitive toolset**: dismantle the plan/apply engine into the four classes of
   primitive commands (read, generate, record, probe); internally reuse the existing
   executor and receipt logic.
3. **P3 delete gates**: remove lease/revision/owner-domain validation paths;
   concurrency degrades to a file lock; confirm existing test rework.
4. **P4 SKILL.md rewrite**: narrative per 3.6; references relocated by internal
   mechanism; sync the boundary descriptions of the other three owner skills.
5. **P5 field validation**: rerun the S1/S2 same-scenario evals (m87), observe whether
   the agent proactively uses primitives and reads status first, compare using adoption
   metrics and token consumption.

## 7. Acceptance Criteria

- On its first turn in a project, the agent can answer: project goal, base state, what
  has been run, open items;
- the agent drives the full flow with a few primitive calls, zero protocol-field
  assembly, compact output per step;
- after a session interruption, a new session recovers from Case facts without
  resubmitting jobs or rebuilding;
- S1/S2 scenario rerun: router adoption significantly up, total token consumption
  significantly down;
- the existing test suite is all green after rework.

## 8. Open Questions

1. Human-readable form of the readiness board: only improve `entityctl status` output
   (single authority in the control area), or also drop an `ENTITY-STATE.md` in the
   project directory (more intuitively anchored, but with dual-write drift risk)?
   Currently leaning toward the former.
2. How to migrate old v5 Case data (router.db) to the new presentation layer: a
   one-time migration script, or only guarantee old data is readable while new projects
   use the new path?
3. How far to abandon multi-agent concurrency protection: is a single-writer file lock
   sufficient for real usage (two agent sessions working on the same project
   simultaneously)?
