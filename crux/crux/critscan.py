"""CritScan (Round 1 spec, specs/round1-core.md S4): isolation-with-
refinement search over a fixed, externally-supplied candidate space.

This module implements the Round 1 CONTRIBUTION ONLY -- the search. The
candidate space (which subsets are proposable at all) is entirely the
caller's business: this file reads nothing from `problem` except
`problem.oracle` (the sole channel to the outside world, S3 R3.2) and
`problem.elements` (used only for its LENGTH/CONTENT as an opaque
fingerprint for I8 -- never interpreted, never used to branch on task
identity, per the hard "no oracle introspection" rule).

Per S4.5, deliberately NOT here: any deduction rule, any probability model,
any multi-granularity machinery, any per-task constant. The window
controller (S4.4) is the only tuning surface and it is parameter-free.

Soundness (I1, S7) does not depend on monotonicity anywhere in this file:
every assignment to the working `kept` list is either a `del kept[i:j]`
immediately following an observed `True` on exactly that resulting set, or
(in `audit`) a full rebind to a candidate immediately following an observed
`True` on exactly that candidate. Grep for `kept = ` / `kept, pos = ` /
`del kept` below to check this by inspection.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from crux.crux.core import BudgetExhausted, ReductionProblem

__all__ = [
    "CritState",
    "reduce",
    "isolate",
    "audit",
    "next_mark_position",
]

# S7 preamble: "Assert these in a debug mode; the auditor will look for
# them." Off by default so the O(k)-per-iteration invariant checks (I2-I6)
# never sit in the call-count-critical hot path during a real benchmark
# run; flip on with CRUX_CRITSCAN_DEBUG=1 (or by setting the module
# attribute directly) for tests and audits. I8's own check is cheap
# (O(n) ONCE per `reduce` call, not per iteration) and stays on
# unconditionally -- see the comment at its call site.
DEBUG = bool(int(os.environ.get("CRUX_CRITSCAN_DEBUG", "0")))


@dataclass
class CritState:
    """S4.1, verbatim for the three fields the spec defines plus `rebase`.

    A mark is not a claim of permanence. It is the recorded fact "at a
    context of size ctx_size[c], deleting c alone was observed to fail",
    with provenance. S5 says what is and is not licensed by it.

    Everything below `universe` is INSTRUMENTATION ONLY (S11): additive
    bookkeeping never read by the algorithm itself and never a substitute
    for `problem.oracle.calls` / `.cache_hits`, which remain the sole
    authoritative counters (I9, hard rule #2 "honest call counting"). It
    exists so a harness -- or this file's own tests / the Round 1 gate --
    can see where a `reduce` call's oracle calls were spent without
    instrumenting the shared Oracle itself. All of it is cumulative across
    however many `reduce` calls share one CritState; it is lost (as
    intended -- ephemeral) if the caller never threads a state in.
    """

    marks: set = field(default_factory=set)       # element ids currently blocked
    ctx_size: dict = field(default_factory=dict)   # |kept| when the mark was made
    universe: Optional[frozenset] = None           # kept at the previous call

    # I8 (space scoping): a fingerprint of the element universe U this state
    # has been used against. Stamped on first use, checked on every later
    # use -- see `reduce`. Never derived from the oracle, only from the
    # element list the reducer already legitimately holds (R3.2).
    space_id: object = None

    # --- instrumentation only, from here down (S11) ---
    main_loop_calls: int = 0
    isolate_calls: int = 0
    audit_calls: int = 0
    marks_made: int = 0
    audit_reversals: int = 0
    audit_sweeps: int = 0
    window_successes: int = 0
    window_failures: int = 0
    w_at_success: list = field(default_factory=list)
    deleted_by_window: int = 0
    deleted_by_isolate: int = 0

    def rebase(self, kept):
        ks = set(kept)
        if self.universe is not None and not ks <= self.universe:
            self.marks.clear(); self.ctx_size.clear()   # kept GREW -> every mark is void
        self.marks &= ks
        self.ctx_size = {c: v for c, v in self.ctx_size.items() if c in self.marks}
        self.universe = frozenset(ks)

    def stats(self) -> dict:
        """Convenience snapshot of the instrumentation fields for reporting."""
        return {
            "main_loop_calls": self.main_loop_calls,
            "isolate_calls": self.isolate_calls,
            "audit_calls": self.audit_calls,
            "marks_made": self.marks_made,
            "audit_reversals": self.audit_reversals,
            "audit_sweeps": self.audit_sweeps,
            "window_successes": self.window_successes,
            "window_failures": self.window_failures,
            "mean_w_at_success": (sum(self.w_at_success) / len(self.w_at_success)) if self.w_at_success else None,
            "max_w_at_success": max(self.w_at_success) if self.w_at_success else None,
            "deleted_by_window": self.deleted_by_window,
            "deleted_by_isolate": self.deleted_by_isolate,
        }


def next_mark_position(kept, marks, cursor):
    """First index >= cursor whose element is marked, else len(kept).

    By I3 this is len(kept) on every call within a single pass: the main
    loop below only ever marks `kept[cursor]` itself (immediately followed
    by `cursor += 1`) or the position `isolate` returns (immediately
    followed by `cursor = pos + 1`), so every mark that exists is already
    strictly behind the cursor by the time this is next called, and
    `CritState.rebase` (I7) only ever removes marks or clears the set
    entirely -- it can never insert one ahead of where a threaded-in state
    resumes (that resumption already skips past the marked prefix before
    the main loop starts). So the honest O(1)-amortised answer, without
    rescanning up to `len(kept) - cursor` elements on every one of the
    O(k * log(n/k)) main-loop iterations, is simply `len(kept)`.

    This is verified rather than assumed whenever CRUX_CRITSCAN_DEBUG=1: the
    real linear scan below replaces the shortcut, so a violation of I3
    changes behaviour (the clamp still works, just slower) instead of
    silently mis-clamping.
    """
    if DEBUG:
        i = cursor
        n = len(kept)
        while i < n and kept[i] not in marks:
            i += 1
        return i
    return len(kept)


def isolate(problem: ReductionProblem, kept: list, lo: int, hi: int):
    """S4.3 -- the Round 1 contribution.

    PRE:  problem.oracle(kept minus kept[lo:hi]) was observed False.
    POST: kept[lo] is blocked at the current context; every element that was
          in [lo, hi) and lay to the left of it has been deleted.
    COST: exactly ceil(log2(hi - lo)) oracle calls.

    The load-bearing detail: a clean left half is deleted IMMEDIATELY,
    inside the search (`del kept[lo:mid]`), rather than being discarded
    when the search returns -- getting this wrong silently throws away
    about half the pool per isolation (S4.3).

    Both branches preserve the isolate precondition on the new [lo, hi):
      - clean branch  -- `kept_new \\ kept_new[lo:hi)` is the SAME element
        set as `kept_old \\ kept_old[lo:hi_old)`, whose False was already
        observed;
      - blocked branch -- `O(kept \\ kept[lo:mid))` was just observed False.
    At exit, hi-lo == 1, so O(kept) == True and O(kept \\ {kept[lo]}) ==
    False are both observed facts at the CURRENT context. No monotonicity
    is used anywhere in this function (S5.1).

    Mutates `kept` in place via contiguous slice deletes only (S7
    performance note: a C-level memmove, never a rebuild via comprehension)
    and returns it together with `lo`, the position of the blocking
    element.
    """
    while hi - lo > 1:
        mid = lo + (hi - lo) // 2                  # A = [lo, mid)   B = [mid, hi)
        cand = tuple(kept[:lo] + kept[mid:])       # delete A only
        if problem.oracle(cand):                   # A is clean
            del kept[lo:mid]                       # commit it  <-- the refinement (I1)
            hi -= (mid - lo)                       # B now occupies [lo, hi)
        else:                                       # A blocks; B untouched, still unsettled
            hi = mid
    return kept, lo


def audit(problem: ReductionProblem, kept: list, st: CritState):
    """S5.3 -- revocation. Turns every inferred mark into a measured one.

    On return, every surviving element of `kept` has been directly observed
    undeletable AT THE RETURNED CONTEXT -- not merely inferred from a mark
    made at some earlier, possibly-now-stale context. This is exactly
    ddmin's own guarantee (1-minimality, measured not inferred) and it is
    what makes I1 hold under an arbitrarily non-monotone oracle: without
    this sweep a wrong mark is an absorbing state (S5.2).

    Cost: a mark whose `ctx_size[c] == len(kept)` re-issues a query the
    harness's shared Oracle cache already holds -> 0 real calls. On a
    monotone oracle this sweep costs exactly `k` real calls and produces 0
    reversals in one pass (S11 unit test 3) -- see the module tests.

    This function must never consult a deduction rule: it exists
    specifically to CONTRADICT marks, so anything that answers from marks
    instead of a real oracle call would make it vacuous (S5.3). There is no
    deduction rule in Round 1 (S4.5), so this is naturally satisfied here,
    but it is the exact mistake a Round 3 implementer would make by reusing
    this function unmodified.
    """
    while True:
        cur_len = len(kept)
        # Staleness-descending (earliest-marked first, S5.3): those are the
        # marks most context has moved under, and an early reversal makes
        # every remaining mark staler still, which is what we want to find.
        order = sorted(kept, key=lambda c: (-(st.ctx_size.get(c, 0) - cur_len), c))
        alive = set(kept)
        reversed_any = False
        st.audit_sweeps += 1  # instrumentation only
        i = 0
        while i < len(order):
            c = order[i]
            if c not in alive:                      # removed by an earlier reversal this sweep
                i += 1
                continue
            cand = tuple(x for x in kept if x != c)
            if problem.oracle(cand):                 # the mark was WRONG
                kept = list(cand)                    # I1: assignment immediately after an observed True
                alive.discard(c)
                st.marks.discard(c)
                st.ctx_size.pop(c, None)
                reversed_any = True
                st.audit_reversals += 1              # instrumentation only
                # Non-monotonicity is spatially local (a brace's partner, a
                # decl's use): re-order the untested remainder nearest-first
                # around the reversal site.
                order = order[: i + 1] + sorted(order[i + 1 :], key=lambda x: (abs(x - c), x))
            else:
                st.ctx_size[c] = len(kept)           # refresh: this mark is now MEASURED
            i += 1
        if not reversed_any:
            return kept


def reduce(problem: ReductionProblem, kept, *, state: Optional[CritState] = None):
    """S4.2. `problem.oracle(kept) -> bool` is the only oracle channel.

    `kept` must be a sorted tuple of element indices for which the driver
    has already observed `problem.oracle(kept) == True` (task setup, S4
    preamble). Postcondition: the returned tuple either IS the (normalised)
    input unchanged, or is a set THIS call observed True. There is no third
    case (I1, S7).
    """
    # I2: defensive normalisation. A no-op on well-formed input (the stated
    # precondition is already a sorted, deduplicated tuple); harmless and
    # cheap if a caller ever violates that precondition, and it keeps I2
    # ("kept is strictly increasing at all times") true from the very first
    # line rather than merely "true after the caller behaves".
    kept_on_entry = tuple(sorted(set(kept)))

    st = state if state is not None else CritState()

    # I8 (space scoping): a CritState must never be handed to a different
    # (task, granularity, space). `reduce` has no task/space label to check
    # against -- only `problem` -- so the fingerprint is the one thing that
    # legitimately identifies "the same U" without looking at anything the
    # oracle produces: the element list's own length and content. This is
    # the input's own decomposition into units, which the reducer already
    # holds in full (S3's "why a local structural filter is legitimate"
    # argument applies identically here); it is never derived from a
    # boolean the oracle returned. O(n) once per `reduce` call, not per
    # iteration, so it is left on unconditionally rather than gated by
    # DEBUG.
    space_id = (len(problem.elements), hash(tuple(problem.elements)))
    if st.space_id is None:
        st.space_id = space_id
    elif st.space_id != space_id:
        raise ValueError(
            "CritState reused across a different (task, granularity, space); "
            "I8 requires a fresh CritState (or state=None) per space."
        )

    st.rebase(kept_on_entry)

    kept = list(kept_on_entry)

    cursor = 0
    while cursor < len(kept) and kept[cursor] in st.marks:
        cursor += 1                              # resume a threaded state for free (I3)
    w = max(1, len(kept) - cursor)                # first window = everything still unsettled

    calls_before_call = problem.oracle.calls      # instrumentation only, from here down
    isolate_calls_before_call = st.isolate_calls
    audit_calls_before_call = st.audit_calls

    try:
        while cursor < len(kept):
            if DEBUG:
                assert kept == sorted(kept), "I2 violated: kept not sorted"
                assert set(kept[:cursor]) == (st.marks & set(kept)), "I3 violated"
                potential_before = len(kept) - cursor   # I5: must strictly decrease this iteration

            # --- clamp: never propose a window touching an already-marked element
            limit = next_mark_position(kept, st.marks, cursor) - cursor
            if limit == 0:                        # kept[cursor] is marked; settle it for free
                cursor += 1
                continue
            w = max(1, min(w, limit))
            lo, hi = cursor, cursor + w

            if DEBUG:
                assert not (st.marks & set(kept[lo:hi])), "I4 violated: window touches a mark"

            cand = tuple(kept[:lo] + kept[hi:])
            if problem.oracle(cand):              # the whole window is deletable
                del kept[lo:hi]                   # REFINEMENT: commit the tested set wholesale (I1)
                st.window_successes += 1
                st.deleted_by_window += (hi - lo)
                st.w_at_success.append(w)
                w = w * 2                          # grow
            elif w == 1:
                st.window_failures += 1
                st.marks.add(kept[cursor])
                st.ctx_size[kept[cursor]] = len(kept)
                st.marks_made += 1
                cursor += 1                        # w stays 1: neighbours are probably blocked too
            else:
                st.window_failures += 1
                before_len = len(kept)
                before_calls = problem.oracle.calls
                try:
                    kept, pos = isolate(problem, kept, lo, hi)
                finally:
                    # Attribute even a partial isolate() (e.g. interrupted
                    # by BudgetExhausted mid-binary-search) correctly rather
                    # than letting it leak into main_loop_calls below --
                    # instrumentation only, does not affect kept itself:
                    # isolate() mutates it in place, so any deletions it
                    # already committed (each justified by an observed True,
                    # I1) are visible on `kept` regardless of how this
                    # `try` exits.
                    st.isolate_calls += problem.oracle.calls - before_calls
                st.deleted_by_isolate += before_len - len(kept)
                st.marks.add(kept[pos])
                st.ctx_size[kept[pos]] = len(kept)
                st.marks_made += 1
                cursor = pos + 1
                w = max(1, w // 2)                 # shrink

            if DEBUG:
                assert len(kept) - cursor < potential_before, "I5 violated: potential did not strictly decrease"

        before_calls = problem.oracle.calls
        try:
            kept = audit(problem, kept, st)         # S5 -- this is where soundness is bought
        finally:
            st.audit_calls += problem.oracle.calls - before_calls
    except BudgetExhausted:
        st.main_loop_calls += (
            (problem.oracle.calls - calls_before_call)
            - (st.isolate_calls - isolate_calls_before_call)
            - (st.audit_calls - audit_calls_before_call)
        )
        best = problem.oracle.best
        return best if best is not None else kept_on_entry

    st.main_loop_calls += (
        (problem.oracle.calls - calls_before_call)
        - (st.isolate_calls - isolate_calls_before_call)
        - (st.audit_calls - audit_calls_before_call)
    )
    return tuple(kept)
