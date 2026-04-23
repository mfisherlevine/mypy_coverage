"""Smoke tests for all four output formats."""

from __future__ import annotations

import json
from pathlib import Path

from mypy_coverage.models import MypyConfig
from mypy_coverage.render import (
    Colors,
    render_github,
    render_json,
    render_markdown,
    render_text,
)
from mypy_coverage.report import build_report


from mypy_coverage.models import CoverageReport


def _report(fixtures_dir: Path, *files: str) -> CoverageReport:
    paths = [fixtures_dir / f for f in files]
    return build_report(paths, MypyConfig(), fixtures_dir)


class TestRenderText:
    def test_runs_and_contains_header(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        out = render_text(report, colors=Colors(enabled=False))
        assert "mypy-coverage" in out
        assert "Coverage:" in out
        assert "Breakdown:" in out

    def test_list_flag_shows_unannotated(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        out = render_text(report, list_uncovered=True, colors=Colors(enabled=False))
        assert "bare_one" in out
        assert "bare_two" in out

    def test_list_partial_flag_shows_partials(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        out = render_text(report, list_partial=True, colors=Colors(enabled=False))
        assert "partial_one" in out
        assert "partial_two" in out

    def test_colors_disabled_has_no_escape_codes(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        out = render_text(report, colors=Colors(enabled=False))
        assert "\x1b[" not in out

    def test_colors_enabled_has_escape_codes(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        out = render_text(report, colors=Colors(enabled=True))
        assert "\x1b[" in out


class TestRenderJson:
    def test_valid_json(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        parsed = json.loads(render_json(report))
        assert "summary" in parsed
        assert "definitions" in parsed
        assert parsed["summary"]["counts"]["annotated"] == 2
        assert parsed["summary"]["counts"]["unannotated"] == 2

    def test_definitions_have_expected_fields(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        parsed = json.loads(render_json(report))
        d = parsed["definitions"][0]
        for key in (
            "file",
            "lineno",
            "kind",
            "qualname",
            "status",
            "n_params",
            "decorators",
        ):
            assert key in d
        assert isinstance(d["decorators"], list)


class TestRenderMarkdown:
    def test_basic_structure(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        out = render_markdown(report)
        assert out.startswith("# mypy-coverage report")
        assert "| metric | value |" in out

    def test_lists_unannotated(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        out = render_markdown(report)
        assert "bare_one" in out
        assert "bare_two" in out


class TestRenderGithub:
    def test_produces_warnings_and_notices(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        out = render_github(report)
        assert "::warning " in out  # unannotated items
        assert "::notice " in out  # partial items

    def test_empty_when_everything_passes(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "fully_annotated.py")
        out = render_github(report)
        assert out == ""
