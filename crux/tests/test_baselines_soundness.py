"""Hard rule #1 (PLAN.md / reducer-engineer brief): a reducer must never
return output that fails the oracle -- every algorithm ends with the
last-known-good state, never an untested one. This file independently
re-validates that for every baseline on a representative task set spanning
all four synthetic families plus two real corpus predicates (line and char
granularity), exactly the way crux/bench/run.py's own validity gate does:
call task.predicate_on_kept(result) fresh, never trusting the (possibly
budget-limited, cached) Oracle the reducer itself used.
"""
from __future__ import annotations

import pytest

from crux.baselines import cdd, ddmin_own, ddmin_picire, linear, probdd
from crux.bench.run import _budget_for
from crux.bench.tasks import build_all_tasks

REDUCERS = {
    "ddmin_picire": ddmin_picire.reduce,
    "ddmin_own": ddmin_own.reduce,
    "probdd": probdd.reduce,
    "cdd": cdd.reduce,
    "linear": linear.reduce,
}

# One small task per synthetic family, plus the smallest real corpus entry
# at both granularities it produces -- deliberately small so the suite
# stays fast; the algorithms' own scaling is bench-runner's job, not a
# unit test's.
TASK_NAMES = [
    "hit-5-200-uniform",
    "hit-20-2000-clustered",
    "hit-1-200-adversarial",
    "nest-200",
    "chain-200",
    "blocks-200",
    "ujson-510-indent-buffer-overflow@line",
    "ujson-510-indent-buffer-overflow@char",
]

_ALL_TASKS = {t.name: t for t in build_all_tasks()}
for _name in TASK_NAMES:
    assert _name in _ALL_TASKS, f"fixture task {_name!r} not found by build_all_tasks()"


def _budget_for_test(task) -> int:
    # Corpus char-granularity predicates are cheap-but-restrictive (see
    # PLAN.md Amendment 1's syntax-validity measurement); cap generously
    # but well below production's _budget_for so the suite stays fast even
    # when a call-hungry method never converges -- soundness must hold
    # under budget truncation too, so a tighter cap is a stronger test,
    # not a weaker one.
    return min(_budget_for(len(task.elements)), 4000)


@pytest.mark.parametrize("task_name", TASK_NAMES)
@pytest.mark.parametrize("reducer_name", sorted(REDUCERS))
def test_reducer_output_passes_the_oracle(reducer_name, task_name):
    task = _ALL_TASKS[task_name]
    reduce_fn = REDUCERS[reducer_name]
    problem = task.make_problem(budget=_budget_for_test(task))
    full = tuple(range(len(task.elements)))

    result = reduce_fn(problem, full)

    assert result is not None, (
        f"{reducer_name} on {task_name} returned None -- a budget big enough to "
        "confirm the starting point should never do this"
    )
    # Independent re-check, exactly like run.py's validity gate: never
    # trust the Oracle instance the reducer itself consumed.
    assert task.predicate_on_kept(result) is True, (
        f"{reducer_name} on {task_name} returned a kept-set of size {len(result)} "
        "that FAILS the task's own oracle -- soundness violation"
    )
    # The returned set must itself be a subset of the original universe.
    assert set(result).issubset(set(full))


@pytest.mark.parametrize("task_name", TASK_NAMES)
@pytest.mark.parametrize("reducer_name", sorted(REDUCERS))
def test_reducer_never_grows_the_kept_set(reducer_name, task_name):
    task = _ALL_TASKS[task_name]
    reduce_fn = REDUCERS[reducer_name]
    problem = task.make_problem(budget=_budget_for_test(task))
    full = tuple(range(len(task.elements)))

    result = reduce_fn(problem, full)
    assert result is not None
    assert len(result) <= len(full)
