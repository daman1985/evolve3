"""Shared abstractions for crux: the Oracle wrapper and reduction problems.

Stdlib only. Nothing in here may import picire, numpy, or anything from
crux/baselines or crux/bench -- this module ships as the actual tool.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence

__all__ = [
    "BudgetExhausted",
    "Oracle",
    "ReductionProblem",
    "LineProblem",
    "CharProblem",
]


class BudgetExhausted(Exception):
    """Raised by Oracle.__call__ when a call would exceed its call budget.

    Callers (reducers) MUST catch this and fall back to ``oracle.best`` --
    the smallest kept-set that has actually been confirmed True so far. The
    exception carries that same value on ``.best`` purely for convenience;
    ``oracle.best`` remains the authoritative source after the raise.
    """

    def __init__(self, best: Optional[tuple]):
        self.best = best
        super().__init__(
            "oracle call budget exhausted"
            + (f"; best so far has {len(best)} elements" if best is not None else "; no True result seen yet")
        )


_MISSING = object()


class Oracle:
    """Wraps a user predicate over kept-index sets.

    ``fn`` is a ``Callable[[tuple[int, ...]], bool]`` over KEPT indices --
    reducers never see ``fn`` directly, only this wrapper, so every
    invocation is observed and counted here in one place.

    Counting contract (see PLAN.md S2 and the reducer-engineer brief):
      - ``calls`` counts real executions of ``fn`` ONLY.
      - ``cache_hits`` counts lookups served from the cache, and is NEVER
        folded into ``calls``. A cache hit costs nothing in the real cost
        model (no compiler/test run happens), so it must stay a separate
        counter or every "faithful" comparison in the study is silently
        wrong.
      - An exception raised by ``fn`` still counts as one real call (the
        real world spent the wall-clock time; we just don't like the
        answer), and is treated as a False result. This also means a
        pathological input that crashes our own cheap oracle can never be
        mistaken for "free" the way a cache hit is.
      - ``best`` is knowledge, not cost: it is updated on every True result,
        whether that result came from a fresh call or a cache hit, because
        either way we now know that kept-set works.
    """

    def __init__(self, fn: Callable[[tuple], bool], budget: Optional[int] = None):
        self._fn = fn
        self.budget = budget
        self.calls = 0
        self.cache_hits = 0
        self.best: Optional[tuple] = None
        self._cache: dict[frozenset, bool] = {}

    def __call__(self, kept: Iterable[int]) -> bool:
        key = frozenset(kept)

        cached = self._cache.get(key, _MISSING)
        if cached is not _MISSING:
            self.cache_hits += 1
            if cached:
                self._note_best(key)
            return cached

        if self.budget is not None and self.calls >= self.budget:
            raise BudgetExhausted(self.best)

        # Real execution. Increment BEFORE calling fn so that a raise (or,
        # in principle, a caller-side timeout wrapping fn) still counts --
        # the cost was paid whether or not we liked the outcome.
        self.calls += 1
        try:
            result = bool(self._fn(tuple(sorted(key))))
        except Exception:
            result = False

        self._cache[key] = result
        if result:
            self._note_best(key)
        return result

    def _note_best(self, key: frozenset) -> None:
        if self.best is None or len(key) < len(self.best):
            self.best = tuple(sorted(key))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Oracle(calls={self.calls}, cache_hits={self.cache_hits}, best_size={len(self.best) if self.best is not None else None})"


class ReductionProblem:
    """A sequence of elements to delete from, plus the Oracle over it.

    ``elements`` are the units a reducer is allowed to delete (lines,
    characters, tokens, ...). ``render(kept)`` reconstructs text from a
    kept-index set by joining the corresponding elements back together in
    their ORIGINAL order -- order in ``kept`` itself is irrelevant, since a
    kept-set is a subset, not a sequence.
    """

    def __init__(self, elements: Sequence[str], oracle: Oracle):
        self.elements: list[str] = list(elements)
        self.oracle = oracle

    def render(self, kept: Iterable[int]) -> str:
        return "".join(self.elements[i] for i in sorted(kept))

    def __len__(self) -> int:
        return len(self.elements)

    @staticmethod
    def _split(text: str) -> list[str]:
        raise NotImplementedError

    @classmethod
    def from_text(
        cls,
        text: str,
        predicate: Callable[[str], bool],
        budget: Optional[int] = None,
    ) -> "ReductionProblem":
        """Build a problem straight from raw text plus a text predicate.

        ``predicate`` takes rendered text and returns bool: this is the
        natural unit test authors write ("is this still interesting?").
        Oracle itself only ever sees kept-index tuples, so the text
        rendering happens in the small closure below, once, at
        construction time -- not scattered through every reducer.
        """
        elements = cls._split(text)

        def render(kept: Iterable[int], _elements: list[str] = elements) -> str:
            return "".join(_elements[i] for i in sorted(kept))

        oracle = Oracle(lambda kept: predicate(render(kept)), budget=budget)
        return cls(elements, oracle)


class LineProblem(ReductionProblem):
    """Elements are lines, each including its own trailing newline (if any),
    so render() is a plain '' .join with no separator needed."""

    @staticmethod
    def _split(text: str) -> list[str]:
        return text.splitlines(keepends=True)


class CharProblem(ReductionProblem):
    """Elements are single characters."""

    @staticmethod
    def _split(text: str) -> list[str]:
        return list(text)
