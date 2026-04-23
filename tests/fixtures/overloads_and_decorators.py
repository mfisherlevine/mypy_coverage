"""@overload should count as annotated even with no param/return types.
@staticmethod should count params starting from the first arg (no self)."""

from __future__ import annotations

from typing import overload


@overload
def f(x: int) -> int: ...
@overload
def f(x: str) -> str: ...
def f(x):
    return x


class C:
    @staticmethod
    def static_with_annots(x: int) -> int:
        return x

    @staticmethod
    def static_unannotated(x):
        return x

    @classmethod
    def class_method_annotated(cls, x: int) -> int:
        return x
