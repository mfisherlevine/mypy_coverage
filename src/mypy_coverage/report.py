"""Aggregation: tie discovery, scanning, and silent-Any detection together."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from .discovery import discover_files
from .models import (
    STATUS_ANNOTATED,
    STATUS_EXCLUDED,
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


def per_file_stats(report: CoverageReport, truncate_path: int | None = 60) -> list[PerFileStat]:
    """Return per-file stats for files that have at least one gap.

    ``truncate_path`` shortens long file paths with leading ``...`` so they
    fit in a fixed-width column. Pass ``None`` to keep full paths.
    """
    by_file: dict[str, list[Definition]] = defaultdict(list)
    for d in report.definitions:
        by_file[d.file].append(d)

    entries: list[PerFileStat] = []
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
        display_file = file
        if truncate_path is not None and len(file) > truncate_path:
            display_file = "..." + file[-(truncate_path - 3) :]
        entries.append(
            {
                "file": display_file,
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
