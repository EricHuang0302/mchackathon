"""Deterministic resolution of reported observations into rule inputs.

Several observations may describe the same key. Resolution is a pure function of
the request, uses only the observation envelope, and is specified precisely so
the TypeScript interpreter reaches the same answer:

1. Reject anything the pinned package cannot accept: a key outside the catalog,
   a value that is not valid for the declared type, a proposal source claiming a
   stronger confirmation than it can carry, or a confirmation below the key
   minimum. A rejected observation is reported, never reinterpreted as ``false``.
2. Among the surviving observations of one key, keep those with the highest
   confirmation rank, then those with the latest ``observedAt``.
3. If that top group still disagrees about the value, the key resolves to
   ``unknown`` and is listed in ``conflictingObservationKeys``. A conflict is
   never settled by picking an arbitrary winner.

The literal string ``"unknown"`` is a valid value for any key. It is an explicit
report that the fact is not established, so it competes for the top group like
any other value and can retract an earlier report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .conditions import UNKNOWN
from .package import RulePackage

UNKNOWN_VALUE = "unknown"

CONFIRMATION_RANK = {"proposed": 1, "reported": 2, "confirmed": 3}

#: The strongest confirmation each source can legitimately carry. A model or
#: camera proposal cannot confirm itself.
SOURCE_MAX_CONFIRMATION = {
    "button": "confirmed",
    "voice_report": "reported",
    "dispatcher_report": "confirmed",
    "camera_proposal": "proposed",
    "model_proposal": "proposed",
    "system": "reported",
}


@dataclass(frozen=True)
class ResolvedObservations:
    values: Mapping[str, Any]
    accepted_ids: tuple[str, ...]
    rejected: tuple[Mapping[str, str], ...]
    unknown_keys: tuple[str, ...]
    conflicting_keys: tuple[str, ...]

    def as_output(self) -> dict[str, Any]:
        """Render the JSON shape used by the decision schema."""
        return {
            key: UNKNOWN_VALUE if value is UNKNOWN else value
            for key, value in sorted(self.values.items())
        }


def resolve(
    observations: Sequence[Mapping[str, Any]], package: RulePackage
) -> ResolvedObservations:
    """Resolve reported observations against the pinned package catalog."""
    rejected: list[dict[str, str]] = []
    accepted_ids: list[str] = []
    candidates: dict[str, list[Mapping[str, Any]]] = {}

    for observation in observations:
        key = observation["key"]
        definition = package.observations.get(key)
        if definition is None:
            rejected.append(
                {
                    "observationId": observation["observationId"],
                    "key": key,
                    "code": "unknown_observation_key",
                }
            )
            continue

        value = observation["value"]
        is_explicit_unknown = value == UNKNOWN_VALUE and isinstance(value, str)
        if not is_explicit_unknown and not definition.accepts(value):
            rejected.append(
                {
                    "observationId": observation["observationId"],
                    "key": key,
                    "code": "invalid_value",
                }
            )
            continue

        confirmation = observation["confirmation"]
        source_ceiling = SOURCE_MAX_CONFIRMATION[observation["source"]]
        if CONFIRMATION_RANK[confirmation] > CONFIRMATION_RANK[source_ceiling]:
            rejected.append(
                {
                    "observationId": observation["observationId"],
                    "key": key,
                    "code": "source_cannot_confirm",
                }
            )
            continue

        if CONFIRMATION_RANK[confirmation] < CONFIRMATION_RANK[definition.minimum_confirmation]:
            rejected.append(
                {
                    "observationId": observation["observationId"],
                    "key": key,
                    "code": "insufficient_confirmation",
                }
            )
            continue

        accepted_ids.append(observation["observationId"])
        candidates.setdefault(key, []).append(observation)

    values: dict[str, Any] = {key: UNKNOWN for key in package.observations}
    conflicting: list[str] = []

    for key, group in candidates.items():
        best = max(
            (CONFIRMATION_RANK[item["confirmation"]], item["observedAt"])
            for item in group
        )
        top = [
            item
            for item in group
            if (CONFIRMATION_RANK[item["confirmation"]], item["observedAt"]) == best
        ]
        distinct = {_value_identity(item["value"]) for item in top}
        if len(distinct) > 1:
            conflicting.append(key)
            continue
        winner = top[0]["value"]
        if winner == UNKNOWN_VALUE and isinstance(winner, str):
            continue
        values[key] = winner

    unknown_keys = sorted(key for key, value in values.items() if value is UNKNOWN)
    return ResolvedObservations(
        values=values,
        accepted_ids=tuple(sorted(accepted_ids)),
        rejected=tuple(sorted(rejected, key=lambda item: item["observationId"])),
        unknown_keys=tuple(unknown_keys),
        conflicting_keys=tuple(sorted(conflicting)),
    )


def _value_identity(value: Any) -> tuple[str, Any]:
    """Distinguish ``True`` from ``1`` when comparing reported values."""
    return (type(value).__name__, value)
