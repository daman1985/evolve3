"""Unit tests for ReductionProblem / LineProblem / CharProblem (crux.crux.core):
splitting, order-independent rendering, and the from_text -> Oracle wiring
that every reducer and every task ultimately sits on top of.
"""
from __future__ import annotations

from crux.crux.core import CharProblem, LineProblem, Oracle, ReductionProblem


def test_line_problem_splits_keeping_newlines():
    text = "one\ntwo\nthree"
    problem = LineProblem.from_text(text, predicate=lambda t: True)
    assert problem.elements == ["one\n", "two\n", "three"]


def test_line_problem_full_kept_renders_original_text():
    text = "alpha\nbeta\ngamma\n"
    problem = LineProblem.from_text(text, predicate=lambda t: True)
    full = tuple(range(len(problem.elements)))
    assert problem.render(full) == text


def test_char_problem_splits_into_single_characters():
    text = "ab\nc"
    problem = CharProblem.from_text(text, predicate=lambda t: True)
    assert problem.elements == ["a", "b", "\n", "c"]
    full = tuple(range(len(problem.elements)))
    assert problem.render(full) == text


def test_render_ignores_argument_order_and_reconstructs_original_order():
    text = "L0\nL1\nL2\nL3\n"
    problem = LineProblem.from_text(text, predicate=lambda t: True)
    # Deliberately pass kept out of order and with a non-list iterable.
    assert problem.render((3, 0, 2)) == "L0\nL2\nL3\n"
    assert problem.render(iter([2, 0])) == "L0\nL2\n"


def test_render_on_empty_kept_is_empty_string():
    text = "a\nb\n"
    problem = LineProblem.from_text(text, predicate=lambda t: True)
    assert problem.render(()) == ""


def test_from_text_predicate_receives_rendered_text_not_indices():
    seen = []

    def predicate(rendered_text: str) -> bool:
        seen.append(rendered_text)
        return "keep-me" in rendered_text

    text = "drop\nkeep-me\ndrop\n"
    problem = LineProblem.from_text(text, predicate=predicate)
    assert isinstance(problem.oracle, Oracle)

    assert problem.oracle((1,)) is True
    assert problem.oracle((0, 2)) is False
    assert seen == ["keep-me\n", "drop\ndrop\n"]


def test_from_text_wires_budget_through_to_the_oracle():
    problem = LineProblem.from_text("a\nb\nc\n", predicate=lambda t: True, budget=2)
    assert problem.oracle.budget == 2


def test_reduction_problem_len_matches_element_count():
    text = "x\ny\nz\n"
    problem = LineProblem.from_text(text, predicate=lambda t: True)
    assert len(problem) == 3


def test_reduction_problem_can_be_constructed_directly_from_elements_and_oracle():
    # The path tasks.py actually uses (Task.make_problem): elements + a
    # kept-index predicate wired straight into a fresh Oracle, bypassing
    # from_text's own text-splitting entirely.
    elements = ["e0", "e1", "e2"]
    oracle = Oracle(lambda kept: 1 in kept)
    problem = ReductionProblem(elements, oracle)
    assert problem.render((0, 2)) == "e0e2"
    assert problem.oracle((1,)) is True
    assert problem.oracle((0, 2)) is False
