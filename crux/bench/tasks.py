"""The benchmark's task set: real-bug corpus tasks with cheap in-process
oracles (see corpus_recipe.py) plus synthetic tasks with a known optimum.

A Task is granularity-agnostic on the outside: `elements` is whatever
sequence is being reduced, and `predicate_on_kept` is a
`Callable[[tuple[int, ...]], bool]` over kept INDICES -- the exact shape
`crux.crux.core.Oracle` wants for its `fn`, so `task.make_problem(budget)`
needs no adaptation layer. Corpus tasks additionally carry a
text-level predicate (`predicate_on_text`) and enough path/format
information for the external (Perses) adapter to run against the same
real file, independently of anything built here.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from crux.crux.core import Oracle, ReductionProblem
from crux.bench.corpus_recipe import (
    _balanced_brackets,
    compute_recipe,
    make_predicate,
    max_depth,
)

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

LINE_TASK_MIN_LINES = 8
CHAR_TASK_MAX_BYTES = 5000


@dataclass
class Task:
    name: str
    kind: str  # "corpus" | "synthetic"
    elements: list
    predicate_on_kept: Callable[[tuple], bool]
    granularity: Optional[str] = None  # "line" | "char" | None (synthetic)
    known_optimum: Optional[int] = None  # in ELEMENTS; synthetic tasks only
    reference_bytes: Optional[int] = None  # informational; corpus tasks only
    reference_valid: Optional[bool] = None  # informational; corpus tasks only
    used_fallback: bool = False  # corpus tasks only: REQUIRED had no real reference
    predicate_on_text: Optional[Callable[[str], bool]] = None  # corpus tasks only
    entry_dir: Optional[Path] = None  # corpus tasks only (for external tools)
    original_path: Optional[Path] = None  # corpus tasks only
    fmt: Optional[str] = None  # corpus tasks only

    def render(self, kept) -> str:
        return "".join(self.elements[i] for i in sorted(kept))

    def make_problem(self, budget: Optional[int] = None) -> ReductionProblem:
        """A FRESH Oracle + ReductionProblem every call -- the harness must
        never reuse one across two different (method, task) runs, or call
        counts leak between them."""
        oracle = Oracle(self.predicate_on_kept, budget=budget)
        return ReductionProblem(self.elements, oracle)


# --------------------------------------------------------------------------
# Corpus tasks
# --------------------------------------------------------------------------


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8", "surrogateescape"))


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def build_corpus_tasks() -> list[Task]:
    tasks: list[Task] = []
    for entry_dir in sorted(p for p in CORPUS_DIR.iterdir() if p.is_dir()):
        recipe = compute_recipe(entry_dir)
        predicate_on_text = make_predicate(recipe)
        original_text = recipe.original_path.read_text(encoding="utf-8", errors="surrogateescape")

        # Hard assertion (this round's spec): predicate(original) must be
        # True for every task. A failure here means the RECIPE is wrong
        # for this format/entry, not that the entry should be dropped or
        # special-cased -- fix corpus_recipe.py, never this loop.
        if not predicate_on_text(original_text):
            raise AssertionError(
                f"predicate(original) is False for corpus entry {entry_dir.name!r} "
                "-- fix corpus_recipe.py, not this entry"
            )

        reference_bytes = None
        reference_valid = None
        if recipe.reference_path is not None:
            reference_text = recipe.reference_path.read_text(encoding="utf-8", errors="surrogateescape")
            reference_bytes = _byte_len(reference_text)
            # Informational only (round-0 spec): the reference is an
            # external tool's own output under a DIFFERENT (real) oracle;
            # it is not asserted to satisfy ours.
            reference_valid = predicate_on_text(reference_text)

        common = dict(
            reference_bytes=reference_bytes,
            reference_valid=reference_valid,
            used_fallback=recipe.used_fallback,
            predicate_on_text=predicate_on_text,
            entry_dir=entry_dir,
            original_path=recipe.original_path,
            fmt=recipe.fmt,
        )

        if _line_count(original_text) >= LINE_TASK_MIN_LINES:
            elements = original_text.splitlines(keepends=True)
            tasks.append(
                Task(
                    name=f"{entry_dir.name}@line",
                    kind="corpus",
                    elements=elements,
                    predicate_on_kept=_kept_predicate(elements, predicate_on_text),
                    granularity="line",
                    **common,
                )
            )

        if _byte_len(original_text) < CHAR_TASK_MAX_BYTES:
            elements = list(original_text)
            tasks.append(
                Task(
                    name=f"{entry_dir.name}@char",
                    kind="corpus",
                    elements=elements,
                    predicate_on_kept=_kept_predicate(elements, predicate_on_text),
                    granularity="char",
                    **common,
                )
            )

    return tasks


def _kept_predicate(elements: list, predicate_on_text: Callable[[str], bool]) -> Callable[[tuple], bool]:
    def predicate_on_kept(kept, _elements=elements, _pred=predicate_on_text) -> bool:
        return _pred("".join(_elements[i] for i in sorted(kept)))

    return predicate_on_kept


# --------------------------------------------------------------------------
# Synthetic tasks
# --------------------------------------------------------------------------

HIT_KS = (1, 5, 20, 100)
HIT_NS = (200, 2000, 20000)
HIT_MODES = ("uniform", "clustered", "adversarial")

NEST_NS = (200, 2000)
CHAIN_NS = (200, 2000, 20000)
BLOCKS_NS = (200, 2000)


def _seeded(*parts) -> random.Random:
    return random.Random("crux-synthetic::" + "::".join(str(p) for p in parts))


def _placement_uniform(n: int, k: int, rng: random.Random) -> list[int]:
    return sorted(rng.sample(range(n), k))


def _placement_clustered(n: int, k: int, rng: random.Random) -> list[int]:
    """k required indices packed into 2-3 contiguous, non-overlapping runs."""
    n_clusters = 2 if k < 6 or n < 1000 else 3
    n_clusters = min(n_clusters, k)
    # Split k into n_clusters positive run-lengths (front runs absorb the
    # remainder, same tie-break convention used throughout this project).
    sizes = []
    remaining = k
    for i in range(n_clusters):
        size = -(-remaining // (n_clusters - i))  # ceil division
        sizes.append(size)
        remaining -= size
    indices: list[int] = []
    # Place runs at random non-overlapping start offsets, spaced out across
    # the index range so they do not collide.
    span = n // n_clusters
    for i, size in enumerate(sizes):
        lo = i * span
        hi = max(lo, (i + 1) * span - size)
        start = rng.randint(lo, hi) if hi > lo else lo
        indices.extend(range(start, start + size))
    return sorted(set(indices))


def _placement_adversarial(n: int, k: int, rng: random.Random) -> list[int]:
    """k required indices spread as evenly as possible across [0, n) -- the
    classic worst case for ddmin-style contiguous chunk splitting, since no
    chunk smaller than ~n/k can contain more than one of them."""
    if k <= 1:
        return [rng.randrange(n)]
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


_HIT_PLACEMENTS = {
    "uniform": _placement_uniform,
    "clustered": _placement_clustered,
    "adversarial": _placement_adversarial,
}


def _subset_predicate(required: frozenset) -> Callable[[tuple], bool]:
    def predicate_on_kept(kept, _required=required) -> bool:
        return _required.issubset(kept)

    return predicate_on_kept


def build_hit_tasks() -> list[Task]:
    tasks = []
    for n in HIT_NS:
        for k in HIT_KS:
            if k > n:
                continue
            for mode in HIT_MODES:
                rng = _seeded("hit", k, n, mode)
                required_idx = _HIT_PLACEMENTS[mode](n, k, rng)
                elements = [f"e{i}" for i in range(n)]
                tasks.append(
                    Task(
                        name=f"hit-{k}-{n}-{mode}",
                        kind="synthetic",
                        elements=elements,
                        predicate_on_kept=_subset_predicate(frozenset(required_idx)),
                        known_optimum=k,
                    )
                )
    return tasks


def _nest_predicate(depth_required: int) -> Callable[[tuple], bool]:
    def predicate_on_kept(kept, elements=None) -> bool:
        raise RuntimeError("unused placeholder")  # replaced per-task below

    return predicate_on_kept


def build_nest_tasks() -> list[Task]:
    tasks = []
    for n in NEST_NS:
        rng = _seeded("nest", n)
        d = max(1, n // 4)
        p = max(0, n // 2 - d)  # number of independent, fully-removable "()" padding pairs
        seq = ["("] * d + [")"] * d
        for _ in range(p):
            pos = rng.randint(0, len(seq))
            seq[pos:pos] = ["(", ")"]
        elements = seq

        def predicate_on_kept(kept, _elements=elements, _d=d) -> bool:
            text = "".join(_elements[i] for i in sorted(kept))
            return _balanced_brackets(text) and max_depth(text) >= _d

        tasks.append(
            Task(
                name=f"nest-{n}",
                kind="synthetic",
                elements=elements,
                predicate_on_kept=predicate_on_kept,
                known_optimum=2 * d,
            )
        )
    return tasks


def build_chain_tasks() -> list[Task]:
    tasks = []
    for n in CHAIN_NS:
        rng = _seeded("chain", n)
        length = max(2, n // 10)
        chain = sorted(rng.sample(range(n), length))
        elements = [f"e{i}" for i in range(n)]

        def predicate_on_kept(kept, _chain=chain) -> bool:
            kept_set = set(kept)
            if _chain[-1] not in kept_set:
                return False  # anchor: the top of the chain is unconditionally required
            for idx in range(len(_chain) - 1):
                # element i is required only when element i+1 is kept.
                if _chain[idx + 1] in kept_set and _chain[idx] not in kept_set:
                    return False
            return True

        tasks.append(
            Task(
                name=f"chain-{n}",
                kind="synthetic",
                elements=elements,
                predicate_on_kept=predicate_on_kept,
                known_optimum=length,
            )
        )
    return tasks


def build_blocks_tasks() -> list[Task]:
    tasks = []
    for n in BLOCKS_NS:
        core_size = max(1, n // 100)
        start = n // 2 - core_size // 2
        required = frozenset(range(start, start + core_size))
        elements = [f"e{i}" for i in range(n)]
        tasks.append(
            Task(
                name=f"blocks-{n}",
                kind="synthetic",
                elements=elements,
                predicate_on_kept=_subset_predicate(required),
                known_optimum=core_size,
            )
        )
    return tasks


def build_synthetic_tasks() -> list[Task]:
    return build_hit_tasks() + build_nest_tasks() + build_chain_tasks() + build_blocks_tasks()


def build_all_tasks() -> list[Task]:
    return build_corpus_tasks() + build_synthetic_tasks()
