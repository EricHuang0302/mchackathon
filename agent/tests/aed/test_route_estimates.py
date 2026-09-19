"""Route providers, fallback labeling, and retrieval estimates."""

from __future__ import annotations

from datetime import timedelta

import pytest

from data.aed.models import GeoPoint

from app.services.aed.retrieval import (
    DEFAULT_RETRIEVAL_ASSUMPTION,
    estimate_remaining_after_collection,
    estimate_retrieval,
)
from app.services.aed.routing import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DeterministicFakeRouteProvider,
    GoogleRoutesProvider,
    HttpResponse,
    RouteEstimateSource,
    RouteFreshness,
    RouteProviderError,
    estimate_walking_route,
)
from .conftest import HELPER_POINT, PATIENT_POINT, helper_status_at

AED_POINT = GeoPoint(latitude=25.0500, longitude=121.5200)


def test_fake_provider_is_deterministic(now):
    provider = DeterministicFakeRouteProvider()

    first = estimate_walking_route(provider, HELPER_POINT, AED_POINT, now=now)
    second = estimate_walking_route(provider, HELPER_POINT, AED_POINT, now=now)

    assert first.distance_meters == second.distance_meters
    assert first.duration_seconds == second.duration_seconds
    assert first.source is RouteEstimateSource.ROUTE_PROVIDER
    assert first.is_route_based is True
    assert first.uncertainty == ()


def test_route_failure_falls_back_to_a_labeled_straight_line(now):
    """Scenario: route provider failure."""

    provider = DeterministicFakeRouteProvider(fail_when=lambda origin, destination: True)

    estimate = estimate_walking_route(provider, HELPER_POINT, AED_POINT, now=now)

    assert estimate.source is RouteEstimateSource.STRAIGHT_LINE_FALLBACK
    assert estimate.is_route_based is False
    assert estimate.failure_reason == "provider_unavailable"
    assert "route_provider_failed:provider_unavailable" in estimate.uncertainty
    assert "straight_line_distance_not_a_walking_route" in estimate.uncertainty
    assert "duration_derived_from_assumed_walking_speed" in estimate.uncertainty
    described = estimate.describe(now)
    assert described["routeBased"] is False
    assert described["source"] == "straight_line_fallback"


def test_estimate_freshness_degrades_with_age(now):
    provider = DeterministicFakeRouteProvider()
    estimate = estimate_walking_route(provider, HELPER_POINT, AED_POINT, now=now)

    assert estimate.freshness_at(now) is RouteFreshness.FRESH
    assert estimate.freshness_at(now + timedelta(seconds=90)) is RouteFreshness.AGING
    assert estimate.freshness_at(now + timedelta(seconds=600)) is RouteFreshness.STALE
    assert estimate.describe(now + timedelta(seconds=600))["ageSeconds"] == 600.0


def test_google_routes_adapter_maps_a_successful_response(now, monkeypatch):
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "synthetic-test-key")
    captured = {}

    def transport(request):
        captured["request"] = request
        return HttpResponse(
            status_code=200,
            body='{"routes": [{"distanceMeters": 812, "duration": "654s"}]}',
        )

    provider = GoogleRoutesProvider(transport=transport)
    estimate = estimate_walking_route(provider, HELPER_POINT, AED_POINT, now=now)

    assert estimate.is_route_based is True
    assert estimate.distance_meters == 812.0
    assert estimate.duration_seconds == 654.0
    assert estimate.provider == "google-routes"
    request = captured["request"]
    assert request.headers["X-Goog-Api-Key"] == "synthetic-test-key"
    assert "routes.distanceMeters" in request.headers["X-Goog-FieldMask"]
    assert '"travelMode": "WALK"' in request.body


def test_google_routes_adapter_without_credentials_raises(now, monkeypatch):
    monkeypatch.delenv("GOOGLE_ROUTES_API_KEY", raising=False)
    provider = GoogleRoutesProvider(transport=lambda request: HttpResponse(200, "{}"))

    with pytest.raises(RouteProviderError) as excinfo:
        provider.walking_route(HELPER_POINT, AED_POINT, computed_at=now)

    assert excinfo.value.reason_code == "missing_credentials"


@pytest.mark.parametrize(
    ("response", "reason_code"),
    [
        (HttpResponse(500, ""), "provider_http_error"),
        (HttpResponse(200, "not json"), "invalid_provider_response"),
        (HttpResponse(200, '{"routes": []}'), "no_route_found"),
        (HttpResponse(200, '{"routes": [{"duration": "12s"}]}'), "invalid_provider_response"),
        (HttpResponse(200, '{"routes": [{"distanceMeters": 5, "duration": "x"}]}'), "invalid_provider_response"),
    ],
)
def test_google_routes_adapter_rejects_unusable_responses(
    now, monkeypatch, response, reason_code
):
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "synthetic-test-key")
    provider = GoogleRoutesProvider(transport=lambda request: response)

    with pytest.raises(RouteProviderError) as excinfo:
        provider.walking_route(HELPER_POINT, AED_POINT, computed_at=now)

    assert excinfo.value.reason_code == reason_code


def test_google_routes_transport_exception_becomes_a_route_failure(now, monkeypatch):
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "synthetic-test-key")

    def transport(request):
        raise ConnectionError("synthetic transport failure")

    provider = GoogleRoutesProvider(transport=transport)
    estimate = estimate_walking_route(provider, HELPER_POINT, AED_POINT, now=now)

    assert estimate.source is RouteEstimateSource.STRAIGHT_LINE_FALLBACK
    assert estimate.failure_reason == "transport_error"


def test_configured_timeout_reaches_the_injected_transport(now, monkeypatch):
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "synthetic-test-key")
    seen = {}

    def transport(request):
        seen["timeout"] = request.timeout_seconds
        return HttpResponse(
            status_code=200,
            body='{"routes": [{"distanceMeters": 100, "duration": "80s"}]}',
        )

    provider = GoogleRoutesProvider(transport=transport, timeout_seconds=2.5)
    provider.walking_route(HELPER_POINT, AED_POINT, computed_at=now)

    assert seen["timeout"] == 2.5


def test_default_timeout_is_communicated_when_not_overridden(now, monkeypatch):
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "synthetic-test-key")
    seen = {}

    def transport(request):
        seen["timeout"] = request.timeout_seconds
        return HttpResponse(
            status_code=200,
            body='{"routes": [{"distanceMeters": 100, "duration": "80s"}]}',
        )

    GoogleRoutesProvider(transport=transport).walking_route(
        HELPER_POINT, AED_POINT, computed_at=now
    )

    assert seen["timeout"] == DEFAULT_HTTP_TIMEOUT_SECONDS


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_is_rejected_before_transport(now, monkeypatch, timeout):
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "synthetic-test-key")
    called = False

    def transport(request):
        nonlocal called
        called = True
        return HttpResponse(200, "{}")

    provider = GoogleRoutesProvider(transport=transport, timeout_seconds=timeout)

    with pytest.raises(RouteProviderError) as excinfo:
        provider.walking_route(HELPER_POINT, AED_POINT, computed_at=now)

    assert excinfo.value.reason_code == "invalid_timeout"
    assert called is False


def test_transport_timeout_is_reported_as_provider_timeout(now, monkeypatch):
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "synthetic-test-key")

    def transport(request):
        raise TimeoutError(f"exceeded {request.timeout_seconds}s")

    provider = GoogleRoutesProvider(transport=transport, timeout_seconds=0.25)

    with pytest.raises(RouteProviderError) as excinfo:
        provider.walking_route(HELPER_POINT, AED_POINT, computed_at=now)
    assert excinfo.value.reason_code == "provider_timeout"

    estimate = estimate_walking_route(provider, HELPER_POINT, AED_POINT, now=now)
    assert estimate.source is RouteEstimateSource.STRAIGHT_LINE_FALLBACK
    assert estimate.failure_reason == "provider_timeout"
    assert "route_provider_failed:provider_timeout" in estimate.uncertainty


@pytest.mark.parametrize(
    "route",
    [
        '{"distanceMeters": true, "duration": "10s"}',
        '{"distanceMeters": -5, "duration": "10s"}',
        '{"distanceMeters": 5, "duration": "-10s"}',
        '{"distanceMeters": 5, "duration": "NaNs"}',
        '{"distanceMeters": 5, "duration": "Infinitys"}',
        '{"distanceMeters": 5, "duration": true}',
    ],
)
def test_non_finite_or_negative_route_values_are_rejected(now, monkeypatch, route):
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "synthetic-test-key")
    provider = GoogleRoutesProvider(
        transport=lambda request: HttpResponse(200, f'{{"routes": [{route}]}}')
    )

    with pytest.raises(RouteProviderError) as excinfo:
        provider.walking_route(HELPER_POINT, AED_POINT, computed_at=now)

    assert excinfo.value.reason_code == "invalid_provider_response"


def test_retrieval_estimate_keeps_outbound_return_and_assumption_separate(now, fresh_helper):
    provider = DeterministicFakeRouteProvider()

    estimate = estimate_retrieval(
        provider,
        helper_location=fresh_helper,
        aed_id="synthetic-demo:aed-1",
        aed_point=AED_POINT,
        patient_point=PATIENT_POINT,
        now=now,
    )

    assert estimate.outbound.destination == AED_POINT
    assert estimate.return_leg.origin == AED_POINT
    assert estimate.return_leg.destination == PATIENT_POINT
    assert estimate.retrieval_assumption is DEFAULT_RETRIEVAL_ASSUMPTION
    assert estimate.total_seconds == pytest.approx(
        estimate.outbound.duration_seconds
        + DEFAULT_RETRIEVAL_ASSUMPTION.seconds
        + estimate.return_leg.duration_seconds
    )
    assert estimate.fully_route_based is True
    described = estimate.describe(now)
    assert described["components"]["retrievalAssumption"]["measured"] is False
    assert any(code.startswith("retrieval_time_assumed") for code in estimate.uncertainty)


def test_helper_already_at_the_aed_collapses_the_outbound_leg(now):
    """Scenario: helper is already at the AED."""

    provider = DeterministicFakeRouteProvider()
    at_aed = helper_status_at(AED_POINT, reported_at=now, now=now)

    estimate = estimate_retrieval(
        provider,
        helper_location=at_aed,
        aed_id="synthetic-demo:aed-1",
        aed_point=AED_POINT,
        patient_point=PATIENT_POINT,
        now=now,
    )

    assert estimate.outbound.source is RouteEstimateSource.AT_DESTINATION
    assert estimate.outbound.duration_seconds == 0.0
    assert "proximity_is_not_a_collection_report" in estimate.outbound.uncertainty
    assert estimate.fully_route_based is False
    assert estimate.total_seconds == pytest.approx(
        DEFAULT_RETRIEVAL_ASSUMPTION.seconds + estimate.return_leg.duration_seconds
    )


def test_retrieval_without_a_helper_position_anchors_on_the_patient(now):
    provider = DeterministicFakeRouteProvider()
    from app.services.aed.helpers import evaluate_helper_location

    missing = evaluate_helper_location(None, now=now, helper_id="helper-1")

    estimate = estimate_retrieval(
        provider,
        helper_location=missing,
        aed_id="synthetic-demo:aed-1",
        aed_point=AED_POINT,
        patient_point=PATIENT_POINT,
        now=now,
    )

    assert "outbound_anchored_on_patient_location" in estimate.outbound.uncertainty
    assert "helper_position_unknown" in estimate.uncertainty


def test_remaining_leg_after_collection_covers_helper_to_patient(now, fresh_helper):
    provider = DeterministicFakeRouteProvider()

    estimate = estimate_remaining_after_collection(
        provider,
        helper_location=fresh_helper,
        patient_point=PATIENT_POINT,
        now=now,
    )

    assert estimate.origin == HELPER_POINT
    assert estimate.destination == PATIENT_POINT
    assert "post_collection_remaining_leg" in estimate.uncertainty
