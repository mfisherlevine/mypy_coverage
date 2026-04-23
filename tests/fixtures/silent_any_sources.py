"""Imports and patterns used to exercise --silent-any detection."""

from __future__ import annotations

from somelib import thing  # declared ignore_missing_imports in test config
import other_pkg.submodule  # wildcard match against "other_pkg.*"

from typing import Any  # should NOT be flagged (typing isn't ignored)

result = thing()  # type: ignore[misc]


@thing
def decorated_by_ignored(x: int) -> int:
    return x


def normal(x: int) -> int:
    return x
