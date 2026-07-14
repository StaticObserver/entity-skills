#!/usr/bin/env python3
"""Validate requirements.json and construct entity-deps.local.json.

Subcommands:
  validate <requirements.json>
  create <requirements.json> [--merge <old.json>] [--from-discovery <discovery.json>]
  record-install --checkpoint <entity-deps.local.json> --dep <name> ...
"""

import argparse
import json
import os
import platform
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from _json_io import (
    add_json_flag,
    derive_paths,
    get_dotted,
    load_json,
    protocol_error,
    protocol_ok,
    write_json_atomic,
)
from _version_profile import version_profile as detect_version_profile
from entity_state import record_step
from entity_schema import CONSISTENCY_RULES, OPTIONAL_DEFAULTS, REQUIRED_ALWAYS, REQUIRED_BUILD


# ===========================================================================
# Shared helpers
# ===========================================================================


def _has(obj: Dict[str, Any], dotted: str) -> bool:
    val = get_dotted(obj, dotted)
    if val is None:
        return False
    if isinstance(val, str) and val == "":
        return False
    return True


def requirements_snapshot(req: Dict[str, Any]) -> Dict[str, Any]:
    """Return the request fields that make a dependency checkpoint reusable."""
    entity = req.get("entity", {}) if isinstance(req.get("entity"), dict) else {}
    env = req.get("environment", {}) if isinstance(req.get("environment"), dict) else {}
    compile_cfg = req.get("compile", {}) if isinstance(req.get("compile"), dict) else {}
    return {
        "entity": {
            "checkout_root": entity.get("checkout_root", ""),
            "workdir": entity.get("workdir", ""),
            "version_bucket": entity.get("version_bucket", ""),
            "dependency_profile": entity.get("dependency_profile", ""),
        },
        "environment": {
            "backend": env.get("backend", ""),
            "output": env.get("output", True),
            "mpi": env.get("mpi", False),
            "gpu_aware_mpi": env.get("gpu_aware_mpi", False),
        },
        "compile": {
            "pgen": compile_cfg.get("pgen", ""),
            "pgens": compile_cfg.get("pgens", ""),
            "cxx_standard": compile_cfg.get("cxx_standard", ""),
            "precision": compile_cfg.get("precision", ""),
            "deposit": compile_cfg.get("deposit", ""),
            "shape_order": compile_cfg.get("shape_order", ""),
            "debug": compile_cfg.get("debug", False),
            "tests": compile_cfg.get("tests", False),
            "build_intent": compile_cfg.get("build_intent", ""),
        },
    }


# ===========================================================================
# Subcommand: validate
# ===========================================================================


def check_required(req: Dict[str, Any], fields: List[str], phase: str) -> List[Dict[str, str]]:
    missing: List[Dict[str, str]] = []
    for path in fields:
        if not _has(req, path):
            missing.append({"field": path, "phase": phase})
    return missing


def check_consistency(req: Dict[str, Any]) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    for rule_id, condition, pair, msg in CONSISTENCY_RULES:
        if condition:
            cond_field, cond_val = condition
            actual = get_dotted(req, cond_field)
            if actual is None or str(actual).lower() != cond_val:
                continue

        field_a, field_b = pair
        val_a = get_dotted(req, field_a)
        if field_b:
            val_b = get_dotted(req, field_b)
            if rule_id == "pgen.mutex" and val_a is not None and val_b is not None:
                issues.append({"rule": rule_id, "message": msg, "fields": [field_a, field_b]})
        else:
            if val_a is None or (isinstance(val_a, str) and val_a == ""):
                issues.append({"rule": rule_id, "message": msg, "fields": [field_a]})

    return issues


def run_validation(req: Dict[str, Any]) -> Dict[str, Any]:
    always_missing = check_required(req, REQUIRED_ALWAYS, "always")
    build_missing = check_required(req, REQUIRED_BUILD, "build")
    missing_fields = always_missing + build_missing
    consistency_issues = check_consistency(req)
    unsupported_version = False
    try:
        detect_version_profile(req)
    except (ValueError, SystemExit) as exc:
        unsupported_version = True
        consistency_issues.append({
            "rule": "entity.version.supported",
            "message": str(exc),
            "fields": ["entity.version_bucket", "entity.dependency_profile"],
        })

    status = "pass"
    if missing_fields or unsupported_version:
        status = "fail"
    elif consistency_issues:
        status = "partial"

    return {
        "status": status,
        "missing_fields": missing_fields,
        "consistency_issues": consistency_issues,
    }


def cmd_validate(args: argparse.Namespace) -> None:
    if not args.requirements_json.exists():
        result = {
            "status": "fail",
            "missing_fields": [{"field": "(file)", "phase": "always"}],
            "consistency_issues": [],
        }
        if args.json:
            protocol_error("checkpoint.validate", "File not found", result=result)
        print(json.dumps(result))
        raise SystemExit(1)

    req = load_json(args.requirements_json)
    result = run_validation(req)
    blocking = result["status"] == "fail" or (
        result["status"] == "partial" and not args.allow_partial
    )
    if result["status"] == "pass":
        record_step(
            args.requirements_json.parent,
            "requirements_validated",
            "pass",
            inputs={"requirements_json": str(args.requirements_json.resolve())},
        )

    if args.json:
        if blocking:
            protocol_error("checkpoint.validate", "Validation failed", result=result)
        protocol_ok("checkpoint.validate", result=result)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
        if blocking:
            raise SystemExit(1)


# ===========================================================================
# Subcommand: create
# ===========================================================================


def detect_target() -> Dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "arch": platform.machine(),
        "shell": os.environ.get("SHELL", "bash"),
        "context": "login",
    }


def build_checkpoint(
    req: Dict[str, Any],
    discovery: Optional[Dict[str, Any]] = None,
    merge_from: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    entity = req.get("entity", {})
    workdir = str(entity.get("workdir", "")) if isinstance(entity, dict) else ""

    if not workdir:
        workdir = os.environ.get("ENTITY_WORKDIR", "")
    if not workdir:
        raise SystemExit("ENTITY_WORKDIR must be set or present in requirements.entity.workdir")

    selected: Dict[str, Any] = {}
    if discovery and isinstance(discovery, dict):
        for dep, entry in discovery.items():
            if isinstance(entry, dict):
                selected[dep] = dict(entry)

    if merge_from and isinstance(merge_from, dict):
        merge_selected = merge_from.get("selected", {})
        if isinstance(merge_selected, dict):
            for dep, entry in merge_selected.items():
                if isinstance(entry, dict) and dep not in selected:
                    selected[dep] = dict(entry)
        merge_decisions = merge_from.get("decisions", {})
        decisions = merge_decisions if isinstance(merge_decisions, dict) and merge_decisions else {}
    else:
        decisions = {}

    profile = detect_version_profile(req)

    checkout_root = str(entity.get("checkout_root", "")) if isinstance(entity, dict) else ""
    version_bucket = str(entity.get("version_bucket", "")) if isinstance(entity, dict) else ""
    dep_profile = (
        str(entity.get("dependency_profile", profile.get("name", "")))
        if isinstance(entity, dict)
        else ""
    )

    checkpoint: Dict[str, Any] = {
        "schema_version": 1,
        "generated_at": now,
        "requirements": {
            "path": "",
            "embedded": requirements_snapshot(req),
        },
        "target": detect_target(),
        "entity": {
            "checkout_root": checkout_root,
            "version_bucket": version_bucket,
            "dependency_profile": dep_profile,
            "workdir": workdir,
        },
        "candidates": {},
        "selected": selected,
        "decisions": decisions,
        "paths": derive_paths(selected),
        "build_scripts": {
            "directory": str(Path(workdir) / "generated" / "source-build-scripts"),
            "generated_at": now,
            "scripts": {},
        },
        "compatibility": {
            "status": "unknown",
            "checked_at": "",
            "checks": [],
            "issues": [],
        },
        "env_sh": {
            "path": str(Path(workdir) / "env.sh"),
            "status": "missing",
            "generated_at": "",
            "validation": {},
        },
        "status": {
            "checkpoint": "partial",
            "satisfies_requirements_json": False,
            "ready_for_entity_build": False,
            "reuse_notes": [],
        },
    }

    return checkpoint


def cmd_create(args: argparse.Namespace) -> None:
    req = load_json(args.requirements_json)

    discovery = None
    if args.from_discovery:
        discovery = load_json(args.from_discovery)

    merge_from = None
    if args.merge:
        if args.merge.exists():
            merge_from = load_json(args.merge)

    checkpoint = build_checkpoint(req, discovery, merge_from)

    if args.output:
        output_path = args.output
    else:
        workdir = str(
            (req.get("entity", {}) if isinstance(req.get("entity"), dict) else {})
            .get("workdir", "")
            or os.environ.get("ENTITY_WORKDIR", "")
        )
        if not workdir:
            msg = "Cannot determine output path: use --output or set ENTITY_WORKDIR"
            if args.json:
                protocol_error("checkpoint.create", msg)
            raise SystemExit(msg)
        output_path = Path(workdir) / "entity-deps.local.json"

    checkpoint["requirements"]["path"] = str(args.requirements_json.resolve())
    write_json_atomic(output_path, checkpoint)
    record_step(
        output_path.parent,
        "checkpoint_updated",
        "pass",
        inputs={"requirements_json": str(args.requirements_json.resolve())},
        outputs={"checkpoint_json": str(output_path.resolve())},
        message="checkpoint created",
    )

    if args.json:
        protocol_ok("checkpoint.create", output=str(output_path.resolve()))
    else:
        print(f"entity-deps.local.json written to {output_path.resolve()}")


# ===========================================================================
# Subcommand: record-install
# ===========================================================================


ALLOWED_DEPS = {"cmake", "compiler", "gpu_toolkit", "mpi", "kokkos", "hdf5", "adios2"}


def _path_if_set(value: Optional[Path], kind: str) -> str:
    if value is None:
        return ""
    if kind == "dir" and not value.is_dir():
        raise SystemExit(f"{kind} path does not exist or is not a directory: {value}")
    if kind == "file" and not value.is_file():
        raise SystemExit(f"{kind} path does not exist or is not a file: {value}")
    if kind == "exists" and not value.exists():
        raise SystemExit(f"path does not exist: {value}")
    return str(value.resolve())


def cmd_record_install(args: argparse.Namespace) -> None:
    checkpoint = load_json(args.checkpoint)
    dep = args.dep.lower()
    if dep not in ALLOWED_DEPS:
        raise SystemExit(f"unsupported dependency: {args.dep}")

    prefix = _path_if_set(args.prefix, "dir")
    cmake_config = _path_if_set(args.cmake_config, "file")
    bin_path = _path_if_set(args.bin, "exists")
    include = _path_if_set(args.include, "dir")
    lib = _path_if_set(args.lib, "exists")
    log_path = _path_if_set(args.log, "file")

    if not (prefix or cmake_config or bin_path):
        raise SystemExit("record-install requires at least one of --prefix, --cmake-config, or --bin")

    selected = checkpoint.setdefault("selected", {})
    if not isinstance(selected, dict):
        selected = {}
        checkpoint["selected"] = selected

    existing = selected.get(dep, {})
    if not isinstance(existing, dict):
        existing = {}

    now = datetime.now(timezone.utc).isoformat()
    entry: Dict[str, Any] = dict(existing)
    entry.update({
        "name": dep,
        "provider": args.provider,
        "validation": {
            **(existing.get("validation", {}) if isinstance(existing.get("validation"), dict) else {}),
            "installed": True,
            "recorded_at": now,
        },
    })
    if args.version:
        entry["version"] = args.version
    if prefix:
        entry["prefix"] = prefix
    if bin_path:
        entry["bin"] = bin_path
    if include:
        entry["include"] = include
    if lib:
        entry["lib"] = lib
    if cmake_config:
        entry["cmake_config"] = cmake_config
    if args.compiler_signature:
        entry["compiler_signature"] = args.compiler_signature
    if args.mpi_signature:
        entry["mpi_signature"] = args.mpi_signature
    if log_path:
        validation = entry.setdefault("validation", {})
        if isinstance(validation, dict):
            validation["install_log"] = log_path

    selected[dep] = entry
    checkpoint["paths"] = derive_paths(selected)
    checkpoint["compatibility"] = {
        "status": "unknown",
        "checked_at": "",
        "checks": [],
        "issues": ["dependency install record changed; rerun compatibility check"],
    }
    status = checkpoint.setdefault("status", {})
    if isinstance(status, dict):
        status["checkpoint"] = "partial"
        status["ready_for_entity_build"] = False

    write_json_atomic(args.checkpoint, checkpoint)
    record_step(
        args.checkpoint.parent,
        "checkpoint_updated",
        "pass",
        inputs={"checkpoint_json": str(args.checkpoint.resolve())},
        outputs={"checkpoint_json": str(args.checkpoint.resolve())},
        message=f"recorded {dep} install evidence",
    )
    if args.json:
        protocol_ok("checkpoint.record_install", checkpoint=str(args.checkpoint.resolve()), dep=dep)
    else:
        print(f"recorded {dep} install evidence in {args.checkpoint.resolve()}")


# ===========================================================================
# Main
# ===========================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="subcommand")

    # --- validate ---
    p_val = sub.add_parser("validate", help="Validate requirements.json completeness and consistency")
    p_val.add_argument("requirements_json", type=Path)
    p_val.add_argument("--allow-partial", action="store_true",
                       help="Exit 0 for consistency issues. Use only while drafting requirements.")
    add_json_flag(p_val)

    # --- create ---
    p_cre = sub.add_parser("create", help="Construct entity-deps.local.json from requirements.json")
    p_cre.add_argument("requirements_json", type=Path, help="Path to requirements.json")
    p_cre.add_argument("--from-discovery", type=Path, dest="from_discovery",
                       help="JSON file with dependency candidate entries")
    p_cre.add_argument("--merge", type=Path, dest="merge",
                       help="Existing entity-deps.local.json to merge selected/decisions from")
    p_cre.add_argument("--output", type=Path,
                       help="Output path (default: $ENTITY_WORKDIR/entity-deps.local.json)")
    add_json_flag(p_cre)

    # --- record-install ---
    p_rec = sub.add_parser("record-install", help="Record installed dependency evidence in checkpoint JSON")
    p_rec.add_argument("--checkpoint", type=Path, required=True, help="entity-deps.local.json to update")
    p_rec.add_argument("--dep", required=True, help="Dependency name: cmake, compiler, gpu_toolkit, mpi, kokkos, hdf5, adios2")
    p_rec.add_argument("--provider", default="source-build",
                       choices=["module", "system", "local-prefix", "source-build", "entity-dependencies", "unknown", "none"])
    p_rec.add_argument("--prefix", type=Path)
    p_rec.add_argument("--cmake-config", type=Path, dest="cmake_config")
    p_rec.add_argument("--bin", type=Path)
    p_rec.add_argument("--include", type=Path)
    p_rec.add_argument("--lib", type=Path)
    p_rec.add_argument("--version", default="")
    p_rec.add_argument("--compiler-signature", default="")
    p_rec.add_argument("--mpi-signature", default="")
    p_rec.add_argument("--log", type=Path)
    add_json_flag(p_rec)

    args = parser.parse_args()
    if args.subcommand is None:
        parser.print_help()
        raise SystemExit(1)
    if args.subcommand == "validate":
        cmd_validate(args)
    elif args.subcommand == "create":
        cmd_create(args)
    elif args.subcommand == "record-install":
        cmd_record_install(args)


if __name__ == "__main__":
    main()
