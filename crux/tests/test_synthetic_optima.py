"""Synthetic tasks' known optima must actually be achievable -- i.e.
known_optimum (and known_optimum_bytes) must name a real True kept-set of
that exact size, not just a theoretical lower bound. This matters beyond
documentation: run.py's s_t metric uses known_optimum_bytes directly as
size*_t for every synthetic task (PLAN.md S2), so a wrong value there
silently corrupts every s_t / E number computed against it.

Two independent verification strategies, chosen per task family and
deliberately NOT reusing tasks.py's own private RNG/placement helpers, so
a bug shared between the task builder and its checker cannot cancel out:

  - hit / chain / blocks: `linear.reduce` (the simplest, easiest-to-trust
    baseline -- an exhaustive single-element sweep to fixpoint) is proven
    in the accompanying report to converge to the UNIQUE 1-minimal True
    set for these three predicate shapes specifically (pure superset
    requirement, or blocks' cascading-chain requirement), so using it here
    as a witness generator does not just re-assert the builder's own
    intent.
  - nest: a from-scratch closed-form witness extraction
    (_util.extract_depth_witness), which needs no knowledge of where
    padding pairs were spliced in -- see its docstring.
"""
from __future__ import annotations

import pytest

from crux.baselines import linear
from crux.bench.run import _budget_for
from crux.bench.tasks import build_synthetic_tasks

from _util import byte_len, extract_depth_witness, render

_TASKS = {t.name: t for t in build_synthetic_tasks()}


# --------------------------------------------------------------------------
# hit / blocks / chain: linear.reduce as an independent witness generator
# --------------------------------------------------------------------------

# hit-{k}-{n}-{mode}: restrict to n=200 (the smallest N) across every k
# and mode, plus the smallest chain/blocks task -- covers every predicate
# SHAPE at least once while keeping the suite fast (see run.py's own
# _budget_for: cost scales with n, and correctness here does not depend
# on n at all).
_LINEAR_REACHABLE = sorted(
    name
    for name in _TASKS
    if (name.startswith("hit-") and name.split("-")[2] == "200")
    or name in ("chain-200", "blocks-200")
)


def test_fixture_selection_is_nonempty():
    # Guards the test list itself against a naming-convention change in
    # tasks.py silently emptying it out from under this file.
    assert len(_LINEAR_REACHABLE) >= 10, _LINEAR_REACHABLE


@pytest.mark.parametrize("task_name", _LINEAR_REACHABLE)
def test_known_optimum_reachable_via_linear_sweep(task_name):
    task = _TASKS[task_name]
    budget = min(_budget_for(len(task.elements)), 10_000)
    problem = task.make_problem(budget=budget)
    full = tuple(range(len(task.elements)))

    result = linear.reduce(problem, full)

    assert result is not None
    assert task.predicate_on_kept(result) is True
    assert len(result) == task.known_optimum, (
        f"{task_name}: linear sweep reached {len(result)} elements, "
        f"known_optimum says {task.known_optimum} -- either the optimum is "
        f"wrong or linear failed to reach the (provably unique) 1-minimal fixpoint"
    )
    rendered_bytes = byte_len(render(task.elements, result))
    assert rendered_bytes == task.known_optimum_bytes, (
        f"{task_name}: reachable witness is {rendered_bytes} bytes, "
        f"known_optimum_bytes says {task.known_optimum_bytes}"
    )


# --------------------------------------------------------------------------
# nest: closed-form witness, no oracle calls needed at all
# --------------------------------------------------------------------------

_NEST_TASKS = sorted(name for name in _TASKS if name.startswith("nest-"))


def test_nest_fixture_selection_is_nonempty():
    assert len(_NEST_TASKS) >= 2, _NEST_TASKS


@pytest.mark.parametrize("task_name", _NEST_TASKS)
def test_nest_known_optimum_reachable_via_closed_form_witness(task_name):
    task = _TASKS[task_name]
    assert task.known_optimum % 2 == 0
    d = task.known_optimum // 2

    witness = extract_depth_witness(task.elements, d)

    assert len(witness) == task.known_optimum
    assert task.predicate_on_kept(witness) is True
    assert byte_len(render(task.elements, witness)) == task.known_optimum_bytes


def test_nest_known_optimum_is_a_true_lower_bound_not_just_a_reachable_size():
    # Independent of reachability: no True kept-set of this predicate can
    # be smaller than 2*d at all, because a balanced string needs equal
    # open/close counts and >=d nesting needs >=d of each. Spot-check on
    # the smaller nest task that every subset strictly smaller than
    # known_optimum, built by dropping the LAST element of the closed-form
    # witness (breaking the nest), does in fact fail.
    task = _TASKS["nest-200"]
    d = task.known_optimum // 2
    witness = extract_depth_witness(task.elements, d)
    for i in range(len(witness)):
        smaller = witness[:i] + witness[i + 1 :]
        assert task.predicate_on_kept(smaller) is False, (
            f"nest-200: dropping witness element at position {i} unexpectedly "
            "still satisfies the predicate -- known_optimum would be wrong"
        )
