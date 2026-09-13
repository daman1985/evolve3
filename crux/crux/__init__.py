"""crux: a general-purpose, call-count-frugal test-case reducer.

This package (``crux.crux``... no -- the shipped package is simply ``crux``,
rooted at ``crux/crux/`` in the repository) contains only the shared
abstractions and, eventually, the reduction algorithm and CLI. It is stdlib
only: no dependency on picire/numpy/anything in crux/baselines or crux/bench
may leak in here.
"""

from .core import (
    BudgetExhausted,
    CharProblem,
    LineProblem,
    Oracle,
    ReductionProblem,
)

__all__ = [
    "BudgetExhausted",
    "CharProblem",
    "LineProblem",
    "Oracle",
    "ReductionProblem",
]
