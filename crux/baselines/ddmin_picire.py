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
  - cache: `ConfigCache` -- verified directly against picire/cli.py's
    `create_parser` (`--cache ... default='config'`), which resolves to
    `outcome_cache.config = ConfigCache` (picire/outcome_cache.py). This
    is also `DD.__init__`'s own internal default when no cache is passed.

    An earlier version of this adapter used `ContentCache` instead, on the
    theory that it is "behaviourally equivalent for our purposes" because
    picire's splitters only ever produce configs that are order-preserving
    sub-sequences of the original index list. That reasoning is correct
    only when every element renders to distinct text, so no two different
    index sets can ever collide on content (true of the hit/chain/blocks
    synthetic families, whose elements are `f"e{i}"`). It is FALSE in
    general: `ConfigCache` keys by the exact sequence of indices tested,
    while `ContentCache` keys by rendered text, and any task with repeated
    element content -- the `nest` synthetic family (elements are just
    repeated '(' / ')' characters), and, critically, every real corpus
    task (source code is full of repeated tokens/characters/whitespace)
    -- gives the two caches genuinely different hit rates. Measured
    directly (round-0 verification, swapping only the cache class,
    everything else identical): `ContentCache` needed 580 real calls on
    `ujson-510-indent-buffer-overflow@char` where `ConfigCache` needed
    3033 (>5x), and 284 vs. 711 on `nest-200`. `ConfigCache` is the one
    that is actually picire's own default, so it is the faithful choice
    per this project's baseline rule (do not "improve" a baseline); using
    the wrong one was silently making the ddmin_picire reference stronger
    than real `picire --cache config` would be. Fixed here.
"""
from __future__ import annotations

from picire.config_iterators import forward
from picire.dd import DD
from picire.outcome import Outcome
from picire.outcome_cache import ConfigCache

from crux.crux.core import BudgetExhausted, ReductionProblem


def reduce(problem: ReductionProblem, kept: tuple) -> tuple:
    def test(config, config_id):
        # picire's Outcome.FAIL means "interesting" (the property under
        # test still holds) -- see picire/subprocess_test.py:
        # `Outcome.FAIL if returncode == 0 else Outcome.PASS`, the same
        # "0 = interesting" convention every delta-debugger uses. Our
        # oracle's True means exactly that.
        return Outcome.FAIL if problem.oracle(tuple(config)) else Outcome.PASS

    # ConfigCache needs no test builder (its cache key is the raw index
    # sequence, not rendered content) -- unlike ContentCache, so there is
    # no render-based wiring to set up here at all.
    cache = ConfigCache()

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
