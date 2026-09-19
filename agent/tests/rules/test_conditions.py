"""Three-valued condition evaluation, operator by operator."""

from __future__ import annotations

import pytest

from app.services.rules.conditions import (
    ALLOWED_OPERATORS,
    UNKNOWN,
    Tri,
    evaluate,
    referenced_keys,
)

T, F, U = Tri.TRUE, Tri.FALSE, Tri.UNKNOWN


def test_the_operator_allowlist_is_closed():
    assert ALLOWED_OPERATORS == {
        "all",
        "any",
        "not",
        "eq",
        "in",
        "lt",
        "gte",
        "is_unknown",
        "is_known",
    }


@pytest.mark.parametrize(
    ("condition", "values", "expected"),
    [
        ({"eq": {"key": "a", "value": True}}, {"a": True}, T),
        ({"eq": {"key": "a", "value": True}}, {"a": False}, F),
        ({"eq": {"key": "a", "value": True}}, {"a": UNKNOWN}, U),
        ({"eq": {"key": "a", "value": True}}, {}, U),
        ({"in": {"key": "b", "values": ["x", "y"]}}, {"b": "x"}, T),
        ({"in": {"key": "b", "values": ["x", "y"]}}, {"b": "z"}, F),
        ({"in": {"key": "b", "values": ["x", "y"]}}, {"b": UNKNOWN}, U),
        ({"lt": {"key": "n", "value": 8}}, {"n": 7}, T),
        ({"lt": {"key": "n", "value": 8}}, {"n": 8}, F),
        ({"lt": {"key": "n", "value": 8}}, {"n": UNKNOWN}, U),
        ({"gte": {"key": "n", "value": 8}}, {"n": 8}, T),
        ({"gte": {"key": "n", "value": 8}}, {"n": 7}, F),
        ({"gte": {"key": "n", "value": 8}}, {"n": UNKNOWN}, U),
    ],
)
def test_comparison_operators_propagate_unknown(condition, values, expected):
    assert evaluate(condition, values) is expected


@pytest.mark.parametrize(
    ("condition", "values", "expected"),
    [
        ({"is_unknown": {"key": "a"}}, {"a": UNKNOWN}, T),
        ({"is_unknown": {"key": "a"}}, {}, T),
        ({"is_unknown": {"key": "a"}}, {"a": False}, F),
        ({"is_known": {"key": "a"}}, {"a": False}, T),
        ({"is_known": {"key": "a"}}, {"a": UNKNOWN}, F),
        ({"is_known": {"key": "a"}}, {}, F),
    ],
)
def test_only_the_meta_operators_collapse_unknown(condition, values, expected):
    """These are the sole operators that turn unknown into a definite boolean."""
    assert evaluate(condition, values) is expected


def test_not_propagates_unknown():
    condition = {"not": {"eq": {"key": "a", "value": True}}}
    assert evaluate(condition, {"a": False}) is T
    assert evaluate(condition, {"a": True}) is F
    assert evaluate(condition, {"a": UNKNOWN}) is U


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"a": True, "b": True}, T),
        ({"a": True, "b": False}, F),
        ({"a": False, "b": UNKNOWN}, F),
        ({"a": True, "b": UNKNOWN}, U),
        ({"a": UNKNOWN, "b": UNKNOWN}, U),
    ],
)
def test_all_is_false_dominant(values, expected):
    condition = {
        "all": [{"eq": {"key": "a", "value": True}}, {"eq": {"key": "b", "value": True}}]
    }
    assert evaluate(condition, values) is expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"a": False, "b": False}, F),
        ({"a": True, "b": False}, T),
        ({"a": True, "b": UNKNOWN}, T),
        ({"a": False, "b": UNKNOWN}, U),
        ({"a": UNKNOWN, "b": UNKNOWN}, U),
    ],
)
def test_any_is_true_dominant(values, expected):
    condition = {
        "any": [{"eq": {"key": "a", "value": True}}, {"eq": {"key": "b", "value": True}}]
    }
    assert evaluate(condition, values) is expected


def test_booleans_and_integers_are_never_confused():
    assert evaluate({"eq": {"key": "n", "value": 1}}, {"n": True}) is F
    assert evaluate({"eq": {"key": "a", "value": True}}, {"a": 1}) is F
    assert evaluate({"in": {"key": "n", "values": [1]}}, {"n": True}) is F


def test_referenced_keys_walks_the_whole_tree():
    condition = {
        "all": [
            {"eq": {"key": "a", "value": True}},
            {"any": [{"is_known": {"key": "b"}}, {"not": {"lt": {"key": "c", "value": 1}}}]},
        ]
    }
    assert referenced_keys(condition) == {"a", "b", "c"}
