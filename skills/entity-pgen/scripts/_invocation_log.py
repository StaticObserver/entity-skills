#!/usr/bin/env python3
"""Passive invocation logging for the Entity skill CLIs.

Append-only JSONL: one record per actual CLI invocation, accumulating
real-world usage data in production. This is deliberately separate from the
eval-time observability trace. NEVER breaks the host tool: every
failure in the logging path is swallowed, and the host's exit-code and
exception semantics propagate unchanged.

``ENTITY_SKILL_INVOCATION_LOG`` overrides the log path; the exact value
``off`` (case-insensitive) disables logging entirely (test suites use this
to keep their traffic out of the production log).

Standard library only; Python 3.6 compatible. Installed skills are
self-contained directories, so each skill ships a byte-identical copy of
this module under its own scripts/.
"""

import contextlib
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import time

SCHEMA_VERSION = 1
ENV_OVERRIDE = "ENTITY_SKILL_INVOCATION_LOG"
SECRET_RE = re.compile(
    r"token|secret|password|passwd|api[-_]?key|credential", re.IGNORECASE)
# Best-effort client attribution: presence of a well-known agent-client
# variable is recorded by NAME only (values may carry secrets).
AGENT_ENV_HINTS = (
    "KIMI_CLI", "KIMI_CODE",
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
    "CODEX_CLI", "CODEX_HOME",
)


def sanitize_argv(argv):
    """Redact values of secret-looking flags; the flag name itself stays.
    Handles both `--flag value` and `--flag=value` forms."""
    sanitized = []
    redact_next = False
    for arg in argv:
        arg = str(arg)
        if redact_next:
            sanitized.append("<redacted>")
            redact_next = False
            continue
        if arg.startswith("--"):
            name, separator, unused = arg[2:].partition("=")
            if SECRET_RE.search(name):
                sanitized.append(
                    "--%s=<redacted>" % name if separator else arg)
                if not separator:
                    redact_next = True
                continue
        sanitized.append(arg)
    return sanitized


def _log_path(now):
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return override
    return os.path.join(
        os.path.expanduser("~"), ".entity-skills", "observability",
        "invocations", now.strftime("%Y-%m") + ".jsonl")


def _logging_disabled():
    return os.environ.get(ENV_OVERRIDE, "").strip().lower() == "off"


def _agent_hint():
    hits = [name for name in AGENT_ENV_HINTS if os.environ.get(name)]
    return ",".join(hits) or None


def _skill_version(script_file):
    try:
        path = os.path.join(
            os.path.dirname(os.path.abspath(script_file)), os.pardir, "VERSION")
        with open(path) as handle:
            return handle.read().strip() or None
    except (OSError, IOError):
        return None


def _ppid_comm():
    try:
        out = subprocess.run(
            ["ps", "-o", "comm=", "-p", str(os.getppid())],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            universal_newlines=True, timeout=5)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def record(skill, script, argv, exit_code, started, error_type=None,
           script_file=None):
    """Append one invocation record. Every failure is swallowed by design."""
    with contextlib.suppress(Exception):
        if _logging_disabled():
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        entry = {
            "schema_version": SCHEMA_VERSION,
            "ts": now.isoformat().replace("+00:00", "Z"),
            "duration_ms": int((time.time() - started) * 1000),
            "skill": skill,
            "script": script,
            "argv": sanitize_argv(argv),
            "cwd": os.getcwd(),
            "exit_code": exit_code,
            "pid": os.getpid(),
            "host": socket.gethostname(),
        }
        if error_type:
            entry["error_type"] = error_type
        version = _skill_version(script_file or sys.argv[0])
        if version:
            entry["skill_version"] = version
        comm = _ppid_comm()
        if comm:
            entry["ppid_comm"] = comm
        hint = _agent_hint()
        if hint:
            entry["agent_hint"] = hint
        path = _log_path(now)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "a") as handle:
            handle.write(
                json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


@contextlib.contextmanager
def trace_invocation(skill, script, argv, script_file=None):
    """Thin wrapper around a CLI main: one record per invocation, with the
    host's SystemExit code and exceptions re-raised unchanged."""
    started = time.time()
    exit_code = 0
    error_type = None
    try:
        yield
    except SystemExit as exc:
        code = exc.code
        if code is None or isinstance(code, bool):
            exit_code = 0 if code is None else int(code)
        elif isinstance(code, int):
            exit_code = code
        else:
            exit_code = 1
            error_type = "SystemExit"
        raise
    except Exception as exc:  # noqa: BLE001 - re-raised unchanged
        exit_code = 1
        error_type = type(exc).__name__
        raise
    finally:
        record(skill, script, argv, exit_code, started, error_type,
               script_file=script_file)
