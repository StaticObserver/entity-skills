# ADIOS2 Build Notes

ADIOS2 is the most complex dependency because of its multi-library dependency
chain (Kokkos + HDF5) and GPU-aware compilation.

## Version Policy

| Profile | ADIOS2 version | Kokkos support | CUDA via |
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

Depending on profile/backend:
| Condition | Options |
|-----------|---------|
| MPI=ON     | `-DADIOS2_USE_MPI=ON -DADIOS2_HAVE_HDF5_VOL=ON` |
| MPI=OFF    | `-DADIOS2_USE_MPI=OFF -DADIOS2_HAVE_HDF5_VOL=OFF` |
| All supported builds | `-DADIOS2_USE_Kokkos=ON` |
| CUDA | `-DADIOS2_USE_CUDA=OFF` (CUDA goes through Kokkos) |

Additional CUDA requirements:
```
-DCMAKE_CUDA_COMPILER=<cuda_prefix>/bin/nvcc
-DCMAKE_CUDA_ARCHITECTURES=<arch_number>
```
These are required because ADIOS2+Kokkos triggers CMake's `enable_language(CUDA)`.

CMAKE_PREFIX_PATH must include both the Kokkos and HDF5 prefixes before the
ADIOS2 configure, with Kokkos first (so that ADIOS2 finds KokkosConfig.cmake
before falling back to a non-Kokkos path).

## Known Issues

### CUDA GPU dynamic libraries required
- Symptom: link errors `cannot find -l cuda`, `libcuda.so not found`, or missing `libcudart.so`
- Trigger: ADIOS2 2.11.x with the Kokkos CUDA backend links against the CUDA runtime libraries
- Fix: add both the stubs and the real library paths to the linker flags. Stubs first (login nodes prefer them for non-GPU symbols), then the real library path (GPU nodes need libcuda.so and libcudart.so):
  ```bash
  STUBS="<cuda_prefix>/targets/x86_64-linux/lib/stubs"
  CUDA_LIB="<cuda_prefix>/targets/x86_64-linux/lib"
  export LDFLAGS="-L$STUBS -L$CUDA_LIB ${LDFLAGS:-}"
  export CMAKE_EXE_LINKER_FLAGS="-L$STUBS -L$CUDA_LIB ${CMAKE_EXE_LINKER_FLAGS:-}"
  export CMAKE_SHARED_LINKER_FLAGS="-L$STUBS -L$CUDA_LIB ${CMAKE_SHARED_LINKER_FLAGS:-}"
  ```
  The stubs provide enough symbols for ADIOS2 to link on login nodes;
  the real library path is needed at both link time and runtime on GPU nodes.
  The generated build scripts add both paths automatically.

### enable_language(CUDA) missing required variables
- Symptom: CMake error "No CMAKE_CUDA_COMPILER could be found"
- Trigger: ADIOS2 with the Kokkos CUDA backend triggers CUDA language support
- Fix: explicitly set `-DCMAKE_CUDA_COMPILER=<cuda_prefix>/bin/nvcc` in the cmake configure

### Incomplete cmake --install (missing targets files)
- Symptom: Entity cmake configure fails with "adios2 targets not found", or `cmake --install` exits non-zero
- Trigger: ADIOS2's `cmake --install` tries to install all targets, including the tools (`adios2_remote_server`, `bpls`, etc.). On login nodes without `libcuda.so.1`, the tool targets fail to link, and the install step is all-or-nothing.
- Fix: the generated build scripts now pass `-DADIOS2_BUILD_TOOLS=OFF` to skip the tools entirely. Entity only needs the libraries (libadios2_core.so, libadios2_c.so, libadios2_cxx.so), not the CLI tools.

### GCC libstdc++ ABI version mismatch
- Symptom: `undefined reference to std::__cxx11::...` during ADIOS2 linking
- Trigger: mixing GCC versions (libstdc++ from an old system GCC with a newer compiler)
- Fix: ensure LD_LIBRARY_PATH includes the selected compiler's lib64 directory.
  This is handled by env.sh generation.

### nvcc_wrapper using the wrong host compiler
- Symptom: ADIOS2 configure detects the wrong host compiler
- Trigger: the Kokkos nvcc_wrapper script carries a stale NVCC_WRAPPER_DEFAULT_COMPILER
- Fix: patch nvcc_wrapper, or create a wrapper script that sets the variable first:
  ```bash
  #!/bin/bash
  export NVCC_WRAPPER_DEFAULT_COMPILER=/path/to/g++
  exec /path/to/kokkos/bin/nvcc_wrapper "$@"
  ```

## Post-Build Verification

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

Verification:
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
