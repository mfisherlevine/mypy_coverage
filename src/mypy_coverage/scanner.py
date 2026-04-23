"""AST scanner that classifies every function, method, and class."""

from __future__ import annotations

import ast
from pathlib import Path

from .discovery import display_path
from .models import (
    ALWAYS_ANNOTATED_DECORATORS,
    STATUS_ANNOTATED,
    STATUS_EXCLUDED,
    STATUS_PARTIAL,
    STATUS_UNANNOTATED,
    Definition,
)

FunctionLike = ast.FunctionDef | ast.AsyncFunctionDef


def scan_file(
    path: Path,
    excluded: bool = False,
    root: Path | None = None,
) -> tuple[list[Definition], bool]:
    """Return ``(definitions, parse_ok)`` for a single file.

    ``parse_ok`` is False if the file could not be read or parsed; in that
    case ``definitions`` is empty. ``excluded=True`` marks every
    definition in the file with the ``excluded`` status -- use this when
    the file is skipped by mypy's ``exclude`` config so the report can
    still show what's inside.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], False
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [], False

    defs: list[Definition] = []
    rel = display_path(path, root)

    def walk(
        node: ast.AST,
        name_stack: list[str],
        class_stack: list[str],
        in_class_body: bool,
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qualname = ".".join(name_stack + [child.name])
                defs.append(
                    Definition(
                        file=rel,
                        lineno=child.lineno,
                        kind="class",
                        qualname=qualname,
                        parent_class=class_stack[-1] if class_stack else None,
                        status=STATUS_EXCLUDED if excluded else STATUS_ANNOTATED,
                        n_params=0,
                        n_annotated_params=0,
                        has_return_annotation=False,
                        decorators=decorator_names(child.decorator_list),
                        reason="file excluded" if excluded else "",
                    )
                )
                walk(
                    child,
                    name_stack + [child.name],
                    class_stack + [child.name],
                    in_class_body=True,
                )
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.append(
                    classify_function(
                        child,
                        name_stack=name_stack,
                        parent_class=class_stack[-1] if in_class_body else None,
                        rel=rel,
                        excluded=excluded,
                    )
                )
                walk(
                    child,
                    name_stack + [child.name],
                    class_stack,
                    in_class_body=False,  # function body isn't a class body
                )
            else:
                walk(child, name_stack, class_stack, in_class_body)

    walk(tree, [], [], in_class_body=False)
    return defs, True


def classify_function(
    node: FunctionLike,
    name_stack: list[str],
    parent_class: str | None,
    rel: str,
    excluded: bool,
) -> Definition:
    """Decide which status bucket a function/method falls into."""
    decorators = decorator_names(node.decorator_list)
    qualname = ".".join(name_stack + [node.name])
    kind = "method" if parent_class is not None else "function"

    params, annotated_params = count_annotated_params(node, in_class=parent_class is not None)
    has_return = node.returns is not None

    if excluded:
        status = STATUS_EXCLUDED
        reason = "file excluded"
    elif any(d in ALWAYS_ANNOTATED_DECORATORS for d in decorators):
        status = STATUS_ANNOTATED
        reason = ""
    elif params == 0 and not has_return:
        # Zero real params, no return annotation: mypy treats as unannotated.
        status = STATUS_UNANNOTATED
        reason = "no annotations"
    elif params == annotated_params and has_return:
        status = STATUS_ANNOTATED
        reason = ""
    elif annotated_params == 0 and not has_return:
        status = STATUS_UNANNOTATED
        reason = "no annotations"
    else:
        status = STATUS_PARTIAL
        reason = partial_reason(params, annotated_params, has_return)

    return Definition(
        file=rel,
        lineno=node.lineno,
        kind=kind,
        qualname=qualname,
        parent_class=parent_class,
        status=status,
        n_params=params,
        n_annotated_params=annotated_params,
        has_return_annotation=has_return,
        decorators=decorators,
        reason=reason,
    )


def count_annotated_params(node: FunctionLike, in_class: bool) -> tuple[int, int]:
    """Count real params (excluding self/cls) and how many are annotated."""
    args = node.args
    all_args: list[ast.arg] = []
    all_args.extend(args.posonlyargs)
    all_args.extend(args.args)
    all_args.extend(args.kwonlyargs)
    if args.vararg is not None:
        all_args.append(args.vararg)
    if args.kwarg is not None:
        all_args.append(args.kwarg)

    # Drop leading self/cls for instance/class methods (but not @staticmethod).
    if in_class and all_args:
        is_static = "staticmethod" in decorator_names(node.decorator_list)
        if not is_static and all_args[0].arg in {"self", "cls"}:
            all_args = all_args[1:]

    total = len(all_args)
    annotated = sum(1 for a in all_args if a.annotation is not None)
    return total, annotated


def decorator_names(decorators: list[ast.expr]) -> tuple[str, ...]:
    """Best-effort stringification of decorator expressions."""
    names: list[str] = []
    for dec in decorators:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = expr_to_dotted_name(target)
        if name:
            names.append(name)
    return tuple(names)


def expr_to_dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = expr_to_dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def partial_reason(params: int, annotated: int, has_return: bool) -> str:
    bits = []
    if not has_return:
        bits.append("missing return annotation")
    if params > annotated:
        bits.append(f"{params - annotated}/{params} params unannotated")
    return "; ".join(bits)
