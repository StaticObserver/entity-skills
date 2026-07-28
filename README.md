# Entity Skills Package

A skills package that helps agents run astrophysical simulations with
[Entity](https://github.com/entity-toolkit/entity).

`skills/entity-ledger/SKILL.md` is the deterministic record entry point for
simulation projects. The Ledger converges the public model into
`Project → Case → Identity → Evidence`: the agent handles conversation with
the user, scientific judgment, and workflow orchestration, while the Ledger
provides deterministic primitives — read (status/show), generate
(render-run/snapshot-source), record (record build/run-prepare/run-launch/
run-exit/data/intent), and probe (status --live). Write primitives carry
built-in evidence probes: verify first, then commit to the ledger, with zero
writes on failure. Well-scoped read-only or standalone domain tasks can still
invoke the corresponding owner skill directly.

- `entity-pgen`: PGen, matching TOML, and design records;
- `entity-env-build`: dependency environment and Entity build;
- `entity-nt2py`: nt2py data access, plotting, and export.

The workflow order is orchestrated by the agent according to the user's goal;
no separate run skill is established. The SQLite `ledger.db` (schema v2) is
the only structured controller authority; Local runs the same executor logic
in-process, while SSH uses a content-addressed executor copy.

```text
entity-skills/
├── skills/
│   ├── entity-ledger/
│   │   ├── SKILL.md
│   │   ├── agents/
│   │   ├── scripts/
│   │   ├── references/
│   │   └── templates/
│   ├── entity-pgen/
│   ├── entity-env-build/
│   └── entity-nt2py/
├── tests/
├── tools/skill_observability/
├── evals/e2e-neutral-streaming/
├── design/
└── legacy/
```

For the current architecture, see
`design/router-case-centric-restructure-2026-07-23.md`; for the migration
plan, see `design/router-restructure-migration-2026-07-23.md`. `router-v5-*`,
`architecture-v4.md`, and `model-efficient-router-flow.md` are historical
designs and do not represent the current public entry point. For the skill
execution observability contract, see `design/skill-observability.md`.
`design/` and `legacy/` are not part of the Ledger runtime context.

## Shared Control State

Codex, Claude Code, Kimi Code, and plain shells share
`~/.entity-ledger/ledger.db` on the control machine by default (schema v2:
Site, Case, project bindings, identity, and audit events; concurrency is a
single-writer file lock). Identity, events, and evidence references are not
written to client-private directories or source repositories. When the remote
is unavailable, the last control snapshot can still be read, but cached
evidence does not represent current remote facts.

```bash
python3 skills/entity-ledger/scripts/entityctl.py doctor
python3 skills/entity-ledger/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  install --source-root /path/to/entity-skills/skills
python3 skills/entity-ledger/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  site add --profile /absolute/site-profile.json
python3 skills/entity-ledger/scripts/entityctl.py site list
python3 skills/entity-ledger/scripts/entityctl.py export --output /absolute/export.json

# Read project status (dashboard: readiness board + Run ledger + pending items + suggested next steps)
python3 skills/entity-ledger/scripts/entityctl.py status \
  --project-root /absolute/project [--live] [--json]
python3 skills/entity-ledger/scripts/entityctl.py show --project-root /absolute/project

# Generate (zero writes)
python3 skills/entity-ledger/scripts/entityctl.py render-run \
  --project-root /absolute/project --toml input.toml --site <site> [--gpus N]
python3 skills/entity-ledger/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  snapshot-source --project-root /absolute/project

# Record (probe evidence first, then commit to the ledger)
python3 skills/entity-ledger/scripts/entityctl.py \
  --actor-run-id <run-id> --actor-provider <provider> \
  record run-prepare --project-root /absolute/project --toml input.toml --site <site>
python3 skills/entity-ledger/scripts/entityctl.py ... record run-launch --project-root ...
python3 skills/entity-ledger/scripts/entityctl.py ... record run-exit  --project-root ...
python3 skills/entity-ledger/scripts/entityctl.py ... record build --project-root ... \
  --site <site> --checkpoint deps.local.json --executable /abs/entity.xc
python3 skills/entity-ledger/scripts/entityctl.py ... record data   --project-root ...
python3 skills/entity-ledger/scripts/entityctl.py ... record intent --project-root ... \
  --text "<current research goal>"
```

`record run-prepare` requires the simulation parameters to be confirmed (the
`<input>.decisions.json` written by `pgen_preflight.py confirm` must match the
TOML byte-for-byte); `record run-launch` is receipt-protected, so re-running it
will not resubmit the job, and jobs submitted bypassing the Ledger can be
claimed with `--adopt-job/--adopt-pid`; `status` reads only the local
controller by default, while `--live` performs at most three bounded scheduler
queries.

`entityctl install` publishes a hash-verified runtime version to
`~/.entity-skills/bundles/`; the discovery directories of Codex, Claude Code,
and Kimi Code keep only symlink projections pointing to the same bundle,
instead of maintaining three separate copies of the files.

Direct invocation of `entity-pgen` falls into read-only and standalone
modification. It must run its own preflight before writing; the preflight
queries the Ledger store, and a target that falls within a registered Case's
source/identity/active-run Locator is treated as managed — managed writes must
be registered through the Ledger's record primitives. Ledger control state
lives in an independent control root and does not rely on `_case/` markers in
source ancestor directories.

## Repository and Release

All four skills are developed, tested, and released together in this
repository. `skills/` does not use nested Git repositories or submodules;
cross-skill contract changes should land in the same branch and pull request.

- `main` holds the usable whole-package state;
- development uses short-lived branches; no long-lived branches are kept for individual skills;
- a release tag (e.g. `v0.1.0`) pins a jointly verified set of the four skills;
- the old single-skill repositories are kept for history only and are no longer entry points for development or release.

See `CONTRIBUTING.md` for detailed collaboration conventions.

## Skill Execution Observability

`tools/skill_observability/skill_observer.py` provides a platform-independent
append-only trace. It records skill identity, key decisions, tool calls,
artifacts, and external verification; it does not record hidden chains of
thought, and it does not write back to the Ledger or owner state.

When creating a run, you must pass the task, the agent/tool configuration
fingerprints, and the actually exposed skills. The Entity source, Ledger Case,
and raw data root are explicitly protected via `--protected-root`; skill
sources are added to the protection list automatically.

```bash
python3 tools/skill_observability/skill_observer.py start \
  --task-id <task-id> \
  --input-ref <task-ref> \
  --input-sha256 <task-sha256> \
  --variant full \
  --agent-provider <provider> \
  --agent-model <model> \
  --agent-configuration <agent-config-sha256> \
  --tool-profile <tool-profile> \
  --tool-configuration <tool-config-sha256> \
  --skill skills/entity-ledger \
  --skill skills/entity-pgen \
  --protected-root /absolute/entity-source \
  --protected-root /absolute/ledger-case \
  --protected-root /absolute/raw-data
```

Wrap commands with the returned `<run-dir>`; small JSON outputs can be kept as
sanitized evidence:

```bash
python3 tools/skill_observability/skill_observer.py tool \
  --run-dir <run-dir> \
  --name pgen-preflight \
  --capture-json \
  --capture-json-name pgen-preflight \
  --capture-authority entity-pgen-preflight \
  -- python3 skills/entity-pgen/scripts/pgen_preflight.py <arguments>

python3 tools/skill_observability/skill_observer.py evidence pgen-preflight \
  --run-dir <run-dir> \
  --result <run-dir>/evidence/pgen-preflight.json \
  --expect allowed

python3 tools/skill_observability/skill_observer.py finish \
  --run-dir <run-dir> --status completed

python3 tools/skill_observability/skill_observer.py validate \
  --run-dir <run-dir>
```

`evidence` supports historical validators such as `router-action`, `env-build`,
and `nt2py-inventory`. For the full protocol and evidence levels, see
`design/skill-observability.md`.

## End-to-End Skill Comparison Evaluation

`evals/e2e-neutral-streaming/` is a lightweight A/B comparison: skill and
no-skill groups run the same simulation task, comparing traces, token
consumption, and completion time. For the task text, physical parameters, and
launch procedure, see `evals/e2e-neutral-streaming/RUNBOOK.md`. The comparison
oracle (5 gates under `oracle/` plus `thresholds.json`, covered by
`tests/test_oracle.py`) is retained; the schema and fake Slurm scaffolding were
removed on 2026-07-21 — see git history for earlier versions.

Existing Codex, Claude Code, and Kimi Code records can all be imported
incrementally. The adapters keep only the hash, size, order, native
session/agent IDs, and raw platform usage of tool calls/outputs, explicitly
ignore conversation text and reasoning, and exclude the observer's own calls:

```bash
python3 tools/skill_observability/skill_observer.py import-codex \
  --run-dir <run-dir> \
  --rollout /absolute/path/to/codex-rollout.jsonl

python3 tools/skill_observability/skill_observer.py import-claude \
  --run-dir <run-dir> \
  --transcript /absolute/path/to/claude-session.jsonl

python3 tools/skill_observability/skill_observer.py import-kimi \
  --run-dir <run-dir> \
  --session /absolute/path/to/kimi-session-directory
```

Local verification:

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s skills/entity-pgen/tests -v
python3 -m unittest discover -s skills/entity-env-build/tests -v
python3 -m py_compile \
  tools/skill_observability/*.py \
  tools/skill_observability/adapters/*.py
```
