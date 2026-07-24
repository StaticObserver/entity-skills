# E2E A/B Test Runbook (lightweight A/B)

One task, two conditions, three commands per round. This file is the only setup document.

## Task specification (sent to the agent under test together with the task text)

Follow `task.md` and `physics-spec.json` (this directory) through the full Entity
simulation workflow:

1. Confirm the evaluation site environment and produce a build environment script;
2. Produce a consistent `docs/design.md` + `pgen.hpp` + input TOML;
3. Clean-build `entity.xc`;
4. Submit **exactly one** Slurm job and wait for it to terminate;
5. Read the output with nt2py, do field/particle analysis, and produce figures plus a
   short conclusion.

Site and constraints:

- Server: `ssh m87` (personal workstation, single GPU, **no Slurm, no MPI**, environment
  explored by the agent itself);
- Resource ceiling: 1 GPU / walltime ≤ 10 minutes;
- Data analysis uses CPU resources only, no GPU;
- Source code and dependencies: discovered by the agent itself (the source-cache is
  pre-staged at a discoverable location; its path is not in the task text);
- No public internet; do not modify read-only dependencies or the frozen source;
  analysis must not write into the raw-data root;
- Credentials must not enter any source code, script, log, or result file;
- Completion criteria: the job terminates normally, fields/particles at ≥2 time steps
  are readable, and the analysis conclusion is consistent with the "neutral two-stream
  remains approximately steady" physics expectation.

## The two variants

| | S: `skills-v5` (full bundle) | N: `skills-no-router` (only entity-ledger removed) |
|---|---|---|
| Entity skills | `entityctl install` publishes the current bundle (commit `6c6e205`) | entity-* projections under `~/.claude/skills/` temporarily moved away |
| model / task text / shell·ssh tools | identical | identical |
| session | fresh session, empty history | fresh session, empty history |
| workspace | separate project directory + separate Router home | separate project directory (no Router) |

## Per-round commands

Recommended: use the wrapper scripts directly (internally equivalent to the manual steps
below):

```bash
# Launch (create directories, register the trace, start the agent; before launch,
# verify the skill projection state: group S requires entity-ledger present, group N
# requires that only entity-ledger has been moved away while env-build/pgen/nt2py
# remain — launch is refused if these are not satisfied)
evals/e2e-neutral-streaming/run_round.sh skills-v5 2026-07-21-S1 [model]
evals/e2e-neutral-streaming/run_round.sh skills-no-router 2026-07-22-Snr1 [model]

# Wrap-up (first snapshot the project artifacts into traces/<run>/project-snapshot/,
# then import the transcript, segment phases, close the trace; finish must be the last
# step; re-running it detects the terminal event and skips directly)
evals/e2e-neutral-streaming/finish_round.sh 2026-07-21-S1 completed

# Remote cleanup (first pull slurm scripts/logs into traces/<run>/remote-logs/;
# dry-run by default, -f actually deletes the remote data_root and its run directories;
# finally confirm via squeue that no jobs remain)
evals/e2e-neutral-streaming/clean_remote.sh 2026-07-21-S1 -f
```

`run_round.sh` also copies `fixtures/submission.schema.json` into the project
(submission.json must conform to it, so schema conformance is fair across all groups),
self-checks before launch that `~/entity-eval-runs/` must be empty (exits immediately if
non-empty), and prints a residue warning for entity-eval-runs session directories under
`~/.claude/projects/` older than today. Before an S-group launch it also writes
`entityctl doctor`'s bundle_version/bundle_hash into
`~/entity-eval-traces/<run>/bundle.json` (reads version facts only; does not install).

After each round: clean this round's session directory under `~/.claude/projects/`
(slug looks like `-Users-…-entity-eval-runs-<run>-project`), then clean the remote side
with `clean_remote.sh` as above.

Manual steps:

```bash
OBS=tools/skill_observability/skill_observer.py

# 1. Before launch: create the trace (record this moment as the start time)
python3 $OBS start \
  --task-id e2e-neutral-streaming-v1 \
  --input-ref evals/e2e-neutral-streaming/task.md \
  --input-file evals/e2e-neutral-streaming/task.md \
  --variant skills-v5 \
  --agent-provider claude --agent-model <model> \
  --agent-configuration <config-sha256> \
  --tool-profile claude-code-default --tool-configuration <tools-sha256> \
  --skill skills/entity-ledger --skill skills/entity-pgen \
  --skill skills/entity-env-build --skill skills/entity-nt2py \
  --trace-home ~/entity-eval-runs/<run>/traces
# → outputs <run-dir> (group N drops the --skill lines, --variant skills-no-router)
# Note: --agent-configuration / --tool-configuration require lowercase SHA-256 hex,
#     e.g. shasum -a 256 <claude-settings.json> | cut -d' ' -f1

# 2. Send the task text in a fresh Claude Code session (including the full "Task
#    specification" above).
#    Monitoring switch: with OBSERVE=off, just run with plain commands — no output
#    redirection, no hook/settings injection — exactly like a bare run. With
#    OBSERVE=on (default), run headless stream-json, output landing in this round's
#    directory:
OBSERVE=on claude -p "$(cat evals/e2e-neutral-streaming/task.md)" \
  --output-format stream-json --verbose \
  > ~/entity-eval-runs/<run>/transcript.jsonl

# 3. After it ends (OBSERVE=on only): import the transcript for token totals, segment
#    phases, wrap up
python3 $OBS import-claude --run-dir <run-dir> --transcript <transcript.jsonl>
python3 $OBS phases --run-dir <run-dir> --transcript <transcript.jsonl>
# → writes <run-dir>/phases.json: per-phase wall time, four token classes (cache listed
#   separately), tool call/failure/SSH counts; comparable=false when unclassified
#   tokens exceed 10%
python3 $OBS finish --run-dir <run-dir> --status completed \
  --input-tokens <n> --output-tokens <n> --wall-time-ms <ms>
```

Monitoring is out-of-band: segmentation and statistics all happen offline after the run
ends; there is no probe anywhere in the agent's tool-call path, and the skills do not
know monitoring exists. With `OBSERVE=off`, step 3 is skipped entirely and the agent's
run command, settings, and environment are byte-for-byte identical to a bare run.

## Per-round directory convention (outside the repo)

One separate directory per round, e.g. `~/entity-eval-runs/2026-07-22-S1/`:

```text
├── project/       # Agent workspace (PGen, TOML, docs, analysis scripts)
└── controller/    # Group S Router home (point export ENTITY_LEDGER_HOME here; group N does not create it)
```

Harness state lives in the agent-unreachable `~/entity-eval-traces/<run>/` (trace home,
transcript, `project-snapshot/`, `remote-logs/`, `bundle.json`).

The source/build/run/analysis roots on remote `m87` are determined by the site profile's
`roots` (specified when group S registers via `entityctl site add`; rotating the path
per round is recommended, e.g. `~/entity-eval/<run-name>/`); m87 has no Slurm, so run
logs are written to disk by the agent itself.

## Oracle independent review

Run after `finish_round.sh` (does not trust the agent's self-report; re-verifies from
external facts):

```bash
# Pull the raw data and run all five gates (A safety / B PGen / C job data / D physics / E analysis)
python3 evals/e2e-neutral-streaming/oracle/oracle.py \
  --project ~/entity-eval-runs/<run>/project \
  --transcript ~/.claude/projects/<project-slug>/<session>.jsonl \
  --fetch ~/entity-eval-traces/<run>/oracle-data
```

Produces `<project>/oracle-report.json`; overall fail > unknown > pass. Physics
thresholds are frozen in `oracle/thresholds.json` (each entry includes the physics
definition, formula, and gold run observation) and must not be retroactively adjusted
based on S/N results.

## Per-round archiving

After the round ends, put `summary.json` into that round's directory:
- `summary.json`: variant, model, start/end time, wall-clock, input/output tokens,
  Slurm job ID, completed or not, one-sentence result;
- the agent's final self-reported summary (verbatim, may go into `agent-summary.md`).

Note Slurm queueing time separately; it does not count toward agent execution time.
