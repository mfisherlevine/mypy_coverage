"""--silent-any detection."""

from __future__ import annotations

import ast
from pathlib import Path
from textwrap import dedent

from mypy_coverage.models import MypyConfig
from mypy_coverage.silent_any import decorator_head, module_matches, scan_silent_any


def write(p: Path, src: str) -> Path:
    p.write_text(dedent(src))
    return p


class TestModuleMatches:
    def test_exact(self) -> None:
        assert module_matches("foo", {"foo"})
        assert not module_matches("bar", {"foo"})

    def test_dot_star_wildcard(self) -> None:
        assert module_matches("foo.bar", {"foo.*"})
        assert module_matches("foo.bar.baz", {"foo.*"})
        assert not module_matches("fooother.bar", {"foo.*"})

    def test_fnmatch_wildcard(self) -> None:
        assert module_matches("plugin_x", {"plugin_*"})


class TestScanSilentAny:
    def test_imports_from_ignored_module_flagged(self, tmp_path: Path) -> None:
        p = write(
            tmp_path / "a.py",
            """
            from somelib import thing
            from normal import other
            """,
        )
        cfg = MypyConfig(ignored_modules={"somelib"})
        hits = scan_silent_any(p, cfg, root=tmp_path)
        kinds = [h.kind for h in hits]
        assert "ignored-import" in kinds
        details = [h.detail for h in hits if h.kind == "ignored-import"]
        assert any("somelib" in d for d in details)
        assert not any("normal" in d for d in details)

    def test_plain_import_from_ignored_module(self, tmp_path: Path) -> None:
        p = write(tmp_path / "a.py", "import batoid\nimport normal_pkg\n")
        cfg = MypyConfig(ignored_modules={"batoid"})
        hits = scan_silent_any(p, cfg, root=tmp_path)
        details = [h.detail for h in hits if h.kind == "ignored-import"]
        assert any("batoid" in d for d in details)
        assert not any("normal_pkg" in d for d in details)

    def test_type_ignore_comment_flagged(self, tmp_path: Path) -> None:
        p = write(
            tmp_path / "a.py",
            """
            x = 1  # type: ignore[assignment]
            y = 2
            """,
        )
        hits = scan_silent_any(p, MypyConfig(), root=tmp_path)
        ignores = [h for h in hits if h.kind == "type-ignore"]
        assert len(ignores) == 1
        assert ignores[0].lineno == 2  # dedent leaves line 1 blank

    def test_decorator_from_ignored_module(self, tmp_path: Path) -> None:
        p = write(
            tmp_path / "a.py",
            """
            from somelib import deco

            @deco
            def wrapped():
                pass
            """,
        )
        cfg = MypyConfig(ignored_modules={"somelib"})
        hits = scan_silent_any(p, cfg, root=tmp_path)
        untyped_decs = [h for h in hits if h.kind == "untyped-decorator"]
        assert len(untyped_decs) == 1
        assert "deco" in untyped_decs[0].detail
        assert "wrapped" in untyped_decs[0].detail

    def test_decorator_from_normal_module_not_flagged(self, tmp_path: Path) -> None:
        p = write(
            tmp_path / "a.py",
            """
            from normal import deco

            @deco
            def wrapped():
                pass
            """,
        )
        cfg = MypyConfig(ignored_modules=set())
        hits = scan_silent_any(p, cfg, root=tmp_path)
        assert all(h.kind != "untyped-decorator" for h in hits)

    def test_syntax_error_returns_empty(self, tmp_path: Path) -> None:
        p = write(tmp_path / "a.py", "def broken(\n")
        hits = scan_silent_any(p, MypyConfig(), root=tmp_path)
        assert hits == []

    def test_hits_sorted_by_line(self, tmp_path: Path) -> None:
        p = write(
            tmp_path / "a.py",
            """
            import batoid
            x = 1  # type: ignore[assignment]
            from batoid import other
            y = 2  # type: ignore[assignment]
            """,
        )
        cfg = MypyConfig(ignored_modules={"batoid"})
        hits = scan_silent_any(p, cfg, root=tmp_path)
        linenos = [h.lineno for h in hits]
        assert linenos == sorted(linenos)


class TestDecoratorHead:
    def _parse_dec(self, src: str) -> ast.expr:
        node = ast.parse(src).body[0]
        assert isinstance(node, ast.FunctionDef)
        return node.decorator_list[0]

    def test_name(self) -> None:
        target = self._parse_dec("@foo\ndef f(): pass")
        assert decorator_head(target) == "foo"

    def test_attribute(self) -> None:
        target = self._parse_dec("@foo.bar.baz\ndef f(): pass")
        assert decorator_head(target) == "foo"

    def test_call(self) -> None:
        # Our scanner calls decorator_head on the unwrapped .func of a Call.
        node = ast.parse("@foo(1, 2)\ndef f(): pass").body[0]
        assert isinstance(node, ast.FunctionDef)
        dec = node.decorator_list[0]
        assert isinstance(dec, ast.Call)
        assert decorator_head(dec.func) == "foo"
