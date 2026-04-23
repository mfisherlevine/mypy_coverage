"""mypy-coverage: report mypy annotation coverage for a Python codebase."""

from __future__ import annotations

__version__ = "0.1.1"

from .config import discover_config, load_config
from .models import (
    STATUS_ANNOTATED,
    STATUS_PARTIAL,
    STATUS_UNANNOTATED,
    CoverageReport,
    Definition,
    MypyConfig,
    SilentAnyHit,
)
from .report import build_report
from .scanner import scan_file
from .silent_any import scan_silent_any

__all__ = [
    "CoverageReport",
    "Definition",
    "MypyConfig",
    "STATUS_ANNOTATED",
    "STATUS_PARTIAL",
    "STATUS_UNANNOTATED",
    "SilentAnyHit",
    "__version__",
    "build_report",
    "discover_config",
    "load_config",
    "scan_file",
    "scan_silent_any",
]
