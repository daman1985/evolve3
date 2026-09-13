"""Adapter around the installed `picire` package (v21.8, Hodovan & Kiss) --
picire's own reference implementation of ddmin, driven through our Oracle
so call counts come from OUR counter rather than picire's internal
bookkeeping. We do not reimplement ddmin here; see ddmin_own.py for an
independent cross-check implementation instead.

Wiring choices below all mirror picire's own CLI defaults (picire/cli.py
`create_parser`), i.e. "picire's own DD with its default config":
  - reducer class: `picire.dd.DD` (single-process; CLI default when
    `--parallel` is not given).
  - split: `ZellerSplit` with granularity 2 -- `DD.__init__`'s own default
    (`split=None` -> `ZellerSplit()`) and the CLI's `--granularity 2`
    default. Not overridden here.
  - subset/complement iterators: `forward` (picire CLI `--subset-iterator`
    / `--complement-iterator` default).
  - subset_first=True (`DD.__init__`'s own default, and the CLI default
    since `--complement-first` is off by default).
  - cache: `ContentCache`, per this round's brief. (Note: `DD.__init__`'s
    OWN internal default when no cache is passed is actually `ConfigCache`,
    and that is also picire's CLI `--cache` default. We use ContentCache
    here per instruction. The two are behaviourally equivalent for our
    purposes: picire's splitters only ever produce configs that are
    order-preserving sub-sequences of the original index list, so a
    config's sorted-index-tuple identity and its rendered-text identity
    pick out exactly the same duplicates -- ContentCache just recognises
    them by re-rendering text instead of walking an index trie.)
"""
from __future__ import annotations

from picire.config_iterators import forward
from picire.dd import DD
from picire.outcome import Outcome
from picire.outcome_cache import ContentCache

from crux.crux.core import BudgetExhausted, ReductionProblem


def reduce(problem: ReductionProblem, kept: tuple) -> tuple:
    def test(config, config_id):
        # picire's Outcome.FAIL means "interesting" (the property under
        # test still holds) -- see picire/subprocess_test.py:
        # `Outcome.FAIL if returncode == 0 else Outcome.PASS`, the same
        # "0 = interesting" convention every delta-debugger uses. Our
        # oracle's True means exactly that.
        return Outcome.FAIL if problem.oracle(tuple(config)) else Outcome.PASS

    cache = ContentCache()
    # ContentCache needs a way to turn a config (list of kept indices) into
    # the hashable content it caches by; picire's own `cli.reduce()` helper
    # wires this to a `ConcatTestBuilder` over the same atoms passed to the
    # tester. We reuse the harness's own renderer for the identical effect.
    cache.set_test_builder(lambda config: problem.render(tuple(config)))

    dd = DD(
        test,
        cache=cache,
        subset_iterator=forward,
        complement_iterator=forward,
        subset_first=True,
    )

    try:
        result = dd(sorted(kept))
    except BudgetExhausted:
        # DD's own __call__ always re-confirms the current config is still
        # FAIL at the top of every iteration (abstract_dd.py), so by the
        # time a budget-limited Oracle raises here, oracle.best is already
        # populated with at least that most-recently-confirmed config.
        return problem.oracle.best

    return tuple(sorted(result))
