"""Helper location freshness, staleness labeling, and proximity."""

from __future__ import annotations

from datetime import timedelta

from data.aed.models import GeoPoint

from app.services.aed.helpers import (
    LocationFreshness,
    assess_proximity,
    evaluate_helper_location,
)
from app.services.aed.retrieval import estimate_retrieval
from app.services.aed.routing import DeterministicFakeRouteProvider
from .conftest import HELPER_POINT, PATIENT_POINT, helper_status_at

AED_POINT = GeoPoint(latitude=25.0500, longitude=121.5200)


def test_recent_position_is_fresh(now):
    status = helper_status_at(HELPER_POINT, reported_at=now, now=now)

    assert status.freshness is LocationFreshness.FRESH
    assert status.age_seconds == 0.0
    assert status.is_stale is False


def test_position_ages_through_aging_into_stale(now):
    reported_at = now - timedelta(seconds=300)

    status = helper_status_at(HELPER_POINT, reported_at=reported_at, now=now)

    assert status.freshness is LocationFreshness.STALE
    assert status.age_seconds == 300.0
    assert status.is_stale is True
    assert "helper_position_stale" in status.uncertainty_codes()


def test_aging_position_is_labeled_between_the_thresholds(now):
    status = helper_status_at(
        HELPER_POINT, reported_at=now - timedelta(seconds=90), now=now
    )

    assert status.freshness is LocationFreshness.AGING


def test_missing_position_is_reported_as_missing(now):
    status = evaluate_helper_location(None, now=now, helper_id="helper-9")

    assert status.freshness is LocationFreshness.MISSING
    assert status.age_seconds is None
    assert status.is_usable is False
    assert status.uncertainty_codes() == ("helper_position_unknown",)


def test_hidden_helper_page_is_flagged_as_suspended_tracking(now):
    status = helper_status_at(
        HELPER_POINT,
        reported_at=now - timedelta(seconds=200),
        now=now,
        page_visible=False,
    )

    assert "helper_page_hidden_tracking_suspended" in status.notes
    assert status.freshness is LocationFreshness.STALE


def test_poor_and_unknown_accuracy_are_flagged(now):
    poor = helper_status_at(
        HELPER_POINT, reported_at=now, now=now, accuracy_meters=350.0
    )
    unknown = helper_status_at(
        HELPER_POINT, reported_at=now, now=now, accuracy_meters=None
    )

    assert any(note.startswith("low_position_accuracy") for note in poor.notes)
    assert "position_accuracy_unknown" in unknown.notes


def test_stale_position_propagates_into_the_retrieval_estimate(now):
    """Scenario: stale helper position."""

    provider = DeterministicFakeRouteProvider()
    stale = helper_status_at(
        HELPER_POINT, reported_at=now - timedelta(seconds=600), now=now
    )

    estimate = estimate_retrieval(
        provider,
        helper_location=stale,
        aed_id="synthetic-demo:aed-1",
        aed_point=AED_POINT,
        patient_point=PATIENT_POINT,
        now=now,
    )

    assert "helper_position_stale" in estimate.uncertainty
    assert "helper_position_stale" in estimate.outbound.uncertainty
    # The route itself is still provider-based; only the anchor is uncertain.
    assert estimate.outbound.is_route_based is True


def test_proximity_reports_arrival_radius_without_claiming_collection(now):
    status = helper_status_at(AED_POINT, reported_at=now, now=now)

    proximity = assess_proximity(status, AED_POINT)

    assert proximity is not None
    assert proximity.at_destination is True
    assert proximity.distance_meters == 0.0
    assert "proximity_is_not_a_collection_report" in proximity.notes
    assert proximity.based_on_stale_position is False


def test_proximity_from_a_stale_position_is_marked_stale(now):
    status = helper_status_at(
        AED_POINT, reported_at=now - timedelta(seconds=600), now=now
    )

    proximity = assess_proximity(status, AED_POINT)

    assert proximity is not None
    assert proximity.based_on_stale_position is True


def test_proximity_is_none_without_a_position(now):
    status = evaluate_helper_location(None, now=now, helper_id="helper-9")

    assert assess_proximity(status, AED_POINT) is None
