"""Walking-route providers and labeled route estimates.

Provider details stay behind :class:`RouteProvider`. Every estimate records
how it was produced: a provider route, or an explicitly labeled straight-line
fallback. A straight-line result is a distance plus an assumption-derived
duration, and it is never presented as route precision.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Protocol

from data.aed.models import GeoPoint

from .geo import haversine_meters


class RouteEstimateSource(str, Enum):
    """How a route estimate was produced."""

    ROUTE_PROVIDER = "route_provider"
    STRAIGHT_LINE_FALLBACK = "straight_line_fallback"
    AT_DESTINATION = "at_destination"


class RouteFreshness(str, Enum):
    """Age classification of an estimate relative to the current instant."""

    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"


@dataclass(frozen=True)
class RouteEstimateConfig:
    """Assumptions used when no provider route is available."""

    # Straight-line distance multiplied by this factor approximates a walked
    # path. It is an assumption, not a measured route.
    detour_factor: float = 1.35
    walking_speed_mps: float = 1.35
    fresh_after: timedelta = timedelta(seconds=60)
    stale_after: timedelta = timedelta(seconds=180)


DEFAULT_ROUTE_ESTIMATE_CONFIG = RouteEstimateConfig()


@dataclass(frozen=True)
class RouteLeg:
    """A raw provider result for one origin/destination pair."""

    distance_meters: float
    duration_seconds: float
    provider: str
    computed_at: datetime


@dataclass(frozen=True)
class RouteEstimate:
    """A route estimate with explicit provenance, freshness, and uncertainty."""

    origin: GeoPoint
    destination: GeoPoint
    distance_meters: float
    duration_seconds: float
    source: RouteEstimateSource
    provider: str
    computed_at: datetime
    uncertainty: tuple[str, ...] = ()
    failure_reason: str | None = None
    config: RouteEstimateConfig = field(default=DEFAULT_ROUTE_ESTIMATE_CONFIG, repr=False)

    @property
    def is_route_based(self) -> bool:
        """True only when a route provider actually returned a route."""

        return self.source is RouteEstimateSource.ROUTE_PROVIDER

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.computed_at).total_seconds())

    def freshness_at(self, now: datetime) -> RouteFreshness:
        age = self.age_seconds(now)
        if age <= self.config.fresh_after.total_seconds():
            return RouteFreshness.FRESH
        if age <= self.config.stale_after.total_seconds():
            return RouteFreshness.AGING
        return RouteFreshness.STALE

    def describe(self, now: datetime) -> dict[str, Any]:
        """A display-ready summary that always carries its own caveats."""

        return {
            "distanceMeters": round(self.distance_meters, 1),
            "durationSeconds": round(self.duration_seconds, 1),
            "source": self.source.value,
            "provider": self.provider,
            "computedAt": self.computed_at.isoformat(),
            "ageSeconds": round(self.age_seconds(now), 1),
            "freshness": self.freshness_at(now).value,
            "routeBased": self.is_route_based,
            "uncertainty": list(self.uncertainty),
            "failureReason": self.failure_reason,
        }


class RouteProviderError(RuntimeError):
    """The provider could not produce a route."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)
        self.reason_code = reason_code
        self.detail = detail


class RouteProvider(Protocol):
    """Computes a walking route between two points."""

    @property
    def name(self) -> str: ...

    def walking_route(
        self, origin: GeoPoint, destination: GeoPoint, *, computed_at: datetime
    ) -> RouteLeg: ...


@dataclass(frozen=True)
class DeterministicFakeRouteProvider:
    """A deterministic stand-in for a real routing provider.

    This is an explicit mock: it derives a walked distance from the
    straight-line distance and a fixed speed, so tests and demonstrations do
    not call an external service. Results must never be presented as measured
    routes.
    """

    detour_factor: float = 1.4
    walking_speed_mps: float = 1.3
    fail_when: Callable[[GeoPoint, GeoPoint], bool] | None = None
    name: str = "deterministic-fake"

    def walking_route(
        self, origin: GeoPoint, destination: GeoPoint, *, computed_at: datetime
    ) -> RouteLeg:
        if self.fail_when is not None and self.fail_when(origin, destination):
            raise RouteProviderError("provider_unavailable", "fake provider configured to fail")
        straight = haversine_meters(origin, destination)
        distance = round(straight * self.detour_factor, 1)
        duration = round(distance / self.walking_speed_mps, 1)
        return RouteLeg(
            distance_meters=distance,
            duration_seconds=duration,
            provider=self.name,
            computed_at=computed_at,
        )


DEFAULT_HTTP_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class HttpRequest:
    """A provider-agnostic HTTP request handed to an injected transport.

    ``timeout_seconds`` is part of the transport contract: the adapter cannot
    interrupt a blocking call itself, so it passes the configured budget down
    and the transport is responsible for enforcing it. A transport that times
    out should raise ``TimeoutError``, which the adapter maps to the
    ``provider_timeout`` route-failure reason code.
    """

    method: str
    url: str
    headers: dict[str, str]
    body: str
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS


@dataclass(frozen=True)
class HttpResponse:
    """A provider-agnostic HTTP response returned by an injected transport."""

    status_code: int
    body: str


@dataclass(frozen=True)
class GoogleRoutesProvider:
    """Adapter for the Google Routes computeRoutes walking mode.

    The HTTP transport is injected, so this module adds no networking
    dependency and no test ever reaches the network. The API key is read from
    the environment at call time and is never stored in the repository.
    """

    transport: Callable[[HttpRequest], HttpResponse]
    api_key_env: str = "GOOGLE_ROUTES_API_KEY"
    endpoint: str = "https://routes.googleapis.com/directions/v2:computeRoutes"
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS
    name: str = "google-routes"

    def walking_route(
        self, origin: GeoPoint, destination: GeoPoint, *, computed_at: datetime
    ) -> RouteLeg:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise RouteProviderError(
                "invalid_timeout", "timeout_seconds must be finite and greater than zero"
            )
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            raise RouteProviderError(
                "missing_credentials", f"{self.api_key_env} is not configured"
            )

        request = HttpRequest(
            method="POST",
            url=self.endpoint,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "routes.distanceMeters,routes.duration",
            },
            body=json.dumps(
                {
                    "origin": _waypoint(origin),
                    "destination": _waypoint(destination),
                    "travelMode": "WALK",
                    "units": "METRIC",
                }
            ),
            timeout_seconds=self.timeout_seconds,
        )

        try:
            response = self.transport(request)
        except TimeoutError as exc:
            raise RouteProviderError(
                "provider_timeout", f"no response within {self.timeout_seconds}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - any transport failure is a route failure
            raise RouteProviderError("transport_error", str(exc)) from exc

        if response.status_code != 200:
            raise RouteProviderError("provider_http_error", f"status {response.status_code}")

        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise RouteProviderError("invalid_provider_response", str(exc)) from exc

        routes = payload.get("routes") if isinstance(payload, dict) else None
        if not isinstance(routes, list) or not routes:
            raise RouteProviderError("no_route_found", "provider returned no routes")

        route = routes[0]
        distance = _finite_nonnegative(route.get("distanceMeters"))
        duration = _parse_duration_seconds(route.get("duration"))
        if distance is None or duration is None:
            raise RouteProviderError(
                "invalid_provider_response", f"unusable route fields: {route!r}"
            )

        return RouteLeg(
            distance_meters=distance,
            duration_seconds=duration,
            provider=self.name,
            computed_at=computed_at,
        )


def estimate_walking_route(
    provider: RouteProvider,
    origin: GeoPoint,
    destination: GeoPoint,
    *,
    now: datetime,
    config: RouteEstimateConfig = DEFAULT_ROUTE_ESTIMATE_CONFIG,
    extra_uncertainty: tuple[str, ...] = (),
) -> RouteEstimate:
    """Ask the provider for a route, falling back to a labeled straight line."""

    try:
        leg = provider.walking_route(origin, destination, computed_at=now)
    except RouteProviderError as exc:
        return straight_line_estimate(
            origin,
            destination,
            now=now,
            config=config,
            failure_reason=exc.reason_code,
            extra_uncertainty=extra_uncertainty,
        )

    return RouteEstimate(
        origin=origin,
        destination=destination,
        distance_meters=leg.distance_meters,
        duration_seconds=leg.duration_seconds,
        source=RouteEstimateSource.ROUTE_PROVIDER,
        provider=leg.provider,
        computed_at=leg.computed_at,
        uncertainty=extra_uncertainty,
        config=config,
    )


def straight_line_estimate(
    origin: GeoPoint,
    destination: GeoPoint,
    *,
    now: datetime,
    config: RouteEstimateConfig = DEFAULT_ROUTE_ESTIMATE_CONFIG,
    failure_reason: str | None = None,
    extra_uncertainty: tuple[str, ...] = (),
) -> RouteEstimate:
    """A straight-line distance with an assumption-derived walking duration."""

    straight = haversine_meters(origin, destination)
    distance = straight * config.detour_factor
    uncertainty = (
        "straight_line_distance_not_a_walking_route",
        "duration_derived_from_assumed_walking_speed",
        *extra_uncertainty,
    )
    if failure_reason:
        uncertainty = (f"route_provider_failed:{failure_reason}", *uncertainty)
    return RouteEstimate(
        origin=origin,
        destination=destination,
        distance_meters=distance,
        duration_seconds=distance / config.walking_speed_mps,
        source=RouteEstimateSource.STRAIGHT_LINE_FALLBACK,
        provider="straight-line",
        computed_at=now,
        uncertainty=uncertainty,
        failure_reason=failure_reason,
        config=config,
    )


def at_destination_estimate(
    point: GeoPoint,
    *,
    now: datetime,
    distance_meters: float,
    config: RouteEstimateConfig = DEFAULT_ROUTE_ESTIMATE_CONFIG,
) -> RouteEstimate:
    """A zero-duration leg for a helper already standing at the destination.

    Reported proximity is a location report, not a confirmation that the
    helper has reached, opened, or collected the AED.
    """

    return RouteEstimate(
        origin=point,
        destination=point,
        distance_meters=distance_meters,
        duration_seconds=0.0,
        source=RouteEstimateSource.AT_DESTINATION,
        provider="proximity",
        computed_at=now,
        uncertainty=(
            "helper_reported_within_arrival_radius",
            "proximity_is_not_a_collection_report",
        ),
        config=config,
    )


def _waypoint(point: GeoPoint) -> dict[str, Any]:
    return {"location": {"latLng": {"latitude": point.latitude, "longitude": point.longitude}}}


def _finite_nonnegative(value: Any) -> float | None:
    """Accept only a real, finite, non-negative number.

    ``bool`` is excluded explicitly because it is a subclass of ``int``, and
    NaN / infinity are rejected so they cannot flow into an estimate and make
    a total silently meaningless.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _parse_duration_seconds(value: Any) -> float | None:
    """Parse the Routes API duration form, for example 123s."""

    if isinstance(value, str):
        if not value.endswith("s"):
            return None
        try:
            value = float(value[:-1])
        except ValueError:
            return None
    return _finite_nonnegative(value)
