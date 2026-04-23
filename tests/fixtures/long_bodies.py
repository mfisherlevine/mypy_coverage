"""Two defs with extremely long bodies. Used to prove coverage is by
definition count, not line count: one annotated + one unannotated = 50%,
regardless of how many lines are inside each function.
"""

from __future__ import annotations


def big_annotated(x: int) -> int:
    """A long-bodied, fully-annotated function."""
    a = x + 1
    b = a + 1
    c = b + 1
    d = c + 1
    e = d + 1
    f = e + 1
    g = f + 1
    h = g + 1
    i = h + 1
    j = i + 1
    k = j + 1
    m = k + 1
    n = m + 1
    o = n + 1
    p = o + 1
    q = p + 1
    r = q + 1
    s = r + 1
    t = s + 1
    u = t + 1
    v = u + 1
    w = v + 1
    y = w + 1
    z = y + 1
    return z


def big_unannotated(x):
    """A long-bodied, unannotated function."""
    a = x + 1
    b = a + 1
    c = b + 1
    d = c + 1
    e = d + 1
    f = e + 1
    g = f + 1
    h = g + 1
    i = h + 1
    j = i + 1
    k = j + 1
    m = k + 1
    n = m + 1
    o = n + 1
    p = o + 1
    q = p + 1
    r = q + 1
    s = r + 1
    t = s + 1
    u = t + 1
    v = u + 1
    w = v + 1
    y = w + 1
    z = y + 1
    return z
