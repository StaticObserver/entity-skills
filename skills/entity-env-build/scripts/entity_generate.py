#!/usr/bin/env python3
"""Generate derived artifacts from JSON state files.

Subcommands:
  deps   generate dependency source-build scripts
  env    generate env.sh from entity-deps.local.json
  build  generate entity-build.sh from requirements.json + env.sh
"""

import argparse
import json
import os
import re
import shlex
import sys
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _json_io import (
    add_json_flag,
    load_json,
    protocol_error,
    protocol_ok,
    write_json_atomic,
)
from entity_state import record_step
from _version_profile import (
    inferred_cxx_standard,
    requested_version,
    version_profile as entity_version_profile,
)
from entity_schema import (
    CMAKE_BOOL_MAP,
    CMAKE_ENV_MAP,
    CMAKE_VALUE_MAP,
    DEFAULT_HDF5_VERSION,
    KOKKOS_BACKEND_FLAGS,
    SOURCE_BUILD_DEPENDENCIES,
    OPTIONAL_SOURCE_DEPENDENCIES,
    entity_paths,
    override_satisfies,
)


# ===========================================================================
# Shared utilities
# ===========================================================================


def q(value: Any) -> str:
    return shlex.quote(str(value))


# Tokens interpolated into generated shell scripts or used as path
# components must match this whitelist (blocks command substitution,
# shell metacharacters, and ".." path traversal).
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9._-]+")
# Valid shell environment variable names.
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _safe_token(value: Any, what: str) -> str:
    """Return *value* if it is a safe shell/path token, else exit with error."""
    text = str(value)
    if not _SAFE_TOKEN_RE.fullmatch(text):
        raise SystemExit(
            f"invalid {what}: {text!r} — only letters, digits, '.', '_', '-' are allowed"
        )
    return text


def bool_on(value: Any) -> str:
    return "ON" if bool(value) else "OFF"


def unique(values: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        value = os.path.expanduser(str(value))
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def get_deps_root(req: Dict[str, Any]) -> Path:
    value = entity_paths(req)["deps_root"]
    if not value:
        raise SystemExit("requirements.json missing entity.deps_root")
    return Path(value)


def get_build_artifacts_dir(req: Dict[str, Any]) -> Path:
    """Independent root for generated scripts, logs, and checkpoints."""
    value = entity_paths(req)["artifacts_root"]
    if not value:
        raise SystemExit("requirements.json missing entity.artifacts_root")
    return Path(value)


# ===========================================================================
# Shell generation helpers
# ===========================================================================


def shell_export(name: str, value: str) -> str:
    return f"export {name}={shlex.quote(value)}"


def shell_path_export(name: str, values: List[str]) -> str:
    values = unique(values)
    if not values:
        return f"# {name}: no entries generated"
    joined = ":".join(values)
    return f"export {name}={shlex.quote(joined)}${{{name}:+:${name}}}"


# ===========================================================================
# Compiler extraction from checkpoint
# ===========================================================================


_CC_TO_HOST_CXX = (("gcc", "g++"), ("clang", "clang++"), ("cc", "c++"))


def _derive_host_cxx(cc: str) -> str:
    """Derive the host C++ compiler from the C compiler (gcc→g++, clang→clang++).

    Falls back to "c++" — matching the build-kokkos.sh default — instead of
    returning the C compiler itself or a CUDA wrapper.
    """
    name = Path(cc).name
    for c_name, cxx_name in _CC_TO_HOST_CXX:
        if name == c_name or name.startswith(c_name + "-"):
            derived = cxx_name + name[len(c_name):]
            parent = str(Path(cc).parent)
            return derived if parent in ("", ".") else str(Path(parent) / derived)
    return "c++"


def selected_compiler(selected: Dict[str, Any]) -> Tuple[str, str, str, str]:
    compiler = selected.get("compiler", {})
    kokkos = selected.get("kokkos", {})
    mpi = selected.get("mpi", {})
    cc = cxx = host_cxx = ""
    if isinstance(compiler, dict):
        cc = str(compiler.get("cc") or compiler.get("c") or "")
        cxx = str(compiler.get("cxx") or compiler.get("cpp") or "")
        host_cxx = str(compiler.get("host_cxx") or compiler.get("host_compiler") or "")
    if not cxx and isinstance(kokkos, dict):
        cxx = str(kokkos.get("nvcc_wrapper") or "")
    if not cc and host_cxx:
        cc = host_cxx
    mpicxx = ""
    if isinstance(mpi, dict):
        mpicxx = str(mpi.get("mpicxx") or "")
    return cc, cxx, host_cxx or _derive_host_cxx(cc), mpicxx


def compiler_env(checkpoint: Dict[str, Any]) -> Dict[str, str]:
    selected = checkpoint.get("selected", {})
    compiler = selected.get("compiler", {}) if isinstance(selected, dict) else {}
    mpi = selected.get("mpi", {}) if isinstance(selected, dict) else {}
    out = {
        "CC": str(compiler.get("cc") or os.environ.get("CC", "")),
        "CXX": str(compiler.get("cxx") or os.environ.get("CXX", "")),
        "HOST_CXX": str(compiler.get("host_cxx") or compiler.get("host_compiler") or ""),
        "MPICXX": str(mpi.get("mpicxx") or os.environ.get("MPICXX", "")),
    }
    if not out["HOST_CXX"]:
        out["HOST_CXX"] = _derive_host_cxx(out["CC"])
    return out


# Kokkos arch → CUDA compute capability mapping
_KOKKOS_TO_CUDA_ARCH: Dict[str, str] = {
    "AMPERE80": "80",
    "AMPERE86": "86",
    "VOLTA70": "70",
    "VOLTA72": "72",
    "TURING75": "75",
    "PASCAL60": "60",
    "PASCAL61": "61",
    "MAXWELL50": "50",
    "MAXWELL52": "52",
    "MAXWELL53": "53",
    "KEPLER30": "30",
    "KEPLER32": "32",
    "KEPLER35": "35",
    "KEPLER37": "37",
    "HOPPER90": "90",
}


def _kokkos_arch_to_cuda(arch: str) -> str:
    """Convert Kokkos architecture name to CUDA compute capability (e.g., AMPERE80→80)."""
    arch = arch.upper().replace("KOKKOS_ARCH_", "")
    if arch not in _KOKKOS_TO_CUDA_ARCH:
        raise SystemExit(
            f"unknown Kokkos GPU architecture: {arch!r} "
            f"(no CUDA compute capability mapping; known: {', '.join(sorted(_KOKKOS_TO_CUDA_ARCH))})"
        )
    return _KOKKOS_TO_CUDA_ARCH[arch]


# ===========================================================================
# Dependency script generation (used by subcommand: deps)
# ===========================================================================


def _git_clone_fallback(dep: str, repo_url: str, branch_ref: str) -> str:
    """Generate git clone block with tarball fallback for when network is down."""
    dep_upper = dep.upper()
    fallback = f"""  git clone --depth 1 --branch {branch_ref} {repo_url} "$SRC" || {{
    TARBALL="${{ENTITY_SOURCE_TARBALL_DIR:-}}/{dep}-$VERSION.tar.gz"
    if [ -n "${{ENTITY_SOURCE_TARBALL_DIR:-}}" ] && [ -f "$TARBALL" ]; then
      echo "git clone failed, extracting from tarball: $TARBALL"
      rm -rf "$SRC"
      mkdir -p "$SRC"
      tar xf "$TARBALL" -C "$SRC" --strip-components=1
    else
      echo "ERROR: git clone of {dep} failed. Set ENTITY_SOURCE_TARBALL_DIR or ensure network access."
      echo "Expected tarball: ${{ENTITY_SOURCE_TARBALL_DIR:-}}/{dep}-$VERSION.tar.gz"
      exit 1
    fi
  }}"""
    return fallback


def _toolkit_bin(checkpoint: Dict[str, Any]) -> str:
    """GPU toolkit bin directory recorded in the checkpoint.

    Dependency build scripts run before env.sh exists, so nvcc/hipcc must be
    put on PATH explicitly from selected.gpu_toolkit (bin, else prefix/bin).
    """
    selected = checkpoint.get("selected", {}) if isinstance(checkpoint, dict) else {}
    toolkit = selected.get("gpu_toolkit", {}) if isinstance(selected, dict) else {}
    if not isinstance(toolkit, dict):
        return ""
    bin_dir = str(toolkit.get("bin") or "")
    if bin_dir:
        return bin_dir
    prefix = str(toolkit.get("prefix") or "")
    return str(Path(prefix) / "bin") if prefix else ""


def script_header(name: str, deps_root: Path, artifacts_root: Path, prefix: Path,
                  compilers: Dict[str, str], tarball_dir: str = "",
                  toolkit_bin: str = "") -> str:
    lines = [
        "#!/usr/bin/env bash",
        f"# Generated dependency build script for {name}. Review before execution.",
        "set -euo pipefail",
        'if [ -z "${ENTITY_DEPS_ROOT:-}" ]; then',
        f"  ENTITY_DEPS_ROOT={q(deps_root)}",
        "fi",
        "export ENTITY_DEPS_ROOT",
        f"export BUILD_ARTIFACTS_DIR={q(artifacts_root)}",
        'if [ -z "${PREFIX:-}" ]; then',
        f"  PREFIX={q(prefix)}",
        "fi",
        "export PREFIX",
        'SRC_ROOT="${ENTITY_DEPS_ROOT}/sources"',
        'BUILD_ROOT="${BUILD_ARTIFACTS_DIR}/generated/source-builds"',
        'LOG_DIR="${BUILD_ARTIFACTS_DIR}/build-logs"',
        "mkdir -p \"$SRC_ROOT\" \"$BUILD_ROOT\" \"$PREFIX\" \"$LOG_DIR\"",
    ]
    for key in ("CC", "CXX", "MPICXX"):
        if compilers.get(key):
            lines.append(f"export {key}={q(compilers[key])}")
    if compilers.get("HOST_CXX") and "nvcc_wrapper" in Path(compilers.get("CXX", "")).name:
        lines.append(f"export NVCC_WRAPPER_DEFAULT_COMPILER={q(compilers['HOST_CXX'])}")
    if toolkit_bin:
        lines.append("# nvcc/hipcc from the checkpointed GPU toolkit (env.sh does not exist yet)")
        lines.append(f"export PATH={q(toolkit_bin)}:$PATH")
    if tarball_dir:
        lines.append(f"export ENTITY_SOURCE_TARBALL_DIR={q(tarball_dir)}")
        lines.append('if [ ! -d "${ENTITY_SOURCE_TARBALL_DIR}" ]; then')
        lines.append('  echo "WARNING: ENTITY_SOURCE_TARBALL_DIR does not exist: ${ENTITY_SOURCE_TARBALL_DIR}"')
        lines.append("fi")
    lines.append("")
    return "\n".join(lines)


def _kokkos_script(req: Dict[str, Any], checkpoint: Dict[str, Any], deps_root: Path, tarball_dir: str = "") -> str:
    env = req.get("environment", {})
    compilers = compiler_env(checkpoint)
    profile = entity_version_profile(req)
    version = _safe_token(requested_version(req, "kokkos", profile), "kokkos version")
    prefix = deps_root / "kokkos" / version
    artifacts_root = get_build_artifacts_dir(req)
    if not isinstance(env, dict):
        env = {}
    backend = str(env.get("backend") or "cpu").lower()
    arch = str(env.get("gpu_arch") or "")
    if arch:
        arch = _safe_token(arch, "environment.gpu_arch")
    opts = [
        '-DCMAKE_INSTALL_PREFIX="$PREFIX"',
        "-DCMAKE_CXX_EXTENSIONS=OFF",
        "-DCMAKE_POSITION_INDEPENDENT_CODE=TRUE",
        "-DKokkos_ENABLE_SERIAL=ON",
        "-DKokkos_ENABLE_OPENMP=ON" if backend == "cpu" else "",
        "-DKokkos_ENABLE_CUDA=ON" if backend == "cuda" else "",
        "-DKokkos_ENABLE_HIP=ON" if backend == "hip" else "",
        "-DKokkos_ENABLE_PIC=ON",
        f"-DCMAKE_CXX_STANDARD={profile['cxx_standard']}",
    ]
    if arch:
        opts.append(f"-DKokkos_ARCH_{arch}=ON" if not arch.startswith("Kokkos_ARCH_") else f"-D{arch}=ON")
    opts = [opt for opt in opts if opt]
    cuda_wrapper_block = ""
    if backend == "cuda":
        host_cxx = compilers.get("HOST_CXX") or compilers.get("CXX") or "c++"
        cuda_wrapper_block = f"""
if [ -z "${{NVCC_WRAPPER_DEFAULT_COMPILER:-}}" ]; then
  export NVCC_WRAPPER_DEFAULT_COMPILER={q(host_cxx)}
fi
export CXX="$SRC/bin/nvcc_wrapper"
"""
    return (
        script_header("kokkos", deps_root, artifacts_root, prefix, compilers, tarball_dir,
                      toolkit_bin=_toolkit_bin(checkpoint) if backend in ("cuda", "hip") else "")
        + f"""
VERSION="${{KOKKOS_VERSION:-{version}}}"
SRC="$SRC_ROOT/kokkos-$VERSION"
BUILD="$BUILD_ROOT/kokkos-$VERSION"
if [ ! -d "$SRC/.git" ]; then
{_git_clone_fallback("kokkos", "https://github.com/kokkos/kokkos.git", '"$VERSION"')}
fi
{cuda_wrapper_block}
cmake -S "$SRC" -B "$BUILD" \\
  {' '.join(opts)} 2>&1 | tee "$LOG_DIR/kokkos-configure.log"
cmake --build "$BUILD" -j "${{NCORES:-$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)}}" 2>&1 | tee "$LOG_DIR/kokkos-build.log"
cmake --install "$BUILD" 2>&1 | tee "$LOG_DIR/kokkos-install.log"
"""
    )


def _hdf5_script(req: Dict[str, Any], checkpoint: Dict[str, Any], deps_root: Path, tarball_dir: str = "") -> str:
    env = req.get("environment", {})
    compilers = compiler_env(checkpoint)
    version = _safe_token(requested_version(req, "hdf5", entity_version_profile(req)), "hdf5 version")
    prefix = deps_root / "hdf5" / version
    artifacts_root = get_build_artifacts_dir(req)
    mpi_on = bool(env.get("mpi")) if isinstance(env, dict) else False
    parallel = "-DHDF5_ENABLE_PARALLEL=ON" if mpi_on else "-DHDF5_ENABLE_PARALLEL=OFF"
    return (
        script_header("hdf5", deps_root, artifacts_root, prefix, compilers, tarball_dir)
        + f"""
VERSION="${{HDF5_VERSION:-{version}}}"
SRC="$SRC_ROOT/hdf5-$VERSION"
BUILD="$BUILD_ROOT/hdf5-$VERSION"
if [ ! -d "$SRC/.git" ]; then
{_git_clone_fallback("hdf5", "https://github.com/HDFGroup/hdf5.git", '"hdf5-$VERSION"')}
fi
cmake -S "$SRC" -B "$BUILD" \\
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \\
  -DHDF5_BUILD_CPP_LIB=ON \\
  {parallel} 2>&1 | tee "$LOG_DIR/hdf5-configure.log"
cmake --build "$BUILD" -j "${{NCORES:-$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)}}" 2>&1 | tee "$LOG_DIR/hdf5-build.log"
cmake --install "$BUILD" 2>&1 | tee "$LOG_DIR/hdf5-install.log"
"""
    )


def _adios2_script(req: Dict[str, Any], checkpoint: Dict[str, Any], deps_root: Path, tarball_dir: str = "") -> str:
    env = req.get("environment", {})
    compilers = compiler_env(checkpoint)
    profile = entity_version_profile(req)
    version = _safe_token(requested_version(req, "adios2", profile), "adios2 version")
    hdf5_version = _safe_token(requested_version(req, "hdf5", profile), "hdf5 version")
    kokkos_version = _safe_token(requested_version(req, "kokkos", profile), "kokkos version")
    prefix = deps_root / "adios2" / version
    artifacts_root = get_build_artifacts_dir(req)
    if not isinstance(env, dict):
        env = {}
    mpi_on = bool(env.get("mpi"))
    backend = str(env.get("backend") or "cpu").lower()
    prefix_parts = [str(deps_root / "hdf5" / hdf5_version)]
    if profile["adios2_uses_kokkos"]:
        prefix_parts.insert(0, str(deps_root / "kokkos" / kokkos_version))
    cmake_prefix_base = ":".join(prefix_parts)
    # CUDA + Kokkos requires explicit CMAKE_CUDA_COMPILER and ARCHITECTURES
    cuda_extra = ""
    if backend == "cuda" and profile["adios2_uses_kokkos"]:
        selected = checkpoint.get("selected", {}) if isinstance(checkpoint, dict) else {}
        gpu_toolkit = selected.get("gpu_toolkit", {}) if isinstance(selected, dict) else {}
        cuda_prefix = str(gpu_toolkit.get("prefix") or "")
        kokkos_entry = selected.get("kokkos", {})
        cuda_arch = str(
            (kokkos_entry.get("cuda_arch") if isinstance(kokkos_entry, dict) else "")
            or env.get("gpu_arch", "")
        )
        if cuda_prefix and cuda_arch:
            # Map Kokkos arch name to CUDA compute capability
            arch_num = _kokkos_arch_to_cuda(cuda_arch)
            stubs_path = f"{cuda_prefix}/targets/x86_64-linux/lib/stubs"
            cuda_lib_path = f"{cuda_prefix}/targets/x86_64-linux/lib"
            link_flags = q(f"-L{stubs_path} -L{cuda_lib_path}")
            cuda_extra = f"""
# CUDA + Kokkos: set CUDA compiler and architecture for enable_language(CUDA)
export CMAKE_CUDA_COMPILER={q(cuda_prefix + '/bin/nvcc')}
export CMAKE_CUDA_ARCHITECTURES={q(arch_num)}
# Both stubs (login nodes) and real libs (GPU nodes) — order: stubs first
# so the linker prefers stubs for symbols that don't need real GPU
export LDFLAGS={link_flags}"${{LDFLAGS:+ $LDFLAGS}}"
export CMAKE_EXE_LINKER_FLAGS={link_flags}"${{CMAKE_EXE_LINKER_FLAGS:+ $CMAKE_EXE_LINKER_FLAGS}}"
export CMAKE_SHARED_LINKER_FLAGS={link_flags}"${{CMAKE_SHARED_LINKER_FLAGS:+ $CMAKE_SHARED_LINKER_FLAGS}}"
"""
    opts = [
        '-DCMAKE_INSTALL_PREFIX="$PREFIX"',
        f"-DCMAKE_CXX_STANDARD={profile['cxx_standard']}",
        "-DCMAKE_CXX_EXTENSIONS=OFF",
        "-DCMAKE_POSITION_INDEPENDENT_CODE=TRUE",
        "-DBUILD_SHARED_LIBS=ON",
        "-DADIOS2_USE_Python=OFF",
        "-DADIOS2_USE_Fortran=OFF",
        "-DADIOS2_USE_ZeroMQ=OFF",
        "-DBUILD_TESTING=OFF",
        "-DADIOS2_BUILD_EXAMPLES=OFF",
        f"-DADIOS2_USE_MPI={'ON' if mpi_on else 'OFF'}",
        "-DADIOS2_USE_HDF5=ON",
        f"-DADIOS2_HAVE_HDF5_VOL={'ON' if mpi_on else 'OFF'}",
        f"-DADIOS2_USE_Kokkos={'ON' if profile['adios2_uses_kokkos'] else 'OFF'}",
        "-DADIOS2_BUILD_TOOLS=OFF",
        "-DADIOS2_USE_CUDA=ON" if backend == "cuda" and not profile["adios2_uses_kokkos"] else "",
    ]
    opts = [opt for opt in opts if opt]
    return (
        script_header("adios2", deps_root, artifacts_root, prefix, compilers, tarball_dir,
                      toolkit_bin=_toolkit_bin(checkpoint) if backend in ("cuda", "hip") else "")
        + f"""
VERSION="${{ADIOS2_VERSION:-v{version}}}"
SRC="$SRC_ROOT/ADIOS2-$VERSION"
BUILD="$BUILD_ROOT/ADIOS2-$VERSION"
CMAKE_PREFIX_PATH_BASE={q(cmake_prefix_base)}
export CMAKE_PREFIX_PATH="${{CMAKE_PREFIX_PATH_BASE}}${{CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}}"
if [ ! -d "$SRC/.git" ]; then
{_git_clone_fallback("adios2", "https://github.com/ornladios/ADIOS2.git", '"$VERSION"')}
fi
{cuda_extra}
cmake -S "$SRC" -B "$BUILD" \\
  {' '.join(opts)} 2>&1 | tee "$LOG_DIR/adios2-configure.log"
cmake --build "$BUILD" -j "${{NCORES:-$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)}}" 2>&1 | tee "$LOG_DIR/adios2-build.log"
cmake --install "$BUILD" 2>&1 | tee "$LOG_DIR/adios2-install.log"
"""
    )


def _mpi_script(req: Dict[str, Any], checkpoint: Dict[str, Any], deps_root: Path, tarball_dir: str = "") -> str:
    compilers = compiler_env(checkpoint)
    profile = entity_version_profile(req)
    version = _safe_token(requested_version(req, "openmpi", profile), "openmpi version")
    prefix = deps_root / "openmpi" / version
    artifacts_root = get_build_artifacts_dir(req)
    return (
        script_header("openmpi", deps_root, artifacts_root, prefix, compilers, tarball_dir)
        + """
cat >&2 <<'MSG'
OpenMPI source build is intentionally not auto-generated yet.
Prefer a system/module MPI. If source MPI is required, add a reviewed
OpenMPI+UCX script here and record the reason in entity-deps.local.json.
MSG
exit 2
"""
    )


SCRIPT_FACTORIES = {
    "kokkos": _kokkos_script,
    "hdf5": _hdf5_script,
    "adios2": _adios2_script,
    "mpi": _mpi_script,
}


def dep_list(value: Optional[str], req: Dict[str, Any]) -> List[str]:
    if value:
        deps = [item.strip().lower() for item in value.split(",") if item.strip()]
        unknown = [dep for dep in deps if dep not in {"kokkos", "hdf5", "adios2", "mpi"}]
        if unknown:
            raise SystemExit(f"unsupported dependencies: {', '.join(unknown)}")
        return deps
    env = req.get("environment", {})
    deps = ["kokkos"]
    if isinstance(env, dict) and env.get("mpi") and env.get("build_mpi_from_source"):
        deps.insert(0, "mpi")
    if not isinstance(env, dict) or env.get("output", True):
        deps.extend(["hdf5", "adios2"])
    return deps


def cmd_deps(args: argparse.Namespace) -> None:
    req = load_json(args.requirements_json)
    checkpoint = load_json(args.checkpoint)
    deps_root = get_deps_root(req)
    out_dir = args.output_dir or deps_root / "scripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    scripts: Dict[str, Dict[str, str]] = {}
    profile = entity_version_profile(req)
    generated: List[str] = []
    tarball_dir = getattr(args, 'source_tarball_dir', "") or ""
    for dep in dep_list(args.deps, req):
        text = SCRIPT_FACTORIES[dep](req, checkpoint, deps_root, tarball_dir)
        path = out_dir / f"build-{dep}.sh"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
        scripts[dep] = {
            "path": str(path.resolve()),
            "status": "generated",
            "source": "entity-env-build/scripts/entity_generate.py",
            "based_on": "Entity dependencies.py/wiki dependency generator",
            "version_profile": str(profile["name"]),
            "cxx_standard": str(profile["cxx_standard"]),
            "version": requested_version(req, dep, profile),
        }
        if dep == "adios2":
            scripts[dep]["adios2_uses_kokkos"] = "true" if profile["adios2_uses_kokkos"] else "false"
        generated.append(str(path.resolve()))

    if not args.no_update_json:
        build_scripts = checkpoint.setdefault("build_scripts", {})
        if not isinstance(build_scripts, dict):
            build_scripts = {}
            checkpoint["build_scripts"] = build_scripts
        build_scripts.update({
            "directory": str(out_dir.resolve()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version_profile": str(profile["name"]),
            "cxx_standard": str(profile["cxx_standard"]),
            "scripts": scripts,
        })
        write_json_atomic(args.checkpoint, checkpoint)

    if args.json:
        protocol_ok("generate.deps", scripts=generated, count=len(generated))


# ===========================================================================
# env.sh generation (subcommand: env)
# ===========================================================================


def dep_prefixes(selected: Dict[str, Any]) -> List[str]:
    prefixes: List[str] = []
    for dep in selected.values():
        if isinstance(dep, dict):
            prefix = dep.get("prefix") or dep.get("install_prefix")
            if prefix:
                prefixes.append(str(prefix))
    return unique(prefixes)


def dep_bins(selected: Dict[str, Any]) -> List[str]:
    bins: List[str] = []
    for dep in selected.values():
        if isinstance(dep, dict):
            bin_path = dep.get("bin")
            if bin_path:
                p = Path(str(bin_path))
                bins.append(str(p.parent) if p.is_file() else str(p))
            prefix = dep.get("prefix") or dep.get("install_prefix")
            if prefix:
                bins.append(str(Path(str(prefix)) / "bin"))
    return unique(bins)


def dep_libs(selected: Dict[str, Any]) -> List[str]:
    libs: List[str] = []
    for dep in selected.values():
        if isinstance(dep, dict):
            lib_path = dep.get("lib")
            if lib_path:
                p = Path(str(lib_path))
                libs.append(str(p.parent) if p.is_file() else str(p))
            prefix = dep.get("prefix") or dep.get("install_prefix")
            if prefix:
                libs.append(str(Path(str(prefix)) / "lib"))
                libs.append(str(Path(str(prefix)) / "lib64"))
    return unique(libs)


def _warnings_accepted(data: Dict[str, Any]) -> bool:
    decisions = data.get("decisions", {})
    if not isinstance(decisions, dict):
        return False
    return override_satisfies(decisions.get("compatibility_warnings_accepted"))


def require_compatibility_pass(
    data: Dict[str, Any],
    allow_incomplete: bool,
    allow_warnings: bool = False,
) -> None:
    if allow_incomplete:
        return
    compatibility = data.get("compatibility", {})
    status = str(compatibility.get("status") or "") if isinstance(compatibility, dict) else ""
    if status == "pass":
        return
    if status == "warn" and allow_warnings and _warnings_accepted(data):
        return
    if status == "warn" and allow_warnings:
        raise SystemExit(
            "entity-deps.local.json compatibility.status=warn requires "
            "decisions.compatibility_warnings_accepted before env.sh generation"
        )
    raise SystemExit(
        f"entity-deps.local.json compatibility.status={status}, must be pass. "
        "(use --allow-incomplete only for debugging)"
    )


def generate_env(data: Dict[str, Any], json_path: Path) -> str:
    selected = data.get("selected", {})
    if not isinstance(selected, dict):
        selected = {}
    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        paths = {}

    prefixes = dep_prefixes(selected)
    # ENTITY_DEPS_ROOT is the independent dependency root for this execution site.
    # Install layout is <deps_root>/<dep>/<version>, so:
    #   - multiple deps: commonpath(prefixes) already is deps_root
    #   - single dep:    strip the <dep>/<version> components (parent.parent)
    entity_section = data.get("entity", {})
    recorded_deps_root = (
        str(entity_section.get("deps_root") or "")
        if isinstance(entity_section, dict)
        else ""
    )
    if recorded_deps_root:
        deps_root = recorded_deps_root
    elif prefixes:
        if len(prefixes) > 1:
            deps_root = str(Path(os.path.commonpath(prefixes)))
        else:
            deps_root = str(Path(prefixes[0]).parent.parent)
    elif paths.get("ENTITY_DEPS_ROOT"):
        deps_root = str(paths["ENTITY_DEPS_ROOT"])
    else:
        deps_root = str(json_path.parent)
    path_entries = unique([*(paths.get("PATH") or []), *dep_bins(selected)])
    cmake_entries = unique([*(paths.get("CMAKE_PREFIX_PATH") or []), *dep_prefixes(selected)])
    ld_entries = unique([*(paths.get("LD_LIBRARY_PATH") or []), *dep_libs(selected)])
    dyld_entries = unique([*(paths.get("DYLD_LIBRARY_PATH") or [])])

    cc, cxx, host_cxx, mpicxx = selected_compiler(selected)

    lines = [
        "#!/usr/bin/env bash",
        "# Generated from entity-deps.local.json. Do not edit by hand.",
        "set -euo pipefail",
        shell_export("ENTITY_DEPS_JSON", str(json_path.resolve())),
        shell_export("ENTITY_DEPS_ROOT", deps_root),
    ]

    # Pre-commands
    pre_commands = paths.get("pre_commands", []) if isinstance(paths, dict) else []
    if isinstance(pre_commands, list) and pre_commands:
        lines.append("")
        lines.append("# Site-specific pre-commands from entity-deps.local.json")
        lines.extend(str(cmd) for cmd in pre_commands if cmd)

    # Modules
    modules = paths.get("modules", []) if isinstance(paths, dict) else []
    if isinstance(modules, list) and modules:
        lines.append("")
        lines.append("# --- Modules ---")
        lines.append("if command -v module &>/dev/null; then")
        for mod in modules:
            if mod:
                lines.append(f"  module load {shlex.quote(str(mod))}")
        lines.append("fi")

    lines.extend([
        shell_path_export("PATH", path_entries),
        shell_path_export("CMAKE_PREFIX_PATH", cmake_entries),
        shell_path_export("LD_LIBRARY_PATH", ld_entries),
    ])
    if dyld_entries:
        lines.append(shell_path_export("DYLD_LIBRARY_PATH", dyld_entries))
    if cc:
        lines.append(shell_export("CC", cc))
    if cxx:
        lines.append(shell_export("CXX", cxx))
    if "nvcc_wrapper" in Path(cxx).name and host_cxx:
        lines.append(shell_export("NVCC_WRAPPER_DEFAULT_COMPILER", host_cxx))
    if mpicxx:
        lines.append(shell_export("MPICXX", mpicxx))

    # Extra env overrides (skip keys already exported by auto-generated logic)
    _already_exported = {"ENTITY_DEPS_JSON", "ENTITY_DEPS_ROOT", "PATH", "CMAKE_PREFIX_PATH",
                         "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "CC", "CXX",
                         "NVCC_WRAPPER_DEFAULT_COMPILER", "MPICXX"}
    extra_env = paths.get("extra_env", {}) if isinstance(paths, dict) else {}
    if isinstance(extra_env, dict) and extra_env:
        deduped = {k: v for k, v in extra_env.items() if k not in _already_exported and v}
        invalid_names = [str(k) for k in deduped if not _ENV_NAME_RE.fullmatch(str(k))]
        if invalid_names:
            raise SystemExit(
                "invalid extra_env variable name(s): "
                + ", ".join(repr(name) for name in invalid_names)
                + " — must match [A-Za-z_][A-Za-z0-9_]*"
            )
        if deduped:
            lines.append("")
            lines.append("# Site-specific environment overrides from entity-deps.local.json")
            for var, val in deduped.items():
                lines.append(shell_export(str(var), str(val)))

    lines.append("")
    return "\n".join(lines)


def default_env_path(data: Dict[str, Any], json_path: Path) -> Path:
    env_sh = data.get("env_sh", {})
    if isinstance(env_sh, dict) and env_sh.get("path"):
        return Path(str(env_sh["path"]))
    artifacts = data.get("artifacts", {})
    if isinstance(artifacts, dict) and artifacts.get("env_sh"):
        return Path(str(artifacts["env_sh"]))
    # Default: same directory as the checkpoint JSON (i.e. _build/)
    return json_path.parent / "env.sh"


def cmd_env(args: argparse.Namespace) -> None:
    data = load_json(args.json_path)
    require_compatibility_pass(data, args.allow_incomplete, args.allow_warnings)
    if args.output is None:
        args.output = default_env_path(data, args.json_path)
    script = generate_env(data, args.json_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(script, encoding="utf-8")
    args.output.chmod(0o755)

    if not args.no_update_json:
        env_sh = data.setdefault("env_sh", {})
        if not isinstance(env_sh, dict):
            env_sh = {}
            data["env_sh"] = env_sh
        env_sh.update({
            "path": str(args.output.resolve()),
            "status": "generated",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_from_checkpoint": str(args.json_path.resolve()),
            "validation": {"bash_syntax": "not_run", "commands": []},
        })
        write_json_atomic(args.json_path, data)
        record_step(
            args.output.parent,
            "env_generated",
            "pass",
            inputs={"checkpoint_json": str(args.json_path.resolve())},
            outputs={"env_sh": str(args.output.resolve())},
        )

    if args.json:
        protocol_ok("generate.env", output=str(args.output.resolve()))


# ===========================================================================
# entity-build.sh generation (subcommand: build)
# ===========================================================================


def cmake_options(req: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    env = req.get("environment", {})
    compile_cfg = req.get("compile", {})
    pgen = compile_cfg.get("pgen")
    pgens = compile_cfg.get("pgens")
    if not pgen and not pgens:
        raise SystemExit("requirements.json missing required field: compile.pgen or compile.pgens")

    opts: List[str] = []
    # pgen
    if pgen:
        opts.append(f"-Dpgen={pgen}")
    else:
        pgens_val = ",".join(str(item) for item in pgens) if isinstance(pgens, list) else str(pgens)
        opts.append(f"-Dpgens={pgens_val}")

    # Value-mapped options from entity_schema.py
    for json_key, cmake_key in CMAKE_VALUE_MAP.items():
        val = compile_cfg.get(json_key, "")
        if val:
            opts.append(f"-D{cmake_key}={val}")

    # Bool-mapped options
    for json_key, cmake_key in CMAKE_BOOL_MAP.items():
        opts.append(f"-D{cmake_key}={bool_on(compile_cfg.get(json_key, False))}")

    # Environment-mapped options
    for json_key, cmake_key in CMAKE_ENV_MAP.items():
        opts.append(f"-D{cmake_key}={bool_on(env.get(json_key, False))}")

    # C++ standard
    opts.append(f"-DCMAKE_CXX_STANDARD={inferred_cxx_standard(req)}")

    # Backend
    backend = str(env.get("backend") or "cpu").lower()
    gpu_arch = str(env.get("gpu_arch") or "")
    if backend in KOKKOS_BACKEND_FLAGS:
        opts.append(f"-D{KOKKOS_BACKEND_FLAGS[backend]}=ON")
    if gpu_arch:
        flag = f"-D{gpu_arch}=ON" if gpu_arch.startswith("Kokkos_ARCH_") else f"-DKokkos_ARCH_{gpu_arch}=ON"
        opts.append(flag)

    # CXX flags (shell_command() applies shlex.quote to each opt exactly once;
    # do not pre-quote here or cmake receives literal quote characters)
    cmake_cxx_flags = compile_cfg.get("cmake_cxx_flags", "")
    if cmake_cxx_flags:
        opts.append(f'-DCMAKE_CXX_FLAGS={str(cmake_cxx_flags)}')

    # Install
    install_prefix = compile_cfg.get("install_prefix")
    if compile_cfg.get("install") and install_prefix:
        opts.append(f"-DCMAKE_INSTALL_PREFIX={install_prefix}")

    # Extra options
    for extra in compile_cfg.get("extra_cmake_options") or []:
        opts.append(str(extra))

    # Shell-raw options (compiler from env vars)
    raw_shell_opts: List[str] = [
        '-DCMAKE_CXX_COMPILER="${CXX}"',
        '-DCMAKE_C_COMPILER="${CC}"',
    ]

    return opts, raw_shell_opts


def require_string(obj: Dict[str, Any], path: str) -> str:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise SystemExit(f"requirements.json missing required field: {path}")
        cur = cur[part]
    if cur in (None, ""):
        raise SystemExit(f"requirements.json field is empty: {path}")
    return str(cur)


def default_build_dir(req: Dict[str, Any]) -> str:
    """Entity cmake build tree supplied by the build-site contract."""
    return entity_paths(req)["build_root"]


def _verify_checkpoint_gate(
    checkpoint: Dict[str, Any],
    env_sh: Path,
    allow_warnings: bool = False,
    allow_stale_env: bool = False,
) -> None:
    require_compatibility_pass(checkpoint, allow_incomplete=False, allow_warnings=allow_warnings)
    checkpoint_env = checkpoint.get("env_sh", {})
    if isinstance(checkpoint_env, dict):
        recorded_path = checkpoint_env.get("path", "")
        if recorded_path and Path(recorded_path).resolve() != env_sh.resolve():
            msg = (
                f"checkpoint env_sh.path ({recorded_path}) differs from "
                f"--env argument ({env_sh}). The env.sh may be stale."
            )
            if not allow_stale_env:
                raise SystemExit(msg)
            print(f"WARNING: {msg}", file=sys.stderr)


def shell_command(parts: List[str]) -> str:
    return " ".join(q(part) for part in parts)


def generate_build_script(
    req: Dict[str, Any], req_path: Path, env_sh: Path, run_id: str,
    clean_build: bool = False,
) -> Tuple[str, Dict[str, str]]:
    checkout = entity_paths(req)["source_checkout"]
    if not checkout:
        raise SystemExit("requirements.json cannot resolve entity.source_checkout")
    compile_cfg = req.setdefault("compile", {})
    build_dir = str(compile_cfg.get("build_dir") or default_build_dir(req))
    compile_cfg["build_dir"] = build_dir
    compile_cfg.setdefault("cxx_standard", inferred_cxx_standard(req))
    jobs = str(compile_cfg.get("jobs") or "")
    run_id_q = q(run_id)

    fixed_opts, raw_shell_opts = cmake_options(req)
    configure_cmd = shell_command(["cmake", "-B", build_dir, *fixed_opts])
    if raw_shell_opts:
        configure_cmd += " " + " ".join(raw_shell_opts)
    build_parts = ["cmake", "--build", build_dir]
    if jobs:
        build_parts.extend(["-j", jobs])

    log_dir = get_build_artifacts_dir(req) / "build-logs"

    lines = [
        "#!/usr/bin/env bash",
        "# Generated from requirements.json and env.sh. Do not edit by hand.",
        "set -euo pipefail",
        f"source {q(env_sh.resolve())}",
        f"LOG_DIR={q(log_dir)}",
        "mkdir -p \"$LOG_DIR\"",
        f"cd {q(checkout)}",
    ]
    if clean_build:
        lines.append(f"rm -rf {q(build_dir)}")
        lines.append("echo 'Cleaned previous build tree'")
    lines.extend([
        f'TS=$(date -u +%Y%m%dT%H%M%SZ)',
        "mkdir -p \"$HOME/.entity-env-build\"",
        "# -- cmake configure --",
        f"{configure_cmd} 2>&1 | tee \"$LOG_DIR/entity-configure-$TS.log\"",
        f"echo '{{\"ts\":\"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'\",\"run\":{run_id_q},\"action\":\"build.configure\",\"script\":\"entity-build.sh\",\"status\":\"ok\"}}' >> ~/.entity-env-build/run.log",
        "# -- cmake build --",
        f"{shell_command(build_parts)} 2>&1 | tee \"$LOG_DIR/entity-build-$TS.log\"",
        f"echo '{{\"ts\":\"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'\",\"run\":{run_id_q},\"action\":\"build.compile\",\"script\":\"entity-build.sh\",\"status\":\"ok\"}}' >> ~/.entity-env-build/run.log",
    ])
    if compile_cfg.get("tests"):
        lines.append(shell_command(["ctest", "--test-dir", build_dir, "--output-on-failure"]))
    if compile_cfg.get("install"):
        lines.append(shell_command(["cmake", "--install", build_dir]))
    lines.append("")

    meta = {
        "configure_command": configure_cmd,
        "build_command": shell_command(build_parts),
        "expected_executable": str(Path(build_dir) / "src" / "entity.xc"),
    }
    return "\n".join(lines), meta


def cmd_build(args: argparse.Namespace) -> None:
    req = load_json(args.requirements_json)
    entity_version_profile(req)
    if not args.env.exists():
        msg = f"env.sh not found: {args.env}"
        if args.json:
            protocol_error("generate.build", msg)
        raise SystemExit(msg)

    compile_cfg = req.get("compile", {})
    if not isinstance(compile_cfg, dict):
        compile_cfg = {}
    build_dir = str(compile_cfg.get("build_dir") or default_build_dir(req))
    # Only an actual CMake build tree is dangerous to reconfigure — metadata
    # under build_dir (requirements.json, checkpoint, _artifacts/) is expected
    # on a first build when artifacts_root defaults to <build_root>/_artifacts.
    build_dir_path = Path(build_dir)
    has_cmake_tree = (
        (build_dir_path / "CMakeCache.txt").is_file()
        or (build_dir_path / "CMakeFiles").is_dir()
    )
    if not args.reuse_build_dir and not args.clean_build and has_cmake_tree:
        msg = (
            f"拒绝生成构建脚本:compile.build_dir 指向已存在的 CMake 构建树 {build_dir}"
            "(检测到 CMakeCache.txt/CMakeFiles)。"
            "在其上重新 configure 会重链/覆盖既有构建树——若该树已登记进 Ledger,"
            "登记证据(可执行文件 sha256)将与磁盘内容失真。本轮构建请使用新的"
            " build_dir(新的构建身份);确认要原地重建时显式传 --reuse-build-dir"
            "(--clean-build 会先清空树,同样视为显式确认)。"
        )
        if args.json:
            protocol_error("generate.build", msg)
        raise SystemExit(msg)

    if args.checkpoint:
        if not args.checkpoint.exists():
            msg = f"entity-deps.local.json not found: {args.checkpoint}"
            if args.json:
                protocol_error("generate.build", msg)
            raise SystemExit(msg)
        checkpoint = load_json(args.checkpoint)
        _verify_checkpoint_gate(
            checkpoint,
            args.env.resolve(),
            allow_warnings=args.allow_warnings,
            allow_stale_env=args.allow_stale_env,
        )
        env_fingerprint = (
            checkpoint.get("env_sh", {}).get("generated_at", "")
            if isinstance(checkpoint.get("env_sh"), dict)
            else ""
        )
    else:
        print(
            "WARNING: --checkpoint not provided. Skipping compatibility gate validation. "
            "Use --checkpoint for production builds.",
            file=sys.stderr,
        )
        env_fingerprint = ""

    run_id = getattr(args, '_run_id', None) or _uuid.uuid4().hex[:8]

    if args.output is None:
        artifacts = req.get("artifacts", {})
        if isinstance(artifacts, dict) and artifacts.get("entity_build_sh"):
            args.output = Path(str(artifacts["entity_build_sh"]))
        else:
            args.output = get_build_artifacts_dir(req) / "entity-build.sh"

    script, meta = generate_build_script(req, args.requirements_json, args.env, run_id,
                                          clean_build=args.clean_build)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(script, encoding="utf-8")
    args.output.chmod(0o755)

    if not args.no_update_json:
        artifacts = req.setdefault("artifacts", {})
        if not isinstance(artifacts, dict):
            artifacts = {}
            req["artifacts"] = artifacts
        artifacts["entity_build_sh"] = str(args.output.resolve())
        build_script = req.setdefault("entity_build_script", {})
        if not isinstance(build_script, dict):
            build_script = {}
            req["entity_build_script"] = build_script
        build_script.update({
            "path": str(args.output.resolve()),
            "status": "generated",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_from": {
                "requirements_json": str(args.requirements_json.resolve()),
                "env_sh": str(args.env.resolve()),
                "env_fingerprint": env_fingerprint,
                "checkpoint_json": str(args.checkpoint.resolve()) if args.checkpoint else "",
            },
        })
        result = req.setdefault("build_result", {})
        if not isinstance(result, dict):
            result = {}
            req["build_result"] = result
        result.update({"status": "not_run", **meta})
        write_json_atomic(args.requirements_json, req)
        record_step(
            args.output.parent,
            "build_script_generated",
            "pass",
            inputs={
                "requirements_json": str(args.requirements_json.resolve()),
                "env_sh": str(args.env.resolve()),
            },
            outputs={"entity_build_sh": str(args.output.resolve())},
            run_id=run_id,
        )

    if args.json:
        protocol_ok("generate.build", output=str(args.output.resolve()))

# ===========================================================================
# Main
# ===========================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="subcommand")

    # --- deps ---
    p_deps = sub.add_parser("deps", help="Generate dependency source-build scripts")
    p_deps.add_argument("requirements_json", type=Path)
    p_deps.add_argument("--checkpoint", type=Path, required=True)
    p_deps.add_argument("--deps", help="Comma-separated deps: mpi,kokkos,hdf5,adios2")
    p_deps.add_argument("--output-dir", type=Path)
    p_deps.add_argument("--source-tarball-dir",
                        help="Directory with dependency source tarballs (e.g., kokkos-4.5.0.tar.gz). "
                             "Used as fallback when git clone fails.")
    p_deps.add_argument("--no-update-json", action="store_true")
    add_json_flag(p_deps)

    # --- env ---
    p_env = sub.add_parser("env", help="Generate env.sh from entity-deps.local.json")
    p_env.add_argument("json_path", type=Path)
    p_env.add_argument("--output", type=Path)
    p_env.add_argument("--allow-incomplete", action="store_true")
    p_env.add_argument("--allow-warnings", action="store_true",
                       help="Allow compatibility.status=warn only when decisions.compatibility_warnings_accepted is set.")
    p_env.add_argument("--no-update-json", action="store_true")
    add_json_flag(p_env)

    # --- build ---
    p_build = sub.add_parser("build", help="Generate entity-build.sh from requirements.json + env.sh")
    p_build.add_argument("requirements_json", type=Path)
    p_build.add_argument("--env", type=Path, required=True)
    p_build.add_argument("--checkpoint", type=Path, help="entity-deps.local.json for gate validation")
    p_build.add_argument("--output", type=Path)
    p_build.add_argument("--clean-build", action="store_true",
                         help="Remove build tree before cmake configure (disables incremental build)")
    p_build.add_argument("--reuse-build-dir", action="store_true",
                         help="Allow compile.build_dir to point at an existing non-empty "
                              "build tree (explicit confirmation of an in-place rebuild)")
    p_build.add_argument("--allow-warnings", action="store_true",
                         help="Allow compatibility.status=warn only when decisions.compatibility_warnings_accepted is set.")
    p_build.add_argument("--allow-stale-env", action="store_true",
                         help="Allow --env to differ from checkpoint env_sh.path. Use only for debugging.")
    p_build.add_argument("--no-update-json", action="store_true")
    p_build.add_argument("--run-id", help="Run ID for event log (auto-generated if omitted)")
    add_json_flag(p_build)

    args = parser.parse_args()

    if args.subcommand is None:
        parser.print_help()
        raise SystemExit(1)

    # Inject run_id for build subcommand
    if args.subcommand == "build":
        args._run_id = getattr(args, 'run_id', None) or _uuid.uuid4().hex[:8]

    if args.subcommand == "deps":
        cmd_deps(args)
    elif args.subcommand == "env":
        cmd_env(args)
    elif args.subcommand == "build":
        cmd_build(args)


if __name__ == "__main__":
    from _invocation_log import trace_invocation
    with trace_invocation("entity-env-build", "entity_generate.py", sys.argv[1:], script_file=__file__):
        main()
