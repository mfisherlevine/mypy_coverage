"""Nesting: nested functions should count as functions, not methods, even
when the outer context is a method. Nested classes are still classes."""

from __future__ import annotations


def outer(x: int) -> int:
    def inner(y: int) -> int:
        return y

    def unannotated_inner(y):
        return y

    return inner(x) + unannotated_inner(x)


class Outer:
    def method(self, x: int) -> int:
        def nested_in_method(y: int) -> int:
            return y

        def nested_unannotated(y):
            return y

        class NestedClass:
            def nested_method(self) -> None:
                return None

        return nested_in_method(x) + nested_unannotated(x)
