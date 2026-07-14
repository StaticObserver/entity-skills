# Kokkos Build Notes

## Version Policy

| Profile | Entity Version | Kokkos Version | C++ Standard |
|---------|---------------|----------------|-------------|
| modern  | >= 1.4.0      | 5.x (default 5.0.1) | 20 |

Entity versions before `1.4.0` are unsupported.

## CMake Options

Baseline:
```
-DCMAKE_CXX_EXTENSIONS=OFF
-DCMAKE_POSITION_INDEPENDENT_CODE=TRUE
-DKokkos_ENABLE_SERIAL=ON
-DKokkos_ENABLE_PIC=ON
-DCMAKE_CXX_STANDARD=<profile_cxx_standard>
```

Backend-dependent:
| Backend | Options |
|---------|---------|
| cpu     | `-DKokkos_ENABLE_OPENMP=ON` |
| cuda    | `-DKokkos_ENABLE_CUDA=ON -DKokkos_ARCH_<ARCH>=ON` |
| hip     | `-DKokkos_ENABLE_HIP=ON -DKokkos_ARCH_<ARCH>=ON` |

## CUDA Backend — nvcc_wrapper

CUDA builds MUST use Kokkos `nvcc_wrapper` as CXX. Critical settings:

1. **Host compiler**: `NVCC_WRAPPER_DEFAULT_COMPILER` must point to a compatible host compiler
2. **CUDA toolkit**: nvcc must be on PATH before running cmake
3. **Architecture**: Explicitly set `Kokkos_ARCH_*` (e.g., `AMPERE80` for A100, `VOLTA70` for V100)

Install prefix contains `bin/nvcc_wrapper` — this is what selected.compiler.cxx must point to.

## Known Issues

### GCC Version Too Old for Kokkos 5.x
- Symptom: C++20 feature errors during Kokkos configure
- Trigger: GCC < 10.4 with modern profile
- Fix: Use a newer GCC (module, spack, or local install). Minimum GCC 10.4 for modern profile.

### NVCC Version Too Old for C++20
- Symptom: `-std=c++20` not recognized by nvcc
- Trigger: NVCC < 12.2 with modern profile
- Fix: Upgrade CUDA toolkit to 12.2+. Check `nvcc --version`.

### nvcc_wrapper Host Compiler Propagation
- Symptom: nvcc_wrapper uses wrong host compiler (system default instead of selected)
- Trigger: PATH has multiple GCC installations
- Fix: Set `NVCC_WRAPPER_DEFAULT_COMPILER` explicitly before cmake configure. Check the generated nvcc_wrapper script header.

### Kokkos_ENABLE_PIC Warning
- Symptom: CMake warning "Manually-specified variables were not used: Kokkos_ENABLE_PIC"
- Trigger: Kokkos 5.x ignores this flag (PIC is always on)
- Fix: Ignore; the flag is harmless.

## Post-Build Validation

Expected install structure:
```
<prefix>/
├── bin/nvcc_wrapper          ← Must exist and be executable (CUDA only)
├── include/
├── lib64/
│   ├── libkokkoscore.a
│   ├── libkokkoscontainers.a
│   ├── libkokkossimd.a
│   └── cmake/Kokkos/KokkosConfig.cmake  ← Must exist
```

Verify:
```bash
<prefix>/bin/nvcc_wrapper --version  # CUDA only
cmake --find-package -DNAME=Kokkos -DCOMPILER_ID=GNU -DLANGUAGE=CXX -DMODE=EXIST
```
