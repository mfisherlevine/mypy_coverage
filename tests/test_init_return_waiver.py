"""Trust, but verify: cross-check the scanner against real mypy.

The scanner claims mypy waives the ``-> None`` return annotation for
``__init__`` / ``__init_subclass__``. This test proves it by running mypy on
tests/fixtures/init_methods.py and confirming, for every definition, that the
scanner's status bucket agrees with what mypy actually does.

Each fixture method body is the single expression ``42 + "abc"``. Under
``--disallow-untyped-defs --disallow-incomplete-defs`` (and crucially WITHOUT
``--check-untyped-defs``), mypy's output reveals each definition's bucket:

    error on def line?   error on body line?   bucket
    -------------------  --------------------  -----------
    no                   yes (body checked)    ANNOTATED  (fully typed)
    yes                  yes (body checked)    PARTIAL    (checked but incomplete)
    yes                  no  (body skipped)    UNANNOTATED (untyped)

This mapping depends only on *where* errors land, not on mypy's exact wording,
so it is stable across mypy versions.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from mypy_coverage.models import STATUS_ANNOTATED, STATUS_PARTIAL, STATUS_UNANNOTATED
from mypy_coverage.scanner import scan_file

pytest.importorskip("mypy")

FIXTURE = Path(__file__).parent / "fixtures" / "init_methods.py"
ERROR_LINE = re.compile(r":(\d+): error:")


def _mypy_error_lines(target: Path, cwd: Path, cache_dir: Path) -> set[int]:
    """Return the set of line numbers mypy reports an error on."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--disallow-untyped-defs",
            "--disallow-incomplete-defs",
            "--no-error-summary",
            "--no-color-output",
            "--cache-dir",
            str(cache_dir),
            str(target),
        ],
        capture_output=True,
        text=True,
        # Run from a config-free dir so the repo's strict pyproject (which
        # excludes fixtures) doesn't interfere.
        cwd=str(cwd),
    )
    return {int(m.group(1)) for m in ERROR_LINE.finditer(proc.stdout)}


def _mypy_bucket(def_line: int, body_line: int, error_lines: set[int]) -> str:
    def_err = def_line in error_lines
    body_err = body_line in error_lines
    if not def_err and body_err:
        return STATUS_ANNOTATED
    if def_err and body_err:
        return STATUS_PARTIAL
    if def_err and not body_err:
        return STATUS_UNANNOTATED
    raise AssertionError(
        f"mypy reported no error on def line {def_line} or body line {body_line}; "
        "cannot classify (expected a deliberate type error in every body)"
    )


def test_scanner_agrees_with_mypy(tmp_path: Path) -> None:
    target = tmp_path / "init_methods.py"
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    error_lines = _mypy_error_lines(target, cwd=tmp_path, cache_dir=tmp_path / ".mypy_cache")

    defs, ok = scan_file(target)
    assert ok
    callables = [d for d in defs if d.kind != "class"]
    assert callables, "fixture produced no function/method definitions"

    mismatches: list[str] = []
    for d in callables:
        mypy_status = _mypy_bucket(d.lineno, d.lineno + 1, error_lines)
        if d.status != mypy_status:
            mismatches.append(
                f"{d.qualname} (line {d.lineno}): scanner={d.status} mypy={mypy_status}"
            )
    assert not mismatches, "scanner disagrees with mypy:\n" + "\n".join(mismatches)

    # Guard against a degenerate pass: all three buckets must be exercised.
    seen = {d.status for d in callables}
    assert seen == {STATUS_ANNOTATED, STATUS_PARTIAL, STATUS_UNANNOTATED}
