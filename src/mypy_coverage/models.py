"""Data types shared across the package."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Coverage status buckets:
#   annotated   - every param (except self/cls) and the return type are typed.
#   partial     - at least one annotation exists but some are missing. Mypy
#                 still checks the body; unannotated params default to Any.
#   unannotated - zero annotations. Body is skipped when check_untyped_defs
#                 is False. This is the "silently uncovered" bucket.
#   excluded    - file matched an exclude pattern; mypy never sees it.
STATUS_ANNOTATED = "annotated"
STATUS_PARTIAL = "partial"
STATUS_UNANNOTATED = "unannotated"
STATUS_EXCLUDED = "excluded"

ALL_STATUSES = (STATUS_ANNOTATED, STATUS_PARTIAL, STATUS_UNANNOTATED, STATUS_EXCLUDED)

# Decorators that force a function to count as annotated regardless of params.
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

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = defaultdict(int)
        for d in self.definitions:
            c[d.status] += 1
            c[f"{d.kind}:{d.status}"] += 1
            c["total"] += 1
            c[d.kind] += 1
        return dict(c)

    def _denominator(self) -> int:
        return sum(1 for d in self.definitions if d.status != STATUS_EXCLUDED)

    def percent_checked(self) -> float:
        """Fraction of definitions whose body mypy actually analyses."""
        total = self._denominator()
        if total == 0:
            return 100.0
        checked = sum(
            1 for d in self.definitions if d.status in (STATUS_ANNOTATED, STATUS_PARTIAL)
        )
        return 100.0 * checked / total

    def percent_fully_typed(self) -> float:
        """Fraction of definitions with complete annotations."""
        total = self._denominator()
        if total == 0:
            return 100.0
        typed = sum(1 for d in self.definitions if d.status == STATUS_ANNOTATED)
        return 100.0 * typed / total
