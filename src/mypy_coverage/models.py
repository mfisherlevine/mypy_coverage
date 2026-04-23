"""Data types shared across the package."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Coverage status buckets. ``status`` always reflects the annotation
# state of the definition itself; whether mypy actually analyses it is
# tracked orthogonally via ``in_excluded_file``.
#   annotated   - every param (except self/cls) and the return type are typed.
#   partial     - at least one annotation exists but some are missing. Mypy
#                 still checks the body; unannotated params default to Any.
#   unannotated - zero annotations. Body is skipped when check_untyped_defs
#                 is False. This is the "silently uncovered" bucket.
STATUS_ANNOTATED = "annotated"
STATUS_PARTIAL = "partial"
STATUS_UNANNOTATED = "unannotated"

ALL_STATUSES = (STATUS_ANNOTATED, STATUS_PARTIAL, STATUS_UNANNOTATED)

# Decorators that force a function to count as annotated regardless of params.
ALWAYS_ANNOTATED_DECORATORS = frozenset({"overload", "typing.overload"})


@dataclass(frozen=True)
class Definition:
    """One function, method, or class definition found during the scan.

    ``status`` is the intrinsic annotation state of this particular
    definition. ``in_excluded_file`` is a separate orthogonal flag set
    when the file matched mypy's ``exclude`` pattern -- mypy will not
    analyse this definition at all, but we still classify it so its
    annotation state is visible in the report's excluded-files section.
    Definitions with ``in_excluded_file=True`` do NOT contribute to the
    main coverage percentages.
    """

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
    in_excluded_file: bool = False


@dataclass(frozen=True)
class SilentAnyHit:
    """A syntactic pattern that usually resolves to Any at runtime."""

    file: str
    lineno: int
    kind: str  # "ignored-import" | "type-ignore" | "untyped-decorator"
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


@dataclass
class CoverageReport:
    """Aggregated result of a scan."""

    root: Path
    config: MypyConfig
    definitions: list[Definition]
    silent_any: list[SilentAnyHit]
    scanned_files: list[Path]
    excluded_files: list[Path]
    unparseable: list[Path]

    def counts(self, in_excluded_file: bool = False) -> dict[str, int]:
        """Counts broken down by status and kind.

        By default counts the main body of definitions (those that count
        toward coverage). Pass ``in_excluded_file=True`` to get counts
        for definitions that only live in excluded files.
        """
        c: dict[str, int] = defaultdict(int)
        for d in self.definitions:
            if d.in_excluded_file != in_excluded_file:
                continue
            c[d.status] += 1
            c[f"{d.kind}:{d.status}"] += 1
            c["total"] += 1
            c[d.kind] += 1
        return dict(c)

    def _main_defs(self) -> list[Definition]:
        return [d for d in self.definitions if not d.in_excluded_file]

    def _excluded_defs(self) -> list[Definition]:
        return [d for d in self.definitions if d.in_excluded_file]

    def percent_checked(self, in_excluded_file: bool = False) -> float:
        """Fraction of definitions whose body mypy actually analyses.

        By default computed over the main body (excluded-file defs are
        omitted -- mypy doesn't analyse them anyway). Pass
        ``in_excluded_file=True`` to get the same metric walled off to
        definitions inside excluded files (useful for visibility, but
        remember mypy never sees those).
        """
        defs = self._excluded_defs() if in_excluded_file else self._main_defs()
        if not defs:
            return 100.0
        checked = sum(1 for d in defs if d.status in (STATUS_ANNOTATED, STATUS_PARTIAL))
        return 100.0 * checked / len(defs)

    def percent_fully_typed(self, in_excluded_file: bool = False) -> float:
        """Fraction of definitions with complete annotations.

        See :meth:`percent_checked` for the meaning of ``in_excluded_file``.
        """
        defs = self._excluded_defs() if in_excluded_file else self._main_defs()
        if not defs:
            return 100.0
        typed = sum(1 for d in defs if d.status == STATUS_ANNOTATED)
        return 100.0 * typed / len(defs)
