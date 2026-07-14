# Entity: Dependency Installation Methods (Archived)

## Method 1: `dependencies.py` (Recommended, v1.4.0+)

Python script in repo root. Requires Python >= 3.7.
```bash
./dependencies.py
```
Terminal UI collects configuration choices (Kokkos backend, GPU arch, MPI mode), generates `$HOME/.entity/install.sh`. Running that script compiles all dependencies into `$HOME/.entity/`, with module files at `$HOME/.entity/modules/`. Load with:
```bash
module use --append $HOME/.entity/modules
```

Default versions targeted: Kokkos 5.0.1, ADIOS2 2.11.0.

## Method 2: Docker

Pre-built images on Docker Hub: `morninbru/entity:<tag>`

Available tags:
- `cuda` — gcc 11.4 + CUDA 12.2, with GPU runtime (4.55 GB)
- `cuda-compilers` — same, no GPU runtime needed
- `rocm` — gcc 9.4 + ROCm 6.1.2 (1.75 GB)
- `rocm-compilers` — same, no GPU runtime needed

Usage:
```bash
docker compose run entity-<tag>
```
Mounts current directory as home inside container. Port 8080 forwarded for Jupyter. NVIDIA GPUs require [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

Manual build from Dockerfiles:
```bash
docker build --no-cache -t myentity:<toolkit> -f dev/Dockerfile.<toolkit> .
docker run -it --runtime=nvidia --gpus all -p 8080:8080 -v "$(pwd)":/home/myentity/ myentity:<tag>
```
For AMD GPUs, replace `--runtime=nvidia --gpus all` with `--device /dev/kfd --device /dev/dri --security-opt seccomp=unconfined`.

## Method 3: Spack

```bash
git clone https://github.com/spack/spack.git
source spack/share/spack/setup-env.sh
spack compiler add
spack external find
spack env create entity-env && spack env activate entity-env

# Install dependencies within environment
spack install --add hdf5 +cxx
spack install --add adios2 +hdf5 +pic
spack install --add kokkos +cuda +wrapper cuda_arch=80 +pic +aggressive_vectorization
```

Key tips:
- Always run `spack spec <PACKAGE>` before installing to verify configuration
- Use `%clang` to target specific compilers
- Strongly prefer pre-installed system MPI/CUDA over building through Spack
- Set `concretizer:targets:host_compatible:false` if login node differs from compute node
- Use `spack gc` for build cache cleanup

## Method 4: Manual Build from Source

### OpenMPI
Download from open-mpi.org, configure with `--prefix`, `make -j`, `make install`.

### Kokkos
```bash
git clone https://github.com/kokkos/kokkos.git
cmake -B build -D CMAKE_INSTALL_PREFIX=<prefix> \
  -D Kokkos_ENABLE_CUDA=ON \        # or Kokkos_ENABLE_OPENMP=ON for CPU
  -D Kokkos_ARCH_AMPERE80=ON \      # A100; see Kokkos arch keywords
  -D Kokkos_ENABLE_PIC=ON
cmake --build build -j $(nproc) && cmake --install build
```

### ADIOS2
```bash
git clone https://github.com/ornladios/ADIOS2.git
cmake -B build -D CMAKE_INSTALL_PREFIX=<prefix> \
  -D ADIOS2_USE_HDF5=ON -D ADIOS2_USE_MPI=ON \
  -D ADIOS2_USE_CUDA=ON              # optional
cmake --build build -j $(nproc) && cmake --install build
```

**ADIOS2 CMake target name change (v2.10.x → v2.11.x)**:
- Old: `adios2::cxx11_mpi` / `adios2::cxx11`
- New: `adios2::cxx_mpi` / `adios2::cxx`
- Entity 1.4.x expects the new naming. If linking against an older ADIOS2 < 2.11, this will fail.
