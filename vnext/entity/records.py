from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import EntityError


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_id(value: str, field: str = "id") -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise EntityError(
            f"{field} must match {ID_RE.pattern}: {value!r}",
            code="invalid_id",
        )
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EntityError(f"JSON file not found: {path}", code="not_found") from exc
    except json.JSONDecodeError as exc:
        raise EntityError(
            f"invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}",
            code="invalid_json",
        ) from exc
    if not isinstance(value, dict):
        raise EntityError(f"JSON root must be an object: {path}", code="invalid_json")
    return value


def load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return load_json(path)


def write_json(path: Path, value: dict[str, Any], *, replace: bool = True) -> None:
    if path.exists() and not replace:
        raise EntityError(f"record already exists: {path}", code="already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_text(path: Path, text: str, *, executable: bool = False, replace: bool = True) -> None:
    if path.exists() and not replace:
        raise EntityError(f"file already exists: {path}", code="already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if executable:
            os.chmod(temp_name, 0o755)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise EntityError(f"destination already exists: {destination}", code="already_exists")
    if not source.is_dir():
        raise EntityError(f"source directory not found: {source}", code="not_found")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)


def require_fields(record: dict[str, Any], fields: tuple[str, ...], path: Path) -> None:
    missing = [name for name in fields if record.get(name) in (None, "")]
    if missing:
        raise EntityError(
            f"missing fields in {path}: {', '.join(missing)}",
            code="invalid_record",
        )
