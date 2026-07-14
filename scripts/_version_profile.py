"""Shared Entity version profile logic.

Used by entity_compat.py and entity_generate.py to avoid duplicating
the supported Entity version policy.

Profile constants live in entity_schema.py (single source of truth).
"""

import sys
from typing import Any, Dict, List, Tuple

from entity_schema import PROFILES, DEFAULT_HDF5_VERSION
from entity_schema import DEFAULT_VERSION_PROFILES as _DEFAULT_VERSION_PROFILES


DEFAULT_VERSION_PROFILES = _DEFAULT_VERSION_PROFILES  # re-export
MIN_SUPPORTED_ENTITY_VERSION = (1, 4, 0)
MIN_CUDA_ENTITY_VERSION = (1, 4, 3)


def _parse_digits(version_str: str) -> List[int]:
    """Parse a version string like '1.4.0' or 'v1.4' into [major, minor, ...]."""
    digits: List[int] = []
    for part in version_str.removeprefix("v").split("."):
        part = part.strip()
        if part.isdigit():
            digits.append(int(part))
        elif part in ("x", "X", "*"):
            digits.append(0)
        else:
            break
    return digits


def _normalized_version(version: str) -> Tuple[int, int, int]:
    digits = _parse_digits(version)
    if len(digits) < 2:
        raise ValueError(f"invalid Entity version: {version}")
    return tuple((digits + [0, 0, 0])[:3])


def detect_profile_name(req: Dict[str, Any]) -> str:
    """Validate the Entity version and return the only supported profile."""
    entity = req.get("entity", {})
    if not isinstance(entity, dict):
        raise ValueError("requirements.entity is missing")

    profile = str(entity.get("dependency_profile") or "").lower()
    version = str(entity.get("version_bucket") or entity.get("version") or "").lower()
    if version:
        normalized = _normalized_version(version)
        if normalized < MIN_SUPPORTED_ENTITY_VERSION:
            raise ValueError(
                f"Entity {version} is unsupported; minimum supported version is 1.4.0"
            )

    if profile and profile != "modern":
        raise ValueError(
            f"unsupported dependency_profile={profile}; only modern is supported"
        )
    if not version and not profile:
        raise ValueError(
            "requirements.entity.version_bucket or dependency_profile is required"
        )
    return "modern"


def validate_supported_request(req: Dict[str, Any]) -> str:
    """Validate the supported Entity/dependency/C++ configuration."""
    name = detect_profile_name(req)
    compile_cfg = req.get("compile", {})
    cxx_standard = (
        str(compile_cfg.get("cxx_standard") or "")
        if isinstance(compile_cfg, dict)
        else ""
    )
    expected = str(PROFILES[name]["cxx_standard"])
    if cxx_standard and cxx_standard != expected:
        raise ValueError(
            f"unsupported compile.cxx_standard={cxx_standard}; Entity >=1.4.0 requires {expected}"
        )

    entity = req.get("entity", {})
    version = str(entity.get("version_bucket") or entity.get("version") or "").lower()
    environment = req.get("environment", {})
    backend = (
        str(environment.get("backend") or "").lower()
        if isinstance(environment, dict)
        else ""
    )
    if backend == "cuda":
        if not version:
            raise ValueError("CUDA builds require an exact Entity version >=1.4.3")
        if _normalized_version(version) < MIN_CUDA_ENTITY_VERSION:
            raise ValueError(
                f"Entity {version} supports CPU builds only; CUDA requires Entity >=1.4.3"
            )
    return name


def profile_for(req: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Return (profile_name, profile_dict) suitable for compatibility checks."""
    name = validate_supported_request(req)
    return name, PROFILES[name]


def version_profile(req: Dict[str, Any]) -> Dict[str, Any]:
    """Return the full default-version profile dict (for source-build scripts)."""
    try:
        name = validate_supported_request(req)
    except ValueError as exc:
        raise SystemExit(str(exc))
    return DEFAULT_VERSION_PROFILES[name]


def inferred_cxx_standard(req: Dict[str, Any]) -> str:
    """Derive C++ standard from requirements.compile or entity profile."""
    name = validate_supported_request(req)
    return str(PROFILES[name]["cxx_standard"])


def requested_version(req: Dict[str, Any], dep: str, profile: Dict[str, Any]) -> str:
    """Return the concrete source-build tag for *dep*.

    Consults requirements.environment.dependency_versions first, then falls
    back to the supported profile defaults.
    """
    env = req.get("environment", {})
    versions = env.get("dependency_versions", {}) if isinstance(env, dict) else {}
    if isinstance(versions, dict) and versions.get(dep):
        return str(versions[dep])

    if dep in ("mpi", "openmpi"):
        return str(versions.get("mpi") or versions.get("openmpi") or "system")
    if dep == "kokkos":
        return str(profile["kokkos_default"])
    if dep == "adios2":
        return str(profile["adios2"])
    if dep == "hdf5":
        return DEFAULT_HDF5_VERSION
    raise KeyError(dep)
