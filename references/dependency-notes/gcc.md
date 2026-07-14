# GCC Build Notes

## Known-Bad Versions

### GCC 12.2.0 ICE: if constexpr in Template Code
- **Symptom**: `internal compiler error: in tsubst_copy, at cp/pt.cc:17004`
- **Trigger**: Entity 1.4.3+ framework code using `if constexpr` constructs in template-heavy paths (e.g., `simulation.cpp`). Also triggered by TOML11 `std::source_location::current()` consteval failures.
- **Affected versions**: GCC 12.2.0 (possibly other 12.x). Not triggered on GCC 13.3+ or 11.x.
- **Fix**: Use GCC 13.3+ or GCC 11.x. Do not use GCC 12.x for Entity builds.
- **Detection**: `entity_compat.py` flags any GCC 12.2.x as `compiler.version.gcc.known_bad` with status WARN.

## C++ Standards Support

| GCC Version | C++20 | Notes |
|-------------|-------|-------|
| 8.x | Partial | Unsupported |
| 10.4+ | Yes | Minimum supported version |
| 11.x | Yes | Safe choice |
| 12.x | Yes | **Known ICE with if constexpr** |
| 13.3+ | Yes | Recommended for Entity >= 1.4.0 |

## SDK Compatibility

### NVCC + GCC Host
- NVCC wraps the host GCC compiler. The host GCC must be a version compatible with the CUDA toolkit:
  - CUDA 12.0: ships with GCC 12.x headers by default; may need `--allow-unsupported-compiler`
  - CUDA 12.2+: supports GCC 12.x and 13.x
- When using conda GCC, ensure `libstdc++` path is in `LD_LIBRARY_PATH` for correct ABI linking.

### Spack GCC
Preferred way to get a newer GCC on HPC systems:
```bash
spack install gcc@13.3.0
spack load gcc@13.3.0
```
Use `spack find gcc` to discover available versions before scaffolding environment.
