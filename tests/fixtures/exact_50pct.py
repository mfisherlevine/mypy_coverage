"""Exactly 3 annotated + 3 unannotated defs: 50% on both metrics.

The ``class Container`` *itself* counts as a definition (status=annotated
for classes), but so does another class below — we balance them so the
six function-kind defs drive the split.
"""

from __future__ import annotations


# Three fully annotated.
def ann_one(x: int) -> int:
    return x


def ann_two(x: int, y: int) -> int:
    return x + y


def ann_three() -> None:
    return None


# Three fully unannotated.
def un_one(x):
    return x


def un_two(x, y):
    return x + y


def un_three():
    pass
