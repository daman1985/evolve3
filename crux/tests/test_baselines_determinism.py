"""Hard rule #6 (PLAN.md): fixed seeds everywhere, same input -> same
output, same call count, every run. Each reducer is run twice from
scratch (a brand-new Task-built Oracle each time, per tasks.py's own
"never reuse an Oracle across two runs" contract) and both the returned
kept-set AND every Oracle counter must match exactly.
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

TASK_NAMES = [
    "hit-20-2000-clustered",
    "hit-100-2000-adversarial",
    "nest-200",
    "chain-200",
    "blocks-200",
    "ujson-510-indent-buffer-overflow@char",
    "gcc49-udlit-char-pack-template@line",
]

_ALL_TASKS = {t.name: t for t in build_all_tasks()}
for _name in TASK_NAMES:
    assert _name in _ALL_TASKS, f"fixture task {_name!r} not found by build_all_tasks()"


def _run(reduce_fn, task):
    budget = min(_budget_for(len(task.elements)), 4000)
    problem = task.make_problem(budget=budget)
    full = tuple(range(len(task.elements)))
    result = reduce_fn(problem, full)
    return result, problem.oracle.calls, problem.oracle.cache_hits


@pytest.mark.parametrize("task_name", TASK_NAMES)
@pytest.mark.parametrize("reducer_name", sorted(REDUCERS))
def test_same_task_twice_gives_identical_result_and_call_counts(reducer_name, task_name):
    task = _ALL_TASKS[task_name]
    reduce_fn = REDUCERS[reducer_name]

    result_a, calls_a, hits_a = _run(reduce_fn, task)
    result_b, calls_b, hits_b = _run(reduce_fn, task)

    assert result_a == result_b, f"{reducer_name} on {task_name}: result differs across identical runs"
    assert calls_a == calls_b, f"{reducer_name} on {task_name}: call count differs across identical runs ({calls_a} vs {calls_b})"
    assert hits_a == hits_b, f"{reducer_name} on {task_name}: cache_hits differs across identical runs ({hits_a} vs {hits_b})"


def test_determinism_holds_across_three_repeats_not_just_two():
    # A weaker two-run check could pass by coincidence if non-determinism
    # only shows up occasionally (e.g. a set() iteration-order dependency
    # that happens to agree half the time); three independent repeats of
    # the most RNG-dependent baseline (cdd, which draws from a
    # random.Random(SEED) every run) raise that bar a little further.
    task = _ALL_TASKS["hit-20-2000-clustered"]
    runs = [_run(cdd.reduce, task) for _ in range(3)]
    results = {r[0] for r in runs}
    call_counts = {r[1] for r in runs}
    assert len(results) == 1, f"cdd result not stable across 3 runs: {results}"
    assert len(call_counts) == 1, f"cdd call count not stable across 3 runs: {call_counts}"
