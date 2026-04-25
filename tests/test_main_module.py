"""``python -m mypy_coverage`` entry point."""

from __future__ import annotations

import subprocess
import sys

from mypy_coverage import __version__


def test_dash_m_runs_and_reports_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mypy_coverage", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert __version__ in result.stdout
