# Entity Debugging Guide (Archived)

## Compile-Time Errors

### CMake Can't Find Kokkos
```
Could not find a package configuration file provided by "Kokkos"
```
**Fix**: Let Kokkos build in-tree (default behavior). If you specified an external Kokkos, ensure `CMAKE_PREFIX_PATH` points to it, or add `-D Kokkos_ROOT=/path/to/kokkos`.

### CUDA Architecture Mismatch
```
nvcc fatal: Unsupported GPU architecture 'compute_XX'
```
**Fix**: Check your GPU model and set the correct architecture flag:
```bash
nvidia-smi --query-gpu=name --format=csv,noheader
```
Match to the correct `Kokkos_ARCH_*` flag (see 01-build-env.md GPU table).

### Compiler Version Incompatibility
```
error: no matching function for call to ...
```
or cryptic template errors. Common causes:
- **GCC too old** (< 10) — C++20 features missing (Entity 1.4.x + Kokkos 5.x require C++20)
- **CUDA/host compiler mismatch** — check [compatibility matrix](https://gist.github.com/ax3l/9489132)
- **Kokkos not compiled with C++20** — add `-D CMAKE_CXX_STANDARD=20`

### Missing Problem Generator
```
CMake Error: pgen '<name>' not found
```
**Fix**: Check that `pgens/<name>/pgen.hpp` exists. Common typos in the pgen name. List available pgens:
```bash
ls pgens/*/pgen.hpp
```

### ADIOS2 Not Found or HDF5 Issues
**Fix**: Disable ADIOS2 in-tree build and use system ADIOS2, or vice versa. If HDF5 linking fails, try building without it (Entity's BP5 format is preferred anyway).

### GPU-Aware MPI Errors
```
error: 'MPIX_Query_cuda_support' was not declared
```
**Fix**: Disable GPU-aware MPI: `-D gpu_aware_mpi=OFF`. This is needed on many systems.

## Configuration Warnings to Watch For

### Kokkos Architecture Warnings
If CMake auto-detects the wrong GPU architecture (especially on login nodes that differ from compute nodes), explicitly set it:
```bash
-D Kokkos_ARCH_AMPERE80=ON    # for A100 compute nodes
```

### MPI Domain Decomposition
If `simulation.number` doesn't divide the grid cleanly, expect warnings. Use `decomposition = [-1, -1, -1]` for auto-detection.

## Runtime Output Files

When a simulation runs, it produces:

| File | Content | When to Check |
|------|---------|---------------|
| `<name>.info` | Parameters, compiler version, architecture, runtime config | Always — verify your setup |
| `<name>.log` | Timestamps of each substep | Debugging crashes or stalls |
| `<name>.err` | Error messages and warnings | **First file to check on failure** |
| stdout | Live progress: step durations, particle counts, ETA | Monitor simulation health |
| `*.bp` / `*.h5` | Field/Particle/Spectra data | Output enabled |
| `<name>.csv` | Box-averaged stats per timestep | Quick physics sanity checks |

## Live Standard Output Interpretation

Example output line during a run:
```
Step: 1000 | Time: 10.5 | dt: 0.01 | Walltime: [...]
  comm: 0.12s | deposit: 0.45s | filter: 0.05s | solver: 0.30s | pusher: 0.55s
  Npart: 2457600 | ETA: 2h 15m
```

What to watch:
- **Npart dropping rapidly** — particles being absorbed/lost at boundaries; check boundary config
- **Npart growing without bound** — injection rate too high; check pgen InitPrtls
- **dt shrinking** — CFL condition violated; check `timestep.CFL`, reduce it (e.g., 0.45 → 0.3)
- **solver time dominating** — field solver is the bottleneck; consider coarser resolution
- **pusher time dominating** — too many particles; reduce ppc0 or use coarser stride

## Common Runtime Errors

### "Maximum number of particles exceeded"
```
ERROR: maxnpart exceeded for species X
```
**Fix**: Increase `maxnpart` for that species in TOML, or reduce injection rate.

### CFL Violation / Instability
```
WARNING: dt too small
```
or NaN values in outputs.
**Fix**: Reduce `algorithms.timestep.CFL` (e.g., 0.95 → 0.45). Ensure `scales` parameters are physically consistent.

### GPU-Aware MPI Runtime Error
Program crashes during MPI communication.
**Fix**: Recompile with `-D gpu_aware_mpi=OFF`. This is the most common issue on multi-node GPU runs.

### Boundary Condition Errors
- **ATMOSPHERE**: Missing `temperature` or `density` in `[boundaries.atmosphere]`
- **MATCH**: `match_ds` too small — oscillation at boundaries; increase to 5-10% of domain
- **CONDUCTOR**: Must pair with `REFLECT` for particles
- **HORIZON**: Only valid in GR with Kerr-Schild metric; ensure correct `ks_rh`

### Spherical Coordinate Gotchas
- Theta/phi boundaries are auto-set — only specify r boundaries
- Check that rmin > 0 (singularity at origin)
- QSpherical: `qsph_r0 < 0` gives near-uniform grid in r

### NaN Propagation
Fields become NaN, typically after a few steps.
**Causes**:
1. CFL too aggressive (reduce to 0.3)
2. Too few particles per cell (increase `ppc0`)
3. Sharp gradients in initial conditions (smooth them)
4. Boundary layer too thin (increase `match_ds`)

**Diagnosis**: Compile with `-D DEBUG=ON` — adds bounds checks and assertions. Run fewer steps first.

## Debug Build

```bash
cmake -B build -D DEBUG=ON -D pgen=<name> ...
cmake --build build -j
```

Debug mode enables:
- Array bounds checking
- Assertions throughout the code
- More verbose error messages
- Disables optimizations (slower but more diagnostic info)

## Running Unit Tests

Enable tests during CMake configuration:
```bash
cmake -B build -D TESTS=ON -D pgen=<name> ...
cmake --build build -j
ctest --test-dir build/ --output-on-failure
```

Filter specific tests:
```bash
ctest --test-dir build/ -R particle     # Only particle-related tests
ctest --test-dir build/ -R field        # Only field-related tests
```

## Performance Diagnostics

### Blocking Timers
Enable in TOML:
```toml
[diagnostics]
blocking_timers = true
```
Shows detailed wall-clock breakdown of each algorithm stage per step:
- **communications**: MPI data exchange (high = network bottleneck)
- **current deposit**: Particle→grid interpolation (high = many particles or high shape_order)
- **current filter**: Smoothing passes (high if `current_filters > 2`)
- **field solver**: FDTD update (high = large grid or complex metric)
- **particle pusher**: Particle advance (high = many particles or complex pusher like GR)

### Optimization Strategies
| Bottleneck | Solution |
|-----------|----------|
| Communications | Use fewer MPI ranks, check GPU-aware MPI, batch outputs |
| Current deposit | Reduce `shape_order`, reduce `ppc0`, increase `clear_interval` |
| Field solver | Reduce resolution, use 2D instead of 3D, check stencil coefficients |
| Particle pusher | Reduce ppc0, increase stride, use Boris instead of Vay |
| Output | Increase output `interval`, use `downsampling`, reduce quantities list |

## Checkpoint and Restart

Simulations can be checkpointed:
```toml
[output.checkpoint]
interval = 10000                    # Checkpoint every 10000 steps
keep = 2                            # Keep last 2 checkpoints (0=disable, -1=all)
walltime = "23:30:00"              # Force checkpoint before job limit
write_path = "/path/to/checkpoints"
```

Restart from checkpoint:
```toml
[output.checkpoint]
read_path = "/path/to/checkpoints"
is_resuming = true
```
The `start_step` and `start_time` are auto-inferred from the checkpoint.

## Systematic Debug Workflow

1. **Check `.err` file first** — Entity writes clear error messages there
2. **Check `.info` file** — verify all parameters were parsed correctly
3. **Run with `log_level = "VERBOSE"`** in `[diagnostics]` for maximum output
4. **Enable block timers** to identify which phase fails
5. **Reduce the problem**: 2D instead of 3D, coarser grid, fewer particles
6. **Compile with DEBUG=ON** for array bounds checking
7. **Run a known working pgen** (e.g., from examples) before debugging your own
8. **Single-GPU first**, then add MPI after it works on one GPU
