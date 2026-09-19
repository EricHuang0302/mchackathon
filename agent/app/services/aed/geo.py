"""Geographic helpers shared by the AED services."""

from __future__ import annotations

import math
from dataclasses import dataclass

from data.aed.models import GeoPoint

EARTH_RADIUS_METERS = 6_371_008.8
METERS_PER_DEGREE_LATITUDE = 111_320.0


@dataclass(frozen=True)
class BoundingBox:
    """Latitude/longitude bounds used as a cheap prefilter."""

    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float

    def contains(self, point: GeoPoint) -> bool:
        return (
            self.min_latitude <= point.latitude <= self.max_latitude
            and self.min_longitude <= point.longitude <= self.max_longitude
        )


def haversine_meters(origin: GeoPoint, destination: GeoPoint) -> float:
    """Great-circle distance in meters. This is a straight line, not a route."""

    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(destination.latitude)
    delta_lat = lat2 - lat1
    delta_lng = math.radians(destination.longitude - origin.longitude)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(a)))


def bounding_box(center: GeoPoint, radius_meters: float) -> BoundingBox:
    """A bounding box that fully contains ``radius_meters`` around ``center``."""

    delta_lat = radius_meters / METERS_PER_DEGREE_LATITUDE
    cos_lat = math.cos(math.radians(center.latitude))
    # Guard against the degenerate longitude scale near the poles.
    meters_per_degree_lng = max(METERS_PER_DEGREE_LATITUDE * cos_lat, 1.0)
    delta_lng = radius_meters / meters_per_degree_lng
    return BoundingBox(
        min_latitude=center.latitude - delta_lat,
        max_latitude=center.latitude + delta_lat,
        min_longitude=center.longitude - delta_lng,
        max_longitude=center.longitude + delta_lng,
    )
