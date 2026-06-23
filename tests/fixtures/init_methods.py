"""Every __init__ / __init_subclass__ annotation shape, plus contrasts.

mypy infers a ``None`` return for ``__init__`` and ``__init_subclass__``, so an
explicit ``-> None`` is NOT required for them to be fully typed -- as long as at
least one parameter is annotated. This fixture enumerates every combination so
both the scanner unit tests and the mypy cross-check (see
tests/test_init_return_waiver.py) can assert agreement with real mypy.

Each method body is the single expression ``42 + "abc"`` -- a deliberate type
error. The scanner ignores bodies, but mypy only reports that error when it
actually type-checks the body, which reveals whether mypy considers the method
typed (checked) or untyped (skipped). Do not "fix" these bodies; the fixtures
dir is excluded from lint/format/mypy on purpose.

Expected status per definition is noted inline as ANNOTATED / PARTIAL /
UNANNOTATED.
"""

from __future__ import annotations


# --- __init__: the return annotation is waived once a param is annotated ---


class InitNoParamsReturn:  # def __init__(self) -> None  -> ANNOTATED
    def __init__(self) -> None:
        42 + "abc"


class InitNoParamsNoReturn:  # def __init__(self)  -> UNANNOTATED
    def __init__(self):
        42 + "abc"


class InitOneAnnotReturn:  # def __init__(self, x: int) -> None  -> ANNOTATED
    def __init__(self, x: int) -> None:
        42 + "abc"


class InitOneAnnotNoReturn:  # def __init__(self, x: int)  -> ANNOTATED (the fix)
    def __init__(self, x: int):
        42 + "abc"


class InitOneBareNoReturn:  # def __init__(self, x)  -> UNANNOTATED
    def __init__(self, x):
        42 + "abc"


class InitOneBareReturn:  # def __init__(self, x) -> None  -> PARTIAL
    def __init__(self, x) -> None:
        42 + "abc"


class InitMixedNoReturn:  # def __init__(self, x: int, y)  -> PARTIAL
    def __init__(self, x: int, y):
        42 + "abc"


class InitMixedReturn:  # def __init__(self, x: int, y) -> None  -> PARTIAL
    def __init__(self, x: int, y) -> None:
        42 + "abc"


class InitAllAnnotNoReturn:  # def __init__(self, x: int, y: int)  -> ANNOTATED (the fix)
    def __init__(self, x: int, y: int):
        42 + "abc"


class InitAllAnnotReturn:  # def __init__(self, x: int, y: int) -> None  -> ANNOTATED
    def __init__(self, x: int, y: int) -> None:
        42 + "abc"


class InitTwoBareNoReturn:  # def __init__(self, a, b)  -> UNANNOTATED
    def __init__(self, a, b):
        42 + "abc"


class InitTwoBareReturn:  # def __init__(self, a, b) -> None  -> PARTIAL
    def __init__(self, a, b) -> None:
        42 + "abc"


# --- __init_subclass__: mypy waives its return annotation too ---


class SubclassOneAnnotNoReturn:  # def __init_subclass__(cls, x: int)  -> ANNOTATED
    def __init_subclass__(cls, x: int):
        42 + "abc"


class SubclassNoParamsReturn:  # def __init_subclass__(cls) -> None  -> ANNOTATED
    def __init_subclass__(cls) -> None:
        42 + "abc"


class SubclassNoParamsNoReturn:  # def __init_subclass__(cls)  -> UNANNOTATED
    def __init_subclass__(cls):
        42 + "abc"


class SubclassMixedNoReturn:  # def __init_subclass__(cls, x: int, y)  -> PARTIAL
    def __init_subclass__(cls, x: int, y):
        42 + "abc"


# --- Contrast: methods whose return is NOT waived by mypy ---


class NewOneAnnotNoReturn:  # def __new__(cls, x: int)  -> PARTIAL (return required)
    def __new__(cls, x: int):
        42 + "abc"


class NewNoParamsNoReturn:  # def __new__(cls)  -> UNANNOTATED
    def __new__(cls):
        42 + "abc"


class RegularOneAnnotNoReturn:  # def method(self, x: int)  -> PARTIAL (return required)
    def method(self, x: int):
        42 + "abc"


# Module-level function literally named __init__: NOT a method, so no waiver.
def __init__(x: int):  # -> PARTIAL (return still required outside a class)
    42 + "abc"
