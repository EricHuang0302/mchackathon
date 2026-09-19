"""Region bounds used to reject out-of-region coordinates.

The bounding box is configuration, not a constant of the problem. It is
defined once here so validators do not inline their own copies. The default
covers Taiwan including the outlying islands (Kinmen, Matsu, Penghu).
"""

from __future__ import annotations

from dataclasses import dataclass

from data.aed.models import GeoPoint


@dataclass(frozen=True)
class RegionBounds:
    """Inclusive latitude/longitude bounds for an accepted service region."""

    name: str
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float

    def contains(self, point: GeoPoint) -> bool:
        return (
            self.min_latitude <= point.latitude <= self.max_latitude
            and self.min_longitude <= point.longitude <= self.max_longitude
        )


TAIWAN_REGION = RegionBounds(
    name="taiwan",
    min_latitude=21.5,
    max_latitude=26.5,
    min_longitude=118.0,
    max_longitude=122.5,
)

DEFAULT_REGION = TAIWAN_REGION
