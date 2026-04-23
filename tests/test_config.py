"""Config loading/discovery for mypy.ini, setup.cfg, and pyproject.toml."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from mypy_coverage.config import (
    _parse_bool,
    _split_files,
    discover_config,
    load_config,
)


class TestParseBool:
    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "yes", "1", "on"])
    def test_true_values(self, val: str) -> None:
        assert _parse_bool(val) is True

    @pytest.mark.parametrize("val", ["false", "no", "0", "off", "", "nope"])
    def test_false_values(self, val: str) -> None:
        assert _parse_bool(val) is False


class TestSplitFiles:
    def test_comma_separated(self) -> None:
        assert _split_files("a, b,c") == ["a", "b", "c"]

    def test_newline_separated(self) -> None:
        assert _split_files("a\nb\nc") == ["a", "b", "c"]

    def test_mixed(self) -> None:
        assert _split_files("a,\nb\n,c") == ["a", "b", "c"]

    def test_strips_trailing_slash(self) -> None:
        assert _split_files("src/, tests/") == ["src", "tests"]


class TestLoadIniConfig:
    def test_basic(self, tmp_path: Path) -> None:
        p = tmp_path / "mypy.ini"
        p.write_text(
            dedent(
                """
                [mypy]
                check_untyped_defs = True
                files = src/, tests/
                mypy_path = python
                exclude = ^build/|^dist/
                """
            )
        )
        cfg = load_config(p)
        assert cfg.check_untyped_defs is True
        assert cfg.files == ["src", "tests"]
        assert cfg.mypy_path == ["python"]
        assert cfg.exclude_regex is not None
        assert cfg.exclude_regex.search("build/foo.py")
        assert not cfg.exclude_regex.search("src/foo.py")

    def test_ignore_missing_imports_per_module(self, tmp_path: Path) -> None:
        p = tmp_path / "mypy.ini"
        p.write_text(
            dedent(
                """
                [mypy]
                check_untyped_defs = False

                [mypy-somelib]
                ignore_missing_imports = True

                [mypy-other_pkg.*]
                ignore_missing_imports = True

                [mypy-not_ignored]
                ignore_missing_imports = False
                """
            )
        )
        cfg = load_config(p)
        assert cfg.ignored_modules == {"somelib", "other_pkg.*"}

    def test_missing_mypy_section_leaves_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "setup.cfg"
        p.write_text("[other]\nkey = value\n")
        cfg = load_config(p)
        assert cfg.check_untyped_defs is False
        assert cfg.files == []
        assert cfg.ignored_modules == set()

    def test_setup_cfg_uses_mypy_section(self, tmp_path: Path) -> None:
        p = tmp_path / "setup.cfg"
        p.write_text("[mypy]\ncheck_untyped_defs = True\n")
        cfg = load_config(p)
        assert cfg.check_untyped_defs is True

    def test_verbose_regex_exclude(self, tmp_path: Path) -> None:
        """Mypy's ``(?x)`` verbose-mode exclude with whitespace and newlines."""
        p = tmp_path / "mypy.ini"
        p.write_text(
            dedent(
                r"""
                [mypy]
                exclude = (?x)
                    ^legacy/.*
                    | ^ build/.*
                """
            )
        )
        cfg = load_config(p)
        assert cfg.exclude_regex is not None
        assert cfg.exclude_regex.search("legacy/foo.py")
        assert cfg.exclude_regex.search("build/foo.py")
        assert not cfg.exclude_regex.search("src/foo.py")


class TestLoadTomlConfig:
    def test_basic(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text(
            dedent(
                """
                [tool.mypy]
                check_untyped_defs = true
                files = ["src", "tests"]
                mypy_path = "python"
                exclude = ["^build/", "^dist/"]

                [[tool.mypy.overrides]]
                module = "somelib"
                ignore_missing_imports = true

                [[tool.mypy.overrides]]
                module = ["other_pkg.*", "yet_another"]
                ignore_missing_imports = true

                [[tool.mypy.overrides]]
                module = "not_ignored"
                ignore_missing_imports = false
                """
            )
        )
        cfg = load_config(p)
        assert cfg.check_untyped_defs is True
        assert cfg.files == ["src", "tests"]
        assert cfg.mypy_path == ["python"]
        assert cfg.exclude_regex is not None
        assert cfg.exclude_regex.search("build/a.py")
        assert cfg.ignored_modules == {"somelib", "other_pkg.*", "yet_another"}

    def test_empty_tool_mypy_returns_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text("[other]\nx = 1\n")
        cfg = load_config(p)
        assert cfg.check_untyped_defs is False
        assert cfg.files == []

    def test_string_exclude(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text('[tool.mypy]\nexclude = "^build/"\n')
        cfg = load_config(p)
        assert cfg.exclude_regex is not None
        assert cfg.exclude_regex.search("build/x.py")


class TestLoadConfigErrors:
    def test_unknown_extension_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        p.write_text("mypy: {}\n")
        with pytest.raises(ValueError):
            load_config(p)


class TestDiscoverConfig:
    def test_finds_mypy_ini(self, tmp_path: Path) -> None:
        (tmp_path / "mypy.ini").write_text("[mypy]\ncheck_untyped_defs = True\n")
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        found = discover_config(sub)
        assert found == tmp_path / "mypy.ini"

    def test_finds_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.mypy]\n")
        found = discover_config(tmp_path)
        assert found == tmp_path / "pyproject.toml"

    def test_pyproject_without_mypy_section_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\n')
        assert discover_config(tmp_path) is None

    def test_prefers_mypy_ini_over_pyproject(self, tmp_path: Path) -> None:
        """Our candidate order lists ``mypy.ini`` first."""
        (tmp_path / "mypy.ini").write_text("[mypy]\n")
        (tmp_path / "pyproject.toml").write_text("[tool.mypy]\n")
        assert discover_config(tmp_path) == tmp_path / "mypy.ini"

    def test_no_config_returns_none(self, tmp_path: Path) -> None:
        assert discover_config(tmp_path) is None
