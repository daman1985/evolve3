"""CDD, the simplified variant from Zhang et al., "Toward Understanding the
Effectiveness of Probabilistic Delta Debugging", FSE 2024. That paper's
central finding is that most of ProbDD's improvement over ddmin comes from
RANDOMISED candidate selection, not from the learned probability model:
CDD keeps ddmin's coarse-to-fine backbone (try large chunks first, shrink
the chunk size once a size makes no progress, stop once even
single-element tries make no progress) but replaces ddmin's fixed,
systematic left-to-right partition scan with uniformly random subsets of
the current candidate size, and carries no probability model at all.

Faithful to this round's one-line spec ("deletes randomly-chosen subsets
of geometrically decreasing size, no probability model. Fixed seed."),
filled in below with the most literal, least-invented reading available:
picire's own ddmin (ddmin_picire.py) resets to coarse granularity after
EVERY successful reduction and tries exactly `ceil(len(config)/size)`
chunks at a given size before giving up on it; CDD does the same, just
drawing each of those chunks at random with a fixed seed instead of from a
fixed partition.

Two constants below are genuinely this file's own choice, absent from the
one-line spec, and are flagged as such in the reducer-engineer report: the
RNG seed, and SHRINK = 2 (mirroring ddmin's own halving/doubling factor,
the natural choice absent a stated one). Neither is derived from any task
(reducer-engineer hard rule: no per-task constants).
"""
from __future__ import annotations

import random

from crux.crux.core import BudgetExhausted, ReductionProblem

SEED = 0xC0DD  # fixed seed: same input -> same sequence of candidates, always.
SHRINK = 2


def reduce(problem: ReductionProblem, kept: tuple) -> tuple:
    oracle = problem.oracle
    rng = random.Random(SEED)
    active = set(kept)

    # Hard rule (reducer-engineer brief #1): always return a set that was
    # actually tested True. See ddmin_own.py for the fuller rationale.
    try:
        oracle(tuple(sorted(active)))
    except BudgetExhausted:
        return oracle.best

    try:
        while len(active) > 1:
            # One coarse-to-fine pass, exactly like ddmin: start at "try
            # removing about half", shrink geometrically on failure, and
            # stop the whole reduction once a full pass (down to
            # single-element candidates) makes no progress anywhere.
            m = max(1, len(active) // 2)
            progressed_this_pass = False

            while len(active) > 1:
                size = min(m, len(active) - 1)  # never test an empty candidate while >1 remain
                # ddmin would try this many systematic chunks at this
                # granularity (ceil(len(active) / size)); CDD tries that
                # many RANDOM ones instead.
                attempts = -(-len(active) // size)

                success = False
                for _ in range(attempts):
                    size = min(m, len(active) - 1)
                    S = set(rng.sample(sorted(active), size))
                    if oracle(tuple(sorted(active - S))):
                        active -= S
                        success = True
                        break

                if success:
                    progressed_this_pass = True
                    break  # back to the outer loop: fresh coarse m against the smaller active set

                if m == 1:
                    break  # finest granularity, no progress this pass
                m = max(1, m // SHRINK)

            if not progressed_this_pass:
                break  # a full coarse-to-fine pass changed nothing: done
    except BudgetExhausted:
        return oracle.best

    return tuple(sorted(active))
