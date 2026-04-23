"""Exactly 2 annotated + 2 partial + 2 unannotated + nothing else.

Expected: fully_typed = 2/6 = 33.3%, checked = 4/6 = 66.7%.
"""

from __future__ import annotations


def full_one(x: int) -> int:
    return x


def full_two(x: int, y: int) -> int:
    return x + y


def partial_one(x: int, y):
    return x + y  # missing y annotation and return


def partial_two(x) -> int:
    return x  # missing x annotation


def bare_one(x):
    return x


def bare_two():
    pass
