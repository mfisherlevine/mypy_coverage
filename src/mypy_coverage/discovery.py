"""Walk a project tree and decide which files mypy would look at."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from .models import MypyConfig

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "venv",
    }
)


def discover_files(
    paths: Sequence[Path],
    cfg: MypyConfig,
    root: Path,
) -> tuple[list[Path], list[Path]]:
    """Walk ``paths`` and return ``(included, excluded)`` *.py files.

    ``included`` are the files to scan for coverage. ``excluded`` are the
    files that match mypy's exclude regex; we still enumerate them so the
    report can show what lives behind the exclusion.
    """
    included: list[Path] = []
    excluded: list[Path] = []
    seen: set[Path] = set()

    for base in paths:
        for file in iter_python_files(base):
            resolved = file.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if is_excluded(file, cfg, root):
                excluded.append(file)
            else:
                included.append(file)

    included.sort()
    excluded.sort()
    return included, excluded


def iter_python_files(base: Path) -> Iterator[Path]:
    """Yield every ``*.py`` under ``base``, skipping common junk dirs."""
    if base.is_file():
        if base.suffix == ".py":
            yield base
        return
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*.py")):
        if set(path.parts) & _SKIP_DIRS:
            continue
        yield path


def is_excluded(path: Path, cfg: MypyConfig, root: Path) -> bool:
    """Does ``path`` match the mypy ``exclude`` regex?"""
    if cfg.exclude_regex is None:
        return False
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    return bool(cfg.exclude_regex.search(rel) or cfg.exclude_regex.search(str(path)))


def display_path(path: Path, root: Path | None) -> str:
    """Render a path relative to ``root`` when possible."""
    if root is None:
        return path.as_posix()
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
