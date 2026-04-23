"""Enable ``python -m mypy_coverage``."""

from __future__ import annotations

from .cli import main_cli

raise SystemExit(main_cli())
