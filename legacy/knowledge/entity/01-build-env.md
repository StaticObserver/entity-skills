# Entity Build Environment (Archived)

## System Dependencies

### Required
| Dependency | Version | Notes |
|-----------|---------|-------|
| CMake | >= 3.16 | |
| C++ Compiler | GCC >= 10 / Clang >= 11 / Intel >= 19.1 | Must support C++20 (Entity 1.4.x + Kokkos 5.x) |
| Kokkos | >= 5.0 | Performance portability; can be compiled in-tree with Entity. Requires C++20 |
| ADIOS2 | >= 2.11.0 | Data output; **recommended to pre-install** (long compile time) |

### Optional
| Dependency | Version | Notes |
|-----------|---------|-------|
| MPI | OpenMPI / MPICH | Multi-node parallelism |
| CUDA Toolkit | >= 11.0 | For NVIDIA GPU compilation |
| ROCm/HIP | (any recent) | For AMD GPU compilation |
| HDF5 | (any recent) | Alternative output format (BP5 is preferred) |

## Installing Dependencies

See `knowledge/entity/01b-install-methods.md` — covers 4 approaches:
- `dependencies.py` — interactive script (recommended)
- Docker — pre-built images
- Spack — HPC package manager
- Manual build from source

## Environment Check Commands

Check what's available on a machine:
```bash
cmake --version                    # CMake >= 3.16
g++ --version                      # or clang++ --version
mpicxx --version                   # MPI compiler wrapper
nvcc --version                     # CUDA toolkit
hipcc --version                    # ROCm
module avail 2>/dev/null | head    # check module system
nvidia-smi                         # GPU info (NVIDIA)
rocm-smi                           # GPU info (AMD)
```

## CMake Configuration

### Clone Repository
```bash
git clone --recursive https://github.com/entity-toolkit/entity.git
```

### Configure
```bash
cmake -B build -D pgen=<PROBLEM_GENERATOR> [OPTIONS...]
```

### All Build Options

| Option | Description | Values | Default |
|--------|-------------|--------|---------|
| `pgen` | Problem generator | Name (e.g. `reconnection`) or path | Required |
| `precision` | Floating point precision | `single`, `double` | `single` |
| `deposit` | Current deposit scheme | `zigzag`, `esirkepov` | `zigzag` |
| `shape_order` | Interpolation order (1-11) | `1`-`11` | `1` |
| `output` | Enable data output | `ON`, `OFF` | `ON` |
| `mpi` | Multi-node support | `ON`, `OFF` | `OFF` |
| `gpu_aware_mpi` | GPU-aware MPI comms | `ON`, `OFF` | `ON` |
| `DEBUG` | Debug mode | `ON`, `OFF` | `OFF` |
| `TESTS` | Compile unit tests | `ON`, `OFF` | `OFF` |

### GPU Architecture Flags

For CUDA: `-D Kokkos_ENABLE_CUDA=ON -D Kokkos_ARCH_<ARCH>=ON`

| GPU | Kokkos ARCH flag |
|-----|-----------------|
| V100 | `VOLTA70` |
| A100 | `AMPERE80` |
| H100 | `HOPPER90` |
| RTX 3090 | `AMPERE86` |
| RTX 4090 | `ADA89` |

For AMD: `-D Kokkos_ENABLE_HIP=ON -D Kokkos_ARCH_AMD_GFX90A=ON`

For CPU: `-D Kokkos_ENABLE_OPENMP=ON` (or `SERIAL`, `PTHREAD`)

Full list: https://kokkos.github.io/kokkos-core-wiki/keywords.html#architecture-keywords

### Example Configurations

CPU-only with MPI:
```bash
cmake -B build \
  -D pgen=reconnection \
  -D Kokkos_ENABLE_OPENMP=ON \
  -D mpi=ON
```

NVIDIA GPU (single node):
```bash
cmake -B build \
  -D pgen=shock \
  -D Kokkos_ENABLE_CUDA=ON \
  -D Kokkos_ARCH_AMPERE80=ON
```

AMD GPU with MPI:
```bash
cmake -B build \
  -D pgen=turbulence \
  -D Kokkos_ENABLE_HIP=ON \
  -D Kokkos_ARCH_AMD_GFX90A=ON \
  -D mpi=ON \
  -D gpu_aware_mpi=OFF
```

### Compile
```bash
cmake --build build -j $(nproc)
```
Executable is `./build/src/entity.xc`.

### Install
```bash
cmake --install build --prefix /path/to/install
```

## CUDA/Host Compiler Compatibility

CUDA versions have specific host compiler requirements. Check the [compatibility matrix](https://gist.github.com/ax3l/9489132) when using GCC with CUDA.

## Important Warnings

- **GPU-aware MPI** must be disabled on many clusters (Frontier, LUMI, DeltaAI, Aurora, Trillium)
- **Login node architecture** may differ from compute nodes — set `Kokkos_ARCH_*` for the compute node GPU
- Prefer **pre-installed system MPI/CUDA** over building your own
- **ADIOS2 compile time** is very long; pre-install it when possible
- **ADIOS2 < 2.11.0** uses `cxx11_mpi`/`cxx11` CMake targets; **ADIOS2 >= 2.11.0** uses `cxx_mpi`/`cxx`. Entity 1.4.x requires the new naming
- **Kokkos 5.x** requires C++20; cannot be compiled with C++17
