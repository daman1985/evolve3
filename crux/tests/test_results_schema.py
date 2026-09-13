"""PLAN.md S2: 'every result must report `filtered` -- candidates rejected
locally without an oracle call -- alongside `calls`'. Round 0 has no
reducer that does local filtering yet, so this is a schema-presence check
only: the field must exist and be comparable across rounds (so a results
file from a round before any filter existed and one from a round after
line up on the same key), not a check that anything populates it yet.
"""
from __future__ import annotations

import multiprocessing as mp

import crux.bench.run as run_mod
from crux.bench.tasks import build_all_tasks


def test_default_row_schema_carries_filtered_alongside_calls():
    row = run_mod._default_row("linear", "some-task")
    assert "filtered" in row
    assert "calls" in row
    assert row["filtered"] == 0  # nothing populates it yet, per PLAN.md S2
    assert row["calls"] is None  # not attempted: no call count at all yet


def test_default_row_override_still_keeps_filtered_present():
    row = run_mod._default_row("linear", "some-task", calls=42, cache_hits=3)
    assert row["filtered"] == 0
    assert row["calls"] == 42


def test_in_process_run_result_carries_filtered_alongside_calls():
    # End-to-end through run_one() for a real (method, task) pair -- the
    # exact dict shape that lands in results/*.json rows.
    task_name = "hit-1-200-uniform"
    task = next(t for t in build_all_tasks() if t.name == task_name)
    run_mod._TASKS_BY_NAME = {task_name: task}
    try:
        ctx = mp.get_context("fork")
        row = run_mod.run_one("linear", task_name, timeout=30.0, ctx=ctx)
    finally:
        run_mod._TASKS_BY_NAME = {}

    assert row["error"] is None, row["error"]
    assert row["valid"] is True
    assert "filtered" in row
    assert row["filtered"] == 0
    assert isinstance(row["calls"], int) and row["calls"] > 0


def test_compute_metrics_preserves_filtered_on_every_row():
    task_name = "hit-1-200-uniform"
    task = next(t for t in build_all_tasks() if t.name == task_name)
    run_mod._TASKS_BY_NAME = {task_name: task}
    try:
        ctx = mp.get_context("fork")
        row = run_mod.run_one("linear", task_name, timeout=30.0, ctx=ctx)
        rows, aggregate = run_mod.compute_metrics([row])
    finally:
        run_mod._TASKS_BY_NAME = {}

    assert all("filtered" in r for r in rows)
    assert "linear" in aggregate
