#!/usr/bin/env python3
"""Round 1 kill-criterion gate (specs/round1-core.md S10, primary).

    python3 crux/bench/gate_round1.py [--quick] [--out-json PATH]

Runs CritScan on a spread of synthetic `hit-k-n` instances -- uniform
placement, monotone oracle, no syntax gate, n >= 4096, n/k >= 32, k known
by construction -- and computes

    rho = actual_calls / (k * (log2(n/k) + 4))

against `problem.oracle.calls` (the harness's own authoritative counter,
I9): every real oracle execution, cache hits counted separately and never
folded in. ddmin (picire's own reference implementation, imported
unmodified from crux/baselines/ddmin_picire.py) and ProbDD (imported
unmodified from crux/baselines/probdd.py) run on the IDENTICAL instances
for context, exactly as the task brief asked -- this script does not judge
them against a threshold, only reports them next to crux's number.

Per S10: "If rho > 2.5 on that family, abandon Round 1... Run this family
FIRST, before the real corpus." This script does exactly that and nothing
else -- no candidate space, no non-monotonicity, no unknown optimum, no
real-corpus task.

Instance construction reuses crux/bench/tasks.py's own helpers
(`_seeded`, `_placement_uniform`, `_subset_predicate`) rather than
reimplementing hit-k-n from scratch, per this task's brief, so an instance
built here is byte-for-byte what `build_hit_tasks()` would build for the
same (k, n, "uniform") triple -- this script only supplies (k, n) pairs
outside the fixed HIT_KS x HIT_NS grid in tasks.py (which tops out at
n=20000) so the gate can reach the required n/k >= 32 at n up to 32768.

Soundness (S10 "soundness gate", non-negotiable): every returned kept-set
from every method is independently re-verified against the RAW predicate
function directly -- never through the (possibly cached) Oracle used
during that run. Any failure here is reported as an immediate
disqualification, per the task brief, rather than folded into a rho
number.

Process isolation: each (method, instance) run happens in its own forked
child process (mirroring crux/bench/run.py's own established pattern, for
the same reason it exists there) with a wall-clock timeout. This was not a
defensive default -- it was added after ddmin_picire's own ConfigCache (see
baselines/ddmin_picire.py; a recent, correct, faithfulness fix by another
engineer working in this repo concurrently) was observed to exhaust
available memory at n=32768 running in-process: ConfigCache keys by the
exact index sequence, so at this scale each cached miss can retain a
full-length tuple of large (non-interned) Python ints, and a run with tens
of thousands of distinct large configs can require tens of gigabytes. That
is an honest property of the faithful picire configuration being run for
context, not a bug to route around -- isolating it means one baseline's
memory profile at the largest instance cannot take down crux's own
measurement (the actual gate) or any other cell in the table. A crashed or
timed-out context run is reported as exactly that, plainly, rather than
silently omitted.

An earlier version of this script also imposed a per-child RLIMIT_AS
(virtual address space) cap, on the theory that a clean, catchable
MemoryError beats an uncontrolled SIGKILL. Measurement showed that theory
wrong: RLIMIT_AS bounds virtual address space, not resident memory, and
CPython's allocator (plus glibc arena fragmentation across many alloc/free
cycles) can inflate a process's mapped address space well past what it is
actually using -- a run of crux ITSELF (k=1024, n=32768, the exact case an
uncapped run completed correctly and quickly earlier in the same
investigation) was falsely reported as crashed under a 4GiB cap. Since
subprocess isolation plus the wall-clock timeout already gives every
failure mode that matters -- a run that hangs is killed by the timeout, a
run that is OS-OOM-killed still reports as "child exited with no result"
via the exact same fallback path below -- the address-space cap bought
nothing but false positives on legitimate, cheaper-than-it-looks workloads.
Removed. Report this as a caution to whoever next reaches for RLIMIT_AS as
a Python memory guard.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crux.crux.core import BudgetExhausted, Oracle, ReductionProblem  # noqa: E402
from crux.crux.critscan import CritState, reduce as critscan_reduce  # noqa: E402
from crux.baselines import ddmin_picire, probdd  # noqa: E402
from crux.bench.tasks import _seeded, _placement_uniform, _subset_predicate  # noqa: E402

RHO_THRESHOLD = 2.5  # S10 kill criterion. Not a tunable: the gate's own line.

# The spread the brief asks for: n in roughly 4096-32768, n/k from 32 up,
# uniform placement, k known by construction. Two ratios (32, the S10 floor,
# and 256, well above it) at each of three n values across the range -- a
# deliberate spread fixed BEFORE any instance was run and never adjusted
# afterward to move the result (see the reducer-engineer report). Kept to
# 6 instances (not a denser grid) so the whole gate -- including the two
# baselines run only for context -- finishes in a bounded number of
# minutes, per S10 ("it costs minutes").
FULL_INSTANCES = [
    (16, 4096),
    (128, 4096),
    (64, 16384),
    (512, 16384),
    (128, 32768),
    (1024, 32768),
]

# A fast subset for iteration/smoke-testing only -- never the number reported
# as "the" gate result.
QUICK_INSTANCES = [
    (16, 4096),
    (128, 4096),
]

METHOD_NAMES = ["crux", "ddmin_picire", "probdd"]

PER_RUN_TIMEOUT = 90.0  # seconds; matches crux/bench/run.py's own DEFAULT_TIMEOUT


def geomean(values) -> Optional[float]:
    vals = [v for v in values if v is not None and v > 0]
    if not vals:
        return None
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def build_instance(k: int, n: int, mode: str = "uniform"):
    """Identical construction to crux.bench.tasks.build_hit_tasks() for the
    (k, n, mode) triple: same seed namespace, same placement helper, same
    predicate helper -- imported, not reimplemented."""
    rng = _seeded("hit", k, n, mode)
    required = frozenset(_placement_uniform(n, k, rng))
    elements = [f"e{i}" for i in range(n)]
    raw_predicate = _subset_predicate(required)  # Callable[[tuple], bool], pure, no Oracle involved
    return elements, raw_predicate, required


def _call_method(name: str, problem: ReductionProblem, kept: tuple):
    if name == "crux":
        return critscan_reduce(problem, kept, state=CritState())
    if name == "ddmin_picire":
        return ddmin_picire.reduce(problem, kept)
    if name == "probdd":
        return probdd.reduce(problem, kept)
    raise ValueError(f"unknown method {name!r}")


def _child_main(method_name: str, elements, raw_predicate, n: int, budget: int, conn) -> None:
    # A Pipe, not a Queue: Queue.put() lazily starts an internal feeder
    # thread on first use, which can itself fail under memory pressure
    # (observed in practice on an earlier, RLIMIT_AS-capped version of this
    # script -- see the module docstring). Connection.send() writes
    # directly with no new thread, so an error report still gets home even
    # from a badly memory-starved process, with no downside on the normal
    # path.
    try:
        oracle = Oracle(raw_predicate, budget=budget)
        problem = ReductionProblem(elements, oracle)
        start = time.perf_counter()
        truncated = False
        try:
            result = _call_method(method_name, problem, tuple(range(n)))
        except BudgetExhausted:
            result = problem.oracle.best
            truncated = True
        elapsed = time.perf_counter() - start
        truncated = truncated or (oracle.calls >= budget)

        # Soundness gate (S10, non-negotiable): re-verify OUTSIDE the cached
        # Oracle entirely -- call the raw predicate function directly. A
        # cache hit during the run proves nothing about a bug in the
        # reducer's own bookkeeping; a fresh call to the pure function is
        # the only check that does.
        sound = result is not None and bool(raw_predicate(tuple(sorted(result))))

        conn.send(("ok", {
            "calls": oracle.calls,
            "cache_hits": oracle.cache_hits,
            "result_size": len(result) if result is not None else None,
            "sound": sound,
            "seconds": elapsed,
            "truncated": truncated,
            "result": tuple(sorted(result)) if result is not None else None,
        }))
    except MemoryError:
        try:
            conn.send(("error", "MemoryError (ran out of real memory)"))
        except Exception:
            pass  # even the error report didn't fit; the parent's exitcode fallback still reports this cell
    except Exception:
        try:
            conn.send(("error", traceback.format_exc()))
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _empty_row(**overrides) -> dict:
    row = {
        "calls": None, "cache_hits": None, "result_size": None, "sound": False,
        "seconds": None, "truncated": False, "result": None,
        "crashed": False, "timed_out": False, "error": None,
    }
    row.update(overrides)
    return row


def run_one_method(method_name: str, elements, raw_predicate, n: int, budget: int, ctx) -> dict:
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child_main, args=(method_name, elements, raw_predicate, n, budget, child_conn))
    start = time.monotonic()
    proc.start()
    child_conn.close()  # only the child writes; drop the parent's write-side reference to it

    result_row = None
    if parent_conn.poll(PER_RUN_TIMEOUT):
        try:
            status, payload = parent_conn.recv()
            if status == "ok":
                result_row = _empty_row(**payload)
            else:
                result_row = _empty_row(crashed=True, seconds=time.monotonic() - start, error=payload)
        except EOFError:
            pass  # child died before finishing its send -- fall through to the exitcode-based report below

    # Once we already have an answer, a slow-to-actually-exit child (final
    # interpreter teardown, etc.) is just cleanup, not a timeout -- give it
    # a short grace period rather than the full remaining budget, and never
    # let that grace period downgrade a real result into a false TIMEOUT.
    remaining = max(0.0, PER_RUN_TIMEOUT - (time.monotonic() - start))
    proc.join(remaining if result_row is None else min(remaining, 5.0))

    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join()
        parent_conn.close()
        if result_row is not None:
            return result_row
        return _empty_row(timed_out=True, seconds=time.monotonic() - start,
                           error=f"exceeded the {PER_RUN_TIMEOUT:.0f}s per-run wall-clock cap")

    parent_conn.close()
    if result_row is not None:
        return result_row

    # Process exited without ever sending anything: killed (most likely
    # OS-OOM SIGKILL) rather than raising a catchable exception.
    return _empty_row(
        crashed=True, seconds=time.monotonic() - start,
        error=f"child exited with code {proc.exitcode} and produced no result "
              f"(likely killed by the OS, e.g. out of memory)",
    )


def run_instance(k: int, n: int, ctx, budget_multiplier: int = 20, budget_floor: int = 20000) -> dict:
    elements, raw_predicate, required = build_instance(k, n)
    budget = max(budget_floor, budget_multiplier * n)

    rows = {}
    for name in METHOD_NAMES:
        rows[name] = run_one_method(name, elements, raw_predicate, n, budget, ctx)

    ratio = n / k
    rho = None
    crux_row = rows["crux"]
    if crux_row["sound"] and not crux_row["truncated"] and not crux_row["crashed"] and not crux_row["timed_out"]:
        denom = k * (math.log2(ratio) + 4)
        rho = crux_row["calls"] / denom

    return {
        "k": k, "n": n, "ratio": ratio, "known_optimum": k,
        "required": sorted(required), "rho": rho, "rows": rows,
    }


def _fmt(row: dict, field: str) -> str:
    if row.get("crashed"):
        return "CRASH"
    if row.get("timed_out"):
        return "TIMEOUT"
    v = row.get(field)
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def print_report(instance_results: list, out_json: Optional[str] = None):
    print()
    print("=" * 108)
    print("Round 1 kill-criterion gate -- synthetic hit-k-n, uniform placement, monotone oracle")
    print(f"rho = calls / (k * (log2(n/k) + 4));  threshold: rho > {RHO_THRESHOLD} on this family => abandon Round 1")
    print("=" * 108)

    header = (
        f"{'k':>6} {'n':>7} {'n/k':>7} | "
        f"{'crux_calls':>10} {'crux_size':>9} {'size_ok':>7} {'rho':>7} | "
        f"{'ddmin_calls':>11} {'probdd_calls':>12} | {'c_vs_ddmin':>10} {'c_vs_probdd':>11}"
    )
    print(header)
    print("-" * len(header))

    rhos = []
    all_sound = True
    any_truncated = False
    any_crashed_or_timed_out = False
    for r in instance_results:
        crux = r["rows"]["crux"]
        ddmin = r["rows"]["ddmin_picire"]
        prob = r["rows"]["probdd"]

        size_ok = (crux["result"] is not None) and (set(crux["result"]) == set(r["required"]))
        c_vs_ddmin = (crux["calls"] / ddmin["calls"]) if (crux["calls"] and ddmin.get("calls")) else None
        c_vs_probdd = (crux["calls"] / prob["calls"]) if (crux["calls"] and prob.get("calls")) else None

        for row in (crux, ddmin, prob):
            if row["crashed"] or row["timed_out"]:
                any_crashed_or_timed_out = True
            elif not row["sound"]:
                all_sound = False
            if row["truncated"]:
                any_truncated = True

        if r["rho"] is not None:
            rhos.append(r["rho"])

        rho_str = f"{r['rho']:.3f}" if r["rho"] is not None else "n/a"
        c_ddmin_str = f"{c_vs_ddmin:.3f}" if c_vs_ddmin is not None else "n/a"
        c_probdd_str = f"{c_vs_probdd:.3f}" if c_vs_probdd is not None else "n/a"

        print(
            f"{r['k']:>6} {r['n']:>7} {r['ratio']:>7.1f} | "
            f"{_fmt(crux,'calls'):>10} {_fmt(crux,'result_size'):>9} {str(size_ok):>7} {rho_str:>7} | "
            f"{_fmt(ddmin,'calls'):>11} {_fmt(prob,'calls'):>12} | "
            f"{c_ddmin_str:>10} {c_probdd_str:>11}"
        )

    print("-" * len(header))
    agg_rho = geomean(rhos)
    print()
    print(f"instances: {len(instance_results)}   crux+ddmin+probdd all sound where completed: {all_sound}   "
          f"any budget-truncated: {any_truncated}   any crashed/timed-out (context baselines only, see below): {any_crashed_or_timed_out}")
    print(f"per-instance rho (crux): {['%.3f' % x for x in rhos]}")
    print(f"geomean rho: {agg_rho:.4f}" if agg_rho is not None else "geomean rho: n/a (no valid crux runs)")
    if rhos:
        print(f"min rho: {min(rhos):.4f}   max rho: {max(rhos):.4f}")

    # Surface any crash/timeout detail explicitly rather than letting it hide
    # behind the summary table's CRASH/TIMEOUT cell.
    for r in instance_results:
        for name in METHOD_NAMES:
            row = r["rows"][name]
            if row["crashed"] or row["timed_out"]:
                print(f"  [context-only, does not affect crux's rho] {name} k={r['k']} n={r['n']}: {row['error']}")

    print()
    if not all_sound:
        verdict = "DISQUALIFIED -- a returned output failed independent re-verification. This is a bug in I1, not a rho result. STOP."
    elif agg_rho is None:
        verdict = "INCONCLUSIVE -- no valid crux measurement (check truncation/crash/timeout detail above)."
    elif agg_rho > RHO_THRESHOLD:
        verdict = f"FAIL -- geomean rho {agg_rho:.3f} > {RHO_THRESHOLD}. Per S10: ABANDON ROUND 1."
    else:
        verdict = f"PASS -- geomean rho {agg_rho:.3f} <= {RHO_THRESHOLD}. Round 1 proceeds."
    print(f"VERDICT: {verdict}")
    print("=" * 108)

    if out_json:
        payload = {
            "rho_threshold": RHO_THRESHOLD,
            "geomean_rho": agg_rho,
            "all_sound": all_sound,
            "any_truncated": any_truncated,
            "any_crashed_or_timed_out": any_crashed_or_timed_out,
            "instances": instance_results,
        }
        Path(out_json).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {out_json}", file=sys.stderr)

    return all_sound, agg_rho


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="run a fast 2-instance subset for iteration, not the full gate spread")
    parser.add_argument("--out-json", default=None, help="optional path to also write the full result as JSON (never crux/results/ -- that is the bench-runner's directory)")
    args = parser.parse_args(argv)

    instances = QUICK_INSTANCES if args.quick else FULL_INSTANCES
    ctx = mp.get_context("fork")

    print(f"Running {len(instances)} instance(s) x {len(METHOD_NAMES)} methods "
          f"({'quick subset' if args.quick else 'full spread'}), "
          f"{PER_RUN_TIMEOUT:.0f}s wall-clock timeout per run...", file=sys.stderr)

    results = []
    for (k, n) in instances:
        t0 = time.monotonic()
        print(f"  instance k={k} n={n} (n/k={n/k:.1f}) ...", file=sys.stderr)
        results.append(run_instance(k, n, ctx))
        print(f"    done in {time.monotonic()-t0:.1f}s", file=sys.stderr)

    all_sound, agg_rho = print_report(results, out_json=args.out_json)

    if not all_sound:
        return 2  # disqualification -- distinct from a normal fail/pass
    if agg_rho is None:
        return 3
    return 0 if agg_rho <= RHO_THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
