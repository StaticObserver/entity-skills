#!/usr/bin/env python3
"""Executable entrypoint for the package-level skill observability collector."""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from skill_observability.cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())

