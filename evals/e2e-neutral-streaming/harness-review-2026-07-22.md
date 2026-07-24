# E2E Evaluation Harness Issues and Fix Plan (S1 + Snr1 Retrospective)

Scope: problems exposed by **the evaluation harness itself** (task contract, fixtures,
monitoring segmentation, oracle, archiving process) across the two rounds 2026-07-21 S1
(skills-v5) and 2026-07-22 Snr1 (skills-no-router). Skill-side issues are covered in the
sibling document `skill-review-2026-07-22.md`. Raw diagnostic records are in
`findings-2026-07-22.md`.

## A. Task-contract gaps (affect fairness; highest priority)

### A1. The submission schema exists only with the router skill

- Symptom: task.md requires submission.json to "conform to the supplied schema", but
  there is no schema file in the fixtures. S1 (with router installed) got the schema
  from the router contract and conformed; Snr1 (no router) could only invent its own
  layout (`output.data_root` vs `run.data_root`).
- Consequence: the schema-conformance metric actually measures "is the router
  installed", not agent capability; it is unfair to the no-router / N group and can
  cause oracle parsing failures.
- Fix (choose one; user decision needed):
  1. Put `submission.schema.json` into the project directory as a fixture and change
     task.md to point at that file — schema conformance becomes a fair metric for all
     groups;
  2. Keep the status quo, but state in the scoring rubric that "schema conformance" is a
     router skill effect, and keep the oracle parsing layer tolerant with fallbacks (an
     `output.data_root` fallback has been added).

### A2. "Requested analysis" is never defined; Gate E's requirements were never told to the agent

- Symptom: task.md says "perform the requested field and particle analysis" and "write
  all required artifacts", but neither task.md nor physics-spec.json says what to
  analyze or what to deliver. Gate E, however, scores on "has an analysis report file +
  has a re-runnable script". S1 delivered a report but no script; Snr1 delivered neither
  — they were being tested on requirements the agent never received. (The router
  contract does contain these requirements, so this is yet another implicit skill
  dependency.)
- Fix: state the analysis deliverable list explicitly in task.md, e.g.
  `analysis/report.md` (conclusions + evidence) and `analysis/analyze.py` (a script that
  can be re-run against the data root). The oracle's Gate E maps one-to-one onto this
  list.

### A3. No ceiling on particle output stride

- Symptom: the S1 agent set stride to 100 (gold run: 10), so only ~20 macroparticles per
  species entered the analysis, leaving the ux drift conclusion weakly supported; Snr1
  used stride=10 (204 per species). physics-spec does not constrain it.
- Fix: add `output.particle_stride_max` (e.g. 20) to physics-spec, or add a "minimum
  number of analyzed particles" metric to thresholds (suggest ≥ 100 per species).

### A4. The "use CPU for analysis" boundary is vague

- Symptom: task.md only says "Use CPU resources for data analysis" without stating
  whether running nt2py on the login node is a violation or whether interactive srun
  counts as compliant. Snr1 ran the analysis via interactive srun (3 attempts); S1 did
  it differently, making Gate A/C adjudication inconsistent.
- Fix: state explicitly in task.md that "analysis must also not run on the login node;
  it must go through batch or interactive CPU jobs", and add it to the Gate A check
  wordlist.

## B. Evidence-chain and archiving defects

### B1. S1's project artifacts were cleaned up before review (irreversible loss already incurred)

- Symptom: the S1 round cleaned up the agent artifacts per procedure; input.toml /
  pgen.hpp / submission.json were not archived. After Snr1's physics failure (ux -40%,
  E² over by 20×) we wanted an S1-vs-Snr1 root-cause comparison (same spec, same seed,
  same precision, drastically different results), but S1's pgen is no longer
  recoverable, so the comparison could only stop at "different injection implementation
  paths".
- Fix: add an archiving step to `finish_round.sh` — at wrap-up, copy
  `input.toml`, `pgen.hpp`, `submission.json`, `docs/`, and `analysis/` (if present)
  from the project into `~/entity-eval-traces/<run>/project-snapshot/`; the cleanup
  action must happen after the snapshot.

### B2. Remote log retrieval and cleanup are manual steps

- Symptom: Snr1's key evidence (slurm scripts and logs for 12 build jobs, 7 simulation
  submissions, 3 analysis jobs) was archived by manual scp, and `~/entity-run` was
  deleted manually. Missing a pull means losing evidence.
- Fix: add `clean_remote.sh <run-name>` (or a `--clean-remote` option on finish_round):
  first pull logs into traces based on submission.json's artifacts section plus a remote
  run-directory glob, then delete the remote artifact directories, and finally confirm
  via `squeue` that no jobs remain.

### B3. No pre-launch check for cross-round environmental contamination

- Symptom: the S2 contamination incident (the agent reached the development repository
  containing gold run answers via trace files) has been fixed at the architecture level
  (harness state moved out of agent-reachable directories), but three residual surfaces
  remain:
  1. uncleaned run directories from the previous round under `~/entity-eval-runs/`
     (visible to the agent via `ls ..`);
  2. the previous round's session transcript in local `~/.claude/projects/` (different
     slug, but theoretically readable by the agent);
  3. siyuan `~/.bash_history` may contain the previous round's resource-exploration
     commands (unverified, deliberately not read).
- Fix: add a pre-launch self-check to `run_round.sh` — `~/entity-eval-runs/` must be
  empty, and print a warning about residual previous-round sessions; write into the
  RUNBOOK that after each round one should clean the local `~/.claude/projects/<slug>`
  and (if decided) the remote history. Add `entity-eval-runs` (cross-round reference) to
  the transcript contamination scan wordlist.

## C. Monitoring and segmentation

### C1. sbatch-submitted build jobs count toward the run phase

- Symptom: S1's 40 min run phase and Snr1's 105 min both contain build/probing jobs
  (Snr1 had 12 build-type sbatch submissions). Run-phase duration is therefore
  overestimated and env-build underestimated.
- Fix: distinguish build-type from sim-type jobs in the segmentation rules by sbatch job
  name / script content (e.g. job names containing build/rebuild/kk/deps, or scripts
  invoking cmake/make, go to env-build).

### C2. The pgen phase cannot be segmented out (phases only advance)

- Symptom: Snr1's agent wrote the local pgen.hpp only after env-build signals appeared;
  the pgen phase has 0 records and its work was folded into env-build.
- Fix: allow "writing local pgen.hpp / docs design documents" to be re-labeled as pgen
  at any time (writing local files has no external effects, so rollback is safe); or
  leave the rules unchanged and add an annotation in phases.json. Leaning toward the
  former — smaller change.

### C3. finish_round idempotency blemish and stale warning

- Symptom: at Snr1 wrap-up it printed "cannot append an event after the terminal event"
  once (duplicate finish), then succeeded; it also printed a comparable=false warning,
  yet the final phases.json shows comparable=true (the warning was taken from the first
  pass's result).
- Fix: before finishing, detect that the terminal event already exists and skip; make
  the warning read the final on-disk phases.json.

### C4. Missing job lifecycle count metrics

- Symptom: the router's core value proposition is job management, but phases.json only
  has phase durations/tokens and cannot show key comparison points like "7 submissions
  before 1 success" (this round relied on manually counting remote logs).
- Fix: add counters to the segmenter — number of sbatch submissions, number of
  squeue/sacct polls, submission sequences grouped by job name — written into the run
  phase section of phases.json.

## D. Oracle (reviewer)

### D1. Gate B's TOML layout fragility (to fix, recorded)

- Snr1's legal alternative layout caused 4 false fails: lowercase `engine = "srpic"`, no
  explicit `particles.nspec` (Entity derives it from the `[[particles.species]]` array),
  and drift/temperature collected in a custom `[setup]` section. Fix: normalize engine
  case; when nspec is absent take the array length; support both per-species and
  `[setup]` sources for drift/temperature. (Changes parsing only, not thresholds,
  consistent with the "do not retroactively adjust thresholds based on a single round's
  results" principle.)

### D2. Gate D looks only at the last snapshot, with no sample-size floor

- The ux drift uses only the stride-sampled mean of the last snapshot; Snr1's data shows
  the drift is a gradual whole-run trend (0.199 → 0.12), so a single final-snapshot
  point both loses information and is sensitive to sampling noise.
- Fix: change to "the maximum of |mean_ux - 0.2|/0.2 across every snapshot of the whole
  run", combined with A3's minimum-particle-count metric.

### D3. Fixed items (record)

- Fall back to `output.data_root` when `run.data_root` is missing (triggered by Snr1,
  fixed, all 65 tests pass);
- `2>&1`/`2>/dev/null` misjudged as file writes (fixed before S1);
- sacct NTasks empty values treated as unknown (fixed before S1).

## E. Fixed architecture-level issues (record, regression guard)

- **S2 contamination incident**: the trace manifest's `--skill` repository path leaked
  to the agent via `run_dir.txt`. Fix: scripts no longer pass `--skill`, and all harness
  state moved out of agent-reachable directories; no file written into an
  agent-reachable directory may contain repository paths / evaluation-internal
  information.
- **The segmentation false-match trio**: tool-input body-text false match (changed to
  match only command and path targets), reading `.claude/skills/` docs falsely
  triggering phase transitions (changed to count-only), and `squeue`/`sinfo` falsely
  triggering the run phase (run now recognizes only sbatch / entityctl).

## Suggested fix priorities

1. A1, A2 (contract fairness; directly affects the validity of next round's metrics)
2. B1, B2 (evidence chain; prevents a repeat of the S1-style irreversible loss)
3. C4, C1 (key metrics of router value)
4. D1, D2 (oracle false positives / criterion hardening)
5. A3, A4, B3, C2, C3 (polish items)
