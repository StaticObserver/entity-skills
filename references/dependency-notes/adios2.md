# ADIOS2 Build Notes

ADIOS2 is the most complex dependency due to its multi-library dependency chain
(Kokkos + HDF5) and GPU-aware compilation.

## Version Policy

| Profile | ADIOS2 Version | Kokkos Support | CUDA via |
|---------|---------------|----------------|----------|
| modern  | 2.11.x        | ON             | Kokkos only |

## CMake Options

Baseline:
```
-DCMAKE_CXX_EXTENSIONS=OFF
-DCMAKE_POSITION_INDEPENDENT_CODE=TRUE
-DBUILD_SHARED_LIBS=ON
-DADIOS2_USE_Python=OFF
-DADIOS2_USE_Fortran=OFF
-DADIOS2_USE_ZeroMQ=OFF
-DBUILD_TESTING=OFF
-DADIOS2_BUILD_EXAMPLES=OFF
-DADIOS2_USE_HDF5=ON
-DADIOS2_BUILD_TOOLS=OFF
```

Profile/backend-dependent:
| Condition | Options |
|-----------|---------|
| MPI=ON     | `-DADIOS2_USE_MPI=ON -DADIOS2_HAVE_HDF5_VOL=ON` |
| MPI=OFF    | `-DADIOS2_USE_MPI=OFF -DADIOS2_HAVE_HDF5_VOL=OFF` |
| all supported builds | `-DADIOS2_USE_Kokkos=ON` |
| CUDA | `-DADIOS2_USE_CUDA=OFF` (CUDA goes through Kokkos) |

CUDA additionally requires:
```
-DCMAKE_CUDA_COMPILER=<cuda_prefix>/bin/nvcc
-DCMAKE_CUDA_ARCHITECTURES=<arch_number>
```
These are needed because ADIOS2+Kokkos triggers CMake `enable_language(CUDA)`.

CMAKE_PREFIX_PATH must include both Kokkos and HDF5 prefixes before ADIOS2 configure,
with Kokkos first (so ADIOS2 finds KokkosConfig.cmake before falling back to non-Kokkos).

## Known Issues

### CUDA GPU Dynamic Libraries Required
- Symptom: linker error `cannot find -l cuda`, `libcuda.so not found`, or `libcudart.so` missing
- Trigger: ADIOS2 2.11.x with Kokkos CUDA backend links against CUDA runtime libraries
- Fix: Add BOTH stubs and real lib paths to linker flags. Stubs first (login nodes prefer them for non-GPU symbols), then real lib path (GPU nodes need libcuda.so and libcudart.so):
  ```bash
  STUBS="<cuda_prefix>/targets/x86_64-linux/lib/stubs"
  CUDA_LIB="<cuda_prefix>/targets/x86_64-linux/lib"
  export LDFLAGS="-L$STUBS -L$CUDA_LIB ${LDFLAGS:-}"
  export CMAKE_EXE_LINKER_FLAGS="-L$STUBS -L$CUDA_LIB ${CMAKE_EXE_LINKER_FLAGS:-}"
  export CMAKE_SHARED_LINKER_FLAGS="-L$STUBS -L$CUDA_LIB ${CMAKE_SHARED_LINKER_FLAGS:-}"
  ```
  The stubs provide enough symbols for ADIOS2 to link on login nodes;
  the real lib path is needed for GPU nodes at link and runtime.
  The generated build script adds both paths automatically.

### enable_language(CUDA) Without Required Variables
- Symptom: CMake error "No CMAKE_CUDA_COMPILER could be found"
- Trigger: ADIOS2 with Kokkos CUDA backend triggers CUDA language support
- Fix: Set `-DCMAKE_CUDA_COMPILER=<cuda_prefix>/bin/nvcc` explicitly in cmake configure

### Incomplete cmake --install (Missing Targets Files)
- Symptom: Entity cmake configure fails with "adios2 targets not found", or `cmake --install` exits non-zero
- Trigger: ADIOS2 `cmake --install` attempts to install ALL targets including tools (`adios2_remote_server`, `bpls`, etc.). On login nodes without `libcuda.so.1`, tool targets fail to link, and the install step is all-or-nothing.
- Fix: The generated build script now passes `-DADIOS2_BUILD_TOOLS=OFF` to skip tools entirely. Entity only needs the libraries (libadios2_core.so, libadios2_c.so, libadios2_cxx.so), not the CLI tools.

### GCC libstdc++ ABI Version Mismatch
- Symptom: `undefined reference to std::__cxx11::...` during ADIOS2 link
- Trigger: Mixing GCC versions (old system GCC libstdc++ vs new compiler)
- Fix: Ensure LD_LIBRARY_PATH includes the selected compiler's lib64 directory.
  This is handled by env.sh generation.

### nvcc_wrapper With Wrong Host Compiler
- Symptom: ADIOS2 configure detects wrong host compiler
- Trigger: Kokkos nvcc_wrapper script has stale NVCC_WRAPPER_DEFAULT_COMPILER
- Fix: Patch nvcc_wrapper or create a wrapper script that sets the variable first:
  ```bash
  #!/bin/bash
  export NVCC_WRAPPER_DEFAULT_COMPILER=/path/to/g++
  exec /path/to/kokkos/bin/nvcc_wrapper "$@"
  ```

## Post-Build Validation

Expected install structure:
```
<prefix>/
├── bin/
├── include/
├── lib64/
│   ├── libadios2_c.so
│   ├── libadios2.so
│   └── cmake/adios2/
│       ├── adios2-config.cmake
│       ├── adios2-config-version.cmake
│       ├── adios2-targets.cmake
│       ├── adios2-targets-release.cmake
│       ├── adios2-c-targets.cmake
│       ├── adios2-c-targets-release.cmake
│       ├── adios2-cxx-targets.cmake
│       └── adios2-cxx-targets-release.cmake
```

Verify:
```bash
# CMake config
ls <prefix>/lib64/cmake/adios2/adios2-config.cmake

# Targets files (all 6 must exist)
ls <prefix>/lib64/cmake/adios2/adios2-targets*.cmake \
   <prefix>/lib64/cmake/adios2/adios2-c-targets*.cmake \
   <prefix>/lib64/cmake/adios2/adios2-cxx-targets*.cmake

# Libraries
ls <prefix>/lib64/libadios2_c.so <prefix>/lib64/libadios2.so
```
