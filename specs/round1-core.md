# Round 1 spec — CritScan: isolation-with-refinement search, at a fixed candidate space

Status: **revised after the coordinator's syntax-validity measurement.** §0 states what I
am retracting from the original thesis. Everything after §1 is the implementable spec.

Audience: `reducer-engineer` (implementation), `bench-runner` (measurement),
`baseline-auditor` (fairness). No design decisions are left open; where I had a choice
I made it and said why.

---

## §0. What I am retracting

The coordinator's measurement is correct and I reproduced it (§2). Three sentences of the
PLAN.md thesis do not survive it. I am withdrawing them rather than defending them.

| Original claim | Verdict |
|---|---|
| "`O(log\|S\|)` extra queries isolate an element that is **permanently critical** — it can never be deleted again, in any smaller context" | **Retracted.** Permanence requires monotonicity. Syntax and semantics both break monotonicity in the most elementary way (`{` is undeletable alone, deletable with `}`; a declaration is undeletable alone, deletable with its use). Marks are **context-scoped and revocable**, not permanent. |
| "it never needs to be re-tested for 1-minimality" → a free 1-minimality certificate | **Retracted.** We pay for the certificate with an explicit audit sweep, at the same cost as ddmin's final granularity pass (§5). The cache absorbs the part that has not gone stale; the residual is ~`k` real calls. |
| Implicit: the MUS port is unaffected by the candidate-space problem | **Never claimed, and it would be false.** §2 quantifies it. |

I am **not** retracting the core mechanism, and I disagree that the measurement kills it.
Reason, stated precisely so it can be checked rather than believed:

> **Every step of isolation-with-refinement uses only directly observed oracle answers.
> Monotonicity is needed *nowhere* in the search — only in the termination certificate.**

The window test, the binary split, and every deletion committed during a binary split are
each justified by a `True` that was actually observed on exactly the set being committed.
Replace the inferred certificate with a measured one (§5) and the search is sound under an
arbitrarily non-monotone oracle. What that costs is quantified in §6: the
monotonicity-dependent parts were worth about `2k` of a `k·log₂(n/k) + 3k` budget — roughly
**20% of the win, not the win.**

I also accept two framing corrections in full:

- **Grammar-free structural reduction is not a contribution.** Perses ships `dyck-brace`
  and `dyck-brace-parenthesis`. The structural layer in this spec (§3) exists only to make
  the search comparison meaningful, is the same idea as Perses's, and must be described
  that way in SUMMARY.md.
- **The claim is narrower than "MUS beats Perses".** Perses's contribution is the
  *candidate space*; its search inside that space is ddmin-family (its own defaults are
  `--default-list-minimizer-for-hdd CDD` and `--latra-transformation-list-minimizer
  WPROBDD`, and it exposes the list minimizer as a pluggable option — which is direct
  evidence that the two layers are separable *and that the vendor treats them that way*).
  The claim Round 1 tests is:

> **For a fixed candidate space, CritScan reaches a space-minimal output in fewer oracle
> calls than ddmin / CDD / ProbDD do in that same space.**

That is a strictly weaker claim than the original. It is also the one that composes: if it
holds, it drops into Perses's pluggable list-minimizer slot.

---

## §1. The two layers

| Layer | What it decides | Round 1 treatment |
|---|---|---|
| **Candidate space** `𝒟` | Which subsets are proposable at all. Determines what fraction of candidates are well-formed. | An explicit, **shared** experimental axis. Realized as a *decomposition of the input into elements*. Every reducer gets the identical element list. Not a contribution. |
| **Search** | Which subsets to try, in what order, and what to do with each answer. Determines queries-to-`𝒟`-minimal. | The Round 1 contribution. `CritScan`, §4. |

Because the space is realized as a decomposition, **no reducer needs any code change to run
in a different space** — `ddmin`, `CDD`, `ProbDD` and `CritScan` all already consume a list
of elements. This is what makes the cross product in §8 fair and cheap.

Definitions used throughout:

- `U` = the element list for a task at a given (granularity, space). `n = |U|`.
- `kept ⊆ U`, always rendered in original order.
- `O(kept) -> bool`, the only channel to the oracle.
- **`𝒟`-minimal**: no single element of the output can be deleted. With a union-closed
  decomposition (§3) this is the exact analogue of ddmin's 1-minimality, so the guarantee
  crux offers and the guarantee ddmin offers are the *same* guarantee, in the same space.
- `k` = `|output|`.

---

## §2. The measurements this spec is built on

Coordinator's numbers (432 trials, real parsers: `clang -fsyntax-only`, `ast.parse`,
`node --check`, `json.loads`), fraction of deletion candidates that parse:

| granularity | candidate shape | parses |
|---|---|---|
| line | scattered | 6.5% |
| line | contiguous chunk | 22.9% |
| char | scattered | 0.0% |
| char | contiguous chunk | 7.9% |

I re-derived these independently (seeded, same corpus, same parsers) and got line/contiguous
**20.1%**, char/contiguous **7.6%**. Confirmed.

All three measurement scripts are checked in and re-runnable:
`crux/bench/measure/syntax_candidate_rates.py` (the coordinator's, verbatim),
`crux/bench/measure/syntax_filter_rates.py` (tables a, b, d, e below),
`crux/bench/measure/syntax_filter_rates_followup.py` (tables c and d below).
Run them from the repo root; they need `clang`, `node`, `python3`.

I then measured the thing that decides the design — what a **free local structural filter**
does to those rates. Two filters, both grammar-free, both `O(n)`, both zero oracle calls:
Dyck balance over `()[]{}` with string/comment lexing, and Python indentation-suite safety.

**(a) Dyck-balance snapping, line granularity** (`balmeas.py`):

| | parses | notes |
|---|---|---|
| raw contiguous chunk | 20.1% | baseline |
| chunks that already pass the balance filter | **47.7%** | filter yield: 40.5% of raw chunks |
| arbitrary chunk snapped to its largest balanced sub-span | **39.7%** | a snap exists 97.3% of the time, retaining 68% of the proposed span |

**(b) Same, by language, line granularity, snapped:**

| | raw | snapped |
|---|---|---|
| `.js` | 4.2% | **95.8%** |
| `.json` | 70.8% | **83.3%** |
| `.py` | 32.3% | 34.8% |
| `.cpp` | 3.3% | 23.3% |

**(c) Python needs indentation, not brackets** (`balmeas2.py`, 168 trials):

| filter | parses |
|---|---|
| none | 44.0% |
| Dyck balance | 47.6% |
| **indentation-suite safety** | **83.9%** |
| both | **87.5%** |

**(d) What is left for C++ after balance-snapping** (117 candidates, first error bucketed):

| | share |
|---|---|
| compiles clean | 24.8% |
| **semantic error** (`use of undeclared identifier`, `unknown type name`, `no member named`, `no matching function`) | **64.1%** |
| syntax error | 11.1% |

**(e) Char granularity is not rescuable by any grammar-free filter:** 7.6% raw → 8.3%
filtered → 25.0% snapped (and snapping retains only 47% of the proposed span). A delimiter
filter cannot know that `retur` is not `return`.

### What these say

1. **The structural layer is language-shaped and cheap.** For brace languages a Dyck filter
   is nearly sufficient at line granularity (`.js` 4%→96%). For Python it does nothing and
   indentation does everything (44%→84%). Both are ~100 lines of code, zero oracle calls.
2. **C++'s residual is semantic, and no candidate space fixes it.** 64% of *structurally
   valid* C++ candidates fail on undeclared identifiers and missing members. Perses's
   parse-tree space removes the 11% syntax class and leaves the 64% semantic class
   untouched — this is precisely why C-Reduce needs `clang_delta`. Semantic failure is
   irreducible background noise that **every reducer eats equally**. A search that extracts
   more per query is worth *more* in that regime, not less, because the queries are
   expensive and mostly negative.
3. **Char granularity as a flat primary space is a trap.** ~92% of all queries from *every*
   reducer are garbage there. The char-granularity corpus cells measure something close to
   noise and must never carry a headline. (§8.)
4. **The "scattered candidates parse 3.5× worse" objection does not apply to this design.**
   `CritScan` issues **only contiguous spans of the current `kept` sequence** — main-loop
   windows, binary-split halves, and single elements (§4). It lives in the 22.9% column with
   ddmin, not the 6.5% column. **ProbDD** samples scattered subsets and *does* live in the
   6.5% column. On the candidate-shape axis this design ties ddmin and beats ProbDD. §11
   specifies the instrumentation that checks this rather than assuming it.

---

## §3. Candidate spaces (shared infrastructure, not the contribution)

Exactly two spaces in Round 1, plus Perses as an external reference.

### Space **F** — flat
`decompose(text, gran)` = lines (`keepends=True`) or characters. This is what Round 0
already has. No filter, no snapping.

### Space **D** — structured, grammar-free
`decompose(text, gran, lang)` returns a **partition of the text into disjoint spans
covering it**, such that **deleting any subset of units preserves structure**. Union-closure
is the required property; it is what makes `D` a plain element list that every reducer
consumes unchanged, with **zero candidate suppression** (§8 fairness rule).

**Space `D` is defined at LINE granularity only.** Char granularity runs in space F alone.
Reason: at char granularity there is no union-closed fine partition for comma/colon-separated
formats (deleting one item of `[a, b]` leaves `[, b]`), and §2(e) shows char granularity
carries no headline anyway. Do not bodge it; scope it out.

Three decomposers, dispatched on `meta.format`:

**D-dyck** (`cpp`, `c`, `js`, `ts`, `json`, `go`, `rust`, `java`, `css`) — *balanced-factor
partition over lines*:
```
lex the text once: for each offset, bracket depth over ()[]{}, and whether that offset is
inside a string / line comment / block comment (delimiters in those positions are ignored)
walk lines, accumulating:
    start a unit at line i with depth d = depth_at_start_of_line(i)
    extend through line j while depth_at_end_of_line(j) > d
    close the unit at the first j where depth returns to d and no delimiter is unmatched
    absorb a trailing separator line/`,`/`;` into the unit it follows
emit each accumulated line-run as one unit
```
So a line containing `void f() {` merges with every line through its matching `}` into a
single unit. Coarse, but correct.

**Union-closure proof.** Every unit is a *balanced factor* of the text: the delimiter word it
contributes reduces to the empty word. Balance is a homomorphism to the free group on
`{(,[,{}`, so removing any set of balanced factors leaves the remaining delimiter word
balanced. Trailing-separator absorption handles `[a, b]` → `[a]` rather than `[a, ]`.

**Accepted limitation, state it in the writeup.** This is HDD level 1: the interior of a
group is never independently deletable, so on inputs whose content lives inside one
top-level group (the deep-nested JSON tasks) space `D` has almost nothing to delete and will
score *worse on size* than space `F`. That is a true fact about single-level structural
reduction, not a defect of this spec — recursing into levels is exactly Round 3.

**D-suite** (`python`, `yaml`) — *whole statements including their suites*:
```
a unit is one logical line (continuations and bracket-spanning lines joined),
plus, if that line opens a suite (ends with ':'), the entire indented suite beneath it
```
Union-closure: deleting whole statements never orphans a suite and never changes the
indentation of a surviving line. (Deleting a *header* while keeping its body is **not**
union-closed — it needs re-indentation, which is a transformation, not a deletion. Out of
scope; Perses does it.)

**D-line** (`cnf`, and any format with no declared structure) — identical to space F.
The three CNF tasks (`minisat`, `kissat`, `splr`) have essentially no syntax gate, so
`F == D` for them. **These are the real-corpus tasks where the search comparison is
cleanest** and the closest real analogue of `hit-k-n`. Say so in the writeup.

### Rules that keep this honest

- **R3.1** The decomposer is called **once per task** and its output is handed identically
  to all four searches. Record `n_units` per (task, space) in the results JSON so the
  auditor can verify all four saw the same list.
- **R3.2** `CritScan` implements **no local filter of its own**. Its only structural
  knowledge is the element list it is handed. Any structure-aware behaviour must live in
  the decomposer where every baseline gets it too.
- **R3.3** Because every `D` decomposition is union-closed, **no reducer ever suppresses a
  candidate**. The harness must count suppressed-without-oracle-call events per reducer and
  assert it is 0 for all four. A nonzero count means the space is not union-closed and the
  comparison is compromised.
- **R3.4** No cross-space comparison appears in any headline. Every table cell is labelled
  `(space, search)`.

**Why a local structural filter is legitimate and not oracle introspection.** The reducer
reads *its own input file*, which it already holds in full. It learns nothing about the
oracle — not its internals, not its output beyond the boolean, not its timing. Choosing
"lines" as elements is already a structural assumption about text; `D` is the same kind of
assumption made better. C-Reduce (`clang_delta`), Perses (grammars, `dyck-brace`) and
shrinkray (tree-sitter, libcst) all do this. The thing that *would* be cheating is a
reducer whose behaviour depends on anything the oracle returns other than yes/no — and
R3.1–R3.3 make that auditable.

**Fairness note the auditor must enforce:** a structure-aware crux measured against
flat-text ProbDD is a strawman and must not be published. Note also the honest direction of
the effect: **space `D` helps ProbDD more than it helps crux**, because it repairs ProbDD's
single largest liability (scattered candidates) while crux was already contiguous. The `D`
row is therefore the *harder* cell for us, and it is the one the headline claim rests on.

---

## §4. The algorithm — `CritScan`

Interface, exactly as required:

```python
def reduce(problem, kept: tuple[int, ...], *, state: CritState | None = None) -> tuple[int, ...]
```

`problem.oracle(kept) -> bool` is the only oracle channel. `kept` is a **sorted tuple of
element indices into `U`**. Precondition: the driver has already observed `O(kept) == True`
(it does this as task setup). Postcondition: the returned tuple either **is** `kept`
unchanged, or is a set this call observed `True`. There is no third case — see **I1**.

### 4.1 State

```python
@dataclass
class CritState:
    marks:     set[int]        = field(default_factory=set)   # element ids currently blocked
    ctx_size:  dict[int, int]  = field(default_factory=dict)  # |kept| when the mark was made
    universe:  frozenset[int] | None = None                   # kept at the previous call

    def rebase(self, kept):
        ks = set(kept)
        if self.universe is not None and not ks <= self.universe:
            self.marks.clear(); self.ctx_size.clear()   # kept GREW -> every mark is void
        self.marks &= ks
        self.ctx_size = {c: v for c, v in self.ctx_size.items() if c in self.marks}
        self.universe = frozenset(ks)
```

A **mark** is not a claim of permanence. It is the recorded fact *"at a context of size
`ctx_size[c]`, deleting `c` alone was observed to fail"*, with provenance. §5 says what is
and is not licensed by it.

### 4.2 Main loop

```python
def next_mark_position(kept, marks, cursor):
    """First index >= cursor whose element is marked, else len(kept).
       By I3 this is len(kept) on every call within a single pass; it matters only when
       the driver threads a state in. Keep it O(1) amortised with a cached scan pointer."""
    i = cursor
    while i < len(kept) and kept[i] not in marks:
        i += 1
    return i

def reduce(problem, kept, *, state=None):
    kept = list(kept)                       # sorted element ids
    st   = state or CritState()
    st.rebase(kept)

    cursor = 0
    while cursor < len(kept) and kept[cursor] in st.marks:
        cursor += 1                         # resume a threaded state for free
    w = max(1, len(kept) - cursor)          # first window = everything still unsettled

    while cursor < len(kept):
        # --- clamp: never propose a window that contains an already-marked element
        limit = next_mark_position(kept, st.marks, cursor) - cursor   # len(kept)-cursor if none
        if limit == 0:                      # kept[cursor] is marked; settle it for free
            cursor += 1
            continue
        w = max(1, min(w, limit))
        lo, hi = cursor, cursor + w

        cand = tuple(kept[:lo] + kept[hi:])
        if problem.oracle(cand):            # the whole window is deletable
            del kept[lo:hi]                 # REFINEMENT: commit the tested set wholesale
            w = w * 2                       # grow
        elif w == 1:
            st.marks.add(kept[cursor]); st.ctx_size[kept[cursor]] = len(kept)
            cursor += 1                     # w stays 1: neighbours are probably blocked too
        else:
            kept, pos = isolate(problem, kept, lo, hi)
            st.marks.add(kept[pos]); st.ctx_size[kept[pos]] = len(kept)
            cursor = pos + 1
            w = max(1, w // 2)              # shrink

    kept = audit(problem, kept, st)         # §5 — this is where soundness is bought
    return tuple(kept)
```

### 4.3 `isolate` — the mechanism

This is the Round 1 contribution in ten lines. **The load-bearing detail is that a clean
left half is deleted immediately, inside the search, rather than being discarded when the
search returns.** A textbook QuickXplain/`ddmin`-style implementation treats isolation as a
read-only diagnosis and keeps only the single-element conclusion; that throws away roughly
half the pool per isolation. Getting this wrong silently costs ~`k` queries per pass and is
the single most likely implementation error in this spec.

```python
def isolate(problem, kept, lo, hi):
    """PRE:  problem.oracle(kept minus kept[lo:hi]) was observed False.
       POST: kept[lo] is blocked at the current context; every element that was in
             [lo,hi) and lay to the left of it has been deleted.
       COST: exactly ceil(log2(hi-lo)) oracle calls."""
    while hi - lo > 1:
        mid  = lo + (hi - lo) // 2                 # A = [lo,mid)   B = [mid,hi)
        cand = tuple(kept[:lo] + kept[mid:])       # delete A only
        if problem.oracle(cand):                   # A is clean
            del kept[lo:mid]                       # commit it  <-- the refinement
            hi -= (mid - lo)                       # B now occupies [lo, hi)
        else:                                      # A blocks; B untouched, still unsettled
            hi = mid
    return kept, lo
```

Both branches preserve the precondition on the new `[lo,hi)`:
- clean branch — the element set `kept_new \ kept_new[lo:hi)` is *the same set* as
  `kept_old \ kept_old[lo:hi_old)`, whose `False` was observed;
- blocked branch — `O(kept \ kept[lo:mid))` was just observed `False`.

At exit `hi-lo == 1`, so `O(kept) == True` and `O(kept \ {kept[lo]}) == False` are both
observed facts at the *current* context. **No monotonicity was used.**

### 4.4 Window sizing — how a candidate is chosen with no probability model

Round 2 replaces this with the locality-smoothed model. Round 1 uses a parameter-free
multiplicative controller and nothing else:

| event | new `w` |
|---|---|
| initial | `len(kept) - cursor` (the whole unsettled suffix) |
| window deleted (success) | `2w` |
| window blocked, `w > 1` (after `isolate`) | `max(1, w // 2)` |
| window blocked, `w == 1` | `1` |
| every iteration, before proposing | clamped to `[1, limit]` |

Why these:

- **Start at the whole suffix.** The first query is `O(∅)`. It costs exactly one call and
  buys the degenerate case (everything deletable → return `()` immediately). The isolation
  that follows a `False` is a binary search over the whole file that finds the first
  blocking element *and deletes everything before it*, in `⌈log₂ n⌉` calls. This is the
  strongest opening available and it needs no constant. Starting at `n/2` saves that one
  call and loses the degenerate case; not worth a special case.
- **Multiplicative both ways.** The controller's fixed point is `w ≈ n/k`, the mean spacing
  between blocking elements — which is exactly Hwang's optimal pool size `⌊log₂((n-d+1)/d)⌋`
  for group testing with `d` defectives, arrived at without knowing `d` and without a model.
- **Stay at 1 after a singleton failure.** Blocking elements cluster; re-growing after each
  one costs a failed query per step. The cost of this choice is a `log₂` re-ramp on leaving
  a cluster. **This is a known inefficiency and it is Round 2's target** — do not invent a
  fix for it in Round 1, it would destroy attribution.

**There are no other constants in the search.** No randomness anywhere: Round 1 is
bit-for-bit deterministic without a seed.

### 4.5 What is deliberately NOT in Round 1

- **No deduction rule** ("skip querying any set that omits a marked element"). It relies on
  monotonicity, and the clamp in §4.2 means it would never fire anyway. Deferred to Round 3,
  where granularity switches make it valuable — and where it will need the §5 machinery.
- **No probability model** (Round 2). **No multi-granularity** (Round 3). **No structural
  knowledge inside the search** (R3.2).

---

## §5. Soundness and criticality under non-monotonicity

### 5.1 Where each step relies on monotonicity

| step | relies on monotonicity? | if the oracle is non-monotone |
|---|---|---|
| delete a window on success | **no** — direct observation of the exact committed set | nothing |
| delete a clean half inside `isolate` | **no** — same | nothing |
| recurse into `B` after deleting `A` | **no** — the surviving precondition is the same element set whose `False` was observed | nothing |
| mark `kept[lo]` at the current context | **no** for the fact; **yes** for carrying it forward | the mark may become wrong later |
| clamp windows away from marked elements | **yes** | a deletable element is skipped → output inflates |
| terminate when `cursor == len(kept)` | **yes** | termination is premature → output inflates |
| **the returned value** | **no** | nothing — see I1 |

**Soundness of the return value never depends on monotonicity.** `kept` is only ever
assigned immediately after `problem.oracle` returned `True` on exactly that set (I1). The
validity gate cannot fail.

### 5.2 What a wrong mark does, and why it is absorbing without §5.3

`{` is blocked alone and deletable with `}`. `int foo();` is blocked alone and deletable
with its call site. Both produce a mark that is true *now* and false *later*. Left alone:
(i) the output is not `𝒟`-minimal; (ii) the clamp suppresses the query that would have
found it; (iii) the loop terminates with `marks == kept`, so **a second call to `reduce`
returns immediately and can never recover**. A wrong mark is an absorbing state. That is
the whole argument for §5.3 being mandatory rather than optional.

### 5.3 Revocation — the audit sweep

```python
def audit(problem, kept, st):
    """Turn every inferred mark into a measured one. Cost bound: see below."""
    while True:
        order = sorted(kept, key=lambda c: (-(st.ctx_size.get(c, 0) - len(kept)), c))
        alive = set(kept)
        reversed_any = False
        i = 0
        while i < len(order):
            c = order[i]
            if c not in alive:                     # removed by an earlier reversal
                i += 1; continue
            cand = tuple(x for x in kept if x != c)
            if problem.oracle(cand):               # the mark was WRONG
                kept = list(cand); alive.discard(c)
                st.marks.discard(c); st.ctx_size.pop(c, None)
                reversed_any = True
                # non-monotonicity is spatially local (a brace's partner, a decl's use):
                # re-order the untested remainder nearest-first around the reversal site
                order = order[:i+1] + sorted(order[i+1:], key=lambda x: (abs(x - c), x))
            else:
                st.ctx_size[c] = len(kept)         # refresh: this mark is now measured
            i += 1
        if not reversed_any:
            return kept
```

Properties:

- **The guarantee it delivers is exactly ddmin's**: on return, every element of the output
  has been observed undeletable **at the returned context**. `𝒟`-minimality is *measured*,
  not inferred. Neither ddmin nor crux detects joint co-deletions (`{`+`}` when neither was
  ever removed); the structural space `D` is what handles those, for both of them, equally.
- **Cost.** A mark with `ctx_size[c] == len(kept)` re-issues a query the harness cache
  already holds → **0 real oracle calls**. The real cost per sweep is the number of marks
  whose context changed, `≤ k`; `sweeps ≤ reversals + 1` and `reversals ≤ k`, so the honest
  worst case is `O(k²)` and the expected case is `k + O(reversals)`. This is exactly the
  cost structure of ddmin's final granularity pass, which also re-sweeps after every
  success — we are not paying more than the incumbent for the same guarantee. On a monotone
  oracle: exactly `k` real calls, `0` reversals, one sweep — **a unit-test assertion, not a
  hope** (test 3, §11).
- **If `audit_calls` ever exceeds `main_loop_calls` on the real corpus, report it loudly.**
  It would mean the endgame, not the midgame, dominates — and the midgame is the entire
  contribution. §11 records both separately for exactly this reason.
- **The audit must bypass any future deduction rule.** It exists to contradict marks; a
  rule that answers from marks makes it vacuous. Written here because it is the exact
  mistake an implementer will make in Round 3.
- Ordering is by **staleness descending** (earliest-marked first), because those are the
  marks most context has moved under, and an early reversal makes every remaining mark
  staler, which is what we want to discover.

### 5.4 Answer to "does MUS-style search need structural awareness to be viable?"

**It needs it exactly as much as ddmin does, and less than ProbDD does. Not more.**

Grounded in §2: the search's candidates are contiguous (22.9% / 20.1% column). ddmin's are
contiguous. ProbDD's are scattered (6.5% column). The non-monotonicity that wrong marks come
from is the *same* phenomenon that makes a candidate fail to parse, and it hits ddmin's
1-minimality termination and crux's mark-based termination identically — the difference is
that crux's is inferred and must be converted to measured (§5.3), which costs `k` calls, the
same `k` calls ddmin already spends.

**Falsifiable form of that answer**, to be checked in Round 1:

> In space **F** at line granularity, crux and ddmin will produce outputs within **±10% in
> size** on **≥ 80%** of real-corpus tasks (both stall at the same structural barrier),
> while crux uses **35–65%** of ddmin's calls. If instead crux's space-F output is **>25%
> larger** than ddmin's on **≥ 1/3** of tasks, the marking machinery is actively harmful on
> flat text and §5.3 is failing to recover — that falsifies my soundness design (not the
> search), and the fix is to widen the audit, not to abandon the round.

There is no mechanism by which this design "sidesteps" the syntax problem, and I am not
claiming one. What it does is (a) not make it worse by generating scattered candidates, and
(b) extract more per query in a regime where queries are mostly negative.

---

## §6. Query complexity

Model: `n` elements, `k` blocking elements (the output size), monotone oracle, elements
roughly uniformly spread. This is exactly **adaptive group testing**: the query
`O(kept \ P)` returns `False` iff pool `P` contains a defective. `CritScan` is Hwang's
Generalized Binary Splitting with the pool size discovered by a controller instead of
computed from a known `d`.

**Accounting (exact, not asymptotic).** Every iteration either deletes `≥ 1` element or
advances `cursor` by `≥ 1`, and the potential `len(kept) - cursor` strictly decreases, so:

- **blocked events** = `k` (each marks exactly one element), each costing `1 + ⌈log₂ w⌉`;
- **successful deletions** `≤ n - k`, each costing `1`;
- **audit** = `k` real calls on a monotone oracle.

**Hard worst case:** `(n − k) + k·(1 + ⌈log₂ n⌉)` for the search, plus `O(k²)` for the audit
if every sweep reverses — `O(n + k log n + k²)` overall. Note `k ≤ n`, so this is never worse
than ddmin's `O(n²)`, and the `k²` term only materialises on an oracle so non-monotone that
ddmin's own final-pass re-sweeping degrades identically.
**Equilibrium (`w → n/k`), monotone oracle:** `k·(log₂(n/k) + 4)`, of which `+k` is the audit.

| | queries |
|---|---|
| information-theoretic lower bound, `log₂ C(n,k)` | `k·log₂(n/k) + 1.44k` |
| **CritScan (model)** | **`k·(log₂(n/k) + 4)`** |
| Hwang GBS with `d` known | `k·log₂(n/k) + O(k)` |
| ddmin | `O(n²)` worst; in practice dominated by `Σ_g g` over granularity levels plus a re-sweep after every success |
| ProbDD / CDD | heuristic; published gains over ddmin are ~30–60% fewer tests, and FSE'24 showed CDD matches ProbDD — i.e. `c ≈ 0.4–0.7` |

So the model is within `≈2.6k` of the information-theoretic optimum, and the ratio → 1 as
`n/k → ∞`. **This also bounds what Rounds 2–3 can add**: on the pure hidden-set model there
is almost nothing left, so their wins must come from structure (locality, granularity) that
the pure model does not capture. Worth knowing before spending two rounds on it.

**Where the win is largest:** `n/k` large. Sparse tasks — `black` (3124 chars → 17),
`prettier` (1687 → 4), `minisat` (2326 → 14) — and the synthetic families at `n ≥ 10⁴`.
**Where it is smallest:** `n/k → 1`. `kissat` (427 lines → 184) and `splr` (162 → 26) are
the dense real tasks; there `log₂(n/k) ≈ 1` and the model degenerates to `≈ 5k ≈ n`, versus
ddmin's `≈ 2n`. Still a win, but ~2× not ~5×.

**Where it loses to ddmin — three regimes, stated in advance:**

1. **Backward-dependency chains.** If `eᵢ` requires `eᵢ₋₁`, then *deleting* any contiguous
   run orphans the element after it, so every window fails and everything is marked. ddmin
   also tests **subsets** (keep chunk `i` alone), and keeping a *prefix* satisfies every
   backward dependency — so ddmin reduces and crux does not. Crux's left-to-right complement
   scan covers suffix-keeping, not prefix-keeping. **Expect to lose the `chain` family on
   size.** The fix is a direction-alternating pass; it is not in Round 1 because it would
   blur attribution.
2. **Huge binary-aligned deletable blocks with `k = O(1)`.** ddmin's granularity-2
   complement test removes half the file in one query. Crux's opening does the same thing
   via `O(∅)` + isolation, paying one extra call. A tie, with a constant against us.
3. **Cache asymmetry.** ddmin re-tests heavily, so the shared cache deflates its counted
   calls substantially. Crux's scan almost never repeats a query, so the cache saves it
   almost nothing. **The measured `c` is against a cache-deflated denominator**, which is
   the harder comparison; report crux's cache hit rate (expected near 0) alongside ddmin's
   (expected high) so this is visible rather than mysterious.

---

## §7. Invariants for the implementation

Assert these in a debug mode; the auditor will look for them.

- **I1 (soundness — non-negotiable).** `kept` is assigned only by `del kept[i:j]`
  immediately after `problem.oracle` returned `True` on exactly `kept[:i] + kept[j:]`, or by
  the audit's `kept = list(cand)` immediately after `True` on `cand`. **There is no other
  assignment to `kept` anywhere.** Grep for it in review.
- **I2.** `kept` is strictly increasing (sorted, deduplicated) at all times, and is a subset
  of the incoming `kept`, which is a subset of `U`.
- **I3.** `set(kept[:cursor]) == st.marks ∩ set(kept)` at every loop head. Equivalently, all
  marks lie before the cursor and everything before the cursor is marked.
- **I4.** Every proposed window `[lo,hi)` contains no marked element (the §4.2 clamp). With
  I3 this is automatic; assert it anyway — it is what makes the deduction rule unnecessary
  in Round 1 and proves no query is spent on a set already known dead.
- **I5 (termination).** `len(kept) - cursor` strictly decreases every main-loop iteration.
- **I6 (mark provenance).** Every `c ∈ st.marks` has `st.ctx_size[c]` set, and
  `st.ctx_size[c] ≥ len(kept)` always (context only shrinks).
- **I7 (cross-call survival).** Marks survive a later call to `reduce` **only** if the
  incoming `kept ⊆ st.universe`. If `kept` grew — a granularity switch that re-expands, any
  external edit — `rebase` clears every mark. Criticality is scoped to a shrinking chain of
  contexts; this is the invariant that Round 3 will lean on hardest.
- **I8 (space scoping).** Marks are keyed to `(task, granularity, space)`. A state object
  from one space must never be handed to another. Enforce with an id field.
- **I9 (cache key).** The cache is **owned by the harness** (`crux/crux/core.py::Oracle`),
  not by crux, and the current key is `frozenset(kept)` — element ids. That is fine and I am
  not asking for a change: what matters is only that it is **identical for all four
  searches** and that `calls` counts misses only, both of which already hold. Note for the
  writeup that an id-set key (rather than a rendered-bytes key) slightly *understates* every
  reducer's cache benefit, and understates ddmin's most — so it makes our denominator
  larger, i.e. it flatters us. Say so rather than let the auditor find it.
  Crux must not maintain a private cache; its call accounting comes from `oracle.calls`.
- **I10 (budget / totality).** The harness `Oracle` already swallows exceptions as `False`,
  so crux's first query `O(∅)` is safe. But it also raises **`BudgetExhausted`** when
  `calls >= budget`. **`reduce` must catch `BudgetExhausted` and return `problem.oracle.best`**
  (the smallest set ever observed `True`), which preserves I1 exactly. Wrap the whole body:
  ```python
  try:
      ...main loop...; kept = audit(problem, kept, st)
  except BudgetExhausted:
      return problem.oracle.best if problem.oracle.best is not None else tuple(kept_on_entry)
  return tuple(kept)
  ```
  This matters: §2 flags `jq` (120 KB) and `python-rapidjson` (200 KB) at char granularity as
  tasks that will hit any budget. **If a budget truncates a task, it must truncate identically
  for all four searches, and the task must be marked truncated in the results JSON** — a
  truncated `c` is not a call-efficiency measurement and must not enter the geomean silently.
- **I11 (fairness).** `suppressed_without_call` is 0 for every reducer (R3.3).

**Idempotence test:** `reduce(problem, reduce(problem, x))` must return the same tuple and
cost **0 real oracle calls** on a monotone oracle (every audit query is a cache hit). This
is a strong single test of I3, I6, I7 and I9 together.

**Performance note.** Every deletion is a contiguous slice of `kept` (`del kept[i:j]`), which
is a C-level memmove. Do not rebuild `kept` with a comprehension over a set — on the 200 KB
`rapidjson` task at char granularity that is the difference between seconds and minutes.
Building the candidate tuple is unavoidably `O(n)` per call.

---

## §8. Experimental design — isolating the contribution

The cross product, and which cells to run:

| | ddmin (picire) | CDD | ProbDD | **CritScan** |
|---|---|---|---|---|
| **F — flat**, line | run | run | run | run |
| **F — flat**, char | run | run | skip (see below) | run |
| **D — structured**, line | run | run | run | run |
| **D — structured**, char | not defined (§3) | — | — | — |
| **P — parse tree** | Perses default (its list-minimizer *is* CDD) | — | Perses `WPROBDD` | not in Round 1 |

- **Row F is the mandatory minimum.** It requires no new harness machinery and it is the
  clean attribution cell for the search: nothing structural is in play, everyone sees the
  same element list, the only difference is what each does with an answer. **The kill
  criterion is evaluated here and on the synthetics.**
- **Row D is what the contribution claim rests on**, because it is the realistic operating
  point and it is the cell that predicts what happens if the search is dropped into
  Perses's pluggable slot. It is also the *harder* cell for us (§3: `D` repairs ProbDD's
  liability and leaves ours unchanged).
- **Row P: run Perses as an external reference point only.** Report its calls and size next
  to ours; do **not** build an attribution claim on it, because we cannot put our search
  inside it in Round 1. Perses vs crux is a *space+search* comparison and must be labelled
  as such.
- **Cells not worth running:** ProbDD in space F at char granularity (0.0% of its scattered
  candidates parse — it is measuring nothing); Perses on `cnf`/`css` (unsupported); any
  cross-row cell presented as a like-for-like.

**What makes the contribution real vs illusory.**

| observation | reading |
|---|---|
| `c(crux) < c(ddmin)` and `c(crux) < c(ProbDD)` **in the same row**, with `s` within 5% | **Real.** The search wins at fixed candidate space. |
| crux wins only across rows (crux-D vs ddmin-F) | **Illusory.** That is the strawman; do not ship it. |
| crux wins on `c` but `s(crux) ≈ s(ddmin)` and both are far from best-known | **"Gives up faster", not better.** Pre-registered hazard (§9). `E = s²·c` already absorbs most of this because `s` is normalised to best-of-all-methods, so both reducers score badly — check that it does. |
| space `D` improves everyone's `s` a lot and compresses the `c` gap | **Expected**, and it is the honest result: the space matters more than the search on this corpus. Say so. |
| `E(crux, D) < E(everything, D)` and `ρ ≤ 2.5` on synthetics | **The claim holds.** |

**Reporting requirements (auditor-enforced):** every cell labelled `(space, search,
granularity)`; `E`, `geomean s`, `geomean c` reported **split by granularity** (never a
single geomean spanning line and char — §2 item 3); per-reducer candidate-shape statistics
(§11); `n_units` per (task, space); cache hit rates; `suppressed_without_call == 0`.

---

## §9. Predictions

Falsifiable, per cell. `c` is calls relative to picire ddmin **in the same space and
granularity**.

| cell | predicted `geomean c` | predicted `s` vs ddmin (same space) |
|---|---|---|
| synthetic `hit-k-n` uniform, `n ≥ 4096`, `n/k ≥ 32` | **0.10 – 0.25** | tie (both reach optimum) |
| synthetic `hit-k-n` clustered | 0.08 – 0.25 | tie |
| synthetic `hit-k-n` adversarial | 0.30 – 0.60 | tie |
| synthetic `blocks` | 0.10 – 0.30 | tie |
| synthetic `nest` | 0.40 – 0.80 | **tie, both near-zero reduction** — pre-registered non-win |
| synthetic `chain` (backward deps) | 0.4 – 0.9 | **crux worse, up to 2–5×** — pre-registered loss |
| real corpus, CNF tasks (no syntax gate) | **0.15 – 0.40** | tie ±5% |
| real corpus, space **F**, line | 0.35 – 0.65 | tie ±10% on ≥80% of tasks (§5.4) |
| real corpus, space **D**, line | **0.25 – 0.55** | ≤ 1.05× ddmin |
| real corpus, char, space **F** (D undefined there) | 0.40 – 0.80, high variance | noisy; do not lean on |

Headline predictions:

- **`geomean c(crux) ≈ 0.35`**, range **0.25 – 0.55**, across all reported cells.
  (This is deliberately more conservative than the 0.25 I would have written before the
  measurement; the audit sweep and the coarser `D` element lists both eat into it.)
- **`geomean s(crux) ≤ 1.05 × geomean s(ddmin)`** in the same space.
- **`E(crux) ∈ [0.30, 0.60] × E(ddmin)`** in the same space.
- **`c(crux) / c(ProbDD) ∈ [0.45, 0.80]`** in space F, and **`[0.50, 0.85]`** in space D —
  *narrower in the fair cell*, because `D` removes ProbDD's scattered-candidate handicap.
  I expect Round 1 alone to fall **short** of the project's `≤ 0.5 × ProbDD` target; Round 2
  is what should close it.
- **Space `D` will improve `geomean s` for every reducer by more than the search improves
  `c`.** If that is what the table says, it is the honest headline of Round 1 and it should
  be written that way even though it is not the result I would prefer.

Where I expect to lose: `chain`, `nest`, and any Python task in space F (§2c: the Dyck
intuition does nothing for Python, so space F Python is indentation-broken for everyone and
space D is where Python becomes measurable).

---

## §10. Kill criterion

**Primary — one measurement, on the mechanism's home turf.**

The load-bearing prediction is `calls ≈ k·(log₂(n/k) + 4)`. Measure

```
ρ = actual_calls / (k · (log2(n/k) + 4))
```

on **synthetic `hit-k-n` uniform, monotone oracle, no syntax gate, `n ≥ 4096`, `n/k ≥ 32`,
`k` known by construction.** Every confound is removed: no candidate space, no
non-monotonicity, no unknown optimum.

> **If `ρ > 2.5` on that family, abandon Round 1.** The mechanism does not work as
> theorised, and neither Round 2's probability model nor Round 3's granularity machinery can
> repair a broken core. Run this family **first**, before the real corpus — it costs minutes
> and it gates everything else.

**Secondary — redirect, not kill.** If `ρ ≤ 2.5` but `geomean c ≥ 0.85` on the real corpus
in space D at line granularity: the mechanism works, real inputs simply lack the structure
it exploits. That is a signal to move to Rounds 2–3, not to nurse Round 1.

**Tertiary — honesty gate.** If crux's `E` advantage comes with `s(crux) ≈ s(ddmin)` and
both far from best-known on more than half the tasks, the round must be logged as **"crux
gives up faster"**, not as a win.

**Soundness gate (immediate disqualification, not a kill criterion).** Any run whose output
fails the independent re-verification. I1 makes this impossible by construction; if it
happens, the bug is in I1 and nothing else may be reported until it is found.

---

## §11. Instrumentation and test checklist

**Per (task, space, granularity, search), record:** `n_units`, `k` (output size), total real
calls, cache hits, and for crux additionally: calls in the main loop / in `isolate` / in the
audit; marks made; audit reversals; window successes and failures; mean and max `w` at
success; elements deleted by window successes vs **elements deleted inside `isolate`** (the
refinement dividend — if this is near zero, §4.3 was implemented wrong); `ρ`.

**Per reducer, record for the fairness check:** fraction of issued candidates whose deleted
set is contiguous in the current `kept`; mean candidate size as a fraction of `kept`;
`suppressed_without_call` (must be 0).

**Unit tests the engineer must write:**

1. `isolate` costs exactly `⌈log₂(hi−lo)⌉` calls on a synthetic oracle; a counter asserts it.
2. `isolate` deletes every element of the window left of the blocking element — assert on a
   hand-built case, since this is the detail most likely to be dropped.
3. Monotone `hit-k-n`: output equals the planted set exactly; audit does exactly `k` real
   calls and `0` reversals.
4. Idempotence: `reduce(reduce(x))` returns the same tuple at **0** real calls (§7).
5. Non-monotone bracket oracle (`{`/`}` must be deleted together): the audit produces at
   least one reversal and the output is not larger than ddmin's on the same input.
6. `O(∅) == True` degenerate case returns `()`.
7. I1 by construction: a fuzz harness that flips the oracle to `False` at random points and
   asserts the returned set always re-verifies `True`.
8. State threading: mark a run, truncate `kept` externally, re-enter — `rebase` must clear
   marks when `kept` grew and keep them when it shrank (I7).
9. Union-closure of each `D` decomposer: for random subsets of units, assert the rendered
   text still parses with the real parser. **This is the test that protects R3.3** and it is
   the one that will catch decomposer bugs before they contaminate every cell.
