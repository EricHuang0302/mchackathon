"""Normalized AED domain models shared by the ETL and the backend services.

All datetimes are timezone-aware UTC. Opening hours are stored structurally so
that availability can be evaluated deterministically; the raw source text is
always preserved so an unparsed value stays ``unknown`` instead of becoming
``false``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

MINUTES_PER_DAY = 24 * 60

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class AvailabilityStatus(str, Enum):
    """Tri-state availability. ``UNKNOWN`` is a first-class result."""

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GeoPoint:
    """WGS84 coordinate pair."""

    latitude: float
    longitude: float


@dataclass(frozen=True)
class OpeningWindow:
    """One published opening window.

    ``weekday`` is 0 for Monday. ``end_minute`` may exceed ``MINUTES_PER_DAY``
    for windows that run past midnight into the following day.
    """

    weekday: int
    start_minute: int
    end_minute: int


@dataclass(frozen=True)
class OpeningHours:
    """Structured opening hours with the original source text preserved."""

    known: bool
    always_open: bool = False
    windows: tuple[OpeningWindow, ...] = ()
    unknown_weekdays: tuple[int, ...] = ()
    raw: str | None = None
    parse_note: str | None = None

    @classmethod
    def unknown(cls, raw: str | None = None, parse_note: str | None = None) -> "OpeningHours":
        return cls(
            known=False,
            always_open=False,
            windows=(),
            unknown_weekdays=(),
            raw=raw,
            parse_note=parse_note,
        )


@dataclass(frozen=True)
class SourceDescriptor:
    """Provenance of one ingestion input.

    Real source data is downloaded into a local cache and is never committed.
    Fixtures shipped in this repository keep ``synthetic=True``.
    """

    source_system: str
    source_url: str
    dataset_version: str
    retrieved_at: datetime
    synthetic: bool = True
    license_note: str = (
        "Synthetic fixture; not derived from a real AED location or "
        "government dataset."
    )


@dataclass(frozen=True)
class SourceRow:
    """One raw row handed over by a source adapter."""

    row_number: int
    values: dict[str, str]
    descriptor: SourceDescriptor


@dataclass(frozen=True)
class AedRecord:
    """A validated, normalized AED location."""

    stable_id: str
    source_id: str
    source_system: str
    name: str
    point: GeoPoint
    address: str
    opening_hours: OpeningHours
    access_notes: str | None
    access_notes_known: bool
    source_url: str
    source_updated_at: datetime | None
    ingested_at: datetime
    dataset_version: str
    data_quality_notes: tuple[str, ...] = field(default=())
    source_location_id: str | None = None

    @property
    def latitude(self) -> float:
        return self.point.latitude

    @property
    def longitude(self) -> float:
        return self.point.longitude
