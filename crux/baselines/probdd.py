"""ProbDD (Wang, Chen, Cui, et al., "ProbDD: A Probability-Based Delta
Debugging Algorithm", ASE 2021): a probabilistic delta-debugging algorithm
that models each element's deletability as an independent Bernoulli
probability and, each round, tests the probability-sorted PREFIX that
maximises expected number of elements removed -- instead of ddmin's fixed
n-way partition.

Faithful to the algorithm as specified for this round (PLAN.md / round-0
brief, itself a compressed restatement of the published algorithm):
uniform initial probabilities; each round sort by p descending and pick
the prefix maximising expected gain |S| * prod(p_i); permanent deletion on
success; Bayesian update on failure; stop when no candidate has positive
expected gain.
"""
from __future__ import annotations

from crux.crux.core import BudgetExhausted, ReductionProblem

# Wang et al. ASE'21: elements start with no evidence either way -- 0.5,
# the maximum-entropy / uninformative prior, is both the standard choice
# and (to the best of this implementation's knowledge of the paper) the
# value it states. Pinned as a single global constant, not derived from any
# task (reducer-engineer hard rule: no per-task constants).
INITIAL_P = 0.5

# Expected gain is a product of probabilities in [0, 1] times a count, so
# it is never negative; "positive expected gain" is tested against a small
# epsilon purely to absorb floating-point noise from repeated
# multiplication, not as a free algorithmic parameter.
_EPS = 1e-12


def reduce(problem: ReductionProblem, kept: tuple) -> tuple:
    oracle = problem.oracle
    kept_set = set(kept)

    # Hard rule (reducer-engineer brief #1): a reducer must always return a
    # set that was actually tested True. ProbDD's own loop only ever tests
    # PROPER subsets (kept_set minus a nonempty prefix S) below, so without
    # this, a BudgetExhausted before the first successful deletion would
    # leave oracle.best unset. See ddmin_own.py for the fuller rationale.
    try:
        oracle(tuple(sorted(kept_set)))
    except BudgetExhausted:
        return oracle.best

    p: dict[int, float] = {i: INITIAL_P for i in kept_set}

    try:
        while p:
            ranked = sorted(p, key=lambda i: p[i], reverse=True)

            # Expected gain of taking the top-k ranked elements as candidate
            # S: EG(k) = |S| * Pr(all of S simultaneously removable),
            # assuming independence across elements (Wang et al.'s
            # objective). A running product turns the scan over all k into
            # one O(n) pass.
            best_k, best_eg, best_prod = 0, 0.0, 1.0
            running_prod = 1.0
            for k, idx in enumerate(ranked, start=1):
                running_prod *= p[idx]
                eg = k * running_prod
                if eg > best_eg:
                    best_k, best_eg, best_prod = k, eg, running_prod

            if best_k == 0 or best_eg <= _EPS:
                break  # no candidate has positive expected gain: done

            S = set(ranked[:best_k])
            remaining = kept_set - S

            if oracle(tuple(sorted(remaining))):
                # Success: S is confirmed deletable, permanently (paper:
                # "on success delete S permanently") -- drop it from both
                # the kept set and the probability model for good.
                kept_set = remaining
                for i in S:
                    del p[i]
            else:
                # Failure: at least one element of S is required. Bayesian
                # update under the independence assumption. Let
                # P = prod(p_j for j in S) = Pr(all of S removable). Then:
                #   Pr(i removable AND all-of-S removable) = P     (all-of-S
                #     removable already implies i removable, for i in S)
                #   Pr(i removable AND NOT all-of-S removable)
                #     = Pr(i removable) - P = p_i - P
                #   Pr(NOT all-of-S removable) = 1 - P
                # so, by conditioning on the observed failure:
                #   p_i <- Pr(i removable | NOT all-of-S removable)
                #        = (p_i - P) / (1 - P)
                P = best_prod
                denom = 1.0 - P
                for i in S:
                    p[i] = (p[i] - P) / denom if denom > 0 else 0.0
    except BudgetExhausted:
        return oracle.best

    return tuple(sorted(kept_set))
