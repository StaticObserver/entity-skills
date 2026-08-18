# Analysis Management Design: Code, Execution, and Environment

Date: 2026-08-05. Status: finalized, pending implementation. Companion document: workspace-and-computation-site-2026-08-03.md.

## 1. Problem

Analysis scripts are often hard to find and easy to misuse (scripts applied to the
wrong data). Current state (findings from surveying three production projects):
all scripts are CLI-parameterized Python (no notebooks); artifacts go into
per-run directories and never write to the raw run root; but hardcoded paths
coexist with CLI arguments, manual `-vN` version suffixes substitute for
identity, the script↔data binding lives only in people's heads and in prose,
and the same script is manually synced across multiple locations.

Parts already decided but not yet implemented are inherited as-is: analysis is
the sixth dimension of the identity chain,
`analysis_id = f(data_id, spec_hash, code_hash)`, and its parent is the exact
data ID; when the data changes, the analysis becomes stale, and historical
artifacts are never deleted. The 0.4.0 decision stands: scientific methods stay
in entity-nt2py; the Ledger only does registration and provenance.

## 2. Model: Manage Code and Execution Separately

**Analysis code** (source-code nature, Workspace is the authority):

- Only the **general-purpose script library** enters the run ledger, at the
  project level: `projects/<p>/analysis/scripts/`. This is the method layer
  reused across cases/runs (it may be a package, e.g. bh-reconnection's
  aphi_topology).
- Onboarding convention: data paths must be CLI-parameterized. Existing
  hardcoded scripts are absorbed into `scripts/legacy/`; registration is
  **not refused** — the manifest marks `hardcoded_paths: true` and the
  dashboard shows a warning.
- One-off case-level scripts are managed by the agent itself and are **not
  recorded in the ledger**.

**Analysis execution** (a fact, the sixth dimension of the identity chain):

- Execution is the agent's free exploration (where and how to run is not the
  Ledger's concern); `record analysis` performs after-the-fact registration
  plus evidence probing, with zero writes on failure.
- Evidence = the `analysis-manifest.json` in the artifact directory: input
  data_id, script relative path, parameters, interpreter/environment,
  generation time. At record time it is re-probed: the manifest exists and its
  data_id matches the claim, and the script hash matches the registration.
- `analysis_id = hash(data_id, script_hash, params)`; the parent hangs off the
  exact data ID; when the data's current pointer moves, old analyses go stale.
  "Misuse" becomes queryable from this: which analyses have been registered
  against this data, with which script and parameters, and whether they are
  still valid.

## 3. Analysis Environment: Recorded in the deps registry

Python analysis environments (conda/venv) **must be recorded**, attached to the
site's deps registry at the same level as build stacks, so an agent can find
them with a single query (`site deps <site>`).

- Registry entries gain a `kind` field: `build` (default, build toolchain
  stack) | `analysis` (Python environment). For an analysis entry, packages
  records the interpreter path and key package versions (python/numpy/nt2py
  etc.), and recipe records how it was created (a `conda env export` summary or
  a venv path).
- The manifest of `record analysis` records the stack_id of the environment
  used (nullable — ad-hoc environments are not forced to register);
  environments backed by a registered stack are traceable in the dashboard and
  queries.
- `entityctl site deps-add` is extended with `--kind analysis` (gate relaxed:
  env.sh and a compatibility pass are not required; instead the interpreter
  path must actually exist on the site).

## 4. Physical Layout (enabling the 0.7.0 reserved slots)

```text
# Workspace side:
projects/<p>/analysis/scripts/                 # general-purpose script library (authority)
projects/<p>/cases/<c>/analysis/<analysis_id>/ # retrieved copies of reports/figures/manifest (lightweight)

# Site side (executed near the data; large artifacts stay here):
<site_root>/projects/<p>/analysis/<case>/<analysis_id>/   # artifacts + analysis-manifest.json
```

Artifacts never write to the raw run root (existing contract unchanged).

## 5. Primitives and Presentation

```bash
entityctl record analysis --project-root <p> [--case <c>] \
  --script <path relative to scripts/> --data <run_id|data_id> \
  --params '<json>' --output-root <site artifact directory> [--env-stack <stack_id>]
```

- The dashboard analysis cell is upgraded: `none / established / stale`
  (whether the parent data_id is current) + manifest evidence + a
  hardcoded_paths warning marker; the six-cell contract is unchanged.
- `show` outputs the case's analysis list (script, parameters, parent data,
  status).

## 6. Boundaries

- The nt2py boundary is unchanged: data access and plotting methods; it does
  not handle registration and does not judge physical correctness.
- The Ledger does not do: diagnostic methods, artifact format mandates, or
  analysis workflow orchestration.
- One-off case-level scripts: not onboarded, not registered; the agent manages
  them itself.

## 7. Migration

Onboarding existing scripts is carried out by the agent together with the
0.7.0 production migration: general-purpose scripts go into
`projects/<p>/analysis/scripts/` (hardcoded ones into legacy/), and manually
synced copies scattered around are deduplicated with the Workspace as the
authority; historical analysis artifacts are not retroactively registered —
new analyses start from `record analysis`. Existing analysis environments
(such as bh-reconnection's venv) are registered by the agent with
`site deps-add --kind analysis`.

## 8. Development Plan (single phase)

1. store: wire up the write path for the `analysis` dimension (the whitelist
   already has it), maintain the analysis_id in the current projection, and
   propagate staleness (data changes → analysis stale).
2. `record analysis` primitive: manifest evidence probing (local + ssh
   channel), analysis_id derivation, zero-write gate, audit event.
3. site tree: path derivation for
   `projects/<p>/analysis/<case>/<analysis_id>/` (execution_roots extension).
4. deps registry: `kind` field + `site deps-add --kind analysis`
   (interpreter-existence gate).
5. dashboard: analysis cell readiness + evidence + hardcoded warning; the
   analysis list in `show`.
6. Documentation: ledger SKILL.md (primitives + semantics),
   workspace-layout.md (enable the analysis slots), nt2py SKILL.md (one
   sentence: for registration see the ledger), migration-guide.md (script
   onboarding section), CHANGELOG.
7. Tests: all `record analysis` gates, staleness propagation, kind=analysis
   registration, dashboard presentation; full pytest suite green.
