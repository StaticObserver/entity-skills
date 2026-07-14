"""Single source of truth for JSON schemas, field definitions, and profile constants.

All entity-env-build scripts import their schema-level constants from here.
When a requirements.json field changes, this is the only Python file that
needs updating — scripts pick up the change through their imports.

references/json-contracts.md is the human-readable mirror of this file.
"""

from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Version profiles (moved from _version_profile.py)
# ---------------------------------------------------------------------------

PROFILES: Dict[str, Dict[str, Any]] = {
    "modern": {
        "cxx_standard": "20",
        "kokkos": "5.",
        "adios2": "2.11.",
        "adios2_uses_kokkos": True,
    },
}

DEFAULT_VERSION_PROFILES: Dict[str, Dict[str, Any]] = {
    "modern": {
        "name": "modern",
        "cxx_standard": "20",
        "kokkos_family": "5.x",
        "kokkos_default": "5.0.1",
        "adios2_family": "2.11.x",
        "adios2": "2.11.0",
        "adios2_uses_kokkos": True,
    },
}

DEFAULT_HDF5_VERSION = "1.14.6"


# ---------------------------------------------------------------------------
# requirements.json — Required fields by build phase
# ---------------------------------------------------------------------------

REQUIRED_ALWAYS: List[str] = [
    "entity.checkout_root",
    "entity.workdir",
]

REQUIRED_BUILD: List[str] = [
    "compile.pgen",
    "environment.backend",
]

# ---------------------------------------------------------------------------
# requirements.json — Defaults for optional fields
# ---------------------------------------------------------------------------

OPTIONAL_DEFAULTS: Dict[str, str] = {
    "entity.dependency_profile": "auto-detect from entity.version_bucket",
    "environment.output": "true",
    "environment.mpi": "false",
    "environment.gpu_aware_mpi": "false",
    "compile.precision": "single",
    "compile.deposit": "zigzag",
    "compile.shape_order": "1",
    "compile.debug": "false",
    "compile.tests": "false",
    "compile.build_intent": "unspecified",
    "compile.cxx_standard": "profile-derived",
}

# ---------------------------------------------------------------------------
# requirements.json — Consistency rules
# ---------------------------------------------------------------------------

# (rule_id, condition_tuple, field_pair, message)
ConsistencyRule = tuple  # (str, tuple | None, tuple, str)

CONSISTENCY_RULES: List[ConsistencyRule] = [
    ("pgen.mutex", None, ("compile.pgen", "compile.pgens"),
     "compile.pgen and compile.pgens are mutually exclusive. Use one."),
    ("output.requires_policy", ("environment.output", "true"), ("environment.dependency_policy", None),
     "environment.output=true requires environment.dependency_policy to be set (covers ADIOS2 + HDF5)."),
    ("cuda.requires_cxx", ("environment.backend", "cuda"), ("compile.cxx_standard", None),
     "CUDA backend requires compile.cxx_standard to be set (must match the Entity version profile)."),
    ("hip.requires_cxx", ("environment.backend", "hip"), ("compile.cxx_standard", None),
     "HIP backend requires compile.cxx_standard to be set (must match the Entity version profile)."),
]

# ---------------------------------------------------------------------------
# entity-deps.local.json — Dependency entry shape
# ---------------------------------------------------------------------------

DEPENDENCY_ENTRY_KEYS: List[str] = [
    "name",
    "version",
    "provider",
    "prefix",
    "bin",
    "include",
    "lib",
    "cmake_config",
    "compiler_signature",
    "mpi_signature",
    "environment",
    "compile_config",
    "validation",
]

# ---------------------------------------------------------------------------
# Compile options → CMake flag mapping
# ---------------------------------------------------------------------------

# Maps requirements.compile field → CMake -D flag.
# Used by entity_generate.py to derive cmake options without hardcoding.
CMAKE_BOOL_MAP: Dict[str, str] = {
    "debug": "DEBUG",
    "tests": "TESTS",
}

CMAKE_VALUE_MAP: Dict[str, str] = {
    "precision": "precision",
    "deposit": "deposit",
    "shape_order": "shape_order",
}

# Environment-level CMake flags (from requirements.environment)
CMAKE_ENV_MAP: Dict[str, str] = {
    "output": "output",
    "mpi": "mpi",
    "gpu_aware_mpi": "gpu_aware_mpi",
}

# Backend → Kokkos CMake flags
KOKKOS_BACKEND_FLAGS: Dict[str, str] = {
    "cuda": "Kokkos_ENABLE_CUDA",
    "hip": "Kokkos_ENABLE_HIP",
    "cpu": "Kokkos_ENABLE_OPENMP",
}

# ---------------------------------------------------------------------------
# Minimum compiler versions by backend + profile
# ---------------------------------------------------------------------------

# (major, minor) tuples. None means "not required".
CompilerMinVersions = Dict[str, Dict[str, Dict[str, Any]]]

COMPILER_MIN_VERSIONS: CompilerMinVersions = {
    "cpu": {
        "modern": {"gcc": (10, 4), "clang": (12, 0)},
    },
    "cuda": {
        "modern": {"gcc": (10, 4), "nvcc": (12, 2), "clang": (12, 0)},
    },
    "hip": {
        "modern": {"gcc": (10, 4), "rocm": (5, 4), "clang": (14, 0)},
    },
}

# Minimum CMake version required across all profiles
MIN_CMAKE_VERSION = (3, 16)


# ---------------------------------------------------------------------------
# Known-bad compiler versions — blacklist that triggers WARN before build
# ---------------------------------------------------------------------------

CompilerKnownBad = Dict[str, List[Tuple[int, int, int]]]

COMPILER_KNOWN_BAD: CompilerKnownBad = {
    "gcc": [
        (12, 2, 0),  # ICE: internal compiler error in tsubst_copy (cp/pt.cc:17004)
                      # Trigger: if constexpr in template code, Entity 1.4.3+ framework
                      # Fix: use GCC 13.3+ or 11.x
    ],
}


def version_satisfies(actual: tuple, minimum: tuple) -> bool:
    """Check if *actual* version tuple satisfies *minimum* version tuple."""
    return actual >= minimum


# ---------------------------------------------------------------------------
# Compat check override map — decisions overrides that downgrade fail→warn
# ---------------------------------------------------------------------------

# Map compat check IDs → decisions override field names.
# When a compat check fails but user has explicitly acknowledged the risk,
# the matching decisions entry downgrades failure to a warning.
# Override value must be truthy (non-empty string, true bool, or dict with
# confirmed_at/value/source).
COMPAT_OVERRIDE_MAP: Dict[str, str] = {
    "compiler.version.nvcc": "nvcc_version_override",
}


def override_satisfies(override_value: Any) -> bool:
    """Check whether a decisions override entry is valid (user confirmed)."""
    if override_value is None:
        return False
    if isinstance(override_value, bool):
        return override_value
    if isinstance(override_value, dict):
        return bool(
            override_value.get("value")
            or override_value.get("confirmed_at")
            or override_value.get("source")
        )
    return bool(override_value)


# ---------------------------------------------------------------------------
# source-build dependency list (order matters)
# ---------------------------------------------------------------------------

SOURCE_BUILD_DEPENDENCIES: List[str] = ["kokkos", "hdf5", "adios2"]
OPTIONAL_SOURCE_DEPENDENCIES: List[str] = ["mpi"]
