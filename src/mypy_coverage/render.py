"""Render a :class:`CoverageReport` in several formats.

All renderers treat definitions inside mypy-excluded files as walled
off: they're shown in a separate section for visibility but don't
contribute to the main coverage percentages, per-file table, or CI
annotations.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from typing import Any

from .models import (
    STATUS_ANNOTATED,
    STATUS_PARTIAL,
    STATUS_UNANNOTATED,
    CoverageReport,
    Definition,
)
from .report import SORT_PATH, per_file_stats


class Colors:
    """Terminal colour helpers -- no-ops when ``enabled=False``."""

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


def _pct_colored(pct: float, c: Colors) -> str:
    s = f"{pct:5.1f}%"
    if pct >= 90:
        return c.green(s)
    if pct >= 70:
        return c.yellow(s)
    return c.red(s)


def render_text(
    report: CoverageReport,
    list_uncovered: bool = False,
    list_partial: bool = False,
    show_excluded: bool = False,
    include_excluded: bool = True,
    sort_by: str = SORT_PATH,
    colors: Colors | None = None,
) -> str:
    """Render a human-readable summary report.

    ``include_excluded`` controls the walled-off "Excluded files" block.
    When ``False``, the block is omitted entirely regardless of how many
    excluded-file definitions were found; the main report is unaffected
    either way.
    """
    c = colors or Colors(enabled=False)
    lines: list[str] = []

    cfg_src = str(report.config.source) if report.config.source else "<none>"
    lines.append(c.bold("mypy-coverage"))
    lines.append(f"  root:    {report.root}")
    lines.append(f"  config:  {cfg_src}")
    lines.append(f"  scanned: {len(report.scanned_files)} file(s)")
    if report.excluded_files:
        lines.append(f"  excluded: {len(report.excluded_files)} file(s)")
    if report.unparseable:
        lines.append(c.yellow(f"  parse errors: {len(report.unparseable)} file(s)"))
    lines.append("")

    counts = report.counts()
    checked = report.percent_checked()
    fully = report.percent_fully_typed()

    non_excluded_total = counts.get("total", 0)
    lines.append(c.bold("Coverage:"))
    lines.append(
        f"  body-checked by mypy:  {_pct_colored(checked, c)}  "
        f"({counts.get(STATUS_ANNOTATED, 0) + counts.get(STATUS_PARTIAL, 0)}"
        f" / {non_excluded_total})"
    )
    lines.append(
        f"  fully annotated:       {_pct_colored(fully, c)}  "
        f"({counts.get(STATUS_ANNOTATED, 0)} / {non_excluded_total})"
    )
    lines.append("")

    lines.append(c.bold("Breakdown:"))
    lines.append(f"  annotated:    {counts.get(STATUS_ANNOTATED, 0):>5}")
    lines.append(f"  partial:      {counts.get(STATUS_PARTIAL, 0):>5}")
    lines.append(f"  unannotated:  {counts.get(STATUS_UNANNOTATED, 0):>5}")
    lines.append("")

    entries = per_file_stats(report, sort_by=sort_by)
    if entries:
        lines.append(c.bold(f"Per-file (files with gaps, sorted by {sort_by}):"))
        _append_per_file_table(lines, entries)
        lines.append("")

    if list_uncovered:
        uncovered = _defs_matching(report, STATUS_UNANNOTATED, in_excluded_file=False)
        lines.append(c.bold(f"Unannotated (body skipped) -- {len(uncovered)} item(s):"))
        for d in uncovered:
            lines.append(f"  {d.file}:{d.lineno:<5}  {d.kind:<8}  {d.qualname}")
        lines.append("")

    if list_partial:
        partial = _defs_matching(report, STATUS_PARTIAL, in_excluded_file=False)
        lines.append(c.bold(f"Partially annotated -- {len(partial)} item(s):"))
        for d in partial:
            lines.append(f"  {d.file}:{d.lineno:<5}  {d.qualname}  [{d.reason}]")
        lines.append("")

    excluded_counts = report.counts(in_excluded_file=True)
    if include_excluded and excluded_counts.get("total", 0) > 0:
        _append_excluded_section(
            lines,
            report,
            excluded_counts,
            sort_by=sort_by,
            list_members=show_excluded,
            c=c,
        )

    if report.silent_any:
        lines.append(c.bold(f"Silent-Any candidates -- {len(report.silent_any)} item(s):"))
        for hit in report.silent_any:
            lines.append(f"  {hit.file}:{hit.lineno:<5}  [{hit.kind}]  {hit.detail}")
        lines.append("")

    if report.unparseable:
        lines.append(c.yellow("Files with parse errors (skipped):"))
        for p in report.unparseable:
            lines.append(f"  {p}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _append_per_file_table(lines: list[str], entries: list) -> None:  # type: ignore[type-arg]
    header = f"  {'file':<60} {'fully%':>7} {'check%':>7} {'unann':>6} {'part':>5}"
    lines.append(header)
    lines.append(f"  {'-' * 58:<60} {'-------':>7} {'-------':>7} {'-----':>6} {'----':>5}")
    for entry in entries:
        lines.append(
            f"  {entry['file']:<60}"
            f" {entry['fully_pct']:>6.1f}%"
            f" {entry['checked_pct']:>6.1f}%"
            f" {entry['unannotated']:>6}"
            f" {entry['partial']:>5}"
        )


def _append_excluded_section(
    lines: list[str],
    report: CoverageReport,
    excluded_counts: dict[str, int],
    sort_by: str,
    list_members: bool,
    c: Colors,
) -> None:
    """Walled-off section for definitions inside mypy-excluded files."""
    total = excluded_counts.get("total", 0)
    checked = report.percent_checked(in_excluded_file=True)
    fully = report.percent_fully_typed(in_excluded_file=True)

    border = "=" * 72
    lines.append(c.dim(border))
    lines.append(c.bold("Excluded files (visibility only -- NOT counted in main coverage)"))
    lines.append(c.dim(border))
    lines.append("  mypy skips these files entirely. Numbers below are informational --")
    lines.append("  low coverage here is expected and does not affect the main report.")
    lines.append("")
    lines.append(f"  definitions in excluded files:    {total}")
    lines.append(
        f"  body-checked (if not excluded):   {_pct_colored(checked, c)}  "
        f"({excluded_counts.get(STATUS_ANNOTATED, 0) + excluded_counts.get(STATUS_PARTIAL, 0)}"
        f" / {total})"
    )
    lines.append(
        f"  fully annotated:                  {_pct_colored(fully, c)}  "
        f"({excluded_counts.get(STATUS_ANNOTATED, 0)} / {total})"
    )
    lines.append(f"  annotated:    {excluded_counts.get(STATUS_ANNOTATED, 0):>5}")
    lines.append(f"  partial:      {excluded_counts.get(STATUS_PARTIAL, 0):>5}")
    lines.append(f"  unannotated:  {excluded_counts.get(STATUS_UNANNOTATED, 0):>5}")
    lines.append("")

    entries = per_file_stats(
        report,
        sort_by=sort_by,
        in_excluded_file=True,
        include_clean_files=True,
    )
    if entries:
        lines.append(f"  Per-file (excluded, sorted by {sort_by}):")
        _append_per_file_table(lines, entries)
        lines.append("")

    if list_members:
        members = [d for d in report.definitions if d.in_excluded_file]
        members.sort(key=lambda d: (d.file, d.lineno))
        lines.append(f"  Definitions in excluded files -- {len(members)} item(s):")
        for d in members:
            lines.append(f"    {d.file}:{d.lineno:<5}  {d.kind:<8}  {d.status:<11}  {d.qualname}")
        lines.append("")


def _defs_matching(
    report: CoverageReport,
    status: str,
    in_excluded_file: bool,
) -> list[Definition]:
    defs = [
        d
        for d in report.definitions
        if d.status == status and d.in_excluded_file == in_excluded_file
    ]
    defs.sort(key=lambda d: (d.file, d.lineno))
    return defs


def render_json(report: CoverageReport) -> str:
    """Render a machine-readable JSON blob of the full report.

    Definitions are sorted by ``(file, lineno)`` for stable output.
    """
    sorted_defs = sorted(report.definitions, key=lambda d: (d.file, d.lineno))
    definitions = [asdict(d) for d in sorted_defs]
    for d in definitions:
        # Tuples don't round-trip through JSON cleanly.
        d["decorators"] = list(d["decorators"])
    payload: dict[str, Any] = {
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
        "excluded_summary": {
            "counts": report.counts(in_excluded_file=True),
            "percent_body_checked": report.percent_checked(in_excluded_file=True),
            "percent_fully_typed": report.percent_fully_typed(in_excluded_file=True),
        },
        "per_file": per_file_stats(report),
        "per_file_excluded": per_file_stats(
            report, in_excluded_file=True, include_clean_files=True
        ),
        "definitions": definitions,
        "silent_any": [asdict(h) for h in report.silent_any],
        "unparseable": [str(p) for p in report.unparseable],
    }
    return json.dumps(payload, indent=2, default=str)


def render_markdown(report: CoverageReport, include_excluded: bool = True) -> str:
    """Render the report as GitHub-flavoured Markdown.

    ``include_excluded`` controls whether the excluded-files section is
    emitted (see :func:`render_text` for the full semantics).
    """
    lines: list[str] = []
    lines.append("# mypy-coverage report\n")
    lines.append(f"- **Root:** `{report.root}`")
    lines.append(
        f"- **Config:** `{report.config.source}`"
        if report.config.source
        else "- **Config:** _none_"
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
    lines.append("")

    entries = per_file_stats(report, truncate_path=None)
    if entries:
        lines.append("## Files with gaps")
        lines.append("")
        lines.append("| file | fully typed % | body checked % | unannotated | partial |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for e in entries:
            lines.append(
                f"| `{e['file']}` | {e['fully_pct']:.1f}% | {e['checked_pct']:.1f}% "
                f"| {e['unannotated']} | {e['partial']} |"
            )
        lines.append("")

    uncovered = _defs_matching(report, STATUS_UNANNOTATED, in_excluded_file=False)
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

    excluded_counts = report.counts(in_excluded_file=True)
    if include_excluded and excluded_counts.get("total", 0) > 0:
        lines.append("## Excluded files (visibility only — not counted)")
        lines.append("")
        lines.append(
            "> mypy skips these files. The numbers below are informational "
            "and do NOT affect the summary above."
        )
        lines.append("")
        lines.append("| metric | value |")
        lines.append("| --- | ---: |")
        lines.append(
            f"| body-checked (if not excluded) "
            f"| {report.percent_checked(in_excluded_file=True):.1f}% |"
        )
        lines.append(
            f"| fully annotated | " f"{report.percent_fully_typed(in_excluded_file=True):.1f}% |"
        )
        lines.append(f"| annotated | {excluded_counts.get(STATUS_ANNOTATED, 0)} |")
        lines.append(f"| partial | {excluded_counts.get(STATUS_PARTIAL, 0)} |")
        lines.append(f"| unannotated | {excluded_counts.get(STATUS_UNANNOTATED, 0)} |")
        lines.append("")

        exc_entries = per_file_stats(
            report, truncate_path=None, in_excluded_file=True, include_clean_files=True
        )
        if exc_entries:
            lines.append("| file | fully typed % | body checked % | unannotated | partial |")
            lines.append("| --- | ---: | ---: | ---: | ---: |")
            for e in exc_entries:
                lines.append(
                    f"| `{e['file']}` | {e['fully_pct']:.1f}% | {e['checked_pct']:.1f}% "
                    f"| {e['unannotated']} | {e['partial']} |"
                )
            lines.append("")

    if report.silent_any:
        lines.append(f"## Silent-Any candidates ({len(report.silent_any)})")
        lines.append("")
        for hit in report.silent_any:
            lines.append(f"- `{hit.file}:{hit.lineno}` **{hit.kind}** --- {hit.detail}")
        lines.append("")

    return "\n".join(lines)


def render_github(report: CoverageReport) -> str:
    """Render the report as GitHub Actions annotations.

    Definitions inside excluded files are NOT annotated -- mypy doesn't
    analyse them and flagging them would be noise.
    """
    lines: list[str] = []
    for d in report.definitions:
        if d.in_excluded_file:
            continue
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
