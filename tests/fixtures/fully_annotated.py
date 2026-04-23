"""Every def is fully annotated: expected 100% on both metrics."""

from __future__ import annotations


def plain(x: int, y: int) -> int:
    return x + y


def no_args() -> None:
    return None


def varargs(*args: int, **kwargs: str) -> list[int]:
    return list(args)


async def async_fn(x: str) -> str:
    return x


class MyClass:
    def method(self, x: int) -> int:
        return x

    @staticmethod
    def static_method(x: int) -> int:
        return x

    @classmethod
    def class_method(cls, x: int) -> int:
        return x

    @property
    def prop(self) -> int:
        return 1
