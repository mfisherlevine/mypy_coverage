#!/usr/bin/env python3
"""mypy-coverage: report mypy annotation coverage for a Python codebase.

Runs a fast AST-based scan that mirrors how mypy decides whether a function
body gets type-checked. With the default mypy setting ``check_untyped_defs =
False``, a function with *zero* annotations is skipped entirely -- its body
is not analysed and any real type errors inside it are invisible. This tool
enumerates exactly those functions, plus files/patterns the mypy config
excludes outright, and reports aggregate coverage.

Usage examples:

    mypy-coverage                          # scan current project
    mypy-coverage src/ tests/              # scan specific paths
    mypy-coverage --config pyproject.toml  # explicit config
    mypy-coverage --format json | jq       # machine-readable output
    mypy-coverage --list                   # full list of uncovered defs
    mypy-coverage --silent-any             # flag Any-fallthrough imports
    mypy-coverage --threshold 80           # exit 1 if coverage < 80%

Supports mypy config in mypy.ini, setup.cfg [mypy], or pyproject.toml
[tool.mypy]. Only the Python standard library is required.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
from collections import defaultdict
from configparser import ConfigParser, NoSectionError
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef,unused-ignore]
    except ImportError:
        tomllib = None  # type: ignore[assignment,unused-ignore]

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

# Coverage status buckets:
#   annotated   - every param (except self/cls) and the return type are typed.
#   partial     - at least one annotation exists but some are missing. Mypy
#                 still checks the body (missing ones default to Any).
#   unannotated - zero annotations. Body is skipped when check_untyped_defs
#                 is False. This is the "silently uncovered" bucket.
#   excluded    - file matched an exclude pattern; mypy never sees it.
STATUS_ANNOTATED = "annotated"
STATUS_PARTIAL = "partial"
STATUS_UNANNOTATED = "unannotated"
STATUS_EXCLUDED = "excluded"

# Decorators that make a function inherently annotated regardless of params.
ALWAYS_ANNOTATED_DECORATORS = frozenset({"overload", "typing.overload"})


@dataclass(frozen=True)
class Definition:
    """One function, method, or class definition found during the scan."""

    file: str
    lineno: int
    kind: str  # "function" | "method" | "class"
    qualname: str
    parent_class: str | None
    status: str
    n_params: int
    n_annotated_params: int
    has_return_annotation: bool
    decorators: tuple[str, ...]
    reason: str = ""


@dataclass(frozen=True)
class SilentAnyHit:
    """A syntactic pattern that usually resolves to Any at runtime."""

    file: str
    lineno: int
    kind: str  # "ignored-import" | "type-ignore" | "explicit-any" | "untyped-decorator"
    detail: str


@dataclass
class MypyConfig:
    """Subset of mypy config relevant to coverage analysis."""

    source: Path | None = None
    check_untyped_defs: bool = False
    exclude_regex: re.Pattern[str] | None = None
    files: list[str] = field(default_factory=list)
    mypy_path: list[str] = field(default_factory=list)
    ignored_modules: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_CANDIDATES = ("mypy.ini", "setup.cfg", "pyproject.toml", ".mypy.ini")


def discover_config(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a file containing a mypy section."""
    for directory in (start, *start.parents):
        for name in _CONFIG_CANDIDATES:
            candidate = directory / name
            if candidate.is_file() and _has_mypy_section(candidate):
                return candidate
    return None


def _has_mypy_section(path: Path) -> bool:
    suffix = path.suffix.lower()
    try:
        if suffix in {".ini", ".cfg"} or path.name == ".mypy.ini":
            parser = ConfigParser()
            parser.read(path)
            return parser.has_section("mypy")
        if suffix == ".toml":
            if tomllib is None:
                return False
            with path.open("rb") as fh:
                data = tomllib.load(fh)
            return "mypy" in data.get("tool", {})
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return False


def load_config(path: Path) -> MypyConfig:
    """Parse a mypy config file into the fields we care about."""
    cfg = MypyConfig(source=path)
    suffix = path.suffix.lower()
    if suffix in {".ini", ".cfg"} or path.name == ".mypy.ini":
        _load_ini_config(path, cfg)
    elif suffix == ".toml":
        _load_toml_config(path, cfg)
    else:
        raise ValueError(f"Unrecognised config file type: {path}")
    return cfg


def _load_ini_config(path: Path, cfg: MypyConfig) -> None:
    parser = ConfigParser()
    parser.read(path)

    try:
        main = parser["mypy"]
    except KeyError:
        return

    cfg.check_untyped_defs = _parse_bool(main.get("check_untyped_defs", "false"))
    exclude_raw = main.get("exclude")
    if exclude_raw:
        cfg.exclude_regex = _compile_exclude(exclude_raw)
    files_raw = main.get("files")
    if files_raw:
        cfg.files = _split_files(files_raw)
    mypy_path_raw = main.get("mypy_path")
    if mypy_path_raw:
        cfg.mypy_path = _split_files(mypy_path_raw)

    for section_name in parser.sections():
        if not section_name.startswith("mypy-"):
            continue
        section = parser[section_name]
        if _parse_bool(section.get("ignore_missing_imports", "false")):
            module = section_name[len("mypy-") :]
            cfg.ignored_modules.add(module)


def _load_toml_config(path: Path, cfg: MypyConfig) -> None:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    mypy_tbl = data.get("tool", {}).get("mypy", {})
    if not mypy_tbl:
        return

    cfg.check_untyped_defs = bool(mypy_tbl.get("check_untyped_defs", False))

    exclude = mypy_tbl.get("exclude")
    if isinstance(exclude, list):
        cfg.exclude_regex = _compile_exclude("|".join(exclude))
    elif isinstance(exclude, str):
        cfg.exclude_regex = _compile_exclude(exclude)

    files = mypy_tbl.get("files")
    if isinstance(files, list):
        cfg.files = list(files)
    elif isinstance(files, str):
        cfg.files = _split_files(files)

    mypy_path = mypy_tbl.get("mypy_path")
    if isinstance(mypy_path, list):
        cfg.mypy_path = list(mypy_path)
    elif isinstance(mypy_path, str):
        cfg.mypy_path = _split_files(mypy_path)

    overrides = mypy_tbl.get("overrides", [])
    if isinstance(overrides, list):
        for override in overrides:
            if not isinstance(override, dict):
                continue
            if not override.get("ignore_missing_imports"):
                continue
            module = override.get("module")
            if isinstance(module, str):
                cfg.ignored_modules.add(module)
            elif isinstance(module, list):
                cfg.ignored_modules.update(m for m in module if isinstance(m, str))


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "yes", "1", "on"}


def _split_files(value: str) -> list[str]:
    parts: list[str] = []
    for chunk in value.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk.rstrip("/"))
    return parts


def _compile_exclude(pattern: str) -> re.Pattern[str]:
    """Compile a mypy-style exclude regex.

    Mypy accepts a single regex (often with ``(?x)`` verbose mode and
    ``|`` alternation) or a list of regexes. We compile as-is; the caller
    supplies ``|``-joined alternatives for list form.
    """
    return re.compile(pattern)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def discover_files(
    paths: Sequence[Path],
    cfg: MypyConfig,
    root: Path,
) -> tuple[list[Path], list[Path]]:
    """Walk ``paths`` and return ``(included, excluded)`` *.py files.

    ``included`` files should be scanned for coverage. ``excluded`` files
    are enumerated so we can still report on what lives inside them.
    """
    included: list[Path] = []
    excluded: list[Path] = []
    seen: set[Path] = set()

    for base in paths:
        for file in _iter_python_files(base):
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


def _iter_python_files(base: Path) -> Iterator[Path]:
    if base.is_file():
        if base.suffix == ".py":
            yield base
        return
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*.py")):
        # Skip typical junk dirs.
        parts = set(path.parts)
        if parts & {".git", ".mypy_cache", "__pycache__", ".venv", "venv", ".tox"}:
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
    # Mypy matches against the path string; try both relative and absolute.
    return bool(cfg.exclude_regex.search(rel) or cfg.exclude_regex.search(str(path)))


# ---------------------------------------------------------------------------
# AST scan
# ---------------------------------------------------------------------------


def scan_file(path: Path, excluded: bool, root: Path | None = None) -> tuple[list[Definition], bool]:
    """Return ``(definitions, parse_ok)`` for a single file."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], False
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [], False

    defs: list[Definition] = []
    rel = _display_path(path, root)

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
                        decorators=_decorator_names(child.decorator_list),
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
                    _classify_function(
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
                    in_class_body=False,  # function body is not a class body
                )
            else:
                walk(child, name_stack, class_stack, in_class_body)

    walk(tree, [], [], in_class_body=False)
    return defs, True


def _classify_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    name_stack: list[str],
    parent_class: str | None,
    rel: str,
    excluded: bool,
) -> Definition:
    decorators = _decorator_names(node.decorator_list)
    qualname = ".".join(name_stack + [node.name])
    kind = "method" if parent_class is not None else "function"

    params, annotated_params = _count_annotated_params(node, in_class=parent_class is not None)
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
        reason = _partial_reason(params, annotated_params, has_return)

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


def _count_annotated_params(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    in_class: bool,
) -> tuple[int, int]:
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

    # Drop leading self/cls for instance/class methods.
    if in_class and all_args:
        is_static = any(d in {"staticmethod"} for d in _decorator_names(node.decorator_list))
        if not is_static and all_args[0].arg in {"self", "cls"}:
            all_args = all_args[1:]

    total = len(all_args)
    annotated = sum(1 for a in all_args if a.annotation is not None)
    return total, annotated


def _decorator_names(decorators: list[ast.expr]) -> tuple[str, ...]:
    """Best-effort stringification of decorator expressions."""
    names: list[str] = []
    for dec in decorators:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = _expr_to_dotted_name(target)
        if name:
            names.append(name)
    return tuple(names)


def _expr_to_dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_to_dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _partial_reason(params: int, annotated: int, has_return: bool) -> str:
    bits = []
    if not has_return:
        bits.append("missing return annotation")
    if params > annotated:
        bits.append(f"{params - annotated}/{params} params unannotated")
    return "; ".join(bits)


# ---------------------------------------------------------------------------
# Silent-Any detection
# ---------------------------------------------------------------------------


def _display_path(path: Path, root: Path | None) -> str:
    """Render a path relative to ``root`` when possible."""
    if root is None:
        return path.as_posix()
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def scan_silent_any(path: Path, cfg: MypyConfig, root: Path | None = None) -> list[SilentAnyHit]:
    """Best-effort detection of patterns that decay to ``Any`` at runtime.

    We flag:
      * imports from modules configured with ``ignore_missing_imports``
      * ``# type: ignore`` comments
      * decorators imported from ignore_missing_imports modules (can erase
        the type of the function they wrap)
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
    rel = _display_path(path, root)
    ignored = cfg.ignored_modules

    # Collect names imported from ignored modules -> those names are Any.
    names_from_ignored: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and _module_matches(node.module, ignored):
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
                if _module_matches(alias.name, ignored):
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

    # Explicit Any + decorators from ignored modules.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                head = _decorator_head(target)
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
    # `# type: ignore` comments - quickest via regex on source lines.
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


def _module_matches(module: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if pattern == module:
            return True
        # Wildcards: `foo.*` matches `foo.bar`, `foo.bar.baz`.
        if pattern.endswith(".*") and module.startswith(pattern[:-1]):
            return True
        if fnmatch.fnmatch(module, pattern):
            return True
    return False


def _decorator_head(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _decorator_head(node.value)
    return ""


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class CoverageReport:
    root: Path
    config: MypyConfig
    definitions: list[Definition]
    silent_any: list[SilentAnyHit]
    scanned_files: list[Path]
    excluded_files: list[Path]
    unparseable: list[Path]

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = defaultdict(int)
        for d in self.definitions:
            c[d.status] += 1
            c[f"{d.kind}:{d.status}"] += 1
            c["total"] += 1
            c[d.kind] += 1
        return dict(c)

    def percent_checked(self) -> float:
        """Fraction of definitions mypy actually analyses (body-checked)."""
        total = sum(1 for d in self.definitions if d.status != STATUS_EXCLUDED)
        if total == 0:
            return 100.0
        checked = sum(
            1 for d in self.definitions if d.status in (STATUS_ANNOTATED, STATUS_PARTIAL)
        )
        return 100.0 * checked / total

    def percent_fully_typed(self) -> float:
        """Fraction of definitions with complete annotations."""
        total = sum(1 for d in self.definitions if d.status != STATUS_EXCLUDED)
        if total == 0:
            return 100.0
        typed = sum(1 for d in self.definitions if d.status == STATUS_ANNOTATED)
        return 100.0 * typed / total


def build_report(
    paths: Sequence[Path],
    cfg: MypyConfig,
    root: Path,
    want_silent_any: bool,
) -> CoverageReport:
    included, excluded = discover_files(paths, cfg, root)
    definitions: list[Definition] = []
    unparseable: list[Path] = []
    silent_any: list[SilentAnyHit] = []

    for path in included:
        defs, ok = scan_file(path, excluded=False, root=root)
        if not ok:
            unparseable.append(path)
        definitions.extend(defs)
        if want_silent_any:
            silent_any.extend(scan_silent_any(path, cfg, root=root))

    for path in excluded:
        defs, ok = scan_file(path, excluded=True, root=root)
        if not ok:
            unparseable.append(path)
        definitions.extend(defs)

    return CoverageReport(
        root=root,
        config=cfg,
        definitions=definitions,
        silent_any=silent_any,
        scanned_files=included,
        excluded_files=excluded,
        unparseable=unparseable,
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


class Colors:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, text: str, code: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, t: str) -> str:
        return self._wrap(t, "1")

    def green(self, t: str) -> str:
        return self._wrap(t, "32")

    def yellow(self, t: str) -> str:
        return self._wrap(t, "33")

    def red(self, t: str) -> str:
        return self._wrap(t, "31")

    def dim(self, t: str) -> str:
        return self._wrap(t, "2")


def render_text(
    report: CoverageReport,
    list_uncovered: bool,
    list_partial: bool,
    show_excluded: bool,
    colors: Colors,
) -> str:
    lines: list[str] = []

    cfg_src = str(report.config.source) if report.config.source else "<none>"
    lines.append(colors.bold("mypy-coverage"))
    lines.append(f"  root:    {report.root}")
    lines.append(f"  config:  {cfg_src}")
    lines.append(f"  scanned: {len(report.scanned_files)} file(s)")
    if report.excluded_files:
        lines.append(f"  excluded: {len(report.excluded_files)} file(s)")
    if report.unparseable:
        lines.append(
            colors.yellow(f"  parse errors: {len(report.unparseable)} file(s)")
        )
    lines.append("")

    counts = report.counts()
    checked = report.percent_checked()
    fully = report.percent_fully_typed()

    def pct_color(pct: float) -> str:
        s = f"{pct:5.1f}%"
        if pct >= 90:
            return colors.green(s)
        if pct >= 70:
            return colors.yellow(s)
        return colors.red(s)

    lines.append(colors.bold("Coverage:"))
    lines.append(
        f"  body-checked by mypy:  {pct_color(checked)}  "
        f"({counts.get(STATUS_ANNOTATED, 0) + counts.get(STATUS_PARTIAL, 0)}"
        f" / {counts.get('total', 0) - counts.get(STATUS_EXCLUDED, 0)})"
    )
    lines.append(
        f"  fully annotated:       {pct_color(fully)}  "
        f"({counts.get(STATUS_ANNOTATED, 0)}"
        f" / {counts.get('total', 0) - counts.get(STATUS_EXCLUDED, 0)})"
    )
    lines.append("")

    lines.append(colors.bold("Breakdown:"))
    lines.append(f"  annotated:    {counts.get(STATUS_ANNOTATED, 0):>5}")
    lines.append(f"  partial:      {counts.get(STATUS_PARTIAL, 0):>5}")
    lines.append(f"  unannotated:  {counts.get(STATUS_UNANNOTATED, 0):>5}")
    lines.append(f"  excluded:     {counts.get(STATUS_EXCLUDED, 0):>5}")
    lines.append("")

    per_file = _per_file_stats(report)
    if per_file:
        lines.append(colors.bold("Per-file (files with uncovered or partial):"))
        header = f"  {'file':<60} {'fully%':>7} {'check%':>7} {'unann':>6} {'part':>5}"
        lines.append(header)
        lines.append(f"  {'-' * 58:<60} {'-------':>7} {'-------':>7} {'-----':>6} {'----':>5}")
        for entry in per_file:
            lines.append(
                f"  {entry['file']:<60}"
                f" {entry['fully_pct']:>6.1f}%"
                f" {entry['checked_pct']:>6.1f}%"
                f" {entry['unannotated']:>6}"
                f" {entry['partial']:>5}"
            )
        lines.append("")

    if list_uncovered:
        uncovered = [d for d in report.definitions if d.status == STATUS_UNANNOTATED]
        lines.append(colors.bold(f"Unannotated (body skipped) -- {len(uncovered)} item(s):"))
        for d in sorted(uncovered, key=lambda x: (x.file, x.lineno)):
            lines.append(f"  {d.file}:{d.lineno:<5}  {d.kind:<8}  {d.qualname}")
        lines.append("")

    if list_partial:
        partial = [d for d in report.definitions if d.status == STATUS_PARTIAL]
        lines.append(colors.bold(f"Partially annotated -- {len(partial)} item(s):"))
        for d in sorted(partial, key=lambda x: (x.file, x.lineno)):
            lines.append(
                f"  {d.file}:{d.lineno:<5}  {d.qualname}  "
                f"[{d.reason}]"
            )
        lines.append("")

    if show_excluded:
        excluded = [d for d in report.definitions if d.status == STATUS_EXCLUDED]
        lines.append(colors.bold(f"Excluded by config -- {len(excluded)} item(s):"))
        for d in sorted(excluded, key=lambda x: (x.file, x.lineno)):
            lines.append(f"  {d.file}:{d.lineno:<5}  {d.kind:<8}  {d.qualname}")
        lines.append("")

    if report.silent_any:
        lines.append(colors.bold(f"Silent-Any candidates -- {len(report.silent_any)} item(s):"))
        for hit in report.silent_any:
            lines.append(f"  {hit.file}:{hit.lineno:<5}  [{hit.kind}]  {hit.detail}")
        lines.append("")

    if report.unparseable:
        lines.append(colors.yellow("Files with parse errors (skipped):"))
        for p in report.unparseable:
            lines.append(f"  {p}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _per_file_stats(report: CoverageReport) -> list[dict[str, object]]:
    by_file: dict[str, list[Definition]] = defaultdict(list)
    for d in report.definitions:
        by_file[d.file].append(d)

    entries = []
    for file, defs in by_file.items():
        if not any(d.status in (STATUS_UNANNOTATED, STATUS_PARTIAL) for d in defs):
            continue
        non_excl = [d for d in defs if d.status != STATUS_EXCLUDED]
        total = len(non_excl)
        if total == 0:
            continue
        ann = sum(1 for d in non_excl if d.status == STATUS_ANNOTATED)
        partial = sum(1 for d in non_excl if d.status == STATUS_PARTIAL)
        unann = sum(1 for d in non_excl if d.status == STATUS_UNANNOTATED)
        checked = ann + partial
        entries.append(
            {
                "file": file if len(file) <= 60 else "..." + file[-57:],
                "fully_pct": 100.0 * ann / total,
                "checked_pct": 100.0 * checked / total,
                "annotated": ann,
                "partial": partial,
                "unannotated": unann,
                "total": total,
            }
        )
    entries.sort(key=lambda e: (e["fully_pct"], e["file"]))
    return entries


def render_json(report: CoverageReport) -> str:
    definitions = [asdict(d) for d in report.definitions]
    for d in definitions:
        # Tuples don't survive JSON round-tripping cleanly.
        d["decorators"] = list(d["decorators"])
    payload: dict[str, object] = {
        "root": str(report.root),
        "config": str(report.config.source) if report.config.source else None,
        "check_untyped_defs": report.config.check_untyped_defs,
        "summary": {
            "total": len(report.definitions),
            "counts": report.counts(),
            "percent_body_checked": report.percent_checked(),
            "percent_fully_typed": report.percent_fully_typed(),
            "scanned_files": len(report.scanned_files),
            "excluded_files": len(report.excluded_files),
            "unparseable_files": len(report.unparseable),
        },
        "per_file": _per_file_stats(report),
        "definitions": definitions,
        "silent_any": [asdict(h) for h in report.silent_any],
        "unparseable": [str(p) for p in report.unparseable],
    }
    return json.dumps(payload, indent=2, default=str)


def render_markdown(report: CoverageReport) -> str:
    lines: list[str] = []
    lines.append("# mypy-coverage report\n")
    lines.append(f"- **Root:** `{report.root}`")
    lines.append(
        f"- **Config:** `{report.config.source}`" if report.config.source else "- **Config:** _none_"
    )
    lines.append(f"- **Files scanned:** {len(report.scanned_files)}")
    lines.append(f"- **Files excluded:** {len(report.excluded_files)}")
    lines.append("")
    counts = report.counts()
    lines.append("## Summary")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("| --- | ---: |")
    lines.append(f"| body-checked by mypy | {report.percent_checked():.1f}% |")
    lines.append(f"| fully annotated      | {report.percent_fully_typed():.1f}% |")
    lines.append(f"| annotated            | {counts.get(STATUS_ANNOTATED, 0)} |")
    lines.append(f"| partial              | {counts.get(STATUS_PARTIAL, 0)} |")
    lines.append(f"| unannotated          | {counts.get(STATUS_UNANNOTATED, 0)} |")
    lines.append(f"| excluded             | {counts.get(STATUS_EXCLUDED, 0)} |")
    lines.append("")

    per_file = _per_file_stats(report)
    if per_file:
        lines.append("## Files with gaps")
        lines.append("")
        lines.append("| file | fully typed % | body checked % | unannotated | partial |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for e in per_file:
            lines.append(
                f"| `{e['file']}` | {e['fully_pct']:.1f}% | {e['checked_pct']:.1f}% "
                f"| {e['unannotated']} | {e['partial']} |"
            )
        lines.append("")

    uncovered = [d for d in report.definitions if d.status == STATUS_UNANNOTATED]
    if uncovered:
        lines.append(f"## Unannotated definitions ({len(uncovered)})")
        lines.append("")
        by_file: dict[str, list[Definition]] = defaultdict(list)
        for d in uncovered:
            by_file[d.file].append(d)
        for file in sorted(by_file):
            lines.append(f"### `{file}`")
            lines.append("")
            for d in by_file[file]:
                lines.append(f"- L{d.lineno} `{d.qualname}` ({d.kind})")
            lines.append("")

    if report.silent_any:
        lines.append(f"## Silent-Any candidates ({len(report.silent_any)})")
        lines.append("")
        for hit in report.silent_any:
            lines.append(f"- `{hit.file}:{hit.lineno}` **{hit.kind}** — {hit.detail}")
        lines.append("")

    return "\n".join(lines)


def render_github(report: CoverageReport) -> str:
    """GitHub Actions annotation format."""
    lines: list[str] = []
    for d in report.definitions:
        if d.status == STATUS_UNANNOTATED:
            lines.append(
                f"::warning file={d.file},line={d.lineno},title=Unannotated::"
                f"{d.qualname} has no type annotations; mypy skips its body"
            )
        elif d.status == STATUS_PARTIAL:
            lines.append(
                f"::notice file={d.file},line={d.lineno},title=Partially annotated::"
                f"{d.qualname}: {d.reason}"
            )
    for hit in report.silent_any:
        lines.append(
            f"::notice file={hit.file},line={hit.lineno},title=Silent Any ({hit.kind})::"
            f"{hit.detail}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _want_color(choice: str) -> bool:
    if choice == "always":
        return True
    if choice == "never":
        return False
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mypy-coverage",
        description="Report mypy annotation coverage for a Python codebase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Paths (files or directories) to scan. Defaults to the `files` "
        "setting in the mypy config, or the current directory.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to mypy config file. Auto-detected if omitted.",
    )
    parser.add_argument(
        "-r",
        "--root",
        type=Path,
        help="Project root. Defaults to the config's directory, or CWD.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "json", "markdown", "github"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List every unannotated definition.",
    )
    parser.add_argument(
        "--list-partial",
        action="store_true",
        help="List every partially annotated definition.",
    )
    parser.add_argument(
        "--show-excluded",
        action="store_true",
        help="Also list definitions in excluded files.",
    )
    parser.add_argument(
        "--silent-any",
        action="store_true",
        help="Flag syntactic patterns that decay to Any (best-effort).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        metavar="PERCENT",
        help="Exit with status 1 if body-checked coverage is below PERCENT.",
    )
    parser.add_argument(
        "--threshold-metric",
        choices=("checked", "fully-typed"),
        default="checked",
        help="Which percentage --threshold applies to.",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Colourise terminal output.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mypy-coverage {__version__}",
    )

    args = parser.parse_args(argv)

    cfg_path = args.config
    if cfg_path is None:
        cfg_path = discover_config(Path.cwd())

    if cfg_path is not None and not cfg_path.is_file():
        print(f"error: config file not found: {cfg_path}", file=sys.stderr)
        return 2

    cfg = load_config(cfg_path) if cfg_path else MypyConfig()

    root = args.root
    if root is None:
        root = cfg_path.parent if cfg_path else Path.cwd()
    root = root.resolve()

    if args.paths:
        paths = [p if p.is_absolute() else (Path.cwd() / p).resolve() for p in args.paths]
    elif cfg.files or cfg.mypy_path:
        # `files=` are mypy's direct entry points; `mypy_path=` dirs are
        # imported transitively and usually contain most of the source.
        # Scanning both matches what mypy actually checks in practice.
        combined = list(cfg.files) + list(cfg.mypy_path)
        paths = []
        seen: set[Path] = set()
        for entry in combined:
            resolved = (root / entry).resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
    else:
        paths = [root]

    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"error: path does not exist: {p}", file=sys.stderr)
        return 2

    report = build_report(paths, cfg, root, want_silent_any=args.silent_any)

    if args.format == "text":
        output = render_text(
            report,
            list_uncovered=args.list,
            list_partial=args.list_partial,
            show_excluded=args.show_excluded,
            colors=Colors(_want_color(args.color)),
        )
    elif args.format == "json":
        output = render_json(report)
    elif args.format == "markdown":
        output = render_markdown(report)
    elif args.format == "github":
        output = render_github(report)
    else:  # pragma: no cover
        raise AssertionError(f"unknown format: {args.format}")

    sys.stdout.write(output)

    if args.threshold is not None:
        value = (
            report.percent_checked()
            if args.threshold_metric == "checked"
            else report.percent_fully_typed()
        )
        if value < args.threshold:
            print(
                f"\ncoverage {value:.1f}% is below threshold {args.threshold:.1f}%",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
