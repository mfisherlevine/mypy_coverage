"""Smoke tests for all four output formats."""

from __future__ import annotations

import json
import re
from pathlib import Path

from mypy_coverage.models import CoverageReport, MypyConfig
from mypy_coverage.render import (
    Colors,
    render_github,
    render_json,
    render_markdown,
    render_text,
)
from mypy_coverage.report import build_report


def _report(fixtures_dir: Path, *files: str) -> CoverageReport:
    paths = [fixtures_dir / f for f in files]
    return build_report(paths, MypyConfig(), fixtures_dir)


def _report_with_excluded(tmp_path: Path) -> CoverageReport:
    """Project with one kept file and one excluded file, both with gaps."""
    (tmp_path / "keep.py").write_text("def a(x: int) -> int: return x\ndef uncov(x): return x\n")
    (tmp_path / "skip.py").write_text("def b(x): return x\ndef c(x: int) -> int: return x\n")
    cfg = MypyConfig(exclude_regex=re.compile(r"skip\.py$"))
    return build_report([tmp_path], cfg, tmp_path)


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

    def test_excluded_files_never_annotated(self, tmp_path: Path) -> None:
        """No ``::warning`` / ``::notice`` for excluded files -- they'd
        just be noise, and mypy doesn't analyse them anyway."""
        report = _report_with_excluded(tmp_path)
        out = render_github(report)
        assert "uncov" in out  # main body flagged
        assert "skip.py" not in out  # excluded file never annotated


class TestExcludedSectionInText:
    """Excluded files get a walled-off section in the text output."""

    def test_excluded_section_present_when_any_excluded_defs(self, tmp_path: Path) -> None:
        report = _report_with_excluded(tmp_path)
        out = render_text(report, colors=Colors(enabled=False))
        assert "Excluded files" in out
        assert "NOT counted" in out or "not counted" in out

    def test_excluded_section_absent_when_no_excluded_defs(self, fixtures_dir: Path) -> None:
        report = _report(fixtures_dir, "with_partials.py")
        out = render_text(report, colors=Colors(enabled=False))
        assert "Excluded files" not in out

    def test_main_totals_ignore_excluded_defs(self, tmp_path: Path) -> None:
        """Main Coverage line should reflect only the kept file."""
        report = _report_with_excluded(tmp_path)
        out = render_text(report, colors=Colors(enabled=False))
        # 2 defs in keep.py: 1 annotated, 1 unannotated -> 50% fully typed.
        # Excluded file contributes nothing to main totals.
        lines = [line for line in out.splitlines() if "fully annotated" in line]
        assert lines
        assert "50.0%" in lines[0]
        assert "(1 / 2)" in lines[0]

    def test_excluded_section_reports_walled_off_stats(self, tmp_path: Path) -> None:
        """skip.py has 2 defs: 1 annotated, 1 unannotated. That 50% belongs
        to the walled-off section, not the main one."""
        report = _report_with_excluded(tmp_path)
        out = render_text(report, colors=Colors(enabled=False))
        # Split so we only inspect the excluded section.
        marker = "Excluded files"
        assert marker in out
        excluded_chunk = out[out.index(marker) :]
        assert "1 / 2" in excluded_chunk  # 1 annotated / 2 total
        assert "50.0%" in excluded_chunk

    def test_show_excluded_lists_definitions(self, tmp_path: Path) -> None:
        report = _report_with_excluded(tmp_path)
        out = render_text(report, show_excluded=True, colors=Colors(enabled=False))
        # Both excluded-file definitions should be listed with their real status.
        assert "b" in out
        assert "c" in out
        assert "unannotated" in out
        assert "annotated" in out

    def test_include_excluded_false_hides_section(self, tmp_path: Path) -> None:
        report = _report_with_excluded(tmp_path)
        out = render_text(report, include_excluded=False, colors=Colors(enabled=False))
        assert "Excluded files" not in out
        # The main totals must be unchanged (still based on keep.py only).
        assert "(1 / 2)" in out

    def test_include_excluded_default_true(self, tmp_path: Path) -> None:
        """Sanity: default keyword value keeps the section visible."""
        report = _report_with_excluded(tmp_path)
        out = render_text(report, colors=Colors(enabled=False))
        assert "Excluded files" in out


class TestIncludeExcludedInMarkdown:
    def test_include_excluded_false_hides_section(self, tmp_path: Path) -> None:
        report = _report_with_excluded(tmp_path)
        out = render_markdown(report, include_excluded=False)
        assert "Excluded files" not in out

    def test_include_excluded_true_emits_section(self, tmp_path: Path) -> None:
        report = _report_with_excluded(tmp_path)
        out = render_markdown(report, include_excluded=True)
        assert "Excluded files" in out


class TestSortByInRenders:
    """The ``sort_by`` argument reorders the per-file tables without
    changing their contents."""

    def _three_file_report(self, tmp_path: Path) -> CoverageReport:
        (tmp_path / "z_worst.py").write_text("def a(x): return x\ndef b(x): return x\n")
        (tmp_path / "m_mid.py").write_text("def a(x: int) -> int: return x\ndef b(x): return x\n")
        (tmp_path / "a_best.py").write_text("def a(x: int) -> int: return x\ndef b(x): return x\n")
        return build_report([tmp_path], MypyConfig(), tmp_path)

    def test_path_sort_default_puts_files_alphabetically(self, tmp_path: Path) -> None:
        report = self._three_file_report(tmp_path)
        out = render_text(report, colors=Colors(enabled=False))
        a_idx = out.index("a_best.py")
        m_idx = out.index("m_mid.py")
        z_idx = out.index("z_worst.py")
        assert a_idx < m_idx < z_idx

    def test_coverage_sort_puts_worst_first(self, tmp_path: Path) -> None:
        report = self._three_file_report(tmp_path)
        out = render_text(report, sort_by="coverage", colors=Colors(enabled=False))
        z_idx = out.index("z_worst.py")
        m_idx = out.index("m_mid.py")
        a_idx = out.index("a_best.py")
        # z_worst has 0% and should come first; the two 50% files follow
        # tie-broken alphabetically, so a_best then m_mid.
        assert z_idx < a_idx < m_idx
