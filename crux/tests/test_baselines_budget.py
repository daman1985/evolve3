"""Hard rule #1 (PLAN.md) under the specific condition that exercises it:
budget exhaustion. crux.crux.core.BudgetExhausted is raised by the Oracle,
not by reducers -- every reducer MUST catch it internally and fall back to
oracle.best (the last CONFIRMED-True kept-set), never letting the
exception escape reduce() and never returning an untested state.
"""
from __future__ import annotations

import pytest

from crux.crux.core import BudgetExhausted
from crux.baselines import cdd, ddmin_own, ddmin_picire, linear, probdd
from crux.bench.tasks import build_all_tasks

REDUCERS = {
    "ddmin_picire": ddmin_picire.reduce,
    "ddmin_own": ddmin_own.reduce,
    "probdd": probdd.reduce,
    "cdd": cdd.reduce,
    "linear": linear.reduce,
}

# n=2000, k=100, adversarial placement -- natural (unbudgeted) fixpoint
# costs >=2000 real calls for every baseline (measured), so any budget
# well under that is guaranteed insufficient to reach it, for all five.
TASK_NAME = "hit-100-2000-adversarial"
_TASK = next(t for t in build_all_tasks() if t.name == TASK_NAME)
_FULL = tuple(range(len(_TASK.elements)))


@pytest.mark.parametrize("reducer_name", sorted(REDUCERS))
def test_insufficient_budget_never_raises_out_of_reduce(reducer_name):
    reduce_fn = REDUCERS[reducer_name]
    problem = _TASK.make_problem(budget=10)  # far below the >=2000 needed
    # The hard rule under test: BudgetExhausted must never escape reduce().
    result = reduce_fn(problem, _FULL)
    assert result is not None
    assert problem.oracle.calls <= 10


@pytest.mark.parametrize("reducer_name", sorted(REDUCERS))
def test_insufficient_budget_result_is_exactly_oracle_best(reducer_name):
    reduce_fn = REDUCERS[reducer_name]
    problem = _TASK.make_problem(budget=10)
    result = reduce_fn(problem, _FULL)
    # Hard rule, stated precisely: the algorithm ends with the
    # last-known-good state -- i.e. exactly oracle.best, not some other
    # untested value that happens to be similar.
    assert result == problem.oracle.best


@pytest.mark.parametrize("reducer_name", sorted(REDUCERS))
def test_insufficient_budget_result_still_passes_the_oracle(reducer_name):
    reduce_fn = REDUCERS[reducer_name]
    problem = _TASK.make_problem(budget=10)
    result = reduce_fn(problem, _FULL)
    assert _TASK.predicate_on_kept(result) is True


@pytest.mark.parametrize("reducer_name", sorted(REDUCERS))
def test_zero_budget_returns_none_without_raising(reducer_name):
    # budget=0: the Oracle raises BudgetExhausted(best=None) on the very
    # first call, before anything has ever been confirmed True. There is
    # no "last-known-good state" yet, so None is the only honest answer
    # (run.py's harness treats a None result as a reported failure, never
    # as a crash) -- but reduce() itself must still not raise.
    reduce_fn = REDUCERS[reducer_name]
    problem = _TASK.make_problem(budget=0)
    result = reduce_fn(problem, _FULL)
    assert result is None
    assert problem.oracle.calls == 0
    assert problem.oracle.best is None


def test_oracle_itself_raises_budget_exhausted_at_the_documented_boundary():
    # Direct check of the primitive every reducer's try/except relies on:
    # confirms the exception is real, not something a reducer could avoid
    # seeing by accident (e.g. because the Oracle secretly swallows it).
    problem = _TASK.make_problem(budget=1)
    problem.oracle(_FULL)  # consumes the one allowed call, True
    with pytest.raises(BudgetExhausted) as excinfo:
        problem.oracle((0,))  # a genuinely new key: must attempt a real call
    assert excinfo.value.best == problem.oracle.best == _FULL


@pytest.mark.parametrize("reducer_name", sorted(REDUCERS))
def test_generous_budget_is_never_exhausted_on_a_small_task(reducer_name):
    # Converse sanity check: a plainly sufficient budget must not
    # spuriously trip anything -- guards against a reducer that
    # over-counts or mis-tracks its own budget usage.
    small_task = next(t for t in build_all_tasks() if t.name == "hit-5-200-uniform")
    reduce_fn = REDUCERS[reducer_name]
    problem = small_task.make_problem(budget=50_000)
    result = reduce_fn(problem, tuple(range(len(small_task.elements))))
    assert result is not None
    assert problem.oracle.calls < 50_000
    assert small_task.predicate_on_kept(result) is True
