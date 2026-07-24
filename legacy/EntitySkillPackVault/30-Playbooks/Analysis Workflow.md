# Analysis Workflow

## Goal

Turn simulation output into diagnostic evidence.

## Steps

1. Locate the output path and metadata.
2. If a `.err` file exists, read it first.
3. Read `.info` and the stats CSV.
4. Use nt2py lazy load.
5. Select by time/space/species before loading arrays.
6. Generate the required plots and numeric diagnostics.
7. Compare against an expectation or a previous run when possible.
8. Mark the evidence strength.
9. Save the script/notebook and the report.

## Evidence Labels

- visual;
- numerical;
- regression;
- unresolved.
