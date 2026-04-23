"""Aggregation pipeline: ``build_report`` and coverage percentages.

These tests use hand-crafted fixture files whose definition counts are
known exactly. Any regression in the classification or percentage math
will break them in an easy-to-diagnose way.
"""

from __future__ import annotations

from pathlib import Path

from mypy_coverage.models import (
    STATUS_ANNOTATED,
    STATUS_EXCLUDED,
    STATUS_PARTIAL,
    STATUS_UNANNOTATED,
    CoverageReport,
    Definition,
    MypyConfig,
)
from mypy_coverage.report import build_report, per_file_stats


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


class TestExcludedHandling:
    def test_excluded_files_are_separated(self, tmp_path: Path) -> None:
        # Lay out a tree and mark half as excluded.
        (tmp_path / "keep.py").write_text("def a(x: int) -> int: return x\n")
        (tmp_path / "skip.py").write_text("def b(x): return x\n")
        import re

        cfg = MypyConfig(exclude_regex=re.compile(r"skip\.py$"))
        report = build_report([tmp_path], cfg, tmp_path)
        # `b` is inside an excluded file -> status=excluded, and doesn't
        # count toward either metric.
        statuses = {d.qualname: d.status for d in report.definitions}
        assert statuses["a"] == STATUS_ANNOTATED
        assert statuses["b"] == STATUS_EXCLUDED
        assert report.percent_fully_typed() == 100.0

    def test_all_files_excluded_returns_100(self, tmp_path: Path) -> None:
        (tmp_path / "skip.py").write_text("def b(x): return x\n")
        import re

        cfg = MypyConfig(exclude_regex=re.compile(r"skip\.py$"))
        report = build_report([tmp_path], cfg, tmp_path)
        # Nothing countable -> 100% by convention.
        assert report.percent_fully_typed() == 100.0


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
