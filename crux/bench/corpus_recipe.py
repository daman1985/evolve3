"""The one uniform recipe that turns a corpus/<entry>/ directory into a
cheap, in-process oracle predicate -- shared by the in-process tasks
(tasks.py) and the external-tool entry point (external_entry.py) so that
Perses (and later shrinkray), which can only be driven through a real
subprocess/file, are checked against EXACTLY the same predicate our own
methods are, not a re-derived approximation of it.

No per-entry special cases: every entry goes through the same formulas
below, branching only on data availability (does a reduced reference
exist?) and on the small, closed set of `format` values seen in meta.json,
never on entry identity.

This module is bench-only (not shipped in crux/crux/): it may use anything
already installed.
"""
from __future__ import annotations

import ast
import json
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

__all__ = [
    "CorpusRecipe",
    "TOKEN_RE",
    "compute_recipe",
    "make_predicate",
    "max_depth",
    "structurally_valid",
    "token_counts",
]

# One regex tokenizer for everything, per this round's spec: identifiers /
# numbers as runs, and every other non-space character as its own
# single-character token (so e.g. "{", "}", "," are each one "significant
# token"). Whitespace is dropped by simply not being matched.
TOKEN_RE = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|[^\sA-Za-z0-9_]")

_OPEN = "([{"
_CLOSE = ")]}"
_MATCH_OPEN = {")": "(", "]": "[", "}": "{"}

_PYTHON_FORMATS = {"python"}
_CNF_FORMATS = {"cnf"}
# Every other observed format (c, cpp, go, javascript, typescript, rust,
# css, json, ...) falls back to the cheap balanced-delimiter check -- see
# structurally_valid() below.


def token_counts(text: str) -> Counter:
    return Counter(TOKEN_RE.findall(text))


def _iter_unquoted(text: str):
    """Yield characters outside single/double-quoted string or char
    literals. A single generic quote-toggling state machine (with
    backslash-escape handling) is the "cheap" approximation called for --
    not a real per-language lexer (no triple-quotes, raw strings, etc.),
    applied uniformly to every format."""
    in_str = None
    escape = False
    for ch in text:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"'):
            in_str = ch
            continue
        yield ch


def max_depth(text: str) -> int:
    """Maximum bracket-nesting depth, format-agnostic, ignoring bracket
    characters inside cheaply-detected string/char literals. An unmatched
    closing bracket never drives depth negative (clamped at 0) -- this is
    a cheap structural signal, not a parser."""
    depth = 0
    best = 0
    for ch in _iter_unquoted(text):
        if ch in _OPEN:
            depth += 1
            best = max(best, depth)
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
    return best


def _balanced_brackets(text: str) -> bool:
    stack: list[str] = []
    for ch in _iter_unquoted(text):
        if ch in _OPEN:
            stack.append(ch)
        elif ch in _CLOSE:
            if not stack or _MATCH_OPEN[ch] != stack[-1]:
                return False
            stack.pop()
    return not stack


_CNF_HEADER_RE = re.compile(r"^p\s+cnf\s+\d+\s+\d+$")
_CNF_INT_RE = re.compile(r"^-?\d+$")


def _cnf_valid(text: str) -> bool:
    """Non-empty, and every non-comment line well-formed: a `p cnf V C`
    header, or whitespace-separated integers (DIMACS literals / the
    trailing 0). Cheap: no cross-line clause-completion tracking."""
    if not text.strip():
        return False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("c"):
            continue
        if s.startswith("p"):
            if not _CNF_HEADER_RE.match(s):
                return False
            continue
        for tok in s.split():
            if not _CNF_INT_RE.match(tok):
                return False
    return True


def structurally_valid(text: str, fmt: str) -> bool:
    if fmt in _PYTHON_FORMATS:
        try:
            ast.parse(text)
            return True
        except SyntaxError as e:
            # CPython's own parser has a hardcoded nesting ceiling (currently
            # 200 levels of bracket/block nesting -- CPython Parser/pegen.c
            # MAXLEVEL, not affected by sys.setrecursionlimit) and refuses
            # to parse anything past it, regardless of whether the code is
            # otherwise well-formed. One corpus entry
            # (shrinkray-libcst-deep-nesting) is *specifically* a
            # deep-nesting stress case whose original AND reference both
            # exceed that ceiling (~400 levels) -- i.e. every file this
            # task could ever consider "correct" is already unparseable by
            # ast.parse, independent of the reduction quality being
            # measured. Falling back to the same cheap balanced-delimiter
            # check every other bracket-based format uses keeps the
            # ceiling from masquerading as a real syntax error, without
            # weakening ast.parse's role as the real check for genuine
            # python syntax errors (message text is CPython's own, stable
            # across versions; anything else still fails as before).
            if "too many nested" in str(e):
                return _balanced_brackets(text)
            return False
        except Exception:
            return False
    if fmt in _CNF_FORMATS:
        return _cnf_valid(text)
    # c/cpp/js/ts/go/rust/css/json, and any other bracket-delimited
    # format: cheap balanced-delimiter check only (deliberately NOT
    # json.loads for json -- see module docstring / round-0 report: a
    # strict parse would make almost every deletion invalid and leave no
    # headroom to reduce).
    return _balanced_brackets(text)


@dataclass(frozen=True)
class CorpusRecipe:
    entry: str
    fmt: str
    required: dict  # token -> minimum required count
    ref_depth: int
    original_path: Path
    reference_path: Optional[Path]
    used_fallback: bool  # True if no shrinkray/creduce reduced reference existed


def _reference_path(entry_dir: Path) -> Optional[Path]:
    shrinkray = sorted(entry_dir.glob("shrinkray_reduced.*"))
    if shrinkray:
        return shrinkray[0]
    creduce = sorted(entry_dir.glob("creduce_reduced.*"))
    if creduce:
        return creduce[0]
    return None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="surrogateescape")


def compute_recipe(entry_dir: Path) -> CorpusRecipe:
    entry_dir = Path(entry_dir)
    entry = entry_dir.name
    meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
    fmt = meta["format"]

    originals = sorted(entry_dir.glob("original.*"))
    if not originals:
        raise FileNotFoundError(f"no original.* in {entry_dir}")
    original_path = originals[0]
    original_text = _read_text(original_path)

    reference_path = _reference_path(entry_dir)

    if reference_path is not None:
        reference_text = _read_text(reference_path)
        o_counts = token_counts(original_text)
        r_counts = token_counts(reference_text)
        # REQUIRED = R's token multiset intersected with O's (each token's
        # required count capped at its count in O).
        required = {
            tok: min(count, o_counts.get(tok, 0))
            for tok, count in r_counts.items()
            if min(count, o_counts.get(tok, 0)) > 0
        }
        ref_depth = min(max_depth(reference_text), max_depth(original_text))
        used_fallback = False
    else:
        # Fallback (spec-mandated, and noted here + in the round-0 report
        # as less realistic than a real reduced reference): a deterministic
        # 25% sample of O's distinct tokens, each required once. Seeded by
        # the entry name so it's reproducible without depending on
        # PYTHONHASHSEED (random.seed on a str is SHA512-based and stable
        # across processes/runs, unlike hash(str)).
        o_counts = token_counts(original_text)
        distinct = sorted(o_counts)
        k = max(1, round(0.25 * len(distinct)))
        rng = random.Random(f"crux-required-fallback::{entry}")
        sample = rng.sample(distinct, k) if distinct else []
        required = {tok: 1 for tok in sample}
        # No reduced reference means no depth evidence either; 0 imposes no
        # depth floor at all rather than (degenerately) forcing the full
        # original depth to be preserved. See round-0 report.
        ref_depth = 0
        used_fallback = True

    return CorpusRecipe(
        entry=entry,
        fmt=fmt,
        required=required,
        ref_depth=ref_depth,
        original_path=original_path,
        reference_path=reference_path,
        used_fallback=used_fallback,
    )


def make_predicate(recipe: CorpusRecipe) -> Callable[[str], bool]:
    fmt = recipe.fmt
    required = recipe.required
    ref_depth = recipe.ref_depth

    def predicate(text: str) -> bool:
        # Cheapest check first: most random deletions break structure
        # long before they threaten token counts or depth (see PLAN.md
        # Amendment 1's syntax-validity measurement).
        if not structurally_valid(text, fmt):
            return False
        if required:
            counts = token_counts(text)
            for tok, need in required.items():
                if counts.get(tok, 0) < need:
                    return False
        if ref_depth > 0 and max_depth(text) < ref_depth:
            return False
        return True

    return predicate


def predicate_for_entry_dir(entry_dir: Path) -> Callable[[str], bool]:
    """Convenience for external tools (see external_entry.py): re-derive
    the identical predicate purely from files on disk, so a fresh process
    with no shared state reconstructs exactly the same oracle."""
    return make_predicate(compute_recipe(entry_dir))
