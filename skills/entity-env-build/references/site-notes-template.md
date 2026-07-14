# Machine: <hostname>
> last_updated: <YYYY-MM-DD>

<!--
  Template for ~/.entity-env-build/site-notes/<hostname>.md
  Generated at runtime by the AI agent — NOT shipped in skill source.

  The AI agent reads this file at the start of Phase 2 (environment probing) and
  writes to it after discovering new issues or completing builds.

  SECTIONS:
  - Machine Profile     → static: what hardware/software does this machine have?
  - Known-good Combos   → what dependency sets have been proven to work?
  - Known Issues        → what breaks, and how do you fix it?
  - Build History       → what builds have been done on this machine?

  Keep entries concise. Prefer bullet lists over prose.
  Update last_updated at the top whenever you edit.
-->

## Machine Profile
<!-- Fill once per machine; update when the environment changes -->
- Login nodes:
- Scheduler:
- GPU partitions:
- CPU partitions:
- Module init:
- Default Python:
- Notable constraints: <!-- e.g. "NEVER compile on login nodes", "compute nodes no internet", "Python 3.6 only" -->

## Known-good Combinations
<!-- Add after each successful build. Format:
### <pgen> | <backend> | <MPI on/off>
- DTK: <version> | Kokkos: <version> | ADIOS2: <version> | HDF5: <version>
- OpenMPI: <version> | Compiler: <name+version>
- Optimization: <-Ox>
- Precision: <single/double>
- Notes: <any non-obvious detail>
-->

## Known Issues
<!-- Add whenever you discover a non-obvious problem. Format:
### <descriptive title>
- Symptom: <error message pattern>
- Trigger: <what causes it>
- Fix: <concrete steps>
-->

## Build History
<!-- Append after each build. Format:
| <date> | <entity ver> | <pgen> | <backend> | <precision> | <opt> | <result> | <workdir> |
-->
| Date | Entity | PGen | Backend | Precision | Opt | Result | Workdir |
|------|--------|------|---------|-----------|-----|--------|---------|
