"""Single source of truth for JSON schemas, field definitions, and profile constants.

All entity-env-build scripts import their schema-level constants from here.
When a requirements.json field changes, this is the only Python file that
needs updating — scripts pick up the change through their imports.

references/json-contracts.md is the human-readable mirror of this file.
"""

import hashlib
import json
from typing import Any, Dict, List, Tuple
from pathlib import Path

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

REQUIRED_ALWAYS_V1: List[str] = [
    "entity.checkout_root",
    "entity.workdir",
]

REQUIRED_ALWAYS_V2: List[str] = [
    "entity.site_id",
    "entity.source_checkout",
    "entity.source_revision",
    "entity.build_root",
    "entity.deps_root",
]

# Kept for imports from older callers. Validation selects the version-specific
# list through required_entity_fields() below.
REQUIRED_ALWAYS: List[str] = REQUIRED_ALWAYS_V2

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
# Parameter card — compile-parameter confirmation hard gate
# ---------------------------------------------------------------------------

# Tier 1 fields block the build when they drift after confirmation; tier 2
# fields are display-level context shown with the confirmation prompt.
PARAMETER_CARD_TIER1: List[str] = [
    "compile.pgen",
    "compile.pgens",
    "environment.backend",
    "environment.gpu_arch",
    "environment.mpi",
    "environment.gpu_aware_mpi",
    "environment.output",
    "compile.precision",
    "compile.cxx_standard",
    "compile.build_intent",
]

PARAMETER_CARD_TIER2: List[str] = [
    "compile.deposit",
    "compile.shape_order",
    "compile.debug",
    "compile.tests",
    "environment.dependency_policy",
]


def _card_value(req: Dict[str, Any], dotted: str) -> Any:
    cur: Any = req
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def parameter_card(req: Dict[str, Any]) -> Dict[str, Any]:
    """Derive the build parameter card from requirements.json.

    Only fields actually present in *req* are included. The digest covers the
    fields map exactly, so any parameter change after confirmation fails the
    parameters.confirmation compatibility check.
    """
    fields: Dict[str, Dict[str, Any]] = {}
    for tier, names in ((1, PARAMETER_CARD_TIER1), (2, PARAMETER_CARD_TIER2)):
        for dotted in names:
            value = _card_value(req, dotted)
            if value is None:
                continue
            fields[dotted] = {"value": value, "tier": tier}
    digest = hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "kind": "entity-parameter-card",
        "domain": "build",
        "fields": fields,
        "digest": "sha256:" + digest,
    }


def requirements_schema(req: Dict[str, Any]) -> int:
    """Return the requirements schema; v1 is explicit legacy compatibility."""
    try:
        return int(req.get("schema_version", 1))
    except (TypeError, ValueError):
        return -1


def required_entity_fields(req: Dict[str, Any]) -> List[str]:
    return REQUIRED_ALWAYS_V1 if requirements_schema(req) == 1 else REQUIRED_ALWAYS_V2


def entity_paths(req: Dict[str, Any]) -> Dict[str, str]:
    """Resolve build-site paths without inventing a common workspace parent."""
    entity = req.get("entity", {}) if isinstance(req.get("entity"), dict) else {}
    if requirements_schema(req) == 1:
        workdir = str(entity.get("workdir") or "")
        pgen = str((req.get("compile", {}) or {}).get("pgen") or "")
        pgen_root = str(Path(workdir) / "problems" / pgen)
        return {
            "site_id": str(entity.get("site_id") or "legacy-local"),
            "source_checkout": str(entity.get("checkout_root") or ""),
            "build_root": str(Path(pgen_root) / "build"),
            "deps_root": str(Path(workdir) / "deps"),
            "artifacts_root": str(Path(pgen_root) / "_build"),
        }
    build_root = str(entity.get("build_root") or "")
    return {
        "site_id": str(entity.get("site_id") or ""),
        "source_checkout": str(entity.get("source_checkout") or ""),
        "build_root": build_root,
        "deps_root": str(entity.get("deps_root") or ""),
        "artifacts_root": str(entity.get("artifacts_root") or (Path(build_root) / "_artifacts")),
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
    "cc",
    "cxx",
    "host_cxx",
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

# Minimum OpenMPI version when the selected MPI is OpenMPI. Older 4.x
# releases have known ORTE/PMI launch failures under srun on several sites.
MIN_OPENMPI_VERSION = (5, 0)


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
    "parameters.confirmation": "parameters_confirmation_override",
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
