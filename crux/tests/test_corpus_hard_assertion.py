"""PLAN.md's round-0 hard requirement: predicate(original) is True for
every corpus task -- enforced in tasks.py's build_corpus_tasks() as a hard
AssertionError (fix the recipe, never the entry). This file re-derives the
same check per entry directly from corpus_recipe.py, independently of
tasks.py's own loop, so a single broken entry is reported individually by
name instead of surfacing only as one all-or-nothing raise -- and so this
file keeps giving a clean per-entry report even if tasks.py's own function
is what regresses.

Also pins the two informational findings from the round-0 verification
report (reference validity, fallback usage) as regression markers: not
because they are requirements, but so a future change to corpus_recipe.py
that alters either is a noticed, deliberate decision rather than a silent
side effect.
"""
from __future__ import annotations

import pytest

from crux.bench.corpus_recipe import compute_recipe, make_predicate
from crux.bench.tasks import CORPUS_DIR, build_corpus_tasks

_ENTRY_DIRS = sorted(p for p in CORPUS_DIR.iterdir() if p.is_dir())
_ENTRY_NAMES = [p.name for p in _ENTRY_DIRS]


def test_corpus_has_the_expected_number_of_entries():
    # Not a magic number for its own sake: this is the corpus size the
    # round-0 report was verified against (22 entries -> 41 tasks at
    # line+char granularity). A change here should be a deliberate corpus
    # edit, not a silent drop.
    assert len(_ENTRY_NAMES) == 22, _ENTRY_NAMES


@pytest.mark.parametrize("entry_name", _ENTRY_NAMES)
def test_predicate_of_original_is_true(entry_name):
    entry_dir = CORPUS_DIR / entry_name
    recipe = compute_recipe(entry_dir)
    predicate = make_predicate(recipe)
    original_text = recipe.original_path.read_text(encoding="utf-8", errors="surrogateescape")
    assert predicate(original_text) is True, (
        f"{entry_name}: predicate(original) is False -- this must always hold "
        "(PLAN.md round-0 spec); fix corpus_recipe.py, never this entry"
    )


def test_build_corpus_tasks_succeeds_and_every_task_confirms_the_same_thing():
    # The actual code path every other consumer (tasks.py, run.py) uses:
    # the hard assertion inside build_corpus_tasks() must not have been
    # silently bypassed, and each resulting Task's own predicate_on_kept
    # must agree when called on the full kept-set (== the original text).
    tasks = build_corpus_tasks()
    assert len(tasks) == 41, len(tasks)  # 21 @line + 20 @char, see report
    for t in tasks:
        full = tuple(range(len(t.elements)))
        assert t.predicate_on_kept(full) is True, t.name


def test_exactly_the_two_deep_nesting_json_entries_use_the_fallback_required_set():
    # Informational (PLAN.md: "less realistic than a real reduced
    # reference"), pinned so a change in which entries lack a real
    # shrinkray/creduce reference is noticed.
    tasks = {t.name: t for t in build_corpus_tasks()}
    fallback_entries = sorted({t.name.rsplit("@", 1)[0] for t in tasks.values() if t.used_fallback})
    assert fallback_entries == [
        "jq-1.5-cve-2016-4074-deep-nest-segfault",
        "python-rapidjson-10-deep-nest-segfault",
    ]


def test_gcc_udlit_reference_is_a_known_case_of_a_real_reference_failing_our_predicate():
    # Informational, not a requirement (see corpus_recipe.py / tasks.py
    # module docstrings: the reference is an external tool's output under
    # a DIFFERENT real oracle, never asserted to satisfy ours). Verified
    # in the round-0 report to be a genuine creduce output whose brackets
    # are not balanced under our cheap structural check, not a recipe bug.
    tasks = {t.name: t for t in build_corpus_tasks()}
    t = tasks["gcc49-udlit-char-pack-template@line"]
    assert t.reference_valid is False
    assert t.used_fallback is False  # it DOES have a real reference; that reference just fails our predicate


def test_all_other_corpus_references_pass_our_predicate():
    # The converse of the above, so the one known exception stays the
    # only one: every other entry that HAS a real reference must satisfy
    # our predicate under it.
    tasks = {t.name: t for t in build_corpus_tasks()}
    by_entry = {}
    for t in tasks.values():
        entry = t.name.rsplit("@", 1)[0]
        by_entry.setdefault(entry, t)
    failing = sorted(
        entry
        for entry, t in by_entry.items()
        if t.reference_bytes is not None and t.reference_valid is False
    )
    assert failing == ["gcc49-udlit-char-pack-template"]
