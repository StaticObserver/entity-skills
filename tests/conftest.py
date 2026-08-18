#!/usr/bin/env python3
"""Shared pytest fixtures: keep test traffic out of the production
invocation log (I1) — every CLI the suite spawns inherits the kill switch;
tests that exercise the log itself override the variable explicitly."""

import pytest


@pytest.fixture(autouse=True)
def _invocation_log_off(monkeypatch):
    monkeypatch.setenv("ENTITY_SKILL_INVOCATION_LOG", "off")
