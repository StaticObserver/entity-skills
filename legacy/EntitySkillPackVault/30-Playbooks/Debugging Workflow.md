# Debugging Workflow

## Goal

Go from symptom to verified cause with minimal changes.

## Steps

1. Capture the exact command and environment.
2. Classify the failure: build, runtime, output, checkpoint, performance, numerical.
3. Read the information source closest to the error.
4. Narrow down the case.
5. Compare against a known working example.
6. Apply one change.
7. Re-run the minimal check.
8. Record the result and the remaining risk.

## Files to Check First

- build: CMake configure output and compiler errors;
- runtime: `<name>.err`, `<name>.log`, stdout;
- output: `.info`, output directory structure, ADIOS2/HDF5 files;
- analysis: stats CSV and nt2py loading errors.
