#!/usr/bin/env python3
"""The benchmark harness.

    python3 crux/bench/run.py --out results/round0.json \\
        [--methods a,b] [--tasks pattern] [--timeout SEC] [--jobs N]

Runs every requested method against every requested task, independently
re-validates each output, computes the PLAN.md S2 metrics, and writes both
a JSON results file and a markdown table to stdout.

Design notes (see the reducer-engineer round-0 report for the full
rationale):
  - In-process methods (ddmin_picire, ddmin_own, probdd, cdd, linear) each
    run in their OWN forked child process, so a per-run wall-clock timeout
    can actually kill a hung run rather than merely stop waiting for it.
    Tasks are built once in the parent and inherited via fork's
    copy-on-write memory, so closures (predicates) never need to be
    pickled across the process boundary.
  - The external method (perses) already runs as its own OS subprocess
    (the JVM) with its own `subprocess.run(timeout=...)`, which properly
    kills it on expiry, so it is called directly from the scheduling
    thread with no extra process wrapper needed.
  - A ThreadPoolExecutor is the outer scheduler bounding concurrency to
    `--jobs`; the threads themselves do no CPU-bound work (they block on
    Process.join()/subprocess.run()), so real parallelism across up to 4
    cores comes from the child OS processes, matching "parallelise across
    (method, task) pairs with multiprocessing, but each individual
    reduction runs single-threaded and deterministic."
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import math
import multiprocessing as mp
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crux.crux.core import BudgetExhausted, Oracle, ReductionProblem  # noqa: E402
from crux.bench.tasks import Task, build_all_tasks  # noqa: E402
from crux.baselines import cdd, ddmin_own, ddmin_picire, linear, probdd  # noqa: E402
from crux.baselines.perses import run_perses  # noqa: E402

IN_PROCESS_METHODS = {
    "ddmin_picire": ddmin_picire.reduce,
    "ddmin_own": ddmin_own.reduce,
    "probdd": probdd.reduce,
    "cdd": cdd.reduce,
    "linear": linear.reduce,
}
EXTERNAL_METHODS = {"perses"}
ALL_METHODS = list(IN_PROCESS_METHODS) + sorted(EXTERNAL_METHODS)

REFERENCE_METHOD = "ddmin_picire"  # PLAN.md S2: c_t denominator

DEFAULT_TIMEOUT = 90.0  # seconds, shared by in-process wall-clock cap and perses
PERSES_WORK_ROOT = Path("results") / "_perses_work"

# Call budget: generous enough to let every method reach its natural
# fixpoint on ordinary tasks, capped so a genuinely adversarial task (e.g.
# chain-20000 against probdd/linear, which the task is explicitly designed
# to be hard for) cannot blow the wall-clock budget instead -- the
# wall-clock --timeout is the real backstop for those. One formula, scaled
# only by each task's own element count n (not by task identity).
def _budget_for(n: int) -> int:
    return min(50_000, max(3_000, 15 * n))


# Populated in the parent before any worker process is forked, so children
# inherit it via copy-on-write memory instead of needing it pickled through
# a queue (Task.predicate_on_kept is a closure, not reliably picklable).
_TASKS_BY_NAME: dict[str, Task] = {}


def _run_in_process(method_name: str, task_name: str, budget: int, queue: "mp.Queue") -> None:
    try:
        task = _TASKS_BY_NAME[task_name]
        reduce_fn = IN_PROCESS_METHODS[method_name]
        problem = task.make_problem(budget=budget)
        start = time.monotonic()
        budget_exhausted = False
        try:
            result = reduce_fn(problem, tuple(range(len(task.elements))))
        except BudgetExhausted:
            # Hard rule: baselines already catch this themselves and
            # return oracle.best; this is a last-resort net in case a
            # future method forgets to.
            result = problem.oracle.best
            budget_exhausted = True
        elapsed = time.monotonic() - start

        if result is None:
            queue.put(("ok", {
                "calls": problem.oracle.calls,
                "cache_hits": problem.oracle.cache_hits,
                "filtered": 0,
                "final_bytes": None,
                "final_elements": None,
                "valid": False,
                "seconds": elapsed,
                "timed_out": False,
                "budget_exhausted": budget_exhausted or problem.oracle.calls >= budget,
                "error": "reducer returned None: no kept-set was ever confirmed True",
            }))
            return

        # Independent validity gate: re-check the TASK's own predicate,
        # fresh, on the exact kept-set returned -- never through the
        # (possibly budget-limited, cached) Oracle this run just used.
        valid = bool(task.predicate_on_kept(result))

        queue.put(("ok", {
            "calls": problem.oracle.calls,
            "cache_hits": problem.oracle.cache_hits,
            "filtered": 0,
            "final_bytes": len(task.render(result).encode("utf-8", "surrogateescape")),
            "final_elements": len(result),
            "valid": valid,
            "seconds": elapsed,
            "timed_out": False,
            "budget_exhausted": budget_exhausted or problem.oracle.calls >= budget,
            "error": None,
        }))
    except Exception:
        queue.put(("error", traceback.format_exc()))


def _default_row(method_name: str, task_name: str, **overrides) -> dict:
    row = {
        "method": method_name,
        "task": task_name,
        "calls": None,
        "cache_hits": None,
        "filtered": 0,
        "final_bytes": None,
        "final_elements": None,
        "valid": False,
        "seconds": None,
        "timed_out": False,
        "budget_exhausted": False,
        "external": method_name in EXTERNAL_METHODS,
        "lang_used": None,
        "used_fallback_lang": None,
        "error": None,
    }
    row.update(overrides)
    return row


def run_one(method_name: str, task_name: str, timeout: float, ctx: mp.context.BaseContext) -> dict:
    task = _TASKS_BY_NAME[task_name]

    if method_name in EXTERNAL_METHODS:
        if task.kind != "corpus" or task.granularity != "line" or task.entry_dir is None:
            return _default_row(method_name, task_name, error="perses only runs on @line corpus tasks (see round-0 report)")
        work_dir = PERSES_WORK_ROOT / task.entry_dir.name
        try:
            result = run_perses(task.entry_dir, task.original_path, task.fmt, work_dir, timeout=timeout)
        except Exception:
            return _default_row(method_name, task_name, error=traceback.format_exc())
        valid = bool(task.predicate_on_text(result.text)) if task.predicate_on_text else False
        return _default_row(
            method_name, task_name,
            calls=result.calls, cache_hits=0,
            final_bytes=len(result.text.encode("utf-8", "surrogateescape")),
            final_elements=None,
            valid=valid, seconds=result.seconds, timed_out=result.timed_out,
            lang_used=result.lang_used, used_fallback_lang=result.used_fallback_lang,
            error=result.error,
        )

    n = len(task.elements)
    budget = _budget_for(n)
    queue: mp.Queue = ctx.Queue()
    proc = ctx.Process(target=_run_in_process, args=(method_name, task_name, budget, queue))
    start = time.monotonic()
    proc.start()
    proc.join(timeout)

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join()
        return _default_row(
            method_name, task_name,
            seconds=time.monotonic() - start, timed_out=True,
            error=f"exceeded the {timeout:.0f}s per-run wall-clock cap",
        )

    if not queue.empty():
        status, payload = queue.get()
        if status == "ok":
            return _default_row(method_name, task_name, **payload)
        return _default_row(method_name, task_name, seconds=time.monotonic() - start, error=payload)

    return _default_row(
        method_name, task_name, seconds=time.monotonic() - start,
        error=f"worker process exited with code {proc.exitcode} and produced no result (crash?)",
    )


def geomean(values: list) -> Optional[float]:
    vals = [v for v in values if v is not None and v > 0]
    if not vals:
        return None
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def compute_metrics(rows: list) -> tuple[list, dict]:
    """Fill in s_t/c_t per row (PLAN.md S2) and aggregate E/geomean-s/
    geomean-c per method. size*_t and calls_t(ddmin_picire) are both
    computed fresh from these SAME rows, never from a separate baseline
    run, so the metrics are self-consistent for whatever subset was
    actually run in this invocation."""
    by_task: dict[str, list] = {}
    for row in rows:
        by_task.setdefault(row["task"], []).append(row)

    task_meta = {name: _TASKS_BY_NAME[name] for name in by_task}

    size_star: dict[str, Optional[int]] = {}
    ref_calls: dict[str, Optional[int]] = {}
    for task_name, task_rows in by_task.items():
        task = task_meta[task_name]
        valid_sizes = [r["final_bytes"] for r in task_rows if r["valid"] and r["final_bytes"] is not None]
        if task.known_optimum_bytes is not None:
            size_star[task_name] = task.known_optimum_bytes
        elif valid_sizes:
            size_star[task_name] = min(valid_sizes)
        else:
            size_star[task_name] = None

        ref_row = next((r for r in task_rows if r["method"] == REFERENCE_METHOD and r["valid"] and r["calls"]), None)
        ref_calls[task_name] = ref_row["calls"] if ref_row else None

    for row in rows:
        task_name = row["task"]
        row["known_optimum"] = task_meta[task_name].known_optimum
        row["known_optimum_bytes"] = task_meta[task_name].known_optimum_bytes
        row["reference_bytes"] = task_meta[task_name].reference_bytes
        row["reference_valid"] = task_meta[task_name].reference_valid
        row["used_fallback_required"] = task_meta[task_name].used_fallback

        s_star = size_star.get(task_name)
        r_calls = ref_calls.get(task_name)
        if row["valid"] and row["final_bytes"] is not None and s_star is not None:
            row["s_t"] = (row["final_bytes"] + 1) / (s_star + 1)
        else:
            row["s_t"] = None
        if row["valid"] and row["calls"] and r_calls:
            row["c_t"] = row["calls"] / r_calls
        else:
            row["c_t"] = None

    aggregate: dict[str, dict] = {}
    for method in sorted({r["method"] for r in rows}):
        m_rows = [r for r in rows if r["method"] == method]
        valid_rows = [r for r in m_rows if r["valid"] and r["s_t"] is not None and r["c_t"] is not None]
        e_terms = [(r["s_t"] ** 2) * r["c_t"] for r in valid_rows]
        aggregate[method] = {
            "tasks_attempted": len(m_rows),
            "tasks_valid": len(valid_rows),
            "tasks_invalid": sum(1 for r in m_rows if not r["valid"] and not r["timed_out"]),
            "tasks_timed_out": sum(1 for r in m_rows if r["timed_out"]),
            "tasks_budget_exhausted": sum(1 for r in m_rows if r["budget_exhausted"]),
            "E": geomean(e_terms),
            "geomean_s": geomean([r["s_t"] for r in valid_rows]),
            "geomean_c": geomean([r["c_t"] for r in valid_rows]),
            "total_calls": sum(r["calls"] for r in m_rows if r["calls"] is not None),
        }

    return rows, aggregate


def print_markdown(aggregate: dict) -> None:
    print()
    print("| method | E (lower better) | geomean s | geomean c | valid/attempted | timed out | budget exhausted |")
    print("|---|---|---|---|---|---|---|")
    for method, agg in aggregate.items():
        def fmt(x):
            return f"{x:.4g}" if x is not None else "n/a"
        print(
            f"| {method} | {fmt(agg['E'])} | {fmt(agg['geomean_s'])} | {fmt(agg['geomean_c'])} "
            f"| {agg['tasks_valid']}/{agg['tasks_attempted']} | {agg['tasks_timed_out']} | {agg['tasks_budget_exhausted']} |"
        )
    print()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="path to write the JSON results file")
    parser.add_argument("--methods", default=",".join(ALL_METHODS), help="comma-separated method names")
    parser.add_argument("--tasks", default="*", help="comma-separated glob pattern(s) over task names")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="per-run wall-clock timeout, seconds")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 4), help="max concurrent (method, task) runs")
    args = parser.parse_args(argv)

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown = set(methods) - set(ALL_METHODS)
    if unknown:
        parser.error(f"unknown method(s): {sorted(unknown)} (known: {ALL_METHODS})")

    patterns = [p.strip() for p in args.tasks.split(",") if p.strip()]

    print("Building tasks...", file=sys.stderr)
    all_tasks = build_all_tasks()
    global _TASKS_BY_NAME
    _TASKS_BY_NAME = {t.name: t for t in all_tasks}

    selected_tasks = [t for t in all_tasks if any(fnmatch.fnmatch(t.name, p) for p in patterns)]
    if not selected_tasks:
        parser.error(f"no tasks matched pattern(s) {patterns!r}")

    print(f"{len(selected_tasks)} tasks x {len(methods)} methods "
          f"= {len(selected_tasks) * len(methods)} runs, jobs={args.jobs}, timeout={args.timeout}s",
          file=sys.stderr)

    ctx = mp.get_context("fork")
    jobs = [(m, t.name) for m in methods for t in selected_tasks]
    rows = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_one, m, t, args.timeout, ctx): (m, t) for m, t in jobs}
        done = 0
        for future in as_completed(futures):
            m, t = futures[future]
            try:
                row = future.result()
            except Exception:
                row = _default_row(m, t, error=traceback.format_exc())
            rows.append(row)
            done += 1
            if done % 25 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} runs complete", file=sys.stderr)

    rows, aggregate = compute_metrics(rows)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"rows": rows, "aggregate": aggregate}, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out_path}", file=sys.stderr)

    print_markdown(aggregate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
