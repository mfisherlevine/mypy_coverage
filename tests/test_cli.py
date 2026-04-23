"""End-to-end CLI behaviour."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from mypy_coverage.cli import build_parser, main_cli, want_color


@pytest.fixture
def project_with_known_coverage(tmp_path: Path) -> Path:
    """Small project with exactly 50% coverage."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        dedent(
            """
            def typed(x: int) -> int: return x
            def untyped(x): return x
            """
        )
    )
    (tmp_path / "mypy.ini").write_text("[mypy]\nfiles = src/\n")
    return tmp_path


class TestBuildParser:
    def test_help_contains_key_options(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        for flag in ("--threshold", "--list", "--silent-any", "--format"):
            assert flag in help_text

    def test_version_flag_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["--version"])
        assert exc.value.code == 0


class TestWantColor:
    def test_always(self) -> None:
        assert want_color("always") is True

    def test_never(self) -> None:
        assert want_color("never") is False


class TestMainCli:
    def test_text_format_default(
        self, capsys: pytest.CaptureFixture[str], project_with_known_coverage: Path
    ) -> None:
        import os

        cwd = os.getcwd()
        os.chdir(project_with_known_coverage)
        try:
            code = main_cli(["--color", "never"])
        finally:
            os.chdir(cwd)
        assert code == 0
        out = capsys.readouterr().out
        assert "mypy-coverage" in out
        assert "Coverage:" in out

    def test_json_format(
        self, capsys: pytest.CaptureFixture[str], project_with_known_coverage: Path
    ) -> None:
        import os

        cwd = os.getcwd()
        os.chdir(project_with_known_coverage)
        try:
            code = main_cli(["--format", "json", "--color", "never"])
        finally:
            os.chdir(cwd)
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["summary"]["percent_fully_typed"] == 50.0

    def test_threshold_passes_when_coverage_high(
        self, capsys: pytest.CaptureFixture[str], project_with_known_coverage: Path
    ) -> None:
        import os

        cwd = os.getcwd()
        os.chdir(project_with_known_coverage)
        try:
            code = main_cli(["--threshold", "40", "--color", "never"])
        finally:
            os.chdir(cwd)
        assert code == 0

    def test_threshold_fails_when_coverage_low(
        self, capsys: pytest.CaptureFixture[str], project_with_known_coverage: Path
    ) -> None:
        import os

        cwd = os.getcwd()
        os.chdir(project_with_known_coverage)
        try:
            code = main_cli(["--threshold", "90", "--color", "never"])
        finally:
            os.chdir(cwd)
        assert code == 1
        err = capsys.readouterr().err
        assert "below threshold" in err

    def test_list_flag_lists_uncovered(
        self, capsys: pytest.CaptureFixture[str], project_with_known_coverage: Path
    ) -> None:
        import os

        cwd = os.getcwd()
        os.chdir(project_with_known_coverage)
        try:
            code = main_cli(["--list", "--color", "never"])
        finally:
            os.chdir(cwd)
        assert code == 0
        out = capsys.readouterr().out
        assert "untyped" in out

    def test_missing_path_returns_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main_cli([str(tmp_path / "does_not_exist")])
        assert code == 2
        err = capsys.readouterr().err
        assert "does not exist" in err

    def test_missing_config_returns_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main_cli(["--config", str(tmp_path / "nope.ini")])
        assert code == 2
        err = capsys.readouterr().err
        assert "config file not found" in err

    def test_sort_flag_reorders_per_file_table(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """``--sort coverage`` puts the worst file first, ``--sort path`` alphabetical."""
        (tmp_path / "z_worst.py").write_text("def a(x): return x\ndef b(x): return x\n")
        (tmp_path / "a_better.py").write_text(
            "def a(x: int) -> int: return x\ndef b(x): return x\n"
        )
        code = main_cli(["--sort", "path", "--color", "never", str(tmp_path)])
        assert code == 0
        out = capsys.readouterr().out
        assert out.index("a_better.py") < out.index("z_worst.py")

        code = main_cli(["--sort", "coverage", "--color", "never", str(tmp_path)])
        assert code == 0
        out = capsys.readouterr().out
        assert out.index("z_worst.py") < out.index("a_better.py")

    def _excluded_project(self, tmp_path: Path) -> Path:
        (tmp_path / "keep.py").write_text(
            "def a(x: int) -> int: return x\ndef uncov(x): return x\n"
        )
        (tmp_path / "skip.py").write_text("def b(x): return x\n")
        cfg = tmp_path / "mypy.ini"
        cfg.write_text("[mypy]\nexclude = ^skip\\.py$\n")
        return cfg

    def test_show_excluded_section_in_cli(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """End-to-end: the CLI emits a walled-off excluded-files section
        that doesn't affect the main totals."""
        cfg = self._excluded_project(tmp_path)
        code = main_cli(["--config", str(cfg), "--root", str(tmp_path), "--color", "never"])
        assert code == 0
        out = capsys.readouterr().out
        assert "Excluded files" in out
        # Main coverage is 50% from keep.py alone (1 / 2).
        assert "(1 / 2)" in out

    def test_no_include_excluded_hides_section(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """``--no-include-excluded`` suppresses the walled-off block but
        leaves the main totals untouched."""
        cfg = self._excluded_project(tmp_path)
        code = main_cli(
            [
                "--config",
                str(cfg),
                "--root",
                str(tmp_path),
                "--color",
                "never",
                "--no-include-excluded",
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "Excluded files" not in out
        # Main totals untouched: 50% still reported as (1 / 2).
        assert "(1 / 2)" in out

    def test_include_excluded_is_default(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Without any flag, the excluded section IS shown by default."""
        cfg = self._excluded_project(tmp_path)
        code = main_cli(["--config", str(cfg), "--root", str(tmp_path), "--color", "never"])
        assert code == 0
        out = capsys.readouterr().out
        assert "Excluded files" in out

    def test_show_excluded_implies_include_excluded(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """``--show-excluded`` alongside ``--no-include-excluded`` should
        win; hiding a section we're explicitly asked to enumerate would
        be contradictory."""
        cfg = self._excluded_project(tmp_path)
        code = main_cli(
            [
                "--config",
                str(cfg),
                "--root",
                str(tmp_path),
                "--color",
                "never",
                "--no-include-excluded",
                "--show-excluded",
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "Excluded files" in out
        # The listing (detail enumeration) should also be present.
        assert "unannotated" in out

    def test_no_include_excluded_markdown(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Markdown output honours the same flag."""
        cfg = self._excluded_project(tmp_path)
        code = main_cli(
            [
                "--config",
                str(cfg),
                "--root",
                str(tmp_path),
                "--color",
                "never",
                "--format",
                "markdown",
                "--no-include-excluded",
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "Excluded files" not in out

    def test_threshold_metric_fully_typed(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """fully-typed metric should be stricter than checked."""
        (tmp_path / "a.py").write_text(
            dedent(
                """
                def full(x: int) -> int: return x
                def partial(x: int):
                    return x
                """
            )
        )
        # Coverage: fully-typed = 50%, checked = 100%.
        # Threshold 90 on `checked` passes, but on `fully-typed` fails.
        code_checked = main_cli(
            [
                "--threshold",
                "90",
                "--threshold-metric",
                "checked",
                "--color",
                "never",
                str(tmp_path),
            ]
        )
        assert code_checked == 0
        capsys.readouterr()
        code_fully = main_cli(
            [
                "--threshold",
                "90",
                "--threshold-metric",
                "fully-typed",
                "--color",
                "never",
                str(tmp_path),
            ]
        )
        assert code_fully == 1
