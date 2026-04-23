"""Shared pytest helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the absolute path to the ``tests/fixtures/`` directory."""
    return FIXTURES


# Keep pytest from trying to import the fixture .py files as tests.
collect_ignore_glob = ["fixtures/*.py"]
