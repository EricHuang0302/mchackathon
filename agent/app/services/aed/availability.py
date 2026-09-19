"""Availability evaluation from published opening hours.

The result is tri-state. Unknown and ambiguous hours stay ``UNKNOWN``; they
are never coerced into ``CLOSED`` (which would hide a usable AED) or ``OPEN``
(which would claim physical availability without evidence). Nothing here
observes the device itself, so even ``OPEN`` only means "published as open".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from data.aed.models import MINUTES_PER_DAY, AedRecord, AvailabilityStatus, OpeningHours

# Fixed UTC offset for the demonstration region. Using an offset instead of a
# named zone keeps evaluation deterministic and free of tzdata availability.
DEFAULT_UTC_OFFSET_MINUTES = 8 * 60

# A published record older than this is still used, but flagged as uncertain.
DEFAULT_MAX_SOURCE_AGE = timedelta(days=365)


@dataclass(frozen=True)
class AvailabilityAssessment:
    """Tri-state availability with the evidence that produced it."""

    status: AvailabilityStatus
    reason_code: str
    hours_known: bool
    raw_opening_hours: str | None
    source_updated_at: datetime | None
    dataset_version: str
    evaluated_at: datetime
    uncertainty: tuple[str, ...] = ()

    @property
    def is_dispatchable(self) -> bool:
        """``OPEN`` and ``UNKNOWN`` may be dispatched; ``CLOSED`` may not.

        An unknown-hours AED is still worth sending a runner to, as long as the
        uncertainty is shown. A published-closed AED is not.
        """

        return self.status is not AvailabilityStatus.CLOSED


def evaluate_availability(
    record: AedRecord,
    *,
    at: datetime,
    utc_offset_minutes: int = DEFAULT_UTC_OFFSET_MINUTES,
    max_source_age: timedelta = DEFAULT_MAX_SOURCE_AGE,
) -> AvailabilityAssessment:
    """Evaluate ``record`` against its published hours at instant ``at``."""

    status, reason_code = _evaluate_hours(record.opening_hours, at, utc_offset_minutes)

    uncertainty: list[str] = []
    if not record.opening_hours.known:
        uncertainty.append("opening_hours_unknown")
    elif record.opening_hours.unknown_weekdays:
        uncertainty.append("opening_hours_partial")
    if record.source_updated_at is None:
        uncertainty.append("source_update_time_unknown")
    elif at - record.source_updated_at > max_source_age:
        uncertainty.append("stale_source_record")
    if not record.access_notes_known:
        uncertainty.append("access_notes_unknown")

    return AvailabilityAssessment(
        status=status,
        reason_code=reason_code,
        hours_known=record.opening_hours.known,
        raw_opening_hours=record.opening_hours.raw,
        source_updated_at=record.source_updated_at,
        dataset_version=record.dataset_version,
        evaluated_at=at,
        uncertainty=tuple(uncertainty),
    )


def _evaluate_hours(
    hours: OpeningHours, at: datetime, utc_offset_minutes: int
) -> tuple[AvailabilityStatus, str]:
    if not hours.known:
        return AvailabilityStatus.UNKNOWN, "opening_hours_unknown"
    if hours.always_open:
        return AvailabilityStatus.OPEN, "published_always_open"

    local = at + timedelta(minutes=utc_offset_minutes)
    weekday = local.weekday()
    minute_of_day = local.hour * 60 + local.minute

    for window in hours.windows:
        if window.weekday == weekday and window.start_minute <= minute_of_day < window.end_minute:
            return AvailabilityStatus.OPEN, "within_published_window"
        # A window that runs past midnight also covers the following day.
        if (
            window.weekday == (weekday - 1) % 7
            and window.end_minute > MINUTES_PER_DAY
            and minute_of_day < window.end_minute - MINUTES_PER_DAY
        ):
            return AvailabilityStatus.OPEN, "within_published_window_overnight"

    if weekday in hours.unknown_weekdays:
        return AvailabilityStatus.UNKNOWN, "opening_hours_unknown_for_weekday"

    return AvailabilityStatus.CLOSED, "outside_published_window"
