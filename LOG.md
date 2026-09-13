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
