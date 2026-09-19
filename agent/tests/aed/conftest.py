"""Shared synthetic builders for the AED data and routing tests.

Every fixture here is synthetic. No real AED location, incident, or patient
data is used anywhere in this suite.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.aed.hours import parse_opening_hours
from data.aed.models import AedRecord, GeoPoint
from data.aed.normalize import build_stable_id

from app.services.aed.helpers import HelperPosition, evaluate_helper_location

# 2026-09-16 is a Wednesday. 02:00Z is 10:00 in the +08:00 demonstration
# region, which is inside a Mon-Fri 09:00-17:00 window.
WEDNESDAY_MORNING_UTC = datetime(2026, 9, 16, 2, 0, tzinfo=timezone.utc)
WEDNESDAY_NIGHT_UTC = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)

PATIENT_POINT = GeoPoint(latitude=25.0470, longitude=121.5170)
HELPER_POINT = GeoPoint(latitude=25.0472, longitude=121.5172)

SOURCE_SYSTEM = "synthetic-demo"
SOURCE_URL = "https://example.invalid/synthetic-aed-dataset"
DATASET_VERSION = "synthetic-2026-09-01"


def make_record(
    source_id: str,
    *,
    latitude: float,
    longitude: float,
    opening_hours: str = "24/7",
    access_notes: str | None = "Synthetic wall cabinet",
    source_updated_at: datetime | None = datetime(2026, 9, 1, tzinfo=timezone.utc),
    name: str | None = None,
    address: str = "1 Synthetic Road, Taipei",
) -> AedRecord:
    """Build a normalized synthetic AED record without going through the ETL."""

    hours = parse_opening_hours(opening_hours)
    notes = ("unknown_opening_hours",) if not hours.known else ()
    if access_notes is None:
        notes = (*notes, "missing_access_notes")
    return AedRecord(
        stable_id=build_stable_id(SOURCE_SYSTEM, source_id),
        source_id=source_id,
        source_system=SOURCE_SYSTEM,
        name=name or f"Synthetic AED {source_id}",
        point=GeoPoint(latitude=latitude, longitude=longitude),
        address=address,
        opening_hours=hours,
        access_notes=access_notes,
        access_notes_known=access_notes is not None,
        source_url=SOURCE_URL,
        source_updated_at=source_updated_at,
        ingested_at=WEDNESDAY_MORNING_UTC,
        dataset_version=DATASET_VERSION,
        data_quality_notes=notes,
    )


def helper_status_at(
    point: GeoPoint,
    *,
    reported_at: datetime,
    now: datetime,
    helper_id: str = "helper-1",
    accuracy_meters: float | None = 12.0,
    page_visible: bool = True,
):
    """Evaluate a synthetic helper position against an explicit instant."""

    position = HelperPosition(
        helper_id=helper_id,
        point=point,
        reported_at=reported_at,
        accuracy_meters=accuracy_meters,
        page_visible=page_visible,
    )
    return evaluate_helper_location(position, now=now)


@pytest.fixture
def now() -> datetime:
    return WEDNESDAY_MORNING_UTC


@pytest.fixture
def fresh_helper(now: datetime):
    return helper_status_at(HELPER_POINT, reported_at=now, now=now)
