# GCC Build Notes

## Known Bad Versions

### GCC 12.2.0 ICE: if constexpr in template code
- **Symptom**: `internal compiler error: in tsubst_copy, at cp/pt.cc:17004`
- **Trigger**: Entity 1.4.3+ framework code uses `if constexpr` constructs in template-heavy paths (e.g., `simulation.cpp`). TOML11's `std::source_location::current()` consteval failure also triggers it.
- **Affected versions**: GCC 12.2.0 (possibly other 12.x). GCC 13.3+ or 11.x do not trigger it.
- **Fix**: use GCC 13.3+ or GCC 11.x. Do not use GCC 12.x for Entity builds.
- **Detection**: `entity_compat.py` flags any GCC 12.2.x as `compiler.version.gcc.known_bad` with status WARN.

## C++ Standard Support

| GCC version | C++20 | Notes |
|-------------|-------|-------|
| 8.x | Partial | Not supported |
| 10.4+ | Yes | Minimum supported version |
| 11.x | Yes | Safe choice |
| 12.x | Yes | **Known ICE with if constexpr** |
| 13.3+ | Yes | Recommended for Entity >= 1.4.0 |

## SDK Compatibility

### NVCC + GCC Host
- NVCC wraps the host GCC compiler. The host GCC must be a version compatible with the CUDA toolkit:
  - CUDA 12.0: ships with GCC 12.x headers by default; may need `--allow-unsupported-compiler`
  - CUDA 12.2+: supports GCC 12.x and 13.x
- When using conda GCC, ensure the `libstdc++` path is in `LD_LIBRARY_PATH` for correct ABI linking.

### Spack GCC
The preferred way to obtain a newer GCC on HPC systems:
```bash
spack install gcc@13.3.0
spack load gcc@13.3.0
```
Before setting up the environment, discover available versions with `spack find gcc`.
