# Machine: <hostname>
> last_updated: <YYYY-MM-DD>

<!--
  Template for ~/.entity-env-build/site-notes/<hostname>.md
  Generated at runtime by the AI agent — not shipped with the skill source.

  The AI agent reads this file at the start of Phase 2 (environment probing)
  and writes to it when it discovers new issues or completes a build.

  Sections:
  - Machine profile        → static information: what hardware/software does this machine have?
  - Known-good combinations → which dependency combinations have been proven to work?
  - Known issues           → what breaks, and how to fix it?
  - Build history          → which builds have been done on this machine?

  Keep entries concise. Prefer bullet lists over prose.
  Update last_updated at the top on every edit.
-->

## Machine Profile
<!-- Fill in once per machine; update when the environment changes -->
- Login node:
- Scheduler:
- GPU partitions:
- CPU partitions:
- Module initialization:
- Default Python:
- Notable constraints: <!-- e.g. "never compile on the login node", "compute nodes have no external network", "only Python 3.6" -->

## Known-Good Combinations
<!-- Add after every successful build. Format:
### <pgen> | <backend> | <MPI on/off>
- DTK: <version> | Kokkos: <version> | ADIOS2: <version> | HDF5: <version>
- OpenMPI: <version> | Compiler: <name+version>
- Optimization: <-Ox>
- Precision: <single/double>
- Notes: <any non-obvious detail>
-->

## Known Issues
<!-- Add whenever a non-obvious issue is discovered. Format:
### <descriptive title>
- Symptom: <error message pattern>
- Trigger: <what caused it>
- Fix: <concrete steps>
-->

## Build History
<!-- Append after every build. Format:
| <date> | <site_id> | <entity ver> | <source rev> | <backend> | <result> | <build root> |
-->
| Date | Entity | PGen | Backend | Precision | Optimization | Result | Workdir |
|------|--------|------|---------|-----------|-----|--------|---------|
