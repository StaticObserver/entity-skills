# HDF5 Build Notes

## Version Policy

HDF5 version is **1.14.6** for all profiles. Can be overridden via `requirements.environment.dependency_versions.hdf5`.

## CMake Options

```
-DCMAKE_INSTALL_PREFIX="$PREFIX"
-DHDF5_BUILD_CPP_LIB=ON
-DHDF5_ENABLE_PARALLEL=ON     # only when MPI=ON
-DHDF5_ENABLE_PARALLEL=OFF    # when MPI=OFF
```

HDF5 is the simplest of the three source-build dependencies. Rarely causes issues.

## Known Issues

### MPI/Serial Mode Mismatch
- Symptom: Link errors when ADIOS2 expects MPI HDF5 but HDF5 was built serial
- Trigger: `requirements.environment.mpi` changed after HDF5 build
- Fix: Rebuild HDF5 with the correct `HDF5_ENABLE_PARALLEL` setting. HDF5 cannot switch MPI mode without rebuild.

### HDF5 Version Tag Format
- Symptom: git clone fails with "branch not found"
- Trigger: HDF5 uses `hdf5_X.Y.Z` tag format (e.g., `hdf5_1.14.6`)
- Fix: The generated build script handles this already.

## Post-Build Validation

Expected install structure:
```
<prefix>/
├── bin/
├── include/hdf5.h
├── lib/
│   ├── libhdf5.a (or .so)
│   └── libhdf5_cpp.a (or .so)
└── cmake/hdf5-config.cmake     ← Must exist
```

Verify:
```bash
ls <prefix>/cmake/hdf5-config.cmake
ls <prefix>/include/hdf5.h
```
