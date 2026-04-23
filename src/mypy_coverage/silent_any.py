"""Best-effort detection of patterns that decay to Any at runtime."""

from __future__ import annotations

import ast
import fnmatch
from collections.abc import Iterable
from pathlib import Path

from .discovery import display_path
from .models import MypyConfig, SilentAnyHit


def scan_silent_any(
    path: Path,
    cfg: MypyConfig,
    root: Path | None = None,
) -> list[SilentAnyHit]:
    """Return best-effort silent-Any hits for a single file.

    We flag:
      * imports from modules configured with ``ignore_missing_imports``
      * ``# type: ignore`` comments
      * decorators imported from ignore_missing_imports modules (they
        can silently erase the type of the function they wrap)

    True silent-Any detection (e.g. types that decay to Any during mypy's
    semantic analysis) requires running mypy itself.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    hits: list[SilentAnyHit] = []
    rel = display_path(path, root)
    ignored = cfg.ignored_modules

    names_from_ignored: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and module_matches(node.module, ignored):
                for alias in node.names:
                    local = alias.asname or alias.name
                    names_from_ignored[local] = node.module
                    hits.append(
                        SilentAnyHit(
                            file=rel,
                            lineno=node.lineno,
                            kind="ignored-import",
                            detail=f"'{alias.name}' from '{node.module}' -> Any",
                        )
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if module_matches(alias.name, ignored):
                    local = alias.asname or alias.name.split(".")[0]
                    names_from_ignored[local] = alias.name
                    hits.append(
                        SilentAnyHit(
                            file=rel,
                            lineno=node.lineno,
                            kind="ignored-import",
                            detail=f"'{alias.name}' -> Any",
                        )
                    )

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                head = decorator_head(target)
                if head and head in names_from_ignored:
                    hits.append(
                        SilentAnyHit(
                            file=rel,
                            lineno=dec.lineno,
                            kind="untyped-decorator",
                            detail=(
                                f"'{head}' from '{names_from_ignored[head]}' "
                                f"decorates {node.name} -> return type may be Any"
                            ),
                        )
                    )

    for lineno, line in enumerate(source.splitlines(), start=1):
        if "# type: ignore" in line:
            hits.append(
                SilentAnyHit(
                    file=rel,
                    lineno=lineno,
                    kind="type-ignore",
                    detail=line.strip(),
                )
            )

    hits.sort(key=lambda h: (h.file, h.lineno, h.kind))
    return hits


def module_matches(module: str, patterns: Iterable[str]) -> bool:
    """Does a module name match any of the given ``ignored_modules`` patterns?"""
    for pattern in patterns:
        if pattern == module:
            return True
        if pattern.endswith(".*") and module.startswith(pattern[:-1]):
            return True
        if fnmatch.fnmatch(module, pattern):
            return True
    return False


def decorator_head(node: ast.expr) -> str:
    """Return the leftmost identifier of a possibly-dotted decorator."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return decorator_head(node.value)
    return ""
