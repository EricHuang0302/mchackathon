"""Three-valued evaluation of the allowlisted rule condition language.

A condition never becomes executable: it is a small tree of allowlisted
operators over observation keys, evaluated with Kleene logic so that a missing
or unresolved observation stays ``unknown`` and never collapses into ``false``.

Only ``is_unknown`` and ``is_known`` turn an unknown operand into a definite
boolean; every other operator propagates it.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Mapping

from .errors import RulePackageError


class Tri(Enum):
    """Three-valued logic result."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class _Unknown:
    """Sentinel for an observation value that is not established."""

    _instance: "_Unknown | None" = None

    def __new__(cls) -> "_Unknown":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNKNOWN"


UNKNOWN = _Unknown()

#: Operators comparing one observation key. Extending this set is incomplete
#: until the TypeScript interpreter supports it and the shared cases pass.
COMPARISON_OPERATORS = ("eq", "in", "lt", "gte", "is_unknown", "is_known")
COMBINATOR_OPERATORS = ("all", "any", "not")
ALLOWED_OPERATORS = frozenset(COMPARISON_OPERATORS + COMBINATOR_OPERATORS)

#: Operators whose key must hold an integer value.
NUMERIC_OPERATORS = ("lt", "gte")


def operator_of(condition: Any) -> tuple[str, Any]:
    """Return the single allowlisted operator of a condition node."""
    if not isinstance(condition, dict) or len(condition) != 1:
        raise RulePackageError(
            f"a condition must hold exactly one operator, got {condition!r}",
            detail="invalid_condition",
        )
    operator, operand = next(iter(condition.items()))
    if operator not in ALLOWED_OPERATORS:
        raise RulePackageError(
            f"unknown condition operator {operator!r}; "
            f"allowed operators are {sorted(ALLOWED_OPERATORS)}",
            detail="unknown_operator",
        )
    return operator, operand


def referenced_keys(condition: Any) -> set[str]:
    """Collect every observation key a condition tree reads."""
    operator, operand = operator_of(condition)
    if operator in ("all", "any"):
        keys: set[str] = set()
        for child in operand:
            keys |= referenced_keys(child)
        return keys
    if operator == "not":
        return referenced_keys(operand)
    return {operand["key"]}


def _strict_equals(left: Any, right: Any) -> bool:
    """Equality that never treats ``True`` as ``1``."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _tri(value: bool) -> Tri:
    return Tri.TRUE if value else Tri.FALSE


def evaluate(condition: Any, values: Mapping[str, Any]) -> Tri:
    """Evaluate a condition tree against resolved observation values.

    ``values`` maps an observation key to its resolved value, or to ``UNKNOWN``.
    A key missing from the mapping is treated exactly like ``UNKNOWN``.
    """
    operator, operand = operator_of(condition)

    if operator == "all":
        results = [evaluate(child, values) for child in operand]
        if Tri.FALSE in results:
            return Tri.FALSE
        if Tri.UNKNOWN in results:
            return Tri.UNKNOWN
        return Tri.TRUE

    if operator == "any":
        results = [evaluate(child, values) for child in operand]
        if Tri.TRUE in results:
            return Tri.TRUE
        if Tri.UNKNOWN in results:
            return Tri.UNKNOWN
        return Tri.FALSE

    if operator == "not":
        result = evaluate(operand, values)
        if result is Tri.UNKNOWN:
            return Tri.UNKNOWN
        return _tri(result is Tri.FALSE)

    value = values.get(operand["key"], UNKNOWN)

    if operator == "is_unknown":
        return _tri(value is UNKNOWN)
    if operator == "is_known":
        return _tri(value is not UNKNOWN)

    if value is UNKNOWN:
        return Tri.UNKNOWN

    if operator == "eq":
        return _tri(_strict_equals(value, operand["value"]))
    if operator == "in":
        return _tri(any(_strict_equals(value, item) for item in operand["values"]))

    # lt / gte. Package validation guarantees the key is declared as an integer,
    # so a non-integer here means the catalog and the condition disagree.
    if isinstance(value, bool) or not isinstance(value, int):
        raise RulePackageError(
            f"operator {operator!r} needs an integer value for key "
            f"{operand['key']!r}, got {value!r}",
            detail="invalid_condition_value",
        )
    if operator == "lt":
        return _tri(value < operand["value"])
    return _tri(value >= operand["value"])


def first_matching(
    conditions: Iterable[tuple[Any, Any]], values: Mapping[str, Any]
) -> tuple[Any | None, bool]:
    """Return the first ``(condition, payload)`` evaluating true, in order.

    The second element reports whether any earlier or later condition evaluated
    unknown, which lets callers distinguish "nothing matched" from "not enough
    information yet".
    """
    saw_unknown = False
    for condition, payload in conditions:
        result = evaluate(condition, values)
        if result is Tri.TRUE:
            return payload, saw_unknown
        if result is Tri.UNKNOWN:
            saw_unknown = True
    return None, saw_unknown
