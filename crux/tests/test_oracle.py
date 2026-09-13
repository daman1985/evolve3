"""Unit tests for crux.crux.core.Oracle's counting contract (PLAN.md S2 and
the Oracle docstring): real calls vs. cache hits are separate counters, an
exception counts as one real call and is treated as False, a cache hit is
never subject to the budget gate, and BudgetExhausted always carries the
current .best.
"""
from __future__ import annotations

import pytest

from crux.crux.core import BudgetExhausted, Oracle


def test_real_calls_are_counted():
    oracle = Oracle(lambda kept: len(kept) >= 2)
    oracle((1,))
    oracle((1, 2))
    oracle((1, 2, 3))
    assert oracle.calls == 3
    assert oracle.cache_hits == 0


def test_repeat_query_is_a_cache_hit_not_a_call():
    calls_seen = []

    def fn(kept):
        calls_seen.append(kept)
        return True

    oracle = Oracle(fn)
    assert oracle((1, 2)) is True
    assert oracle((2, 1)) is True  # same set, different order/iterable shape
    assert oracle.calls == 1
    assert oracle.cache_hits == 1
    # the underlying fn really was invoked exactly once
    assert len(calls_seen) == 1


def test_cache_keys_by_set_identity_not_argument_order_or_type():
    oracle = Oracle(lambda kept: True)
    oracle([3, 1, 2])
    oracle((1, 2, 3))
    oracle({2, 3, 1})
    assert oracle.calls == 1
    assert oracle.cache_hits == 2


def test_cache_hits_never_folded_into_calls_across_many_repeats():
    oracle = Oracle(lambda kept: True)
    for _ in range(50):
        oracle((1, 2, 3))
    assert oracle.calls == 1
    assert oracle.cache_hits == 49


def test_exception_counts_as_one_real_call_and_is_treated_as_false():
    def fn(kept):
        if kept == (1, 2):
            raise ValueError("boom")
        return True

    oracle = Oracle(fn)
    result = oracle((1, 2))
    assert result is False
    assert oracle.calls == 1
    assert oracle.cache_hits == 0
    # best is not updated on a False (exception-derived) result
    assert oracle.best is None


def test_exception_result_is_cached_so_it_never_re_raises_or_re_executes():
    attempts = []

    def fn(kept):
        attempts.append(kept)
        raise RuntimeError("always explodes")

    oracle = Oracle(fn)
    assert oracle((5,)) is False
    assert oracle((5,)) is False  # must not raise again, must not re-invoke fn
    assert oracle.calls == 1
    assert oracle.cache_hits == 1
    assert len(attempts) == 1


def test_exception_path_does_not_silently_skip_the_counter():
    # A pathological input that always crashes the (cheap, local) oracle
    # must never look "free" the way a cache hit does -- see Oracle's own
    # docstring. This nails down the exact accounting for a mixed sequence
    # of real, crashing, and repeat calls.
    def fn(kept):
        if 0 in kept:
            raise KeyError("bad element")
        return len(kept) <= 2

    oracle = Oracle(fn)
    oracle((0, 1))  # real call #1, raises -> False
    oracle((1, 2))  # real call #2, True
    oracle((1, 2))  # cache hit (of the True result)
    oracle((0, 1))  # cache hit (of the False/exception result)
    assert oracle.calls == 2
    assert oracle.cache_hits == 2


def test_best_updates_on_true_and_tracks_the_smallest_seen():
    oracle = Oracle(lambda kept: len(kept) >= 2)
    oracle((1, 2, 3, 4))
    assert oracle.best == (1, 2, 3, 4)
    oracle((5, 6))  # smaller True set
    assert oracle.best == (5, 6)
    oracle((7, 8, 9))  # larger True set: best must not regress
    assert oracle.best == (5, 6)
    oracle((1,))  # False: best must be unaffected
    assert oracle.best == (5, 6)


def test_cache_hit_path_still_calls_note_best_without_corrupting_it():
    # best is knowledge, not cost (Oracle docstring): the cache-hit branch
    # in __call__ calls _note_best too, not just the real-call branch. By
    # the time any key CAN be a cache hit it was already accounted for at
    # its first (real-call) appearance, so this cannot make best regress
    # or improve -- what it must not do is corrupt calls/cache_hits/best
    # bookkeeping on repeat. Regression target: deleting that call site
    # entirely should not change any assertion here (it would only matter
    # if a cached key's contribution had ever been dropped, which this
    # nails down it is not).
    oracle = Oracle(lambda kept: True)
    oracle((1, 2, 3))
    oracle((1, 2))  # real call, smaller, best -> (1, 2)
    assert oracle.best == (1, 2)
    assert oracle((1, 2, 3)) is True  # cache hit on the larger, earlier key
    assert oracle.best == (1, 2)  # must not regress to the larger key
    assert oracle.calls == 2
    assert oracle.cache_hits == 1


def test_budget_exhausted_raises_and_carries_best():
    oracle = Oracle(lambda kept: True, budget=2)
    oracle((1,))
    oracle((2,))
    assert oracle.calls == 2
    with pytest.raises(BudgetExhausted) as excinfo:
        oracle((3,))
    assert excinfo.value.best == oracle.best
    # (1,) and (2,) tie in size; _note_best only overwrites on a STRICT
    # size improvement, so the first True seen wins the tie.
    assert oracle.best == (1,)
    # calls must not have incremented for the rejected query
    assert oracle.calls == 2


def test_budget_zero_raises_immediately_with_no_best():
    oracle = Oracle(lambda kept: True, budget=0)
    with pytest.raises(BudgetExhausted) as excinfo:
        oracle((1,))
    assert excinfo.value.best is None
    assert oracle.best is None
    assert oracle.calls == 0  # the call never actually happened


def test_cache_hit_bypasses_the_budget_gate():
    # A cache hit must succeed even once the budget is fully spent -- it
    # costs nothing in the real cost model, so gating it on the budget
    # would be wrong (and would make an already-known-True result vanish
    # from `best` at exactly the moment callers rely on it most).
    oracle = Oracle(lambda kept: True, budget=1)
    oracle((1, 2))
    assert oracle.calls == 1
    result = oracle((1, 2))  # exact repeat: must be a cache hit, not rejected
    assert result is True
    assert oracle.calls == 1
    assert oracle.cache_hits == 1


def test_budget_none_means_unbounded():
    oracle = Oracle(lambda kept: True)
    for i in range(500):
        oracle((i,))
    assert oracle.calls == 500


def test_render_and_full_predicate_do_not_affect_call_counting_semantics():
    # Sanity check that Oracle's contract holds identically when fn is
    # itself built from ReductionProblem.from_text's render-then-predicate
    # closure, not just a bare lambda over indices.
    from crux.crux.core import LineProblem

    text = "a\nb\nc\n"
    problem = LineProblem.from_text(text, predicate=lambda t: "b" in t)
    oracle = problem.oracle
    assert oracle((0, 1, 2)) is True
    assert oracle((0, 2)) is False
    assert oracle.calls == 2
    assert oracle((0, 1, 2)) is True  # cache hit
    assert oracle.calls == 2
    assert oracle.cache_hits == 1
