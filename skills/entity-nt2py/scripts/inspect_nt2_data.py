#!/usr/bin/env python3
"""Inspect nt2py metadata.

Field and particle data arrays are never loaded, and Dask-backed arrays
are only counted.  Small index arrays (coordinates, particle steps/times)
are read into memory so they can be summarized."""

import argparse
import json
import logging
import math
import sys
import warnings as py_warnings
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = 1
# Baseline nt2py version the bundled references were written against (see
# "The bundled references target nt2py vX.Y.Z" in ../SKILL.md).  Bump this
# by hand, together with the SKILL.md statement and the references, whenever
# the references are revalidated against a newer nt2py release.
REFERENCE_VERSION = "1.5.3"


class _MessageHandler(logging.Handler):
    def __init__(self, messages: List[str]) -> None:
        super().__init__(level=logging.WARNING)
        self._messages = messages

    def emit(self, record: logging.LogRecord) -> None:
        self._messages.append("{}: {}".format(record.levelname, record.getMessage()))


def _unique(messages: List[str]) -> List[str]:
    result = []
    seen = set()
    for message in messages:
        if message not in seen:
            seen.add(message)
            result.append(message)
    return result


def _json_scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _summarize_array(values: Any) -> Dict[str, Any]:
    import numpy as np

    array = np.asarray(values).reshape(-1)
    summary: Dict[str, Any] = {"count": int(array.size)}
    if array.size == 0:
        return summary

    summary["first"] = _json_scalar(array[0])
    summary["last"] = _json_scalar(array[-1])
    try:
        if np.issubdtype(array.dtype, np.number):
            summary["min"] = _json_scalar(np.nanmin(array))
            summary["max"] = _json_scalar(np.nanmax(array))
    except (TypeError, ValueError):
        pass
    return summary


def _summarize_coordinates(dataset: Any) -> Dict[str, Dict[str, Any]]:
    coordinates: Dict[str, Dict[str, Any]] = {}
    for name in sorted(dataset.coords):
        coordinate = dataset.coords[name]
        backing = coordinate.data
        if type(backing).__module__.startswith("dask"):
            coordinates[str(name)] = {
                "count": int(coordinate.size),
                "lazy": True,
            }
        else:
            coordinates[str(name)] = _summarize_array(backing)
    return coordinates


def _summarize_dataset(dataset: Any, defined: bool) -> Dict[str, Any]:
    return {
        "defined": bool(defined),
        "dimensions": {str(k): int(v) for k, v in dataset.sizes.items()},
        "variables": sorted(str(k) for k in dataset.data_vars),
        "coordinates": _summarize_coordinates(dataset),
    }


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _probe(data_root: Path, messages: List[str]) -> Dict[str, Any]:
    import nt2
    from nt2.utils import DetermineDataFormat

    installed_version = str(nt2.__version__)
    if installed_version != REFERENCE_VERSION:
        messages.append(
            "Installed nt2py {} differs from reference baseline {}.".format(
                installed_version, REFERENCE_VERSION
            )
        )

    logger = logging.getLogger()
    handler = _MessageHandler(messages)
    logger.addHandler(handler)
    caught = []
    try:
        with py_warnings.catch_warnings(record=True) as caught:
            py_warnings.simplefilter("always")
            data = nt2.Data(str(data_root))
    finally:
        logger.removeHandler(handler)
        for warning in caught:
            messages.append(
                "{}: {}".format(warning.category.__name__, str(warning.message))
            )

    fields = _summarize_dataset(data.fields, data.fields_defined)
    spectra = _summarize_dataset(data.spectra, data.spectra_defined)

    particles: Dict[str, Any] = {"defined": bool(data.particles_defined)}
    if data.particles_defined and data.particles is not None:
        particles.update(
            {
                "species": [int(v) for v in data.particles.species],
                "steps": _summarize_array(data.particles.steps),
                "times": _summarize_array(data.particles.times),
                "columns": [str(v) for v in data.particles.columns],
            }
        )
    else:
        particles.update(
            {"species": [], "steps": {"count": 0}, "times": {"count": 0}, "columns": []}
        )

    diagnostics = data.diagnostics
    diagnostics_summary: Dict[str, Any] = {
        "available": diagnostics is not None,
        "rows": 0,
        "columns": [],
    }
    if diagnostics is not None:
        diagnostics_summary.update(
            {
                "rows": int(len(diagnostics)),
                "columns": [str(v) for v in diagnostics.columns],
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "reference_version": REFERENCE_VERSION,
        "nt2py_version": installed_version,
        "version_match": installed_version == REFERENCE_VERSION,
        "data_root": str(data_root),
        "format": DetermineDataFormat(str(data_root)).value,
        "coordinate_system": data.coordinate_system.value,
        "attribute_keys": sorted(str(k) for k in data.attrs),
        "fields": fields,
        "particles": particles,
        "spectra": spectra,
        "diagnostics": diagnostics_summary,
        "warnings": _unique(messages),
    }


def _base_result(data_root: Path) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "error",
        "reference_version": REFERENCE_VERSION,
        "nt2py_version": None,
        "version_match": False,
        "data_root": str(data_root),
        "warnings": [],
    }


def _write_json(result: Dict[str, Any], output: Optional[Path]) -> None:
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    print(rendered)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect nt2py metadata. Loads small index arrays (coordinates, "
            "particle steps/times) for summarizing; never loads field or "
            "particle data arrays."
        )
    )
    parser.add_argument("data_root", type=Path, help="Directory containing fields/particles/spectra")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON mirror outside the Entity data root",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    data_root = args.data_root.expanduser().resolve()
    output = args.output.expanduser().resolve() if args.output is not None else None
    result = _base_result(data_root)
    output_is_safe = output is None or not _is_within(output, data_root)
    messages: List[str] = []

    try:
        if not data_root.is_dir():
            raise ValueError("Data root is not a directory: {}".format(data_root))
        if not output_is_safe:
            raise ValueError("Refusing to write probe output inside the Entity data root")
        result = _probe(data_root, messages)
    except Exception as exc:
        try:
            import nt2

            result["nt2py_version"] = str(nt2.__version__)
            result["version_match"] = str(nt2.__version__) == REFERENCE_VERSION
        except Exception:
            pass
        if data_root.is_dir():
            try:
                from nt2.utils import DetermineDataFormat

                result["format"] = DetermineDataFormat(str(data_root)).value
            except Exception:
                pass
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        result["warnings"] = _unique(messages)
        _write_json(result, output if output_is_safe else None)
        return 1

    _write_json(result, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
