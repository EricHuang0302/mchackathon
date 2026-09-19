"""Tri-state availability evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data.aed.models import AvailabilityStatus

from app.services.aed.availability import evaluate_availability
from .conftest import WEDNESDAY_MORNING_UTC, WEDNESDAY_NIGHT_UTC, make_record


def test_always_open_record_is_published_open():
    record = make_record("A", latitude=25.047, longitude=121.517, opening_hours="24/7")

    assessment = evaluate_availability(record, at=WEDNESDAY_MORNING_UTC)

    assert assessment.status is AvailabilityStatus.OPEN
    assert assessment.reason_code == "published_always_open"
    assert assessment.uncertainty == ()


def test_record_outside_its_published_window_is_closed():
    """Scenario: closed hours."""

    record = make_record(
        "B", latitude=25.047, longitude=121.517, opening_hours="Mon-Fri 09:00-17:00"
    )

    assessment = evaluate_availability(record, at=WEDNESDAY_NIGHT_UTC)

    assert assessment.status is AvailabilityStatus.CLOSED
    assert assessment.reason_code == "outside_published_window"
    assert assessment.is_dispatchable is False


def test_record_inside_its_published_window_is_open():
    record = make_record(
        "C", latitude=25.047, longitude=121.517, opening_hours="Mon-Fri 09:00-17:00"
    )

    assessment = evaluate_availability(record, at=WEDNESDAY_MORNING_UTC)

    assert assessment.status is AvailabilityStatus.OPEN
    assert assessment.reason_code == "within_published_window"


def test_overnight_window_covers_the_early_morning_of_the_next_day():
    record = make_record(
        "D", latitude=25.047, longitude=121.517, opening_hours="Mon-Sun 22:00-02:00"
    )
    # 2026-09-16 17:30Z is Thursday 01:30 local, inside Wednesday's window.
    at = datetime(2026, 9, 16, 17, 30, tzinfo=timezone.utc)

    assessment = evaluate_availability(record, at=at)

    assert assessment.status is AvailabilityStatus.OPEN
    assert assessment.reason_code == "within_published_window_overnight"


def test_unknown_hours_stay_unknown_and_remain_dispatchable():
    """Scenario: unknown hours are preserved, never coerced to closed."""

    record = make_record("E", latitude=25.047, longitude=121.517, opening_hours="")

    assessment = evaluate_availability(record, at=WEDNESDAY_NIGHT_UTC)

    assert assessment.status is AvailabilityStatus.UNKNOWN
    assert assessment.reason_code == "opening_hours_unknown"
    assert assessment.hours_known is False
    assert "opening_hours_unknown" in assessment.uncertainty
    assert assessment.is_dispatchable is True


def test_ambiguous_hours_text_is_unknown_and_keeps_the_raw_value():
    """Scenario: ambiguous hours."""

    record = make_record(
        "F", latitude=25.047, longitude=121.517, opening_hours="daytime only"
    )

    assessment = evaluate_availability(record, at=WEDNESDAY_MORNING_UTC)

    assert assessment.status is AvailabilityStatus.UNKNOWN
    assert assessment.raw_opening_hours == "daytime only"


def test_missing_access_notes_and_update_time_add_uncertainty_codes():
    record = make_record(
        "G",
        latitude=25.047,
        longitude=121.517,
        access_notes=None,
        source_updated_at=None,
    )

    assessment = evaluate_availability(record, at=WEDNESDAY_MORNING_UTC)

    assert assessment.status is AvailabilityStatus.OPEN
    assert "access_notes_unknown" in assessment.uncertainty
    assert "source_update_time_unknown" in assessment.uncertainty


def test_old_source_record_is_flagged_without_changing_the_status():
    record = make_record(
        "H",
        latitude=25.047,
        longitude=121.517,
        source_updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    assessment = evaluate_availability(
        record, at=WEDNESDAY_MORNING_UTC, max_source_age=timedelta(days=365)
    )

    assert assessment.status is AvailabilityStatus.OPEN
    assert "stale_source_record" in assessment.uncertainty
    assert assessment.dataset_version == "synthetic-2026-09-01"
