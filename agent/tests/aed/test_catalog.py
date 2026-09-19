from __future__ import annotations

import pytest

from app.services.aed.catalog import AedCatalogService
from app.services.aed.routing import DeterministicFakeRouteProvider

from .conftest import PATIENT_POINT, WEDNESDAY_MORNING_UTC, make_record


def test_maps_candidates_to_existing_transport_contract() -> None:
    record = make_record(
        "catalog",
        latitude=25.0472,
        longitude=121.5172,
        name="Synthetic Catalog AED",
    )
    service = AedCatalogService(
        [record], route_provider=DeterministicFakeRouteProvider()
    )

    response = service.list_candidates(
        origin=PATIENT_POINT,
        at=WEDNESDAY_MORNING_UTC,
        limit=10,
    )

    assert len(response.candidates) == 1
    candidate = response.candidates[0]
    assert candidate.aedId == record.stable_id
    assert candidate.latitude == record.latitude
    assert candidate.longitude == record.longitude
    assert candidate.address == record.address
    assert candidate.accessNotes == record.access_notes
    assert candidate.availability == "available"
    assert candidate.estimateSource == "route"
    assert candidate.etaSeconds is not None
    assert response.dataUpdatedAt == record.source_updated_at


@pytest.mark.parametrize("limit", [0, 21, True])
def test_requires_bounded_integer_limit(limit: object) -> None:
    service = AedCatalogService([])

    with pytest.raises(ValueError, match="between 1 and 20"):
        service.list_candidates(
            origin=PATIENT_POINT,
            at=WEDNESDAY_MORNING_UTC,
            limit=limit,  # type: ignore[arg-type]
        )


def test_straight_line_fallback_never_exposes_walking_eta() -> None:
    record = make_record("fallback", latitude=25.0472, longitude=121.5172)
    response = AedCatalogService([record]).list_candidates(
        origin=PATIENT_POINT,
        at=WEDNESDAY_MORNING_UTC,
        limit=1,
    )

    candidate = response.candidates[0]
    assert candidate.estimateSource == "straight_line"
    assert candidate.walkingMeters is None
    assert candidate.etaSeconds is None
    assert candidate.routeUpdatedAt is None
