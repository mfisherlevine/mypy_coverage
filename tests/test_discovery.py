"""File discovery and exclude regex matching."""

from __future__ import annotations

import re
from pathlib import Path

from mypy_coverage.discovery import (
    discover_files,
    display_path,
    is_excluded,
    iter_python_files,
)
from mypy_coverage.models import MypyConfig


def touch(p: Path, content: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class TestIterPythonFiles:
    def test_single_file(self, tmp_path: Path) -> None:
        f = touch(tmp_path / "a.py")
        assert list(iter_python_files(f)) == [f]

    def test_non_python_file(self, tmp_path: Path) -> None:
        f = touch(tmp_path / "a.txt")
        assert list(iter_python_files(f)) == []

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        assert list(iter_python_files(tmp_path / "missing")) == []

    def test_walks_directory(self, tmp_path: Path) -> None:
        touch(tmp_path / "a.py")
        touch(tmp_path / "sub" / "b.py")
        touch(tmp_path / "sub" / "deeper" / "c.py")
        touch(tmp_path / "skip.txt")
        files = sorted(p.name for p in iter_python_files(tmp_path))
        assert files == ["a.py", "b.py", "c.py"]

    def test_skips_junk_directories(self, tmp_path: Path) -> None:
        touch(tmp_path / "a.py")
        touch(tmp_path / ".git" / "config.py")
        touch(tmp_path / "__pycache__" / "x.py")
        touch(tmp_path / ".mypy_cache" / "x.py")
        touch(tmp_path / ".venv" / "x.py")
        touch(tmp_path / "venv" / "x.py")
        files = sorted(p.name for p in iter_python_files(tmp_path))
        assert files == ["a.py"]


class TestIsExcluded:
    def test_no_regex_never_excludes(self, tmp_path: Path) -> None:
        cfg = MypyConfig()
        assert is_excluded(tmp_path / "x.py", cfg, tmp_path) is False

    def test_matches_relative_path(self, tmp_path: Path) -> None:
        cfg = MypyConfig(exclude_regex=re.compile(r"^skip/"))
        touch(tmp_path / "skip" / "x.py")
        assert is_excluded(tmp_path / "skip" / "x.py", cfg, tmp_path) is True

    def test_does_not_match_unrelated_files(self, tmp_path: Path) -> None:
        cfg = MypyConfig(exclude_regex=re.compile(r"^skip/"))
        touch(tmp_path / "src" / "x.py")
        assert is_excluded(tmp_path / "src" / "x.py", cfg, tmp_path) is False


class TestDiscoverFiles:
    def test_separates_included_and_excluded(self, tmp_path: Path) -> None:
        cfg = MypyConfig(exclude_regex=re.compile(r"^skip/"))
        touch(tmp_path / "src" / "a.py")
        touch(tmp_path / "skip" / "b.py")
        included, excluded = discover_files([tmp_path], cfg, tmp_path)
        assert [p.name for p in included] == ["a.py"]
        assert [p.name for p in excluded] == ["b.py"]

    def test_deduplicates_across_paths(self, tmp_path: Path) -> None:
        touch(tmp_path / "a.py")
        cfg = MypyConfig()
        # Passing the same path twice should yield one entry, not two.
        included, _ = discover_files([tmp_path, tmp_path], cfg, tmp_path)
        assert len(included) == 1

    def test_sorted_output(self, tmp_path: Path) -> None:
        touch(tmp_path / "b.py")
        touch(tmp_path / "a.py")
        touch(tmp_path / "c.py")
        cfg = MypyConfig()
        included, _ = discover_files([tmp_path], cfg, tmp_path)
        assert [p.name for p in included] == ["a.py", "b.py", "c.py"]


class TestDisplayPath:
    def test_relative_to_root(self, tmp_path: Path) -> None:
        p = tmp_path / "src" / "a.py"
        p.parent.mkdir()
        p.write_text("")
        assert display_path(p, tmp_path) == "src/a.py"

    def test_fallback_when_outside_root(self, tmp_path: Path) -> None:
        outside = Path("/tmp/does_not_matter.py")
        result = display_path(outside, tmp_path)
        assert result == outside.as_posix()

    def test_no_root(self, tmp_path: Path) -> None:
        p = tmp_path / "a.py"
        assert display_path(p, None) == p.as_posix()
