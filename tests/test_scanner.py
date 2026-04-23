"""AST scanner: how it classifies every definition shape."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mypy_coverage.models import (
    STATUS_ANNOTATED,
    STATUS_EXCLUDED,
    STATUS_PARTIAL,
    STATUS_UNANNOTATED,
)
from mypy_coverage.scanner import (
    classify_function,
    count_annotated_params,
    decorator_names,
    expr_to_dotted_name,
    partial_reason,
    scan_file,
)


from mypy_coverage.models import Definition


def statuses_by_qualname(defs: list[Definition]) -> dict[str, str]:
    """Helper: map qualname -> status."""
    return {d.qualname: d.status for d in defs}


def kinds_by_qualname(defs: list[Definition]) -> dict[str, str]:
    return {d.qualname: d.kind for d in defs}


class TestScanFileBasics:
    def test_empty_file_returns_no_defs(self, fixtures_dir: Path) -> None:
        defs, ok = scan_file(fixtures_dir / "empty.py")
        assert ok is True
        assert defs == []

    def test_missing_file_returns_not_ok(self, tmp_path: Path) -> None:
        defs, ok = scan_file(tmp_path / "does_not_exist.py")
        assert ok is False
        assert defs == []

    def test_syntax_error_returns_not_ok(self, fixtures_dir: Path) -> None:
        defs, ok = scan_file(fixtures_dir / "syntax_broken.py")
        assert ok is False
        assert defs == []

    def test_excluded_flag_marks_every_definition(self, fixtures_dir: Path) -> None:
        defs, ok = scan_file(fixtures_dir / "fully_annotated.py", excluded=True)
        assert ok is True
        assert defs
        assert all(d.status == STATUS_EXCLUDED for d in defs)


class TestClassification:
    def test_fully_annotated_file_is_all_annotated(self, fixtures_dir: Path) -> None:
        defs, _ = scan_file(fixtures_dir / "fully_annotated.py")
        non_class = [d for d in defs if d.kind != "class"]
        assert non_class
        for d in non_class:
            assert d.status == STATUS_ANNOTATED, f"{d.qualname}: {d.status}"

    def test_fully_unannotated_file_is_all_unannotated(self, fixtures_dir: Path) -> None:
        defs, _ = scan_file(fixtures_dir / "fully_unannotated.py")
        non_class = [d for d in defs if d.kind != "class"]
        assert non_class
        for d in non_class:
            assert d.status == STATUS_UNANNOTATED, f"{d.qualname}: {d.status}"

    def test_partial_annotation_is_partial(self, fixtures_dir: Path) -> None:
        defs, _ = scan_file(fixtures_dir / "with_partials.py")
        statuses = statuses_by_qualname(defs)
        assert statuses["full_one"] == STATUS_ANNOTATED
        assert statuses["full_two"] == STATUS_ANNOTATED
        assert statuses["partial_one"] == STATUS_PARTIAL
        assert statuses["partial_two"] == STATUS_PARTIAL
        assert statuses["bare_one"] == STATUS_UNANNOTATED
        assert statuses["bare_two"] == STATUS_UNANNOTATED

    def test_nested_function_is_function_not_method(self, fixtures_dir: Path) -> None:
        defs, _ = scan_file(fixtures_dir / "nested.py")
        kinds = kinds_by_qualname(defs)
        # Nested inside a plain function
        assert kinds["outer.inner"] == "function"
        assert kinds["outer.unannotated_inner"] == "function"
        # Nested inside a method — still a function
        assert kinds["Outer.method.nested_in_method"] == "function"
        assert kinds["Outer.method.nested_unannotated"] == "function"

    def test_nested_class_in_method_produces_method(self, fixtures_dir: Path) -> None:
        defs, _ = scan_file(fixtures_dir / "nested.py")
        kinds = kinds_by_qualname(defs)
        assert kinds["Outer.method.NestedClass"] == "class"
        assert kinds["Outer.method.NestedClass.nested_method"] == "method"

    def test_overload_is_always_annotated(self, fixtures_dir: Path) -> None:
        defs, _ = scan_file(fixtures_dir / "overloads_and_decorators.py")
        statuses = statuses_by_qualname(defs)
        # All three `f` defs live at module top with the same qualname — the
        # file has three of them. At least one of them (the non-overload
        # implementation `def f(x): return x`) is unannotated; overloads
        # are annotated because of the decorator.
        f_defs = [d for d in defs if d.qualname == "f"]
        assert len(f_defs) == 3
        annotated_count = sum(1 for d in f_defs if d.status == STATUS_ANNOTATED)
        assert annotated_count == 2  # the two @overload signatures

    def test_staticmethod_params_exclude_no_self(self, fixtures_dir: Path) -> None:
        defs, _ = scan_file(fixtures_dir / "overloads_and_decorators.py")
        statuses = statuses_by_qualname(defs)
        assert statuses["C.static_with_annots"] == STATUS_ANNOTATED
        assert statuses["C.static_unannotated"] == STATUS_UNANNOTATED
        assert statuses["C.class_method_annotated"] == STATUS_ANNOTATED

        # And verify param counting got it right:
        by_q = {d.qualname: d for d in defs}
        assert by_q["C.static_with_annots"].n_params == 1
        assert by_q["C.static_unannotated"].n_params == 1
        # classmethod: cls is dropped, leaving one real param
        assert by_q["C.class_method_annotated"].n_params == 1


class TestCountAnnotatedParams:
    """Direct unit tests via ast parsing."""

    def _parse(self, src: str) -> "ast.FunctionDef":
        import ast

        node = ast.parse(src).body[0]
        assert isinstance(node, ast.FunctionDef)
        return node

    def test_no_params(self) -> None:
        node = self._parse("def f(): pass")
        assert count_annotated_params(node, in_class=False) == (0, 0)

    def test_all_annotated(self) -> None:
        node = self._parse("def f(x: int, y: str) -> None: pass")
        assert count_annotated_params(node, in_class=False) == (2, 2)

    def test_none_annotated(self) -> None:
        node = self._parse("def f(x, y): pass")
        assert count_annotated_params(node, in_class=False) == (2, 0)

    def test_mixed(self) -> None:
        node = self._parse("def f(x: int, y): pass")
        assert count_annotated_params(node, in_class=False) == (2, 1)

    def test_self_dropped_for_method(self) -> None:
        node = self._parse("def f(self, x: int): pass")
        assert count_annotated_params(node, in_class=True) == (1, 1)

    def test_cls_dropped_for_method(self) -> None:
        node = self._parse("def f(cls, x: int): pass")
        assert count_annotated_params(node, in_class=True) == (1, 1)

    def test_staticmethod_keeps_first_arg(self) -> None:
        node = self._parse("@staticmethod\ndef f(x: int): pass")
        assert count_annotated_params(node, in_class=True) == (1, 1)

    def test_counts_varargs(self) -> None:
        node = self._parse("def f(*args: int, **kwargs: str) -> None: pass")
        assert count_annotated_params(node, in_class=False) == (2, 2)

    def test_counts_kwonly(self) -> None:
        node = self._parse("def f(a: int, *, b: int) -> None: pass")
        assert count_annotated_params(node, in_class=False) == (2, 2)


class TestDecoratorNames:
    def _parse_dec(self, src: str) -> list[ast.expr]:
        node = ast.parse(src).body[0]
        assert isinstance(node, ast.FunctionDef)
        return node.decorator_list

    def test_simple_name(self) -> None:
        decs = self._parse_dec("@foo\ndef f(): pass")
        assert decorator_names(decs) == ("foo",)

    def test_dotted_name(self) -> None:
        decs = self._parse_dec("@a.b.c\ndef f(): pass")
        assert decorator_names(decs) == ("a.b.c",)

    def test_call_form(self) -> None:
        decs = self._parse_dec("@foo(1, 2)\ndef f(): pass")
        assert decorator_names(decs) == ("foo",)

    def test_multiple(self) -> None:
        decs = self._parse_dec("@foo\n@bar.baz\ndef f(): pass")
        assert decorator_names(decs) == ("foo", "bar.baz")


class TestHelpers:
    def test_expr_to_dotted_name(self) -> None:
        foo = ast.parse("foo", mode="eval")
        assert isinstance(foo, ast.Expression)
        assert expr_to_dotted_name(foo.body) == "foo"
        abc = ast.parse("a.b.c", mode="eval")
        assert isinstance(abc, ast.Expression)
        assert expr_to_dotted_name(abc.body) == "a.b.c"

    @pytest.mark.parametrize(
        "params,annotated,has_return,expected",
        [
            (1, 0, False, "missing return annotation; 1/1 params unannotated"),
            (2, 1, False, "missing return annotation; 1/2 params unannotated"),
            (2, 2, False, "missing return annotation"),
            (2, 1, True, "1/2 params unannotated"),
        ],
    )
    def test_partial_reason(
        self, params: int, annotated: int, has_return: bool, expected: str
    ) -> None:
        assert partial_reason(params, annotated, has_return) == expected
