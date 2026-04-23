"""Command-line entry point for mypy-coverage."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import discover_config, load_config
from .models import MypyConfig
from .render import Colors, render_github, render_json, render_markdown, render_text
from .report import build_report


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="mypy-coverage",
        description="Report mypy annotation coverage for a Python codebase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Paths (files or directories) to scan. Defaults to the `files` "
        "and `mypy_path` settings in the mypy config, or the current directory.",
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
        "--include-excluded",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include the walled-off coverage report for files excluded by "
        "mypy (default: yes). Pass --no-include-excluded to hide it.",
    )
    parser.add_argument(
        "--show-excluded",
        action="store_true",
        help="Inside the excluded section, list every definition by name "
        "with its real status. Implies --include-excluded.",
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
        help="Exit with status 1 if coverage is below PERCENT.",
    )
    parser.add_argument(
        "--threshold-metric",
        choices=("checked", "fully-typed"),
        default="checked",
        help="Which percentage --threshold applies to.",
    )
    parser.add_argument(
        "--sort",
        choices=("path", "coverage"),
        default="path",
        help="Sort per-file tables by file path (alphabetical, default) or "
        "by coverage (worst first).",
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
    return parser


def want_color(choice: str) -> bool:
    if choice == "always":
        return True
    if choice == "never":
        return False
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def resolve_paths(args: argparse.Namespace, cfg: MypyConfig, root: Path) -> list[Path]:
    """Figure out which paths to scan based on CLI args and config."""
    if args.paths:
        return [p if p.is_absolute() else (Path.cwd() / p).resolve() for p in args.paths]
    if cfg.files or cfg.mypy_path:
        combined = list(cfg.files) + list(cfg.mypy_path)
        out: list[Path] = []
        seen: set[Path] = set()
        for entry in combined:
            resolved = (root / entry).resolve()
            if resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
        return out
    return [root]


def main_cli(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg_path = args.config or discover_config(Path.cwd())

    if cfg_path is not None and not cfg_path.is_file():
        print(f"error: config file not found: {cfg_path}", file=sys.stderr)
        return 2

    cfg = load_config(cfg_path) if cfg_path else MypyConfig()

    root = args.root if args.root else (cfg_path.parent if cfg_path else Path.cwd())
    root = root.resolve()

    paths = resolve_paths(args, cfg, root)
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"error: path does not exist: {p}", file=sys.stderr)
        return 2

    report = build_report(paths, cfg, root, want_silent_any=args.silent_any)

    # --show-excluded implies --include-excluded: listing definitions that
    # live in a section we're about to suppress would be contradictory.
    include_excluded = args.include_excluded or args.show_excluded

    if args.format == "text":
        output = render_text(
            report,
            list_uncovered=args.list,
            list_partial=args.list_partial,
            show_excluded=args.show_excluded,
            include_excluded=include_excluded,
            sort_by=args.sort,
            colors=Colors(want_color(args.color)),
        )
    elif args.format == "json":
        output = render_json(report)
    elif args.format == "markdown":
        output = render_markdown(report, include_excluded=include_excluded)
    elif args.format == "github":
        output = render_github(report)
    else:  # pragma: no cover - argparse restricts choices
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
