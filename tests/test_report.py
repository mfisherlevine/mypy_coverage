"""Aggregation pipeline: ``build_report`` and coverage percentages.

These tests use hand-crafted fixture files whose definition counts are
known exactly. Any regression in the classification or percentage math
will break them in an easy-to-diagnose way.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mypy_coverage.models import (
    STATUS_ANNOTATED,
    STATUS_PARTIAL,
    STATUS_UNANNOTATED,
    CoverageReport,
    Definition,
    MypyConfig,
)
from mypy_coverage.report import SORT_COVERAGE, SORT_PATH, build_report, per_file_stats


def function_defs(report: CoverageReport) -> list[Definition]:
    """Report definitions excluding classes (makes math simpler to reason about)."""
    return [d for d in report.definitions if d.kind != "class"]


def _empty_cfg() -> MypyConfig:
    return MypyConfig()


class TestCoveragePercentages:
    def test_fully_annotated_gives_100(self, fixtures_dir: Path) -> None:
        report = build_report([fixtures_dir / "fully_annotated.py"], _empty_cfg(), fixtures_dir)
        assert report.percent_fully_typed() == 100.0
        assert report.percent_checked() == 100.0

    def test_fully_unannotated_gives_correct_split(self, fixtures_dir: Path) -> None:
        """Classes count as annotated; only functions/methods are unannotated."""
        report = build_report([fixtures_dir / "fully_unannotated.py"], _empty_cfg(), fixtures_dir)
        fns = function_defs(report)
        assert fns
        assert all(d.status == STATUS_UNANNOTATED for d in fns)
        # Every function/method is unannotated; class defs bump the
        # numerator by 1 each (there's one class in the file).
        classes = [d for d in report.definitions if d.kind == "class"]
        assert len(classes) == 1
        expected_fully = 100.0 * len(classes) / len(report.definitions)
        assert abs(report.percent_fully_typed() - expected_fully) < 1e-9

    def test_exact_50_percent(self, fixtures_dir: Path) -> None:
        """3 annotated + 3 unannotated functions -> exactly 50%."""
        report = build_report([fixtures_dir / "exact_50pct.py"], _empty_cfg(), fixtures_dir)
        fns = function_defs(report)
        annotated = sum(1 for d in fns if d.status == STATUS_ANNOTATED)
        unannotated = sum(1 for d in fns if d.status == STATUS_UNANNOTATED)
        assert annotated == 3
        assert unannotated == 3

    def test_partial_contributes_to_checked_but_not_fully(self, fixtures_dir: Path) -> None:
        """2 annotated, 2 partial, 2 unannotated over 6 function defs."""
        report = build_report([fixtures_dir / "with_partials.py"], _empty_cfg(), fixtures_dir)
        fns = function_defs(report)
        ann = sum(1 for d in fns if d.status == STATUS_ANNOTATED)
        part = sum(1 for d in fns if d.status == STATUS_PARTIAL)
        unann = sum(1 for d in fns if d.status == STATUS_UNANNOTATED)
        assert (ann, part, unann) == (2, 2, 2)
        # Only functions in this file -- no classes, so percentages are on
        # pure function counts.
        assert abs(report.percent_fully_typed() - (100.0 * 2 / 6)) < 1e-9
        assert abs(report.percent_checked() - (100.0 * 4 / 6)) < 1e-9

    def test_empty_file_gives_100(self, fixtures_dir: Path) -> None:
        report = build_report([fixtures_dir / "empty.py"], _empty_cfg(), fixtures_dir)
        # No definitions at all -> coverage is trivially 100%.
        assert report.percent_fully_typed() == 100.0
        assert report.percent_checked() == 100.0


class TestCoverageIsByCountNotLines:
    """The whole point of this pair of fixtures."""

    def test_long_bodies(self, fixtures_dir: Path) -> None:
        report = build_report([fixtures_dir / "long_bodies.py"], _empty_cfg(), fixtures_dir)
        fns = function_defs(report)
        assert len(fns) == 2
        assert report.percent_fully_typed() == 50.0

    def test_short_bodies(self, fixtures_dir: Path) -> None:
        report = build_report([fixtures_dir / "short_bodies.py"], _empty_cfg(), fixtures_dir)
        fns = function_defs(report)
        assert len(fns) == 2
        assert report.percent_fully_typed() == 50.0

    def test_long_and_short_give_identical_percentages(self, fixtures_dir: Path) -> None:
        """Body length must not influence coverage."""
        long_r = build_report([fixtures_dir / "long_bodies.py"], _empty_cfg(), fixtures_dir)
        short_r = build_report([fixtures_dir / "short_bodies.py"], _empty_cfg(), fixtures_dir)
        assert long_r.percent_fully_typed() == short_r.percent_fully_typed()
        assert long_r.percent_checked() == short_r.percent_checked()


def _excluded_regex_cfg(pattern: str) -> MypyConfig:
    return MypyConfig(exclude_regex=re.compile(pattern))


class TestExcludedHandling:
    """Excluded files: definitions are classified normally but walled off.

    The contract: they don't count toward the main percentages, they
    show their real annotation status, and they're queryable via the
    ``in_excluded_file`` flag.
    """

    def test_excluded_def_keeps_real_status(self, tmp_path: Path) -> None:
        (tmp_path / "keep.py").write_text("def a(x: int) -> int: return x\n")
        (tmp_path / "skip.py").write_text("def b(x): return x\n")
        report = build_report([tmp_path], _excluded_regex_cfg(r"skip\.py$"), tmp_path)
        by_q = {d.qualname: d for d in report.definitions}
        assert by_q["a"].status == STATUS_ANNOTATED
        assert by_q["a"].in_excluded_file is False
        # `b` gets the real classification, not a special "excluded" status.
        assert by_q["b"].status == STATUS_UNANNOTATED
        assert by_q["b"].in_excluded_file is True

    def test_excluded_def_does_not_count_toward_main(self, tmp_path: Path) -> None:
        (tmp_path / "keep.py").write_text("def a(x: int) -> int: return x\n")
        (tmp_path / "skip.py").write_text("def b(x): return x\n")
        report = build_report([tmp_path], _excluded_regex_cfg(r"skip\.py$"), tmp_path)
        # Main metrics: just `a`, fully annotated -> 100%.
        assert report.percent_fully_typed() == 100.0
        assert report.percent_checked() == 100.0
        assert report.counts()["total"] == 1
        assert report.counts()[STATUS_ANNOTATED] == 1

    def test_excluded_side_metrics_report_reality(self, tmp_path: Path) -> None:
        """Excluded files expose their real coverage on the side."""
        (tmp_path / "skip.py").write_text("def b(x): return x\ndef c(x: int) -> int: return x\n")
        report = build_report([tmp_path], _excluded_regex_cfg(r"skip\.py$"), tmp_path)
        assert report.counts(in_excluded_file=True)["total"] == 2
        assert report.counts(in_excluded_file=True)[STATUS_ANNOTATED] == 1
        assert report.counts(in_excluded_file=True)[STATUS_UNANNOTATED] == 1
        assert report.percent_fully_typed(in_excluded_file=True) == 50.0
        assert report.percent_checked(in_excluded_file=True) == 50.0
        # And the main metrics are unaffected.
        assert report.percent_fully_typed() == 100.0

    def test_all_files_excluded_main_returns_100(self, tmp_path: Path) -> None:
        (tmp_path / "skip.py").write_text("def b(x): return x\n")
        report = build_report([tmp_path], _excluded_regex_cfg(r"skip\.py$"), tmp_path)
        # Nothing in the main body to count -> 100% by convention.
        assert report.percent_fully_typed() == 100.0
        # But excluded-side metric still reports the reality.
        assert report.percent_fully_typed(in_excluded_file=True) == 0.0

    def test_excluded_per_file_stats(self, tmp_path: Path) -> None:
        (tmp_path / "keep.py").write_text("def a(x: int) -> int: return x\n")
        (tmp_path / "skip.py").write_text("def b(x): return x\n")
        report = build_report([tmp_path], _excluded_regex_cfg(r"skip\.py$"), tmp_path)
        # Main per-file stats: `keep.py` is clean, so nothing shown.
        assert per_file_stats(report) == []
        # Excluded-side per-file stats surface `skip.py`.
        ex = per_file_stats(report, in_excluded_file=True, include_clean_files=True)
        assert len(ex) == 1
        assert ex[0]["file"] == "skip.py"
        assert ex[0]["unannotated"] == 1


class TestUnparseableFiles:
    def test_broken_file_recorded(self, fixtures_dir: Path) -> None:
        report = build_report([fixtures_dir / "syntax_broken.py"], _empty_cfg(), fixtures_dir)
        assert len(report.unparseable) == 1
        assert report.definitions == []


class TestPerFileStats:
    def test_omits_files_with_no_gaps(self, tmp_path: Path) -> None:
        (tmp_path / "good.py").write_text("def a(x: int) -> int: return x\n")
        report = build_report([tmp_path], _empty_cfg(), tmp_path)
        assert per_file_stats(report) == []

    def test_reports_files_with_gaps(self, tmp_path: Path) -> None:
        (tmp_path / "bad.py").write_text("def a(x: int) -> int: return x\ndef b(x): return x\n")
        report = build_report([tmp_path], _empty_cfg(), tmp_path)
        stats = per_file_stats(report)
        assert len(stats) == 1
        assert stats[0]["annotated"] == 1
        assert stats[0]["unannotated"] == 1
        assert stats[0]["fully_pct"] == 50.0
        assert stats[0]["checked_pct"] == 50.0

    def test_truncate_path(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "very" / "deep" / "path" / "hidden.py"
        deep.parent.mkdir(parents=True)
        deep.write_text("def bad(x): return x\n")
        report = build_report([tmp_path], _empty_cfg(), tmp_path)
        stats = per_file_stats(report, truncate_path=20)
        assert stats[0]["file"].startswith("...")
        assert len(stats[0]["file"]) == 20


class TestCountsDict:
    def test_counts_breakdown(self, fixtures_dir: Path) -> None:
        report = build_report([fixtures_dir / "with_partials.py"], _empty_cfg(), fixtures_dir)
        counts = report.counts()
        assert counts[STATUS_ANNOTATED] == 2
        assert counts[STATUS_PARTIAL] == 2
        assert counts[STATUS_UNANNOTATED] == 2
        assert counts["function"] == 6
        assert counts["total"] == 6

    def test_counts_excluded_is_separate(self, tmp_path: Path) -> None:
        (tmp_path / "keep.py").write_text("def a(x: int) -> int: return x\n")
        (tmp_path / "skip.py").write_text("def b(x): return x\n")
        report = build_report([tmp_path], _excluded_regex_cfg(r"skip\.py$"), tmp_path)
        assert report.counts()["total"] == 1
        assert report.counts(in_excluded_file=True)["total"] == 1
        assert (
            report.counts()[STATUS_ANNOTATED]
            + report.counts(in_excluded_file=True)[STATUS_UNANNOTATED]
            == 2
        )


class TestPerFileSorting:
    """``sort_by`` controls per-file ordering without changing content."""

    def _three_files(self, tmp_path: Path) -> CoverageReport:
        # Three files at different coverage levels, named in anti-sorted order
        # so alphabetical != coverage-based.
        (tmp_path / "z_worst.py").write_text("def a(x): return x\ndef b(x): return x\n")
        (tmp_path / "m_middle.py").write_text(
            "def a(x: int) -> int: return x\ndef b(x): return x\n"
        )
        (tmp_path / "a_best.py").write_text("def a(x: int) -> int: return x\ndef b(x): return x\n")
        # Note: m_middle and a_best have identical coverage; a_best wins
        # alphabetically as the tiebreaker.
        return build_report([tmp_path], _empty_cfg(), tmp_path)

    def test_default_sort_is_path(self, tmp_path: Path) -> None:
        report = self._three_files(tmp_path)
        entries = per_file_stats(report)
        assert [e["file"] for e in entries] == [
            "a_best.py",
            "m_middle.py",
            "z_worst.py",
        ]

    def test_explicit_path_sort(self, tmp_path: Path) -> None:
        report = self._three_files(tmp_path)
        entries = per_file_stats(report, sort_by=SORT_PATH)
        assert [e["file"] for e in entries] == [
            "a_best.py",
            "m_middle.py",
            "z_worst.py",
        ]

    def test_coverage_sort_puts_worst_first(self, tmp_path: Path) -> None:
        report = self._three_files(tmp_path)
        entries = per_file_stats(report, sort_by=SORT_COVERAGE)
        # z_worst (0%) first, then the two 50%s tiebroken alphabetically.
        assert entries[0]["file"] == "z_worst.py"
        assert entries[0]["fully_pct"] == 0.0
        assert entries[1]["fully_pct"] == 50.0
        assert entries[2]["fully_pct"] == 50.0
        # Tiebreak: alphabetical within equal coverage.
        assert entries[1]["file"] == "a_best.py"
        assert entries[2]["file"] == "m_middle.py"

    def test_invalid_sort_key_raises(self, tmp_path: Path) -> None:
        report = self._three_files(tmp_path)
        with pytest.raises(ValueError):
            per_file_stats(report, sort_by="bogus")

    def test_include_clean_files_adds_fully_typed_files(self, tmp_path: Path) -> None:
        (tmp_path / "clean.py").write_text("def a(x: int) -> int: return x\n")
        (tmp_path / "dirty.py").write_text("def b(x): return x\n")
        report = build_report([tmp_path], _empty_cfg(), tmp_path)
        default_entries = per_file_stats(report)
        assert [e["file"] for e in default_entries] == ["dirty.py"]
        all_entries = per_file_stats(report, include_clean_files=True)
        assert [e["file"] for e in all_entries] == ["clean.py", "dirty.py"]
