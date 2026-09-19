"""Bounded candidate search and deterministic ranking."""

from __future__ import annotations

from data.aed.models import AvailabilityStatus, GeoPoint

from app.services.aed.candidates import CandidateSearchConfig, find_candidates
from app.services.aed.geo import bounding_box, haversine_meters
from .conftest import PATIENT_POINT, WEDNESDAY_NIGHT_UTC, make_record


def _records():
    return [
        make_record("near-open", latitude=25.0472, longitude=121.5172),
        make_record(
            "near-closed",
            latitude=25.0471,
            longitude=121.5171,
            opening_hours="Mon-Fri 09:00-17:00",
        ),
        make_record(
            "near-unknown",
            latitude=25.0473,
            longitude=121.5173,
            opening_hours="",
            access_notes=None,
        ),
        make_record("far-open", latitude=25.0900, longitude=121.5600),
    ]


def test_search_is_bounded_by_radius_and_limit():
    result = find_candidates(
        _records(),
        PATIENT_POINT,
        at=WEDNESDAY_NIGHT_UTC,
        config=CandidateSearchConfig(radius_meters=400.0, limit=2),
    )

    assert len(result.candidates) == 2
    assert result.searched_radius_meters == 400.0
    assert result.radius_expanded is False
    assert all(
        candidate.straight_line_meters <= 400.0 for candidate in result.candidates
    )


def test_ranking_prefers_open_then_unknown_then_closed():
    result = find_candidates(
        _records(),
        PATIENT_POINT,
        at=WEDNESDAY_NIGHT_UTC,
        config=CandidateSearchConfig(radius_meters=400.0, limit=10),
    )

    statuses = [candidate.availability.status for candidate in result.candidates]
    assert statuses == [
        AvailabilityStatus.OPEN,
        AvailabilityStatus.UNKNOWN,
        AvailabilityStatus.CLOSED,
    ]
    assert [candidate.is_dispatchable for candidate in result.candidates] == [
        True,
        True,
        False,
    ]


def test_ranking_breaks_distance_ties_on_the_stable_id():
    # Two records at the same coordinates must still produce one stable order.
    records = [
        make_record("bbb", latitude=25.0472, longitude=121.5172),
        make_record("aaa", latitude=25.0472, longitude=121.5172),
    ]

    result = find_candidates(records, PATIENT_POINT, at=WEDNESDAY_NIGHT_UTC)

    assert [candidate.stable_id for candidate in result.candidates] == [
        "synthetic-demo:aaa",
        "synthetic-demo:bbb",
    ]


def test_search_is_deterministic_for_the_same_inputs():
    records = _records()
    first = find_candidates(records, PATIENT_POINT, at=WEDNESDAY_NIGHT_UTC)
    second = find_candidates(list(reversed(records)), PATIENT_POINT, at=WEDNESDAY_NIGHT_UTC)

    assert [candidate.stable_id for candidate in first.candidates] == [
        candidate.stable_id for candidate in second.candidates
    ]


def test_excluded_candidates_are_removed_inside_the_search():
    """Scenario: an unavailable candidate is not reconsidered."""

    result = find_candidates(
        _records(),
        PATIENT_POINT,
        at=WEDNESDAY_NIGHT_UTC,
        config=CandidateSearchConfig(radius_meters=400.0, limit=10),
        excluded_ids={"synthetic-demo:near-open"},
    )

    assert "synthetic-demo:near-open" not in {
        candidate.stable_id for candidate in result.candidates
    }
    assert result.excluded_count == 1


def test_radius_expands_once_when_nothing_is_nearby():
    result = find_candidates(
        [make_record("distant", latitude=25.0600, longitude=121.5300)],
        PATIENT_POINT,
        at=WEDNESDAY_NIGHT_UTC,
        config=CandidateSearchConfig(radius_meters=200.0, max_radius_meters=3_000.0),
    )

    assert result.radius_expanded is True
    assert result.searched_radius_meters == 3_000.0
    assert len(result.candidates) == 1


def test_search_returns_nothing_when_every_record_is_out_of_range():
    result = find_candidates(
        [make_record("distant", latitude=24.0, longitude=120.0)],
        PATIENT_POINT,
        at=WEDNESDAY_NIGHT_UTC,
    )

    assert result.candidates == ()
    assert result.dispatchable == ()


def test_include_closed_false_drops_published_closed_candidates():
    result = find_candidates(
        _records(),
        PATIENT_POINT,
        at=WEDNESDAY_NIGHT_UTC,
        config=CandidateSearchConfig(radius_meters=400.0, include_closed=False),
    )

    assert all(candidate.is_dispatchable for candidate in result.candidates)


def test_bounding_box_contains_every_point_within_the_radius():
    box = bounding_box(PATIENT_POINT, 500.0)
    north = GeoPoint(PATIENT_POINT.latitude + 0.0044, PATIENT_POINT.longitude)
    east = GeoPoint(PATIENT_POINT.latitude, PATIENT_POINT.longitude + 0.0049)

    assert haversine_meters(PATIENT_POINT, north) <= 500.0
    assert haversine_meters(PATIENT_POINT, east) <= 500.0
    assert box.contains(north)
    assert box.contains(east)
