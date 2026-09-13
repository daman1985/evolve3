# LOG.md — run log

Metric definitions live in PLAN.md §2. Every number below is produced by
`crux/bench/run.py` and reported by the `bench-runner` subagent.

---

## Round 0 — harness, baselines, first scoreboard

### Before

I need a scoreboard before I need an algorithm. The failure mode I most want to
avoid is the one the brief warns about — inventing something, measuring it
against a weak stand-in, and declaring a win — so round 0 buys the
infrastructure that makes that impossible later: the real `picire` ddmin
implementation rather than my own, faithful ProbDD and CDD reimplementations
from the papers, the naive linear reducer as the bottom rung, and 22 real bug
inputs lifted from `shrinkray`'s own MIT-licensed evaluation corpus so the
inputs are not ones I chose to flatter myself. Each corpus entry needs a cheap
in-process oracle that approximates the real bug's requirement (required
tokens plus syntactic validity) — `shrinkray`'s own benchmark harness uses
exactly this approach for exactly this reason: a run has to cost seconds, not
the 900–1500s their real-oracle runs take, or I get one round instead of
seven. I am also adding synthetic tasks with a *known optimum*, because on
those I can measure distance-from-optimal exactly rather than just
"smaller than the other guy". The validity gate — independently re-running the
oracle on every final output — goes in now rather than later, because a
reduction result that does not actually reproduce the bug is not a fast result,
it is a wrong one. Exit condition: every baseline runs on every task and
`E(ddmin)` is on the board.

### Amendment 1 (mid-round-0, before any Round 1 implementation)

Review caught two holes in the pre-registered plan, and the second one was
serious enough to change the thesis.

The first was an omission: Perses, still cited in 2026 surveys as the
state-of-the-art domain-agnostic reducer for hierarchically structured inputs,
was not in my baseline set — on a corpus that is almost entirely source files.
It turned out to vendor trivially (prebuilt 77MB jar, JDK 21 already present,
no Bazel build), so there was no practical excuse; it is now a baseline and
`crux/bench/fetch_perses.sh` fetches it.

The second was a real flaw in the argument. My MUS query-complexity thesis
assumed a query returns meaningful information, but most subsets of a source
file are not valid syntax, and "failed to parse" is not the same information as
"you deleted something required". Rather than argue about it I measured it
(`crux/bench/syntax_validity_probe.py`, real parsers, 432 seeded trials per
cell): at line granularity only **6.5%** of scattered deletion candidates parse
at all, versus 22.9% for contiguous chunks; at character granularity scattered
candidates parsed **0 times out of 432**. C++ at line granularity: 2.2%.
JavaScript: 0%. That is decisive in the wrong direction for my thesis —
scattered candidate sets are exactly what progression/QuickXplain selection
produces and exactly where its complexity win comes from, so the MUS port is
hit *harder* by the syntax problem than ddmin is, not less. Worse, it breaks
soundness: criticality is only permanent under monotonicity, and deleting `{`
fails while deleting `{` and `}` together succeeds, so a syntactic entanglement
would mark an element permanently critical when it is not required at all.

I am not killing the idea, but I am relocating it and narrowing the claim. The
candidate space and the search over it are separable concerns; Perses's
contribution is the former, and its own defaults
(`--default-list-minimizer-for-hdd "CDD"`, `--latra-transformation-list-minimizer
"WPROBDD"`) show its search is still ddmin-family, with the list minimizer
exposed as a pluggable option. So the claim becomes "a better search, composable
with either candidate space" rather than "MUS beats Perses", the experiment
becomes a candidate-space x search cross product read across rows, and
structural awareness moves from Round 3 to Round 1 because it is load-bearing
for soundness. Grammar-free structural reduction is explicitly not claimed as
novel — Perses already ships `dyck-brace` modes. The architect has been sent
the data and told to kill the idea outright if it does not survive it.
