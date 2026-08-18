#!/usr/bin/env python3
"""Check whether entity-deps.local.json satisfies requirements.json.

Implements checks described in references/compatibility-check.md.
Sections referenced in comments map to that document.

Renamed from check_compatibility.py — logic unchanged.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _json_io import add_json_flag, get_dotted, load_json, protocol_error, protocol_ok, write_json_atomic
from _version_profile import profile_for, detect_profile_name
from entity_state import record_step
from entity_schema import (
    COMPILER_MIN_VERSIONS,
    MIN_CMAKE_VERSION,
    MIN_OPENMPI_VERSION,
    COMPAT_OVERRIDE_MAP,
    entity_paths,
    override_satisfies,
    parameter_card,
    version_satisfies,
    COMPILER_KNOWN_BAD,
)


SUPPORTED_SCHEMA_VERSIONS = {1, 2}
CHECKER_VERSION = 1


class IssueList(List[str]):
    """Issue strings that remember which check produced each one.

    Plain append() records an empty check id; append_for() records the
    owning check so _apply_overrides can remove exactly the overridden
    check's issues instead of substring-matching issue text.
    """

    def __init__(self) -> None:
        super().__init__()
        self.check_ids: List[str] = []

    def append(self, text: str) -> None:
        self.check_ids.append("")
        super().append(text)

    def append_for(self, check_id: str, text: str) -> None:
        self.check_ids.append(check_id)
        super().append(text)


def _append_issue(issues: List[str], check_id: str, text: str) -> None:
    """Append *text* tagged with its owning *check_id* when supported."""
    if isinstance(issues, IssueList):
        issues.append_for(check_id, text)
    else:
        issues.append(text)


def compatibility_coverage() -> Dict[str, str]:
    """Return the implemented coverage map for the compatibility contract."""
    return {
        "schema_version": "implemented",
        "requirements_checkpoint_match": "implemented",
        "dependency_path_existence": "implemented",
        "compiler_executable": "implemented",
        "version_profile": "implemented",
        "cuda_nvcc_wrapper": "implemented",
        "adios2_kokkos_profile": "implemented",
        "source_build_install_evidence": "implemented",
        "compiler_signature": "partial",
        "gpu_arch_match": "partial",
        "mpi_output_mode": "partial",
        "path_list_existence": "not_implemented",
        "cmake_package_probe": "not_implemented",
    }


def add(
    checks: List[Dict[str, Any]],
    check_id: str,
    status: str,
    summary: str,
    evidence: Optional[Dict[str, Any]] = None,
    remediation: str = "",
) -> None:
    checks.append(
        {
            "id": check_id,
            "status": status,
            "summary": summary,
            "evidence": evidence or {},
            "remediation": remediation,
        }
    )


def _same_request_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        actual_bool = str(actual).lower() in {"true", "1", "yes"}
        expected_bool = str(expected).lower() in {"true", "1", "yes"}
        return actual_bool == expected_bool
    return actual == expected


REQUEST_SNAPSHOT_FIELDS = [
    "entity.site_id",
    "entity.source_checkout",
    "entity.source_revision",
    "entity.build_root",
    "entity.deps_root",
    "entity.artifacts_root",
    "entity.checkout_root",
    "entity.workdir",
    "entity.version_bucket",
    "entity.dependency_profile",
    "environment.backend",
    "environment.output",
    "environment.mpi",
    "environment.gpu_aware_mpi",
    "compile.pgen",
    "compile.pgens",
    "compile.cxx_standard",
    "compile.precision",
    "compile.deposit",
    "compile.shape_order",
    "compile.debug",
    "compile.tests",
    "compile.build_intent",
]


# ---------------------------------------------------------------------------
# Path / file-system validation helpers
# ---------------------------------------------------------------------------


def _real_path(value: Any) -> Optional[Path]:
    """Return a Path if *value* is a non-empty string, otherwise None."""
    if value and isinstance(value, str):
        return Path(value)
    return None


def validate_dependency_paths(
    checks: List[Dict[str, Any]],
    issues: List[str],
    dep: str,
    entry: Dict[str, Any],
) -> bool:
    """Verify that recorded prefix / cmake_config / bin paths exist on disk.

    Returns True when at least one usable path is confirmed.
    """
    prefix = _real_path(entry.get("prefix"))
    cmake_config = _real_path(entry.get("cmake_config"))
    bin_path = _real_path(entry.get("bin"))

    prefix_ok = prefix is not None and prefix.is_dir()
    config_ok = cmake_config is not None and cmake_config.is_file()
    bin_ok = bin_path is not None and bin_path.exists()

    missing: List[str] = []

    if prefix is not None and not prefix_ok:
        missing.append(f"prefix: {prefix}")
    if cmake_config is not None and not config_ok:
        missing.append(f"cmake_config: {cmake_config}")
    if bin_path is not None and not bin_ok:
        missing.append(f"bin: {bin_path}")

    if missing:
        add(
            checks,
            f"dependency.{dep}.paths",
            "fail",
            f"{dep}: recorded paths do not exist on disk",
            {"missing_paths": missing},
            remediation=f"Verify {dep} is installed at the recorded paths, "
            f"or update entity-deps.local.json selected.{dep} with correct paths.",
        )
        issues.append(f"{dep}: recorded paths do not exist on disk -- {', '.join(missing)}")
        return False

    # At least one path exists
    usable = prefix_ok or config_ok or bin_ok
    if not usable:
        add(
            checks,
            f"dependency.{dep}.paths",
            "fail",
            f"{dep}: no usable paths recorded (prefix/cmake_config/bin all empty)",
            {},
            remediation=f"Add prefix, cmake_config, or bin to selected.{dep} in entity-deps.local.json.",
        )
        issues.append(f"{dep}: no usable paths recorded")
        return False

    add(
        checks,
        f"dependency.{dep}.paths",
        "pass",
        f"{dep}: recorded paths exist on disk",
        {"prefix_ok": prefix_ok, "cmake_config_ok": config_ok, "bin_ok": bin_ok},
    )
    return True


def validate_compiler_executable(
    checks: List[Dict[str, Any]],
    issues: List[str],
    compiler: Dict[str, Any],
) -> bool:
    """Check that compiler.cxx (and .cc if present) exist and are executable."""
    ok = True
    has_any_key = False
    for key, label in (("cxx", "CXX"), ("cc", "CC")):
        path_str = str(compiler.get(key) or "")
        if not path_str:
            continue
        has_any_key = True
        p = Path(path_str)
        if not p.exists():
            add(
                checks,
                f"compiler.{key}.exists",
                "fail",
                f"{label} compiler path does not exist: {p}",
                {"path": path_str},
                remediation=f"Install or locate the correct {label} compiler and update selected.compiler.{key}.",
            )
            issues.append(f"{label} compiler path does not exist: {p}")
            ok = False
        elif not os.access(str(p), os.X_OK):
            add(
                checks,
                f"compiler.{key}.executable",
                "fail",
                f"{label} path is not executable: {p}",
                {"path": path_str},
                remediation=f"Ensure {p} has execute permission.",
            )
            issues.append(f"{label} is not executable: {p}")
            ok = False
    if not has_any_key:
        add(
            checks,
            "compiler.executable",
            "fail",
            "No compiler keys (cxx/cc) found in selected.compiler entry",
            {},
            remediation="Add cxx field to selected.compiler in entity-deps.local.json.",
        )
        issues.append("No compiler keys (cxx/cc) in selected.compiler")
        ok = False
    elif ok:
        add(
            checks,
            "compiler.executable",
            "pass",
            "Compiler paths exist and are executable",
            {},
        )
    return ok


# ---------------------------------------------------------------------------
# Compatibility helpers
# ---------------------------------------------------------------------------


def selected_version(checkpoint: Dict[str, Any], dep: str) -> str:
    selected = checkpoint.get("selected", {})
    if isinstance(selected, dict) and isinstance(selected.get(dep), dict):
        version = selected[dep].get("version")
        if version:
            return str(version).lstrip("v")
    scripts = checkpoint.get("build_scripts", {}).get("scripts", {})
    if isinstance(scripts, dict) and isinstance(scripts.get(dep), dict):
        version = scripts[dep].get("version")
        if version:
            return str(version).lstrip("v")
    return ""


def adios2_uses_kokkos(checkpoint: Dict[str, Any]) -> Optional[bool]:
    selected = checkpoint.get("selected", {})
    adios2 = selected.get("adios2", {}) if isinstance(selected, dict) else {}
    if isinstance(adios2, dict):
        cfg = adios2.get("compile_config", {})
        if isinstance(cfg, dict):
            value = cfg.get("ADIOS2_USE_Kokkos", cfg.get("adios2_uses_kokkos"))
            if value is not None:
                return str(value).lower() in {"on", "true", "1", "yes"}
    scripts = checkpoint.get("build_scripts", {}).get("scripts", {})
    if isinstance(scripts, dict) and isinstance(scripts.get("adios2"), dict):
        value = scripts["adios2"].get("adios2_uses_kokkos")
        if value is not None:
            return str(value).lower() in {"on", "true", "1", "yes"}
    return None


def selected_entry(checkpoint: Dict[str, Any], dep: str) -> Dict[str, Any]:
    selected = checkpoint.get("selected", {})
    if isinstance(selected, dict) and isinstance(selected.get(dep), dict):
        return selected[dep]
    return {}


def has_installed_dependency(checkpoint: Dict[str, Any], dep: str) -> bool:
    """Return True when *dep* has a usable entry with existing paths."""
    entry = selected_entry(checkpoint, dep)
    if not entry:
        return False
    if entry.get("provider") == "source-build" and not entry.get("validation", {}).get(
        "installed"
    ):
        return False
    return bool(entry.get("prefix") or entry.get("cmake_config") or entry.get("bin"))


# ---------------------------------------------------------------------------
# Parameter confirmation hard gate
# ---------------------------------------------------------------------------


def _check_parameters_confirmation(
    checks: List[Dict[str, Any]],
    issues: List[str],
    req: Dict[str, Any],
    checkpoint: Dict[str, Any],
) -> None:
    """Require a recorded parameter confirmation matching the current request."""
    decisions = checkpoint.get("decisions", {})
    record = decisions.get("parameters") if isinstance(decisions, dict) else None
    if not isinstance(record, dict) or not record.get("digest"):
        add(
            checks,
            "parameters.confirmation",
            "fail",
            "Compile parameters have not been confirmed for this checkpoint",
            {},
            remediation="run entity_checkpoint.py confirm <requirements> "
            "--checkpoint <checkpoint> --by <actor>",
        )
        _append_issue(issues, "parameters.confirmation",
                      "compile parameters have no confirmation record")
        return

    expected = parameter_card(req)["digest"]
    actual = str(record.get("digest") or "")
    if actual != expected:
        add(
            checks,
            "parameters.confirmation",
            "fail",
            "Compile parameters changed after confirmation",
            {"confirmed_digest": actual, "current_digest": expected},
            remediation="run entity_checkpoint.py confirm <requirements> "
            "--checkpoint <checkpoint> --by <actor> to re-confirm the changed parameters",
        )
        _append_issue(issues, "parameters.confirmation",
                      "compile parameters changed after confirmation")
        return

    add(
        checks,
        "parameters.confirmation",
        "pass",
        "Compile parameters confirmed for the current requirements",
        {
            "digest": expected,
            "confirmed_by": str(record.get("confirmed_by") or ""),
            "confirmed_at": str(record.get("confirmed_at") or ""),
        },
    )


# ---------------------------------------------------------------------------
# Cross-dependency toolchain consistency helpers
# ---------------------------------------------------------------------------


def _read_cmake_config_var(cmake_config_path: Path, var_name: str) -> Optional[str]:
    """Extract a set() variable value from a CMake config file."""
    if not cmake_config_path.is_file():
        return None
    try:
        text = cmake_config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    pat = re.compile(
        rf"^\s*set\s*\(\s*{re.escape(var_name)}\s+(?:\"([^\"]*)\"|(\S+))\s*\)",
        re.MULTILINE,
    )
    m = pat.search(text)
    if m:
        return m.group(1) or m.group(2)
    return None


def _cross_check_kokkos_compiler(
    checks: List[Dict[str, Any]],
    issues: List[str],
    kokkos_entry: Dict[str, Any],
    compiler: Dict[str, Any],
) -> None:
    """Verify Kokkos was built with a compiler ABI-compatible with selected compiler."""
    kokkos_config = _real_path(
        kokkos_entry.get("cmake_config")
    ) or _real_path(
        str(Path(str(kokkos_entry.get("prefix", ""))) / "lib64" / "cmake" / "Kokkos" / "KokkosConfig.cmake")
    )

    if kokkos_config is None or not kokkos_config.is_file():
        add(
            checks,
            "cross.kokkos_compiler_consistency",
            "warn",
            "Cannot read Kokkos CMake config to verify compiler consistency",
            {},
            remediation="Verify manually that Kokkos was built with the same compiler family (GCC/Clang/hipcc) selected for Entity.",
        )
        return

    kokkos_cxx = _read_cmake_config_var(kokkos_config, "CMAKE_CXX_COMPILER")
    if kokkos_cxx is None:
        add(
            checks,
            "cross.kokkos_compiler_consistency",
            "warn",
            "Kokkos CMake config found but CMAKE_CXX_COMPILER not recorded",
            {"kokkos_config": str(kokkos_config)},
            remediation="Verify manually that Kokkos was built with the same compiler family selected for Entity.",
        )
        return

    selected_cxx = str(compiler.get("cxx") or compiler.get("cpp") or "")
    kokkos_cxx_basename = Path(kokkos_cxx).name
    selected_cxx_basename = Path(selected_cxx).name if selected_cxx else ""

    # Classify each compiler as CUDA wrapper, HIP compiler, or regular C++
    def _classify(name: str) -> str:
        if "nvcc_wrapper" in name:
            return "cuda_wrapper"
        if "hipcc" in name:
            return "hipcc"
        return "host"

    kokkos_class = _classify(kokkos_cxx_basename)
    selected_class = _classify(selected_cxx_basename)

    incompatible = kokkos_class != selected_class

    if incompatible:
        add(
            checks,
            "cross.kokkos_compiler_consistency",
            "fail",
            f"Kokkos was built with {kokkos_cxx_basename} ({kokkos_class}) but Entity will use {selected_cxx_basename} ({selected_class}) — likely ABI incompatible",
            {
                "kokkos_compiler": kokkos_cxx,
                "kokkos_toolchain": kokkos_class,
                "selected_compiler": selected_cxx,
                "selected_toolchain": selected_class,
            },
            remediation=f"Either rebuild Kokkos with {selected_cxx_basename} or select a compiler matching Kokkos's {kokkos_cxx_basename} toolchain.",
        )
        issues.append(
            f"Kokkos compiler ({kokkos_cxx_basename}, {kokkos_class}) incompatible with selected compiler ({selected_cxx_basename}, {selected_class})"
        )
    else:
        add(
            checks,
            "cross.kokkos_compiler_consistency",
            "pass",
            f"Kokkos and Entity use compatible compiler family ({kokkos_cxx_basename})",
            {"kokkos_compiler": kokkos_cxx, "selected_compiler": selected_cxx},
        )


def _cross_check_gpu_toolkit_consistency(
    checks: List[Dict[str, Any]],
    issues: List[str],
    kokkos_entry: Dict[str, Any],
    gpu_toolkit: Dict[str, Any],
    backend: str,
) -> None:
    """Verify GPU toolkit version used to build Kokkos matches selected toolkit."""
    if backend not in ("hip", "cuda"):
        return

    kokkos_config = _real_path(
        kokkos_entry.get("cmake_config")
    ) or _real_path(
        str(Path(str(kokkos_entry.get("prefix", ""))) / "lib64" / "cmake" / "Kokkos" / "KokkosConfig.cmake")
    )

    if kokkos_config is None or not kokkos_config.is_file():
        return

    gpu_prefix = str(gpu_toolkit.get("prefix") or "")

    if backend == "hip":
        kokkos_rocm = _read_cmake_config_var(kokkos_config, "ROCM_PATH")
        if kokkos_rocm and gpu_prefix:
            kokkos_rocm_path = Path(kokkos_rocm).resolve()
            gpu_prefix_path = Path(gpu_prefix).resolve()
            if kokkos_rocm_path != gpu_prefix_path:
                add(
                    checks,
                    "cross.gpu_toolkit_consistency",
                    "fail",
                    f"Kokkos was built with ROCM_PATH={kokkos_rocm} but selected gpu_toolkit prefix is {gpu_prefix} — DTK version mismatch will cause link errors",
                    {
                        "kokkos_rocm_path": str(kokkos_rocm_path),
                        "gpu_toolkit_prefix": str(gpu_prefix_path),
                    },
                    remediation=f"Either select gpu_toolkit at {kokkos_rocm} to match Kokkos, or rebuild Kokkos with the selected toolkit.",
                )
                issues.append(
                    f"Kokkos DTK/ROCm version ({kokkos_rocm}) differs from selected gpu_toolkit ({gpu_prefix})"
                )
            else:
                add(
                    checks,
                    "cross.gpu_toolkit_consistency",
                    "pass",
                    "Kokkos and selected gpu_toolkit use the same ROCm/DTK installation",
                    {"rocm_path": kokkos_rocm},
                )
        elif kokkos_rocm and not gpu_prefix:
            add(
                checks,
                "cross.gpu_toolkit_consistency",
                "warn",
                f"Kokkos expects ROCM_PATH={kokkos_rocm} but no gpu_toolkit is explicitly selected — ensure {kokkos_rocm} is available",
                {"kokkos_rocm_path": kokkos_rocm},
                remediation="Add gpu_toolkit entry to entity-deps.local.json with the matching ROCm prefix.",
            )


def _cross_check_mpi_consistency(
    checks: List[Dict[str, Any]],
    issues: List[str],
    mpi_entry: Dict[str, Any],
    adios2_entry: Dict[str, Any],
    hdf5_entry: Dict[str, Any],
    env: Dict[str, Any],
) -> None:
    """Check that MPI implementation is consistent across ADIOS2 and HDF5."""
    if not isinstance(env, dict) or not env.get("mpi"):
        return

    mpi_prefix = str(mpi_entry.get("prefix") or "")
    if not mpi_prefix:
        return

    mpi_lib = Path(mpi_prefix) / "lib" / "libmpi.so"
    if not mpi_lib.exists():
        mpi_lib = Path(mpi_prefix) / "lib64" / "libmpi.so"

    mpi_real = ""
    try:
        mpi_real = str(mpi_lib.resolve())
    except OSError:
        pass

    for dep_name, dep_entry in (("adios2", adios2_entry), ("hdf5", hdf5_entry)):
        if not dep_entry:
            continue
        dep_mpi = str(dep_entry.get("mpi_provider") or dep_entry.get("mpi_prefix") or "")
        if dep_mpi and dep_mpi != mpi_prefix and str(Path(dep_mpi).resolve()) != mpi_real:
            add(
                checks,
                f"cross.mpi_{dep_name}_consistency",
                "fail",
                f"{dep_name} was built with MPI at {dep_mpi} but selected MPI is at {mpi_prefix} — may cause symbol conflicts",
                {
                    "mpi_selected": mpi_prefix,
                    f"{dep_name}_mpi": dep_mpi,
                },
                remediation=f"Rebuild {dep_name} with the selected MPI, or select the MPI that {dep_name} was built with.",
            )
            issues.append(f"{dep_name} MPI mismatch with selected MPI")


def _mpi_entry_is_openmpi(name: str, entry: Dict[str, Any]) -> bool:
    if name == "openmpi":
        return True
    for field in ("flavor", "implementation", "mpi_implementation", "provider", "name"):
        value = str(entry.get(field) or "").lower().replace(" ", "")
        if "openmpi" in value:
            return True
    return False


def _check_openmpi_min_version(
    checks: List[Dict[str, Any]],
    issues: List[str],
    mpi_name: str,
    mpi_entry: Dict[str, Any],
) -> None:
    """Require OpenMPI >= MIN_OPENMPI_VERSION when the selected MPI is OpenMPI."""
    if not _mpi_entry_is_openmpi(mpi_name, mpi_entry):
        return
    raw = str(mpi_entry.get("version") or "")
    version = _parse_version_pair(raw)
    if not raw or version <= (0, 0):
        add(
            checks,
            "mpi.openmpi_min_version",
            "warn",
            "Selected MPI is OpenMPI but no version is recorded; cannot verify "
            "the >= %d.%d minimum" % MIN_OPENMPI_VERSION,
            {},
            remediation="Record selected.mpi.version and re-run the compatibility check.",
        )
        return
    if not version_satisfies(version, MIN_OPENMPI_VERSION):
        msg = (
            f"OpenMPI {version[0]}.{version[1]} is below minimum "
            f"{MIN_OPENMPI_VERSION[0]}.{MIN_OPENMPI_VERSION[1]} — older OpenMPI "
            "releases have known ORTE/PMI launch failures under srun"
        )
        add(
            checks,
            "mpi.openmpi_min_version",
            "fail",
            msg,
            {"actual": list(version), "required": list(MIN_OPENMPI_VERSION)},
            remediation=(
                f"Select or build OpenMPI {MIN_OPENMPI_VERSION[0]}."
                f"{MIN_OPENMPI_VERSION[1]}+ and update entity-deps.local.json."
            ),
        )
        issues.append(msg)
        return
    add(
        checks,
        "mpi.openmpi_min_version",
        "pass",
        f"OpenMPI {version[0]}.{version[1]} satisfies the minimum",
        {"actual": list(version), "required": list(MIN_OPENMPI_VERSION)},
    )


def run_cross_checks(
    checks: List[Dict[str, Any]],
    issues: List[str],
    req: Dict[str, Any],
    checkpoint: Dict[str, Any],
) -> None:
    """Run cross-dependency toolchain consistency checks."""
    selected = checkpoint.get("selected", {})
    if not isinstance(selected, dict):
        return

    kokkos = selected.get("kokkos", {})
    compiler = selected.get("compiler", {})
    gpu_toolkit = selected.get("gpu_toolkit", {})
    mpi_entry = selected.get("mpi", {})
    adios2_entry = selected.get("adios2", {})
    hdf5_entry = selected.get("hdf5", {})

    env = req.get("environment", {})
    backend = str(env.get("backend") or "cpu").lower() if isinstance(env, dict) else "cpu"

    if isinstance(kokkos, dict) and kokkos:
        if isinstance(compiler, dict) and compiler:
            _cross_check_kokkos_compiler(checks, issues, kokkos, compiler)

        if backend in ("hip", "cuda") and isinstance(gpu_toolkit, dict) and gpu_toolkit:
            _cross_check_gpu_toolkit_consistency(checks, issues, kokkos, gpu_toolkit, backend)

    if isinstance(mpi_entry, dict) and mpi_entry:
        _cross_check_mpi_consistency(
            checks, issues, mpi_entry, adios2_entry, hdf5_entry, env,
        )

    if isinstance(env, dict) and env.get("mpi"):
        for mpi_name in ("mpi", "openmpi"):
            entry = selected.get(mpi_name, {})
            if not isinstance(entry, dict) or not entry:
                continue
            if mpi_name == "openmpi" and entry is selected.get("mpi"):
                continue
            _check_openmpi_min_version(checks, issues, mpi_name, entry)


# ---------------------------------------------------------------------------
# Compiler version pre-check
# ---------------------------------------------------------------------------


def _parse_version_pair(version_str: str) -> tuple:
    """Extract (major, minor) from GCC version string like '12.3.0'."""
    import re as _re
    m = _re.search(r"(\d+)\.(\d+)", version_str)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (0, 0)


def _check_compiler_min_versions(
    checks: List[Dict[str, Any]],
    issues: List[str],
    compiler: Dict[str, Any],
    checkpoint: Dict[str, Any],
    req: Dict[str, Any],
) -> None:
    """Check that selected compiler versions satisfy profile+backend minimums."""
    env = req.get("environment", {}) if isinstance(req.get("environment"), dict) else {}
    backend = str(env.get("backend") or "cpu").lower()
    profile_name = detect_profile_name(req)
    required = COMPILER_MIN_VERSIONS.get(backend, {}).get(profile_name, {})
    if not required:
        return

    selected = checkpoint.get("selected", {}) if isinstance(checkpoint.get("selected"), dict) else {}
    compiler_ver = str(compiler.get("version") or "")
    compiler_version = _parse_version_pair(compiler_ver)

    # Check GCC version
    if "gcc" in required and compiler_version > (0, 0):
        min_gcc = required["gcc"]
        if not version_satisfies(compiler_version, min_gcc):
            msg = (
                f"GCC {compiler_version[0]}.{compiler_version[1]} is below minimum "
                f"{min_gcc[0]}.{min_gcc[1]} for {backend}/{profile_name}"
            )
            add(checks, "compiler.version.gcc", "fail", msg,
                {"actual": list(compiler_version), "required": list(min_gcc)},
                remediation=f"Upgrade GCC to {min_gcc[0]}.{min_gcc[1]}+ or select a newer module/spack compiler.")
            issues.append(msg)
        else:
            add(checks, "compiler.version.gcc", "pass",
                f"GCC {compiler_version[0]}.{compiler_version[1]} satisfies minimum",
                {"version": list(compiler_version)})

    # Check GCC known-bad versions (blacklist)
    if "gcc" in COMPILER_KNOWN_BAD and compiler_version > (0, 0):
        gcc_triple = (compiler_version[0], compiler_version[1], 0)  # minor.patch unknown, check major.minor
        for bad_triple in COMPILER_KNOWN_BAD["gcc"]:
            if gcc_triple[0] == bad_triple[0] and gcc_triple[1] == bad_triple[1]:
                add(checks, "compiler.version.gcc.known_bad", "warn",
                    f"GCC {compiler_version[0]}.{compiler_version[1]}.x is known-bad: ICE with if constexpr. "
                    f"Use GCC {bad_triple[0]}.{bad_triple[1]}+ or 11.x instead.",
                    {"gcc_version": list(compiler_version), "known_bad": list(bad_triple)},
                    remediation="Switch to GCC 13.3+ or GCC 11.x. Avoid GCC 12.x.")
                break

    # Check NVCC version
    gpu_toolkit = selected.get("gpu_toolkit", {}) if isinstance(selected, dict) else {}
    nvcc_ver = str(gpu_toolkit.get("version") or "")
    if "nvcc" in required and nvcc_ver:
        nvcc_version = _parse_version_pair(nvcc_ver)
        if nvcc_version > (0, 0):
            min_nvcc = required["nvcc"]
            if not version_satisfies(nvcc_version, min_nvcc):
                msg = (
                    f"NVCC {nvcc_version[0]}.{nvcc_version[1]} is below minimum "
                    f"{min_nvcc[0]}.{min_nvcc[1]} for {backend}/{profile_name}"
                )
                add(checks, "compiler.version.nvcc", "fail", msg,
                    {"actual": list(nvcc_version), "required": list(min_nvcc)},
                    remediation=f"Upgrade CUDA toolkit to {min_nvcc[0]}.{min_nvcc[1]}+")
                _append_issue(issues, "compiler.version.nvcc", msg)
            else:
                add(checks, "compiler.version.nvcc", "pass",
                    f"NVCC {nvcc_version[0]}.{nvcc_version[1]} satisfies minimum",
                    {"version": list(nvcc_version)})

    # Check CMake minimum version
    cmake_entry = selected.get("cmake", {}) if isinstance(selected, dict) else {}
    cmake_ver = str(cmake_entry.get("version") or "")
    if cmake_ver:
        cmake_version = _parse_version_pair(cmake_ver)
        if cmake_version > (0, 0) and not version_satisfies(cmake_version, MIN_CMAKE_VERSION):
            msg = (
                f"CMake {cmake_version[0]}.{cmake_version[1]} is below minimum "
                f"{MIN_CMAKE_VERSION[0]}.{MIN_CMAKE_VERSION[1]}"
            )
            add(checks, "compiler.version.cmake", "fail", msg,
                {"actual": list(cmake_version), "required": list(MIN_CMAKE_VERSION)},
                remediation=f"Install CMake {MIN_CMAKE_VERSION[0]}.{MIN_CMAKE_VERSION[1]}+")
            issues.append(msg)


# ---------------------------------------------------------------------------
# Override machinery — user-acknowledged risks downgrade fail→warn
# ---------------------------------------------------------------------------


def _apply_overrides(
    checks: List[Dict[str, Any]],
    issues: List[str],
    checkpoint: Dict[str, Any],
) -> None:
    """Scan decisions in checkpoint for overrides; downgrade matching fail→warn."""
    decisions = checkpoint.get("decisions", {})
    if not isinstance(decisions, dict) or not decisions:
        return

    overridden_ids: set = set()
    for i, check in enumerate(checks):
        check_id = str(check.get("id") or "")
        if check.get("status") != "fail":
            continue
        override_key = COMPAT_OVERRIDE_MAP.get(check_id)
        if not override_key:
            continue
        override_value = decisions.get(override_key)
        if not override_satisfies(override_value):
            continue

        # Downgrade fail→warn
        checks[i]["status"] = "warn"
        checks[i]["summary"] = check["summary"] + " (overridden by decisions." + override_key + ")"
        overridden_ids.add(check_id)

    # Remove only the issues that belong to an overridden check (tracked via
    # IssueList check-id tags); never substring-match unrelated issue text.
    if overridden_ids:
        check_ids = (
            issues.check_ids
            if isinstance(issues, IssueList)
            else [""] * len(issues)
        )
        kept = [
            (text, cid)
            for text, cid in zip(issues, check_ids)
            if cid not in overridden_ids
        ]
        issues[:] = [text for text, _ in kept]
        if isinstance(issues, IssueList):
            issues.check_ids[:] = [cid for _, cid in kept]


# ---------------------------------------------------------------------------
# ADIOS2 install integrity validation (for source-build deps)
# ---------------------------------------------------------------------------


_ADIOS2_REQUIRED_TARGETS = [
    "adios2-targets.cmake",
    "adios2-targets-release.cmake",
    "adios2-c-targets.cmake",
    "adios2-c-targets-release.cmake",
    "adios2-cxx-targets.cmake",
    "adios2-cxx-targets-release.cmake",
]


def validate_adios2_install_integrity(
    checks: List[Dict[str, Any]],
    issues: List[str],
    adios2_entry: Dict[str, Any],
) -> bool:
    """Verify ADIOS2 cmake install is complete (all targets files present)."""
    cmake_config = _real_path(adios2_entry.get("cmake_config"))
    if cmake_config is None:
        return False
    config_dir = cmake_config.parent
    missing = [t for t in _ADIOS2_REQUIRED_TARGETS if not (config_dir / t).is_file()]
    if missing:
        add(checks, "dependency.adios2.targets", "fail",
            f"ADIOS2 install incomplete: missing {len(missing)} targets files",
            {"missing": missing, "config_dir": str(config_dir)},
            remediation="Re-run cmake --install or manually copy missing targets files from build tree.")
        issues.append(f"ADIOS2 missing targets: {', '.join(missing)}")
        return False
    add(checks, "dependency.adios2.targets", "pass",
        "ADIOS2 cmake install is complete (all targets files present)",
        {"config_dir": str(config_dir)})
    return True


def version_matches_family(version: str, family_prefix: str) -> bool:
    """Match a selected version against a profile family prefix by '.' segments.

    Family prefixes may carry a trailing dot ("5.", "2.11."); compare segment
    by segment so "5" matches the 5.x family but "55.0.0" does not.
    """
    wanted = [seg for seg in str(family_prefix).removeprefix("v").split(".") if seg]
    actual = [seg for seg in str(version).removeprefix("v").split(".") if seg]
    return bool(wanted) and actual[: len(wanted)] == wanted


# ---------------------------------------------------------------------------
# Main check runner
# ---------------------------------------------------------------------------


def check_source_revision(req: Dict[str, Any], checks: List[Dict[str, Any]],
                          issues: List[str]) -> None:
    entity = req.get("entity", {}) if isinstance(req.get("entity"), dict) else {}
    if req.get("schema_version") != 2:
        return
    checkout = Path(str(entity.get("source_checkout") or ""))
    revision = entity.get("source_revision", {})
    if not checkout.is_dir() or not isinstance(revision, dict):
        add(checks, "source.revision", "fail", "source checkout or revision is missing",
            {"source_checkout": str(checkout)},
            remediation="Materialize and record an immutable source revision before build.")
        issues.append("source revision is not verifiable")
        return
    kind = str(revision.get("kind") or "")
    if kind == "git":
        process = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD", "HEAD^{tree}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
        )
        status = subprocess.run(
            ["git", "-C", str(checkout), "status", "--porcelain"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
        )
        values = [line.strip() for line in process.stdout.splitlines() if line.strip()]
        actual = {"commit": values[0] if len(values) > 0 else "",
                  "tree": values[1] if len(values) > 1 else "",
                  "dirty": status.returncode != 0 or bool(status.stdout.strip())}
        expected = {"commit": str(revision.get("commit") or ""),
                    "tree": str(revision.get("tree") or "")}
        passed = (process.returncode == 0 and not actual["dirty"]
                  and actual["commit"] == expected["commit"]
                  and (not expected["tree"] or actual["tree"] == expected["tree"]))
    elif kind == "snapshot":
        manifest_path = checkout / "snapshot-manifest.json"
        actual = {"snapshot_id": "", "verified_files": 0}
        passed = manifest_path.is_file()
        if passed:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise ValueError("snapshot manifest is not a JSON object")
                actual["snapshot_id"] = str(manifest.get("snapshot_id") or "")
                passed = actual["snapshot_id"] == str(revision.get("snapshot_id") or "")
                for entry in manifest.get("files", []):
                    relative = str(entry.get("path") or "")
                    if (not relative or os.path.isabs(relative)
                            or ".." in Path(relative).parts):
                        passed = False
                        break
                    path = checkout / relative
                    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
                    if digest != entry.get("sha256"):
                        passed = False
                        break
                    actual["verified_files"] += 1
            except (OSError, ValueError) as exc:
                actual["error"] = f"{type(exc).__name__}: {exc}"
                passed = False
        expected = {"snapshot_id": str(revision.get("snapshot_id") or "")}
    else:
        actual = {"kind": kind}
        expected = {"kind": "git or snapshot"}
        passed = False
    add(checks, "source.revision", "pass" if passed else "fail",
        "Materialized source revision matches build request" if passed else
        "Materialized source revision differs from build request",
        {"expected": expected, "actual": actual},
        remediation="Re-materialize the exact Git commit or immutable snapshot.")
    if not passed:
        issues.append("materialized source revision differs from requirements")


def run_checks(
    req: Dict[str, Any], checkpoint: Dict[str, Any]
) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    checks: List[Dict[str, Any]] = []
    issues: List[str] = IssueList()

    # -- Section 1: Request / checkpoint consistency ------------------------
    req_schema = req.get("schema_version")
    checkpoint_schema = checkpoint.get("schema_version")
    if req_schema not in SUPPORTED_SCHEMA_VERSIONS:
        add(
            checks,
            "schema.requirements",
            "fail",
            "Unsupported requirements.json schema_version",
            {"expected": sorted(SUPPORTED_SCHEMA_VERSIONS), "actual": req_schema},
            remediation="Regenerate requirements.json with schema_version=2.",
        )
        issues.append("Unsupported requirements.json schema_version")
    if checkpoint_schema not in SUPPORTED_SCHEMA_VERSIONS:
        add(
            checks,
            "schema.checkpoint",
            "fail",
            "Unsupported entity-deps.local.json schema_version",
            {"expected": sorted(SUPPORTED_SCHEMA_VERSIONS), "actual": checkpoint_schema},
            remediation="Regenerate entity-deps.local.json with schema_version=2.",
        )
        issues.append("Unsupported entity-deps.local.json schema_version")
    if (req_schema in SUPPORTED_SCHEMA_VERSIONS
            and checkpoint_schema in SUPPORTED_SCHEMA_VERSIONS
            and req_schema != checkpoint_schema):
        add(
            checks,
            "schema.match",
            "fail",
            "requirements and checkpoint schema versions differ",
            {"requirements": req_schema, "checkpoint": checkpoint_schema},
            remediation="Regenerate entity-deps.local.json from the current requirements.json.",
        )
        issues.append("requirements and checkpoint schema versions differ")

    req_path = (
        checkpoint.get("requirements", {}).get("path", "")
        if isinstance(checkpoint.get("requirements"), dict)
        else ""
    )
    if req_path:
        req_path = str(req_path)
        if not Path(req_path).exists():
            add(
                checks,
                "consistency.requirements_path",
                "warn",
                f"Checkpoint references requirements.json path that does not exist: {req_path}",
                {"requirements_path": req_path},
                remediation="Update entity-deps.local.json.requirements.path.",
            )

    req_record = checkpoint.get("requirements", {})
    embedded = req_record.get("embedded") if isinstance(req_record, dict) else None
    if not isinstance(embedded, dict):
        add(
            checks,
            "consistency.requirements_embedded",
            "fail",
            "Checkpoint does not embed the request fields required for reuse validation",
            {},
            remediation="Regenerate entity-deps.local.json with entity_checkpoint.py create.",
        )
        issues.append("Checkpoint does not embed reusable requirements snapshot")
    else:
        mismatches: List[Dict[str, Any]] = []
        for field in REQUEST_SNAPSHOT_FIELDS:
            req_value = get_dotted(req, field)
            embedded_value = get_dotted(embedded, field)
            if req_value in (None, "") and embedded_value in (None, ""):
                continue
            if not _same_request_value(req_value, embedded_value):
                mismatches.append({
                    "field": field,
                    "requirements": req_value,
                    "checkpoint": embedded_value,
                })
        if mismatches:
            add(
                checks,
                "consistency.requirements_embedded",
                "fail",
                "Checkpoint was created for different requirements",
                {"mismatches": mismatches},
                remediation="Regenerate or repair entity-deps.local.json for the current requirements.json.",
            )
            issues.append("Checkpoint requirements snapshot differs from current requirements.json")
        else:
            add(
                checks,
                "consistency.requirements_embedded",
                "pass",
                "Checkpoint requirements snapshot matches current requirements",
                {},
            )

    cp_entity = checkpoint.get("entity", {}) if isinstance(checkpoint.get("entity"), dict) else {}
    req_paths = entity_paths(req)
    for field in ["site_id", "source_checkout", "build_root", "deps_root", "artifacts_root"]:
        expected = str(req_paths.get(field) or "")
        actual = str(cp_entity.get(field) or "")
        if actual and expected and actual != expected:
            add(
                checks,
                "consistency.%s" % field,
                "fail",
                "%s mismatch between requirements and checkpoint" % field,
                {"requirements": expected, "checkpoint": actual},
                remediation="Regenerate entity-deps.local.json for the current execution site paths.",
            )
            issues.append("%s differs between requirements.json and checkpoint" % field)

    check_source_revision(req, checks, issues)

    _check_parameters_confirmation(checks, issues, req, checkpoint)

    # -- Section 2: Entity version profile ----------------------------------
    try:
        profile_name, profile = profile_for(req)
        add(
            checks,
            "profile.detect",
            "pass",
            f"Using {profile_name} profile",
            {"profile": profile_name},
        )
    except ValueError as exc:
        add(checks, "profile.detect", "fail", str(exc))
        issues.append(str(exc))
        return "fail", checks, issues

    compile_cfg = req.get("compile", {})
    cxx_standard = (
        str(compile_cfg.get("cxx_standard") or profile["cxx_standard"])
        if isinstance(compile_cfg, dict)
        else str(profile["cxx_standard"])
    )
    if cxx_standard == profile["cxx_standard"]:
        add(
            checks,
            "profile.cxx_standard",
            "pass",
            "C++ standard matches Entity profile",
            {"cxx_standard": cxx_standard},
        )
    else:
        add(
            checks,
            "profile.cxx_standard",
            "fail",
            "C++ standard does not match Entity profile",
            {"expected": profile["cxx_standard"], "actual": cxx_standard},
            remediation=f"Set requirements.compile.cxx_standard to {profile['cxx_standard']} "
            f"or accept the override in decisions.",
        )
        issues.append("C++ standard does not match Entity profile")

    # Upstream only emits -DSHAPE_ORDER for deposit=esirkepov (cmake
    # set_shape_order); with zigzag the binary silently falls back to the
    # built-in first-order scheme and every other link in the chain
    # (CMakeCache, parameter card, build script) looks like the order took
    # effect. That silent no-op is exactly what this gate exists to catch.
    deposit = (
        str(compile_cfg.get("deposit") or "zigzag").lower()
        if isinstance(compile_cfg, dict) else "zigzag"
    )
    shape_order = (
        str(compile_cfg.get("shape_order") or "1")
        if isinstance(compile_cfg, dict) else "1"
    )
    if deposit != "esirkepov" and shape_order != "1":
        msg = (
            f"compile.shape_order={shape_order} has no effect with "
            f"compile.deposit={deposit}: upstream only emits -DSHAPE_ORDER "
            "for deposit=esirkepov, so the binary silently uses the built-in "
            "first-order zigzag scheme"
        )
        add(
            checks,
            "compile.shape_order_requires_esirkepov",
            "fail",
            msg,
            {"deposit": deposit, "shape_order": shape_order},
            remediation="Set compile.deposit=esirkepov to make shape_order take "
            "effect, or drop compile.shape_order.",
        )
        issues.append(msg)
    else:
        add(
            checks,
            "compile.shape_order_requires_esirkepov",
            "pass",
            "shape_order is consistent with the deposit scheme",
            {"deposit": deposit, "shape_order": shape_order},
        )

    for dep, prefix in (("kokkos", profile["kokkos"]), ("adios2", profile["adios2"])):
        version = selected_version(checkpoint, dep)
        if version and version_matches_family(version, prefix):
            add(
                checks,
                f"profile.{dep}_version",
                "pass",
                f"{dep} version matches profile",
                {"version": version},
            )
        else:
            add(
                checks,
                f"profile.{dep}_version",
                "fail",
                f"{dep} version does not match profile",
                {"expected_prefix": prefix, "actual": version},
                remediation=f"Select a {dep} version from the {prefix}x family "
                f"that matches the {profile_name} profile.",
            )
            issues.append(f"{dep} version does not match profile")

    uses_kokkos = adios2_uses_kokkos(checkpoint)
    if uses_kokkos is profile["adios2_uses_kokkos"]:
        add(
            checks,
            "profile.adios2_kokkos",
            "pass",
            "ADIOS2 Kokkos mode matches profile",
            {"adios2_uses_kokkos": uses_kokkos},
        )
    else:
        add(
            checks,
            "profile.adios2_kokkos",
            "fail",
            "ADIOS2 Kokkos mode does not match profile",
            {"expected": profile["adios2_uses_kokkos"], "actual": uses_kokkos},
            remediation=f"Set ADIOS2 compile_config.adios2_uses_kokkos to "
            f"{str(profile['adios2_uses_kokkos']).lower()} for the {profile_name} profile.",
        )
        issues.append("ADIOS2 Kokkos mode does not match profile")

    # -- Section 3: Toolchain consistency -----------------------------------
    selected = checkpoint.get("selected", {})
    compiler = selected.get("compiler", {}) if isinstance(selected, dict) else {}
    compiler_ok = isinstance(compiler, dict) and bool(compiler.get("cxx"))
    add(
        checks,
        "compiler.selected",
        "pass" if compiler_ok else "fail",
        "C++ compiler is selected",
        {"compiler": compiler},
        remediation="Add selected.compiler to entity-deps.local.json with cc and cxx fields.",
    )
    if not compiler_ok:
        issues.append("C++ compiler is not selected")
    else:
        validate_compiler_executable(checks, issues, compiler)
        _check_compiler_min_versions(checks, issues, compiler, checkpoint, req)

    # -- Section 4: Backend check -------------------------------------------
    env = req.get("environment", {})
    backend = (
        str(env.get("backend") or "cpu").lower() if isinstance(env, dict) else "cpu"
    )
    if backend == "cuda":
        cxx = str(
            compiler.get("cxx")
            or selected_entry(checkpoint, "kokkos").get("nvcc_wrapper")
            or ""
        )
        ok = "nvcc_wrapper" in Path(cxx).name
        add(
            checks,
            "backend.cuda.compiler",
            "pass" if ok else "fail",
            "CUDA backend uses Kokkos nvcc_wrapper",
            {"cxx": cxx},
            remediation="Set selected.compiler.cxx to the Kokkos nvcc_wrapper path.",
        )
        if not ok:
            issues.append("CUDA backend requires Kokkos nvcc_wrapper as CXX")
        adios2_script = (
            checkpoint.get("build_scripts", {}).get("scripts", {}).get("adios2", {})
        )
        script_path = (
            adios2_script.get("path") if isinstance(adios2_script, dict) else ""
        )
        if script_path and Path(str(script_path)).exists():
            text = Path(str(script_path)).read_text(encoding="utf-8")
            conflict = (
                "ADIOS2_USE_Kokkos=ON" in text and "ADIOS2_USE_CUDA=ON" in text
            )
            add(
                checks,
                "backend.cuda.adios2_flags",
                "fail" if conflict else "pass",
                "ADIOS2 Kokkos/CUDA flags are not mutually enabled",
                {"script": script_path},
                remediation="Do not set ADIOS2_USE_Kokkos=ON and ADIOS2_USE_CUDA=ON together.",
            )
            if conflict:
                issues.append(
                    "ADIOS2_USE_Kokkos and ADIOS2_USE_CUDA cannot both be ON"
                )
    elif backend == "hip":
        gpu_toolkit = (
            selected.get("gpu_toolkit", {})
            if isinstance(selected, dict)
            else {}
        )
        if isinstance(gpu_toolkit, dict) and gpu_toolkit.get("prefix"):
            tk_prefix = str(gpu_toolkit["prefix"])
            if not Path(tk_prefix).is_dir():
                add(
                    checks,
                    "backend.hip.toolkit",
                    "fail",
                    f"HIP/ROCm toolkit prefix does not exist: {tk_prefix}",
                    {"prefix": tk_prefix},
                    remediation="Verify the GPU toolkit prefix in selected.gpu_toolkit.prefix.",
                )
                issues.append(f"GPU toolkit prefix not found: {tk_prefix}")

    # -- Section 5-6: Dependency presence with path validation --------------
    required = ["kokkos"]
    if isinstance(env, dict) and env.get("output", True):
        required.extend(["hdf5", "adios2"])
    if isinstance(env, dict) and env.get("mpi"):
        required.append("mpi")

    for dep in required:
        entry = selected_entry(checkpoint, dep)
        if not entry:
            add(
                checks,
                f"dependency.{dep}",
                "fail",
                f"{dep} is not selected",
                {},
                remediation=f"Add selected.{dep} to entity-deps.local.json.",
            )
            issues.append(f"{dep} is not selected")
            continue
        validate_dependency_paths(checks, issues, dep, entry)
        # P2: ADIOS2 install integrity check
        if dep == "adios2" and entry.get("provider") == "source-build":
            validate_adios2_install_integrity(checks, issues, entry)
        if not has_installed_dependency(checkpoint, dep):
            add(
                checks,
                f"dependency.{dep}.structural",
                "fail",
                f"{dep} has no installed/discoverable evidence",
                entry,
                remediation=f"Ensure selected.{dep} has prefix, cmake_config, or bin "
                f"that points to a real installation.",
            )
            if f"{dep} is missing installed/discoverable evidence" not in issues:
                issues.append(f"{dep} is missing installed/discoverable evidence")

    # -- Section 7: Cross-dependency toolchain consistency -------------------
    run_cross_checks(checks, issues, req, checkpoint)

    # -- Section 8: Source-build script readiness ---------------------------
    source_scripts = checkpoint.get("build_scripts", {}).get("scripts", {})
    if isinstance(source_scripts, dict):
        for dep, script in source_scripts.items():
            if (
                isinstance(script, dict)
                and script.get("status") == "generated"
                and not has_installed_dependency(checkpoint, dep)
            ):
                add(
                    checks,
                    f"source_build.{dep}",
                    "fail",
                    "Generated source-build script has not produced installed dependency evidence",
                    script,
                    remediation=f"Run the {dep} source-build script and record install evidence "
                    f"in selected.{dep} before retrying compatibility.",
                )
                issues.append(
                    f"{dep} source-build script has not produced installed dependency evidence"
                )

    # -- Section 9: Apply decisions overrides (fail→warn) --------------------
    _apply_overrides(checks, issues, checkpoint)

    return ("pass" if not issues else "fail"), checks, issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements_json", type=Path)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--no-update-json", action="store_true")
    add_json_flag(parser)
    args = parser.parse_args()

    req = load_json(args.requirements_json)
    checkpoint = load_json(args.checkpoint)
    status, checks, issues = run_checks(req, checkpoint)
    compatibility = {
        "status": status,
        "checker_version": CHECKER_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "coverage": compatibility_coverage(),
        "checks": checks,
        "issues": issues,
    }
    if not args.no_update_json:
        checkpoint["compatibility"] = compatibility
        status_section = checkpoint.setdefault("status", {})
        if isinstance(status_section, dict):
            status_section["checkpoint"] = "complete" if status == "pass" else "incompatible"
            status_section["satisfies_requirements_json"] = status == "pass"
            env_sh = checkpoint.get("env_sh", {})
            env_generated = isinstance(env_sh, dict) and env_sh.get("status") == "generated"
            status_section["ready_for_entity_build"] = status == "pass" and env_generated
        write_json_atomic(args.checkpoint, checkpoint)
        record_step(
            args.checkpoint.parent,
            "compatibility_checked",
            status,
            inputs={
                "requirements_json": str(args.requirements_json.resolve()),
                "checkpoint_json": str(args.checkpoint.resolve()),
            },
            outputs={"checkpoint_json": str(args.checkpoint.resolve())},
            message=f"{len(issues)} issue(s)",
        )

    if args.json:
        if status != "pass":
            protocol_error(
                "compatibility_check",
                f"{len(issues)} issue(s) found",
                result=status,
                issues_count=len(issues),
                checks_count=len(checks),
            )
        protocol_ok(
            "compatibility_check",
            result=status,
            checks_count=len(checks),
            issues_count=len(issues),
        )
    else:
        print(json.dumps(compatibility, indent=2, sort_keys=True))
        if status != "pass":
            raise SystemExit(1)


if __name__ == "__main__":
    import sys
    from _invocation_log import trace_invocation
    with trace_invocation("entity-env-build", "entity_compat.py", sys.argv[1:], script_file=__file__):
        main()
