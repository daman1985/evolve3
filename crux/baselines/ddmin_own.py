"""A textbook, independently-written implementation of ddmin (Zeller &
Hildebrandt, "Simplifying and Isolating Failure-Inducing Input", IEEE
Transactions on Software Engineering 28(2), 2002), used as a cross-check
against the picire adapter in ddmin_picire.py: if the two disagree wildly
in call count on the same tasks, that is evidence the picire wiring is off
-- not that "ddmin" itself is ambiguous. See the reducer-engineer report
for that comparison.

Framing note (ambiguity, resolved explicitly): the paper's Figure 8
pseudocode is stated over two baselines, a known-passing change set
`c_pass` and a known-failing change set `c_fail`, with `ddmin(c) =
ddmin2({}, c, 2)`. That formulation has no direct analogue here: crux
reduces a single KEPT-index subset with no separate "passing" baseline to
diff against, exactly like picire's own `DD` (see ddmin_picire.py), which
is the same one-sided simplification essentially every practical ddmin
implementation uses today. This file follows that same one-sided form:
`c_pass` is implicitly always empty, and "test(Delta_i)" / "test(c_fail -
Delta_i)" become plain oracle calls on a candidate kept-set.

The chunk-splitting formula (front-to-back, later chunks absorbing the
division remainder) is the one described in the paper's own reference
implementation and independently re-derived here (not imported from
picire, whose `ZellerSplit` implements the same published formula under a
different name).

A "result cache" is required by this round's spec; crux.crux.core.Oracle
already provides exactly that (memoised by frozenset(kept), with hits
counted separately from real calls), so no second cache is layered on top
here -- doing so would not change the recorded call count, only duplicate
bookkeeping Oracle already does.
"""
from __future__ import annotations

from crux.crux.core import BudgetExhausted, ReductionProblem


def reduce(problem: ReductionProblem, kept: tuple) -> tuple:
    oracle = problem.oracle

    # Hard rule (reducer-engineer brief #1): a reducer must always return a
    # kept-set that was actually tested True. ddmin only ever tests PROPER
    # subsets/complements of the running config below, so without this
    # explicit confirmation, a BudgetExhausted raised before the first
    # success would leave oracle.best unset. picire's own DD performs the
    # equivalent self-check on every iteration (its `assert ... is FAIL`);
    # this gives our independent implementation the same guarantee, at the
    # same one-call cost, up front instead of every iteration.
    try:
        oracle(tuple(sorted(kept)))
    except BudgetExhausted:
        return oracle.best

    c = tuple(sorted(kept))
    n = 2  # Fig. 8: ddmin(c) = ddmin2({}, c, 2) -- start at 2-way granularity.

    try:
        while len(c) >= 2:
            chunks = _split(c, n)

            # Fig. 8, case 1 ("reduce to subset"): some Delta_i alone still
            # interesting? If so, recurse with n reset to 2.
            reduced = False
            for chunk in chunks:
                if not chunk:
                    continue
                if oracle(chunk):
                    c = chunk
                    n = 2
                    reduced = True
                    break
            if reduced:
                continue

            # Fig. 8, case 2 ("reduce to complement"): removing some Delta_i
            # still interesting? If so, recurse with n decremented (floor 2).
            chunk_sets = [frozenset(ch) for ch in chunks]
            for chunk_set in chunk_sets:
                complement = tuple(x for x in c if x not in chunk_set)
                if len(complement) == len(c):
                    continue
                if oracle(complement):
                    c = complement
                    n = max(n - 1, 2)
                    reduced = True
                    break
            if reduced:
                continue

            # Fig. 8, case 3 ("increase granularity") vs. case 4 (done: n is
            # already as fine as it can get, i.e. 1-minimal).
            if n >= len(c):
                break
            n = min(n * 2, len(c))
    except BudgetExhausted:
        return oracle.best

    return c


def _split(seq: tuple, n: int) -> list[tuple]:
    """Partition seq into n contiguous, "roughly equal" pieces (Zeller &
    Hildebrandt 2002, Sec. 5.3), front chunks absorbing the remainder of
    the integer division -- the same tie-break the paper's own reference
    implementation uses."""
    length = len(seq)
    n = min(n, length) if length else max(n, 1)
    chunks = []
    start = 0
    for i in range(n):
        stop = start + (length - start) // (n - i)
        chunks.append(seq[start:stop])
        start = stop
    return chunks
