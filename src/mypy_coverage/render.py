"""Render a :class:`CoverageReport` in several formats."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from typing import Any

from .models import (
    STATUS_ANNOTATED,
    STATUS_EXCLUDED,
    STATUS_PARTIAL,
    STATUS_UNANNOTATED,
    CoverageReport,
    Definition,
)
from .report import per_file_stats


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


def render_text(
    report: CoverageReport,
    list_uncovered: bool = False,
    list_partial: bool = False,
    show_excluded: bool = False,
    colors: Colors | None = None,
) -> str:
    """Render a human-readable summary report."""
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

    def pct_color(pct: float) -> str:
        s = f"{pct:5.1f}%"
        if pct >= 90:
            return c.green(s)
        if pct >= 70:
            return c.yellow(s)
        return c.red(s)

    non_excluded_total = counts.get("total", 0) - counts.get(STATUS_EXCLUDED, 0)
    lines.append(c.bold("Coverage:"))
    lines.append(
        f"  body-checked by mypy:  {pct_color(checked)}  "
        f"({counts.get(STATUS_ANNOTATED, 0) + counts.get(STATUS_PARTIAL, 0)}"
        f" / {non_excluded_total})"
    )
    lines.append(
        f"  fully annotated:       {pct_color(fully)}  "
        f"({counts.get(STATUS_ANNOTATED, 0)} / {non_excluded_total})"
    )
    lines.append("")

    lines.append(c.bold("Breakdown:"))
    lines.append(f"  annotated:    {counts.get(STATUS_ANNOTATED, 0):>5}")
    lines.append(f"  partial:      {counts.get(STATUS_PARTIAL, 0):>5}")
    lines.append(f"  unannotated:  {counts.get(STATUS_UNANNOTATED, 0):>5}")
    lines.append(f"  excluded:     {counts.get(STATUS_EXCLUDED, 0):>5}")
    lines.append("")

    entries = per_file_stats(report)
    if entries:
        lines.append(c.bold("Per-file (files with uncovered or partial):"))
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
        lines.append("")

    if list_uncovered:
        uncovered = [d for d in report.definitions if d.status == STATUS_UNANNOTATED]
        lines.append(c.bold(f"Unannotated (body skipped) -- {len(uncovered)} item(s):"))
        for d in sorted(uncovered, key=lambda x: (x.file, x.lineno)):
            lines.append(f"  {d.file}:{d.lineno:<5}  {d.kind:<8}  {d.qualname}")
        lines.append("")

    if list_partial:
        partial = [d for d in report.definitions if d.status == STATUS_PARTIAL]
        lines.append(c.bold(f"Partially annotated -- {len(partial)} item(s):"))
        for d in sorted(partial, key=lambda x: (x.file, x.lineno)):
            lines.append(f"  {d.file}:{d.lineno:<5}  {d.qualname}  [{d.reason}]")
        lines.append("")

    if show_excluded:
        excluded = [d for d in report.definitions if d.status == STATUS_EXCLUDED]
        lines.append(c.bold(f"Excluded by config -- {len(excluded)} item(s):"))
        for d in sorted(excluded, key=lambda x: (x.file, x.lineno)):
            lines.append(f"  {d.file}:{d.lineno:<5}  {d.kind:<8}  {d.qualname}")
        lines.append("")

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


def render_json(report: CoverageReport) -> str:
    """Render a machine-readable JSON blob of the full report."""
    definitions = [asdict(d) for d in report.definitions]
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
        "per_file": per_file_stats(report),
        "definitions": definitions,
        "silent_any": [asdict(h) for h in report.silent_any],
        "unparseable": [str(p) for p in report.unparseable],
    }
    return json.dumps(payload, indent=2, default=str)


def render_markdown(report: CoverageReport) -> str:
    """Render the report as GitHub-flavoured Markdown."""
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
    lines.append(f"| excluded             | {counts.get(STATUS_EXCLUDED, 0)} |")
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
            lines.append(f"- `{hit.file}:{hit.lineno}` **{hit.kind}** --- {hit.detail}")
        lines.append("")

    return "\n".join(lines)


def render_github(report: CoverageReport) -> str:
    """Render the report as GitHub Actions ``::warning`` / ``::notice`` lines."""
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
