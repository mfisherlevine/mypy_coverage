"""Same structure as ``long_bodies.py`` but with one-liner bodies. Should
produce identical coverage numbers -- proves body length is irrelevant.
"""

from __future__ import annotations


def big_annotated(x: int) -> int: return x


def big_unannotated(x): return x
