"""Aggregation: tie discovery, scanning, and silent-Any detection together."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from .discovery import discover_files
from .models import (
    STATUS_ANNOTATED,
    STATUS_PARTIAL,
    STATUS_UNANNOTATED,
    CoverageReport,
    Definition,
    MypyConfig,
    SilentAnyHit,
)
from .scanner import scan_file
from .silent_any import scan_silent_any


def build_report(
    paths: Sequence[Path],
    cfg: MypyConfig,
    root: Path,
    want_silent_any: bool = False,
) -> CoverageReport:
    """Run the full pipeline and return an aggregated :class:`CoverageReport`."""
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


class PerFileStat(TypedDict):
    """Summary stats for one file in the per-file breakdown."""

    file: str
    fully_pct: float
    checked_pct: float
    annotated: int
    partial: int
    unannotated: int
    total: int


SORT_PATH = "path"
SORT_COVERAGE = "coverage"
VALID_SORT_KEYS = (SORT_PATH, SORT_COVERAGE)


def per_file_stats(
    report: CoverageReport,
    truncate_path: int | None = 60,
    sort_by: str = SORT_PATH,
    in_excluded_file: bool = False,
    include_clean_files: bool = False,
) -> list[PerFileStat]:
    """Return per-file stats.

    Parameters
    ----------
    truncate_path : int | None
        Shorten long file paths with leading ``...`` so they fit in a
        fixed-width column. Pass ``None`` to keep full paths.
    sort_by : str
        ``"path"`` (default, alphabetical) or ``"coverage"`` (worst
        coverage first, then file name).
    in_excluded_file : bool
        If ``False`` (default), stats cover the main body of the report
        (definitions that count toward coverage). If ``True``, stats
        cover definitions inside files excluded from mypy -- reported
        separately as visibility-only.
    include_clean_files : bool
        If ``False`` (default), skip files that have no gaps. Set to
        ``True`` to include every file that contains any definitions.
    """
    if sort_by not in VALID_SORT_KEYS:
        raise ValueError(f"sort_by must be one of {VALID_SORT_KEYS}, got {sort_by!r}")

    by_file: dict[str, list[Definition]] = defaultdict(list)
    for d in report.definitions:
        if d.in_excluded_file != in_excluded_file:
            continue
        by_file[d.file].append(d)

    # Build entries keyed by the raw (untruncated) file path so sorting
    # stays stable regardless of truncation. Truncation is applied at the
    # very end, purely for display.
    raw_entries: list[tuple[str, PerFileStat]] = []
    for file, defs in by_file.items():
        total = len(defs)
        if total == 0:
            continue
        has_gap = any(d.status in (STATUS_UNANNOTATED, STATUS_PARTIAL) for d in defs)
        if not has_gap and not include_clean_files:
            continue
        ann = sum(1 for d in defs if d.status == STATUS_ANNOTATED)
        partial = sum(1 for d in defs if d.status == STATUS_PARTIAL)
        unann = sum(1 for d in defs if d.status == STATUS_UNANNOTATED)
        checked = ann + partial
        raw_entries.append(
            (
                file,
                {
                    "file": file,
                    "fully_pct": 100.0 * ann / total,
                    "checked_pct": 100.0 * checked / total,
                    "annotated": ann,
                    "partial": partial,
                    "unannotated": unann,
                    "total": total,
                },
            )
        )

    if sort_by == SORT_COVERAGE:
        raw_entries.sort(key=lambda kv: (kv[1]["fully_pct"], kv[0]))
    else:
        raw_entries.sort(key=lambda kv: kv[0])

    # Apply display truncation after sorting is finalised.
    entries: list[PerFileStat] = []
    for _raw, entry in raw_entries:
        if truncate_path is not None and len(entry["file"]) > truncate_path:
            entry["file"] = "..." + entry["file"][-(truncate_path - 3) :]
        entries.append(entry)
    return entries
