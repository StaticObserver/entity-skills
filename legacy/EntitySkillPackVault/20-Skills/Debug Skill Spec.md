# Debug Skill Spec

## Mission

Diagnose Entity build, runtime, output, checkpoint, cluster environment, and numerical behavior problems.

This skill is a cross-cutting capability that can be invoked by simulation, analysis, or development workflows.

## Troubleshooting Categories

### Build

- CMake options;
- Kokkos backend and architecture flags;
- compiler and CUDA/HIP compatibility;
- ADIOS2 and HDF5 discovery;
- MPI and GPU-aware MPI.

### Runtime

- `.err` and `.log` files;
- stdout progress;
- abnormal particle growth or loss;
- `maxnpart` exceeded;
- NaN or timestep shrinkage;
- boundary-condition problems.

### Output

- missing fields or particle data;
- BP5/HDF5 format mismatch;
- missing or malformed stats CSV;
- custom output hook not detected;
- checkpoint write/read failures.

### Performance

- communication bottleneck;
- current deposition;
- field solver;
- particle pusher;
- output throughput.

## Workflow

1. Preserve the failing command and environment.
2. Classify the failure: build, runtime, output, checkpoint, performance, or numerical.
3. Read the artifact closest to the error first.
4. Minimize the problem case.
5. Compare with a known-working pgen when feasible.
6. Propose only one change at a time.
7. Rerun the smallest useful check.

## Output

State:

- suspected cause;
- evidence;
- fixes tried or suggested;
- verification result;
- remaining uncertainty.
