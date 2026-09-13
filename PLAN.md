# PLAN.md — Fewer-Query Test-Case Reduction

Manager: main thread. Workers: four subagents in `.claude/agents/`.
Project code: `crux/`. Run log: `LOG.md`. Final writeup: `SUMMARY.md`.

---

## 1. The problem

**Automated test-case reduction (a.k.a. test-case minimisation / delta debugging).**

You have a 4000-line file that crashes a compiler, and a script that answers
one yes/no question: *"does this input still trigger the bug?"* The job is to
shrink the file to something small enough for a human to read, while it keeps
triggering the bug — using as few calls to that script as possible, because in
real life each call is a compile or a test run and costs seconds to minutes.

Formally: given a sequence of `n` elements (lines, tokens, characters, tree
nodes) and a near-monotone oracle `O: subset -> bool` with `O(full) = true`,
find a small `S` with `O(S) = true`, minimising both `|S|` and the number of
evaluations of `O`.

### Why this problem, and why it has real headroom

**It is not saturated.** The entire published literature on general-purpose
reduction is a handful of algorithms from a handful of groups: `ddmin`
(Zeller & Hildebrandt 2002), HDD (Misherghi & Su 2006), C-Reduce (Regehr et
al. 2012, C/C++-specific), Perses (2018), ProbDD (ASE 2021), Vulcan (2023),
and the FSE 2024 analysis that showed ProbDD's gain is largely explained by a
much simpler variant (CDD). There is no commercial incumbent, no well-funded
team, and no ImageNet-style leaderboard soaking up the accessible wins. The
one genuinely excellent engineering effort — DRMacIver's `shrinkray` — is one
person's project and is explicit in its own notes that call count is the cost
that matters and is not solved.

**The headroom is visible in the numbers.** `shrinkray`'s own published
results on its corpus show single reductions taking 918s, 1126s, 1556s of
wall clock. Their benchmark header states the cost model plainly:
`wall-clock ≈ calls × oracle_time`. Meanwhile the theory says we should be
doing far better: reduction is structurally the same problem as **minimal
unsatisfiable subset (MUS) extraction**, where `QuickXplain`/progression-style
algorithms achieve `O(k log(n/k))` oracle queries for a result of size `k`.
`ddmin` is `O(n²)` worst case; ProbDD and CDD are heuristic improvements that
still never convert a failed query into *hard* information. That gap between
"what the MUS people prove" and "what the delta-debugging tools actually do"
is the headroom, and it is not a rounding error — it is a different
complexity class.

**Naive vs. good is a wide gap.** Naive first attempt: "try deleting each
line one at a time" — `O(n)` calls per pass, several passes, and it is what
most people actually hand-roll. `ddmin` is much better. ProbDD/CDD better
still. `shrinkray` better again. There is a genuine ladder here with several
rungs already on it, which is exactly the property asked for.

### Why my approach targets the real best-known method

I am not benchmarking against a hand-written `ddmin` of my own. The baselines
are:

| Baseline | Source | Status |
|---|---|---|
| `picire` ddmin | `pip install picire` (Hodován) | the reference research implementation, with caching and the standard config iterators |
| ProbDD | faithful reimplementation from the ASE'21 paper | audited against published pseudocode by a dedicated subagent |
| CDD | faithful reimplementation from FSE'24 | the paper's own simplification that matches ProbDD |
| linear/greedy | trivial | the naive rung, for scale |
| `shrinkray` | github.com/DRMacIver/shrinkray @ 26.7.8.0 | current best practical general-purpose reducer; run head-to-head where installable (needs py3.12 + uv, available here) |

Benchmark inputs are the **MIT-licensed real bug corpus from `shrinkray`'s own
evaluation suite** (22 entries: gcc/clang ICEs, rustc, tsc, terser, prettier,
mypy, ruff, pylint, black, jq CVE, minisat, kissat, splr), plus synthetic
tasks with a *known optimum* so I can measure distance-from-optimal exactly,
plus larger inputs than the corpus contains. Using the competitor's own
corpus and comparing against their own published reduced sizes is the
strongest available guard against grading myself on a curve.

### The technical thesis (what would be new)

Every existing general reducer throws away most of the information in a
**failed** query. When "delete set `S`" fails, `ddmin` just tries a different
split; ProbDD smears a small Bayesian penalty across all of `S`. But a failure
means *at least one element of `S` is required*, and under the monotonicity
assumption these tools already rely on, `O(log|S|)` extra queries isolate an
element that is **permanently critical** — it can never be deleted again, in
any smaller context, and it never needs to be re-tested for 1-minimality.

So: **import MUS extraction into test-case reduction.** Specifically combine

1. **Critical marking via progression/QuickXplain binary isolation** — turn
   each failure into a hard, permanent fact instead of a soft prior update.
2. **Aggressive refinement on success** — a successful query discards
   everything outside the tested set at once, not just the tested chunk.
3. **A locality-smoothed deletability model** — real deletable regions are
   contiguous and syntactic (a whole unused function, a whole block), so
   candidate sets should be drawn from a spatially smoothed field over the
   sequence, not from i.i.d. per-element probabilities as ProbDD does.
4. **Multi-granularity fixpoint with a shared result cache** — lines → tokens
   → characters, with structural (bracket-aware) chunking.

Items 1+2 are standard in the MUS world and, as far as I can find, absent from
the delta-debugging tools. Item 3 is the axis ProbDD explicitly models wrong
(independence). That combination is the bet.

**Honest statement up front:** `shrinkray` is very good, and it wins on final
*size* partly through machinery orthogonal to the core deletion primitive
(tree-sitter passes, libcst rewrites, identifier normalisation). If I cannot
beat it on size, I will say so in the log and in SUMMARY.md rather than
declare victory. The axis I expect to win on, and am explicitly targeting, is
**oracle calls at equal-or-better size** — which is the axis that actually
determines whether a reduction finishes over lunch or overnight. The core
deletion primitive is shared by *every* reducer, so an improvement there is
transferable, not a point solution.

### What you get at the end

A CLI you can run the same day:

```
crux --oracle ./is-interesting.sh --input bug.cpp --out min.cpp
```

Language-agnostic, no heavy dependencies, works on any file and any predicate
script that exits 0 for "still broken". Plus a Claude Code skill
(`/minimize-repro`) that writes the oracle script for you from a failing
command and runs the reduction. Concretely: next time a 3000-line file breaks
something, you point this at it and get back the 20 lines that matter.

---

## 2. What "success" and "improvement" mean numerically

Fixed seeds; every run deterministic and re-runnable via `crux/bench/run.py`.

For reducer `R` on task `t`:

- `calls_t(R)` — number of **actual oracle executions** (cache hits recorded
  separately and not counted, since a cache hit costs nothing in the real
  cost model). This is the primary cost.
- `size_t(R)` — final output size in bytes. Also recorded in elements.
- **Validity gate**: the harness independently re-runs the oracle on the final
  output. A run whose output fails the oracle scores as a hard failure and the
  whole configuration is disqualified for that round. This is checked by the
  auditor subagent, not by the code that produced the result.

Normalised per task:

- `s_t(R) = (size_t(R) + 1) / (size*_t + 1)` where `size*_t` is the best size
  achieved by **any** method in the study, or the known optimum for synthetic
  tasks. `s = 1.0` means "matched the best anyone did".
- `c_t(R) = calls_t(R) / calls_t(ddmin)` using `picire` ddmin as the fixed
  reference denominator.

**Headline score** (lower is better):

```
E(R) = geomean over tasks of [ s_t(R)^2 * c_t(R) ]
```

Size is squared because a reducer that is fast and worse is useless; the
geometric mean keeps it scale-free and stops one huge task dominating. `E`,
`geomean s`, and `geomean c` are all reported separately every round, along
with the full per-task table — no single number is allowed to hide a
regression.

**Success criteria, stated before any code is written:**

- **Minimum bar**: `E(crux) < E(ProbDD)` and `E(crux) < E(ddmin)`, with
  `geomean s_t(crux) ≤ geomean s_t(ProbDD)` — i.e. fewer calls, not by
  giving up on size.
- **Target**: ≥ 2× fewer oracle calls than ProbDD at equal-or-better size
  (`geomean c ≤ 0.5 × c(ProbDD)`, `geomean s ≤ 1.05`).
- **Stretch**: beat `shrinkray` on calls at equal-or-better size on the shared
  real corpus, on identical oracles.
- **Anti-goal**: any improvement that comes from the reducer knowing something
  about the oracle it could not know in real use is cheating and gets thrown
  out. The auditor's standing job is to hunt for exactly this.

---

## 3. Delegation structure

Four subagents in `.claude/agents/`. The manager (main thread) never writes
implementation code; it writes LOG.md, decides the round, and routes work.

### `reducer-architect` — model: **opus**
Owns the algorithm. Reads the current scoreboard and per-task breakdown,
diagnoses *why* the current version loses calls where it loses them, and
returns a concrete spec (pseudocode + invariants + expected effect) for the
next change. Does not write production code.
*Why opus:* this is the one role where genuine novel insight is the
deliverable — connecting MUS theory to reduction, reading a failure profile
and inferring the structural cause. Low call volume, highest leverage per
call, so the expensive model is the cheap choice here.

### `reducer-engineer` — model: **sonnet**
Owns `crux/`. Implements the architect's spec, writes and maintains unit
tests, keeps the CLI and the baselines working, fixes what the auditor finds.
*Why sonnet:* high-volume, long editing sessions against a written spec, where
the deliverable is correct code that matches a specification rather than
invention. Best quality-per-cost at that volume; opus here would burn budget
on work that is specified, not discovered.

### `bench-runner` — model: **haiku**
Owns measurement. Runs `crux/bench/run.py` across every method and task,
verifies each output against its oracle, emits `results/roundN.json` and a
markdown table, and reports the headline numbers back. Never edits algorithm
code.
*Why haiku:* purely mechanical — invoke, parse JSON, format a table, report.
Run repeatedly per round, sometimes several times while debugging, so the
cheap fast model is exactly right and no capability is being wasted.

### `baseline-auditor` — model: **opus**
Adversarial QA. Standing brief: *assume the result is too good and find out
why.* Checks baselines against published pseudocode, checks the reducer has no
channel to oracle internals, independently re-verifies final outputs, hunts
for benchmark overfitting (e.g. constants tuned per task), and checks that
call counting is not undercounting.
*Why opus:* catching subtle self-deception — an accidentally-weakened baseline,
a leaked oracle detail, a metric that flatters — is adversarial reasoning
under ambiguity, the exact thing weaker models miss. It runs rarely, and one
missed cheat invalidates the entire run, so this is worth the strong model.

---

## 4. Rounds and definition of done

**Seven rounds (0–6).** One paragraph in `LOG.md` before each ("what I'm about
to try and why"), one after ("what happened, what the number came out to").

| Round | Focus | Exit condition |
|---|---|---|
| 0 | Harness, corpus import, all baselines wired, validity gate, first scoreboard | every baseline runs on every task; `E(ddmin)` recorded |
| 1 | Core: critical marking + progression + refinement | `E` beats ddmin; first honest comparison to ProbDD |
| 2 | Locality-smoothed deletability model driving candidate generation | `E` improves over round 1 |
| 3 | Multi-granularity fixpoint + structural chunking (lines/tokens/chars, bracket-aware) | `geomean s` approaches 1.0 |
| 4 | Architect's call, driven by where calls are actually being spent | `E` improves or the round is logged as a dead end with reasoning |
| 5 | Head-to-head vs. `shrinkray` on real oracles; fix what loses | honest head-to-head table published |
| 6 | Packaging: CLI hardening, Claude Code skill, docs, final measurement | tool runs end-to-end on a bug it has never seen |

**Done means:**
1. `E(crux)` beats every baseline, with `geomean s` no worse than ProbDD's — the
   minimum bar in §2, verified by the auditor on a clean re-run.
2. A per-task table published in SUMMARY.md including every task where crux
   *loses*, if any.
3. `crux --oracle X --input Y` works on a real bug outside the benchmark set.
4. The Claude Code skill is installed and demonstrated.

If the minimum bar is not met by round 6, SUMMARY.md says so plainly, reports
the real numbers, and states what the dead end was. A negative result written
up honestly is the outcome I will ship over a flattering one.
