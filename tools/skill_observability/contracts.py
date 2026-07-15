"""Runtime contract validation mirrored by the bundled JSON Schemas.

The observability tool intentionally uses only the Python standard library.
The JSON Schema files are the portable contract; these checks provide the
same fail-closed behavior without adding a runtime jsonschema dependency.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVENT_TYPES = {
    "run.started",
    "run.finished",
    "run.failed",
    "skill.exposed",
    "skill.resource_observed",
    "decision.recorded",
    "tool.started",
    "tool.finished",
    "state.transition_observed",
    "artifact.observed",
    "validation.finished",
    "error.observed",
}
SOURCE_KINDS = {"collector", "agent", "worker", "tool", "validator", "adapter"}
EVIDENCE_LEVELS = {"declared", "observed", "verified"}
PHASES = {"orient", "decide", "execute", "verify", "finish"}
TERMINAL_STATUSES = {"completed", "failed", "incomplete"}


class ContractError(ValueError):
    """Raised when an observability record violates its public contract."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], required: Iterable[str], label: str) -> None:
    expected = set(required)
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ContractError(f"{label} missing keys: {', '.join(missing)}")
    if extra:
        raise ContractError(f"{label} has unknown keys: {', '.join(extra)}")


def _string(value: Any, label: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ContractError(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{label} must be an integer >= {minimum}")
    return value


def _optional_integer(value: Any, label: str) -> None:
    if value is not None:
        _integer(value, label)


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{label} must be a boolean")
    return value


def _sha256(value: Any, label: str) -> str:
    text = _string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise ContractError(f"{label} must be a lowercase SHA-256 hex digest")
    return text


def _timestamp(value: Any, label: str) -> str:
    text = _string(value, label)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return text


def _enum(value: Any, choices: Sequence[str] | set[str], label: str) -> str:
    text = _string(value, label)
    if text not in choices:
        raise ContractError(f"{label} must be one of: {', '.join(sorted(choices))}")
    return text


def validate_manifest(value: Any) -> Dict[str, Any]:
    obj = _mapping(value, "manifest")
    keys = {
        "schema_version", "run_id", "task", "variant", "agent", "tools",
        "skills", "capture", "started_at",
    }
    _exact_keys(obj, keys, "manifest")
    if obj["schema_version"] != SCHEMA_VERSION:
        raise ContractError("manifest.schema_version must be 1")
    _string(obj["run_id"], "manifest.run_id")
    _string(obj["variant"], "manifest.variant")
    _timestamp(obj["started_at"], "manifest.started_at")

    task = _mapping(obj["task"], "manifest.task")
    _exact_keys(task, {"case_id", "input_ref", "input_sha256"}, "manifest.task")
    _string(task["case_id"], "manifest.task.case_id")
    _string(task["input_ref"], "manifest.task.input_ref")
    _sha256(task["input_sha256"], "manifest.task.input_sha256")

    agent = _mapping(obj["agent"], "manifest.agent")
    _exact_keys(agent, {"provider", "model", "configuration"}, "manifest.agent")
    for key in ("provider", "model"):
        _string(agent[key], f"manifest.agent.{key}")
    _sha256(agent["configuration"], "manifest.agent.configuration")

    tools = _mapping(obj["tools"], "manifest.tools")
    _exact_keys(tools, {"profile", "configuration"}, "manifest.tools")
    _string(tools["profile"], "manifest.tools.profile")
    _sha256(tools["configuration"], "manifest.tools.configuration")

    skills = obj["skills"]
    if not isinstance(skills, list):
        raise ContractError("manifest.skills must be an array")
    seen_names = set()
    for index, item in enumerate(skills):
        skill = _mapping(item, f"manifest.skills[{index}]")
        skill_keys = {
            "name", "source", "package_revision", "content_sha256", "dirty", "exposure",
        }
        _exact_keys(skill, skill_keys, f"manifest.skills[{index}]")
        name = _string(skill["name"], f"manifest.skills[{index}].name")
        if name in seen_names:
            raise ContractError(f"manifest.skills contains duplicate name: {name}")
        seen_names.add(name)
        source = Path(_string(skill["source"], f"manifest.skills[{index}].source"))
        if not source.is_absolute():
            raise ContractError(f"manifest.skills[{index}].source must be absolute")
        revision = skill["package_revision"]
        if revision is not None:
            _string(revision, f"manifest.skills[{index}].package_revision")
        _sha256(skill["content_sha256"], f"manifest.skills[{index}].content_sha256")
        if skill["dirty"] is not None:
            _bool(skill["dirty"], f"manifest.skills[{index}].dirty")
        _enum(skill["exposure"], {"injected", "available", "unknown"},
              f"manifest.skills[{index}].exposure")

    capture = _mapping(obj["capture"], "manifest.capture")
    capture_keys = {"raw_input", "raw_tool_output", "decision_records", "protected_roots"}
    _exact_keys(capture, capture_keys, "manifest.capture")
    for key in ("raw_input", "raw_tool_output", "decision_records"):
        _bool(capture[key], f"manifest.capture.{key}")
    roots = capture["protected_roots"]
    if not isinstance(roots, list):
        raise ContractError("manifest.capture.protected_roots must be an array")
    normalized = []
    for index, root in enumerate(roots):
        path = Path(_string(root, f"manifest.capture.protected_roots[{index}]"))
        if not path.is_absolute():
            raise ContractError("manifest.capture.protected_roots entries must be absolute")
        normalized.append(str(path))
    if len(normalized) != len(set(normalized)):
        raise ContractError("manifest.capture.protected_roots must be unique")
    return dict(obj)


def validate_event(value: Any) -> Dict[str, Any]:
    obj = _mapping(value, "event")
    keys = {
        "schema_version", "event_id", "run_id", "seq", "time", "type", "source",
        "evidence_level", "phase", "span_id", "parent_span_id", "payload",
    }
    _exact_keys(obj, keys, "event")
    if obj["schema_version"] != SCHEMA_VERSION:
        raise ContractError("event.schema_version must be 1")
    _string(obj["event_id"], "event.event_id")
    _string(obj["run_id"], "event.run_id")
    _integer(obj["seq"], "event.seq", minimum=1)
    _timestamp(obj["time"], "event.time")
    _enum(obj["type"], EVENT_TYPES, "event.type")
    source = _mapping(obj["source"], "event.source")
    _exact_keys(source, {"kind", "id"}, "event.source")
    _enum(source["kind"], SOURCE_KINDS, "event.source.kind")
    _string(source["id"], "event.source.id")
    _enum(obj["evidence_level"], EVIDENCE_LEVELS, "event.evidence_level")
    _enum(obj["phase"], PHASES, "event.phase")
    _string(obj["span_id"], "event.span_id")
    if obj["parent_span_id"] is not None:
        _string(obj["parent_span_id"], "event.parent_span_id")
    _mapping(obj["payload"], "event.payload")
    return dict(obj)


def validate_artifact(value: Any) -> Dict[str, Any]:
    obj = _mapping(value, "artifact")
    keys = {
        "schema_version", "artifact_id", "run_id", "role", "locator", "media_type",
        "sha256", "size_bytes", "produced_by", "authority",
    }
    _exact_keys(obj, keys, "artifact")
    if obj["schema_version"] != SCHEMA_VERSION:
        raise ContractError("artifact.schema_version must be 1")
    for key in ("artifact_id", "run_id", "role", "media_type", "produced_by", "authority"):
        _string(obj[key], f"artifact.{key}")
    locator = _mapping(obj["locator"], "artifact.locator")
    _exact_keys(locator, {"site_id", "path"}, "artifact.locator")
    _string(locator["site_id"], "artifact.locator.site_id")
    path = Path(_string(locator["path"], "artifact.locator.path"))
    if not path.is_absolute():
        raise ContractError("artifact.locator.path must be absolute")
    _sha256(obj["sha256"], "artifact.sha256")
    _integer(obj["size_bytes"], "artifact.size_bytes")
    return dict(obj)


def validate_result(value: Any) -> Dict[str, Any]:
    obj = _mapping(value, "result")
    keys = {
        "schema_version", "run_id", "terminal_status", "last_seq", "decisions",
        "tool_calls", "artifacts", "validations", "usage", "terminal_event_id",
    }
    _exact_keys(obj, keys, "result")
    if obj["schema_version"] != SCHEMA_VERSION:
        raise ContractError("result.schema_version must be 1")
    _string(obj["run_id"], "result.run_id")
    _enum(obj["terminal_status"], TERMINAL_STATUSES, "result.terminal_status")
    _integer(obj["last_seq"], "result.last_seq")
    _integer(obj["decisions"], "result.decisions")
    _integer(obj["artifacts"], "result.artifacts")
    tool_calls = _mapping(obj["tool_calls"], "result.tool_calls")
    _exact_keys(tool_calls, {"total", "failed"}, "result.tool_calls")
    _integer(tool_calls["total"], "result.tool_calls.total")
    _integer(tool_calls["failed"], "result.tool_calls.failed")
    validations = _mapping(obj["validations"], "result.validations")
    _exact_keys(validations, {"pass", "fail", "unknown"}, "result.validations")
    for key in ("pass", "fail", "unknown"):
        _integer(validations[key], f"result.validations.{key}")
    usage = _mapping(obj["usage"], "result.usage")
    _exact_keys(usage, {"input_tokens", "output_tokens", "wall_time_ms"}, "result.usage")
    for key in ("input_tokens", "output_tokens", "wall_time_ms"):
        _optional_integer(usage[key], f"result.usage.{key}")
    if obj["terminal_event_id"] is not None:
        _string(obj["terminal_event_id"], "result.terminal_event_id")
    return dict(obj)
