# Kokkos Build Notes

## Version Policy

| Profile | Entity version | Kokkos version | C++ standard |
|---------|---------------|----------------|-------------|
| modern  | >= 1.4.0      | 5.x (default 5.0.1) | 20 |

Entity versions before `1.4.0` are not supported.

## CMake Options

Baseline:
```
-DCMAKE_CXX_EXTENSIONS=OFF
-DCMAKE_POSITION_INDEPENDENT_CODE=TRUE
-DKokkos_ENABLE_SERIAL=ON
-DKokkos_ENABLE_PIC=ON
-DCMAKE_CXX_STANDARD=<profile_cxx_standard>
```

Depending on backend:
| Backend | Options |
|---------|---------|
| cpu     | `-DKokkos_ENABLE_OPENMP=ON` |
| cuda    | `-DKokkos_ENABLE_CUDA=ON -DKokkos_ARCH_<ARCH>=ON` |
| hip     | `-DKokkos_ENABLE_HIP=ON -DKokkos_ARCH_<ARCH>=ON` |

## CUDA Backend — nvcc_wrapper

CUDA builds must use the Kokkos `nvcc_wrapper` as CXX. Key settings:

1. **Host compiler**: `NVCC_WRAPPER_DEFAULT_COMPILER` must point to a compatible host compiler
2. **CUDA toolkit**: nvcc must be in PATH before running cmake
3. **Architecture**: set `Kokkos_ARCH_*` explicitly (e.g., `AMPERE80` for A100, `VOLTA70` for V100)

The install prefix contains `bin/nvcc_wrapper` — this is what selected.compiler.cxx must point to.

## Known Issues

### GCC version too old for Kokkos 5.x
- Symptom: C++20 feature errors during Kokkos configure
- Trigger: GCC < 10.4 under the modern profile
- Fix: use a newer GCC (module, spack, or local install). The modern profile requires GCC 10.4 at minimum.

### NVCC version too old for C++20
- Symptom: nvcc does not recognize `-std=c++20`
- Trigger: NVCC < 12.2 under the modern profile
- Fix: upgrade the CUDA toolkit to 12.2+. Check `nvcc --version`.

### nvcc_wrapper host compiler propagation
- Symptom: nvcc_wrapper uses the wrong host compiler (system default instead of the selected one)
- Trigger: multiple GCC installations in PATH
- Fix: explicitly set `NVCC_WRAPPER_DEFAULT_COMPILER` before the cmake configure. Check the header of the generated nvcc_wrapper script.

### Kokkos_ENABLE_PIC warning
- Symptom: CMake warning "Manually-specified variables were not used: Kokkos_ENABLE_PIC"
- Trigger: Kokkos 5.x ignores the flag (PIC is always on)
- Fix: ignore it; the flag is harmless.

## Post-Build Verification

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

Verification:
```bash
<prefix>/bin/nvcc_wrapper --version  # CUDA only
cmake --find-package -DNAME=Kokkos -DCOMPILER_ID=GNU -DLANGUAGE=CXX -DMODE=EXIST
```
