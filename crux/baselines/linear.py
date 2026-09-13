"""The naive rung: repeatedly sweep the currently-kept elements, trying to
delete each one alone (against the up-to-date, possibly already-shrunk-this-
sweep kept set), until a full sweep deletes nothing. This is "try deleting
each line one at a time" (PLAN.md S1) -- what most people hand-roll first --
included as the bottom of the ladder every other method should clear.
"""
from __future__ import annotations

from crux.crux.core import BudgetExhausted, ReductionProblem


def reduce(problem: ReductionProblem, kept: tuple) -> tuple:
    oracle = problem.oracle
    c = set(kept)

    # Hard rule (reducer-engineer brief #1): always return a kept-set that
    # was actually tested True. This sweep only ever tests proper subsets
    # of c below, so confirm the starting point itself first -- otherwise a
    # BudgetExhausted before the first successful deletion would leave
    # oracle.best unset. See ddmin_own.py for the fuller rationale.
    try:
        oracle(tuple(sorted(c)))
    except BudgetExhausted:
        return oracle.best

    try:
        progress = True
        while progress:
            progress = False
            for i in sorted(c):
                candidate = c - {i}
                if oracle(tuple(sorted(candidate))):
                    c = candidate
                    progress = True
    except BudgetExhausted:
        return oracle.best

    return tuple(sorted(c))
