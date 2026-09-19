"""Helper location freshness and proximity.

A helper position is a report from a page that was visible at some instant.
It is never evidence of continuous tracking, and proximity to an AED is never
evidence that the AED was collected. Age is always computed against an
injected instant so that callers, not this module, own the clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from data.aed.models import GeoPoint

from .geo import haversine_meters


class LocationFreshness(str, Enum):
    """Age classification of the last helper location report."""

    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    MISSING = "missing"


@dataclass(frozen=True)
class HelperLocationConfig:
    """Thresholds for labeling a helper position."""

    fresh_after: timedelta = timedelta(seconds=45)
    stale_after: timedelta = timedelta(seconds=120)
    # A position whose reported accuracy is worse than this is flagged.
    poor_accuracy_meters: float = 100.0
    # Within this distance a helper is treated as standing at the destination.
    arrival_radius_meters: float = 30.0


DEFAULT_HELPER_LOCATION_CONFIG = HelperLocationConfig()


@dataclass(frozen=True)
class HelperPosition:
    """One helper location report."""

    helper_id: str
    point: GeoPoint
    reported_at: datetime
    accuracy_meters: float | None = None
    page_visible: bool = True


@dataclass(frozen=True)
class HelperLocationStatus:
    """A helper position with its freshness label and caveats."""

    helper_id: str
    position: HelperPosition | None
    freshness: LocationFreshness
    age_seconds: float | None
    evaluated_at: datetime
    notes: tuple[str, ...] = ()

    @property
    def is_usable(self) -> bool:
        """Whether an estimate may be anchored on this position at all."""

        return self.position is not None

    @property
    def is_stale(self) -> bool:
        return self.freshness in (LocationFreshness.STALE, LocationFreshness.MISSING)

    def uncertainty_codes(self) -> tuple[str, ...]:
        """Codes to attach to any estimate derived from this position."""

        if self.position is None:
            return ("helper_position_unknown",)
        codes = [f"helper_position_{self.freshness.value}"]
        codes.extend(self.notes)
        return tuple(codes)


@dataclass(frozen=True)
class ProximityAssessment:
    """Whether a helper reported being at a destination, and how confidently."""

    helper_id: str
    distance_meters: float
    at_destination: bool
    based_on_stale_position: bool
    notes: tuple[str, ...] = ()


def evaluate_helper_location(
    position: HelperPosition | None,
    *,
    now: datetime,
    helper_id: str | None = None,
    config: HelperLocationConfig = DEFAULT_HELPER_LOCATION_CONFIG,
) -> HelperLocationStatus:
    """Label the last known helper position against ``now``."""

    if position is None:
        return HelperLocationStatus(
            helper_id=helper_id or "unknown",
            position=None,
            freshness=LocationFreshness.MISSING,
            age_seconds=None,
            evaluated_at=now,
            notes=("no_location_report_received",),
        )

    age = max(0.0, (now - position.reported_at).total_seconds())
    if age <= config.fresh_after.total_seconds():
        freshness = LocationFreshness.FRESH
    elif age <= config.stale_after.total_seconds():
        freshness = LocationFreshness.AGING
    else:
        freshness = LocationFreshness.STALE

    notes: list[str] = []
    if not position.page_visible:
        # A hidden helper page stops reporting; the last value keeps ageing.
        notes.append("helper_page_hidden_tracking_suspended")
    if (
        position.accuracy_meters is not None
        and position.accuracy_meters > config.poor_accuracy_meters
    ):
        notes.append(f"low_position_accuracy:{round(position.accuracy_meters)}m")
    if position.accuracy_meters is None:
        notes.append("position_accuracy_unknown")

    return HelperLocationStatus(
        helper_id=position.helper_id,
        position=position,
        freshness=freshness,
        age_seconds=age,
        evaluated_at=now,
        notes=tuple(notes),
    )


def assess_proximity(
    status: HelperLocationStatus,
    destination: GeoPoint,
    *,
    config: HelperLocationConfig = DEFAULT_HELPER_LOCATION_CONFIG,
) -> ProximityAssessment | None:
    """Compare the last known position to a destination.

    Returns ``None`` when no position is available. ``at_destination`` means
    the helper's own device reported being inside the arrival radius; it does
    not mean the helper arrived, entered, or obtained the AED.
    """

    if status.position is None:
        return None

    distance = haversine_meters(status.position.point, destination)
    notes = ["proximity_is_not_a_collection_report", *status.uncertainty_codes()]
    return ProximityAssessment(
        helper_id=status.helper_id,
        distance_meters=distance,
        at_destination=distance <= config.arrival_radius_meters,
        based_on_stale_position=status.is_stale,
        notes=tuple(notes),
    )
