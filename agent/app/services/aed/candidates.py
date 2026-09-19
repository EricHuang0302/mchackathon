"""Bounded AED candidate search with deterministic ranking.

The search is a bounding-box prefilter, an exact great-circle filter, then a
deterministic sort. It never performs a datastore nearest-neighbour query and
it never calls a route provider: routing is applied to the short list only.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from data.aed.models import AedRecord, AvailabilityStatus, GeoPoint

from .availability import (
    DEFAULT_MAX_SOURCE_AGE,
    DEFAULT_UTC_OFFSET_MINUTES,
    AvailabilityAssessment,
    evaluate_availability,
)
from .geo import bounding_box, haversine_meters

# Availability ordering: published-open first, unknown next, closed last.
# Closed candidates stay in the result so a dispatcher can see them, but they
# are never preferred and they are not dispatchable.
_AVAILABILITY_RANK = {
    AvailabilityStatus.OPEN: 0,
    AvailabilityStatus.UNKNOWN: 1,
    AvailabilityStatus.CLOSED: 2,
}


@dataclass(frozen=True)
class CandidateSearchConfig:
    """Bounds and ranking configuration for one search."""

    radius_meters: float = 1_500.0
    max_radius_meters: float = 4_000.0
    limit: int = 5
    include_closed: bool = True
    utc_offset_minutes: int = DEFAULT_UTC_OFFSET_MINUTES
    max_source_age: timedelta = DEFAULT_MAX_SOURCE_AGE


@dataclass(frozen=True)
class AedCandidate:
    """One ranked candidate with its straight-line distance and availability."""

    record: AedRecord
    straight_line_meters: float
    availability: AvailabilityAssessment

    @property
    def stable_id(self) -> str:
        return self.record.stable_id

    @property
    def is_dispatchable(self) -> bool:
        return self.availability.is_dispatchable


@dataclass(frozen=True)
class CandidateSearchResult:
    """The bounded result of one candidate search."""

    origin: GeoPoint
    candidates: tuple[AedCandidate, ...]
    searched_radius_meters: float
    radius_expanded: bool
    examined_count: int
    excluded_count: int
    evaluated_at: datetime

    @property
    def dispatchable(self) -> tuple[AedCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.is_dispatchable)


def find_candidates(
    records: Iterable[AedRecord],
    origin: GeoPoint,
    *,
    at: datetime,
    config: CandidateSearchConfig | None = None,
    excluded_ids: Iterable[str] = (),
) -> CandidateSearchResult:
    """Return up to ``config.limit`` candidates ranked deterministically.

    ``excluded_ids`` is applied inside the search, so a candidate already
    reported unavailable for this incident is never reconsidered.
    """

    config = config or CandidateSearchConfig()
    excluded = frozenset(excluded_ids)
    record_list = list(records)
    excluded_count = sum(1 for record in record_list if record.stable_id in excluded)

    radius = config.radius_meters
    matches = _within_radius(record_list, origin, radius, excluded)
    radius_expanded = False
    if not matches and config.max_radius_meters > radius:
        radius = config.max_radius_meters
        matches = _within_radius(record_list, origin, radius, excluded)
        radius_expanded = True

    candidates = [
        AedCandidate(
            record=record,
            straight_line_meters=distance,
            availability=evaluate_availability(
                record,
                at=at,
                utc_offset_minutes=config.utc_offset_minutes,
                max_source_age=config.max_source_age,
            ),
        )
        for record, distance in matches
    ]
    if not config.include_closed:
        candidates = [candidate for candidate in candidates if candidate.is_dispatchable]

    ranked = rank_candidates(candidates)[: max(config.limit, 0)]
    return CandidateSearchResult(
        origin=origin,
        candidates=ranked,
        searched_radius_meters=radius,
        radius_expanded=radius_expanded,
        examined_count=len(record_list),
        excluded_count=excluded_count,
        evaluated_at=at,
    )


def rank_candidates(candidates: Sequence[AedCandidate]) -> tuple[AedCandidate, ...]:
    """Sort by availability, then distance, then stable ID.

    The stable ID is the final tie-break so equal distances in fixtures (and in
    co-located real records) still produce one deterministic order.
    """

    return tuple(sorted(candidates, key=_ranking_key))


def _ranking_key(candidate: AedCandidate) -> tuple[int, float, str]:
    return (
        _AVAILABILITY_RANK[candidate.availability.status],
        round(candidate.straight_line_meters, 3),
        candidate.stable_id,
    )


def _within_radius(
    records: Sequence[AedRecord],
    origin: GeoPoint,
    radius_meters: float,
    excluded: frozenset[str],
) -> list[tuple[AedRecord, float]]:
    box = bounding_box(origin, radius_meters)
    matches: list[tuple[AedRecord, float]] = []
    for record in records:
        if record.stable_id in excluded:
            continue
        if not box.contains(record.point):
            continue
        distance = haversine_meters(origin, record.point)
        if distance <= radius_meters:
            matches.append((record, distance))
    return matches
