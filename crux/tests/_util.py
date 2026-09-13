"""Shared test helpers. Not collected by pytest itself (no test_* name).

Kept deliberately independent of crux/bench/tasks.py's own construction
internals (RNG seeds, private placement helpers) where practical, so a test
that reconstructs a "known good" witness by different means than the code
under test does not simply repeat the same bug on both sides.
"""
from __future__ import annotations

from typing import Sequence


def byte_len(text: str) -> int:
    return len(text.encode("utf-8", "surrogateescape"))


def render(elements: Sequence[str], kept) -> str:
    return "".join(elements[i] for i in sorted(kept))


def extract_depth_witness(elements: Sequence[str], d: int) -> tuple[int, ...]:
    """Given a sequence of '(' / ')' characters that is balanced with max
    bracket-nesting depth >= d, return an index set of size exactly 2*d
    that is ITSELF balanced with depth exactly d -- i.e. an independently
    (re-)derived, closed-form witness for a nest-N task's known_optimum,
    computed with no knowledge of how the padding pairs were inserted.

    Method: one stack-based scan. The moment the stack of currently-open
    '(' indices first reaches size d, its d entries are a properly nested
    chain (LIFO order guarantees opens[0] < opens[1] < ... < opens[d-1]
    with none yet closed). Continue scanning and record, for each of
    those specific d indices, the index of the ')' that eventually pops
    it. By stack discipline the recorded closes come out in the reverse
    (LIFO) order, so `opens + closes`, sorted, renders as a fully nested
    "("*d + ")"*d -- balanced, depth exactly d, size exactly 2*d. Every
    pushed index is guaranteed to eventually be popped because the input
    is balanced overall, so this always terminates given a genuine
    balanced-with-depth->=d input.
    """
    stack: list[int] = []
    opens: list[int] | None = None
    tracked: set[int] = set()
    matched: dict[int, int] = {}

    for i, ch in enumerate(elements):
        if ch == "(":
            stack.append(i)
            if opens is None and len(stack) == d:
                opens = list(stack)
                tracked = set(opens)
        elif ch == ")":
            if stack:
                popped = stack.pop()
                if popped in tracked and popped not in matched:
                    matched[popped] = i
        if opens is not None and len(matched) == d:
            break

    if opens is None or len(matched) != d:
        raise AssertionError(f"could not extract a depth-{d} witness (opens={opens}, matched={len(matched)})")

    closes = [matched[o] for o in opens]
    return tuple(sorted(opens + closes))
