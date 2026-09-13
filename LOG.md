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

### Calibration note (mid-round-0): shrinkray on a monotone toy task

Before trusting any head-to-head later, I calibrated the SOTA tool on a
deliberately easy task: 300 lines, 3 of them required, oracle = plain substring
grep with **no syntax requirement**, so the predicate is genuinely monotone —
the best possible case for the MUS argument and an easy case generally.

shrinkray used **2256 oracle calls** and returned 41 bytes. Two things worth
recording.

First, the headroom signal. On a monotone oracle with n=300 and k=3, the
MUS-extraction bound O(k log(n/k)) is on the order of 20-60 queries. shrinkray
spent 2256 — roughly 7.5 calls per input line. Some of that is real work beyond
finding the three lines (it kept going at character granularity, and it has a
fixpoint/restart phase), so this is not a like-for-like 40x gap. But it is the
first concrete evidence that the gap between what the theory allows and what
the best available tool spends is large rather than marginal, on exactly the
task shape where the theory should apply cleanly.

Second, an asymmetry I need to be honest about in every size comparison from
here on. The input order was TARGET_17, TARGET_100, TARGET_255; shrinkray
returned `TARGET_100 = 1TARGET_17 = 1TARGET_255 = 1` — reordered, and with the
newlines deleted. It beat the naive delete-only optimum (44 bytes) by
**rewriting**, not just deleting. crux is delete-only, so its search space is
strictly smaller and it can lose on size for reasons that have nothing to do
with search quality. Size comparisons must therefore separate delete-only
reducers (ddmin, ProbDD, CDD, crux) from rewriting reducers (shrinkray, Perses,
C-Reduce), or the size column silently measures "has rewrite passes" rather
than "searches well". Recorded now so it cannot be quietly forgotten when the
numbers arrive.

### Manager verification of the architect's reframing (mid-round-0)

The architect came back with the premise relocated rather than dead: it
retracted "permanently critical" and the free 1-minimality certificate
outright (correct — `{` is undeletable alone and deletable with `}`), and
argued the search itself never relies on monotonicity, only the termination
certificate does, so a measured audit sweep restores soundness under an
arbitrarily non-monotone oracle at a cost of roughly `2k` out of a
`k·log₂(n/k)+3k` budget. It also rebutted my "scattered sets" objection
concretely: its `CritScan` issues only contiguous spans of the current kept
set, so it lands in the 22.9% column with ddmin rather than the 6.5% column
with ProbDD. That rebuttal is load-bearing and is instrumented to be checked
rather than assumed, which is the right disposition.

The claim that most changes the framing is that after grammar-free brace
snapping, C++ candidates that still fail do so mostly for *semantic* reasons,
not syntactic ones — because that bounds how much any structural layer can buy.
I checked it independently rather than take it on faith, writing my own probe
without reading theirs (`crux/bench/measure/manager_semantic_check.py`). I get
**54.5% semantic, 21.9% syntax, 23.5% other** on 187 failures; the architect
reported 64.1% / 11.1%. The exact split differs with the classifier and the
snapping implementation, but the direction is robust: semantic failures
outnumber syntactic ones by somewhere between 2.5x and 6x. A grammar or
parse-tree candidate space removes the syntax slice, which is the minority.
That is a real and slightly counterintuitive result, and it argues that
extracting more information per negative query matters *more* in this regime,
not less.

One caveat I am recording against our own interest, because the architect's
framing understates Perses: the parse-tree layer per se addresses the syntax
slice, but Perses ships additional machinery aimed squarely at the semantic
class — `--enable-mimir-delete-def-with-all-its-concrete-uses` exists precisely
to delete a definition together with its uses, which is the
`undeclared identifier` failure mode. It is off by default. So "Perses removes
the 11%, not the 64%" is true of its default configuration and of the
grammar layer in isolation, and would be unfair as a blanket statement about
the tool. When we run Perses in Round 5 we should report the default
configuration as the headline and note this flag exists.

Next action: the architect's kill criterion — `ρ = calls / (k·(log₂(n/k)+4))`
on monotone `hit-k-n` with `n ≥ 4096`, `n/k ≥ 32`, abandon if `ρ > 2.5` — runs
first in Round 1, before any other Round 1 work, because it costs minutes and
gates everything after it.
