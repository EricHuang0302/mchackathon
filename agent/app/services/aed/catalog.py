"""Transport-model adapter for bounded AED candidate queries."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable

from app.schemas.contracts import AedCandidate as AedCandidateResponse
from app.schemas.contracts import AedListResponse
from data.aed.models import AedRecord, AvailabilityStatus, GeoPoint

from .candidates import CandidateSearchConfig, find_candidates
from .routing import (
    RouteEstimateConfig,
    RouteProvider,
    estimate_walking_route,
    straight_line_estimate,
)


class AedCatalogService:
    """Map AED domain results to the existing Workstream 1 response contract.

    The caller must supply an authorized incident origin. The current HTTP
    contract does not carry or persist that origin, so this adapter deliberately
    does not guess it from an incident identifier.
    """

    def __init__(
        self,
        records: Iterable[AedRecord],
        *,
        route_provider: RouteProvider | None = None,
        search_config: CandidateSearchConfig | None = None,
        route_config: RouteEstimateConfig | None = None,
    ) -> None:
        self._records = tuple(records)
        self._route_provider = route_provider
        self._search_config = search_config or CandidateSearchConfig()
        self._route_config = route_config or RouteEstimateConfig()

    def list_candidates(
        self,
        *,
        origin: GeoPoint,
        at: datetime,
        limit: int,
        excluded_ids: Iterable[str] = (),
    ) -> AedListResponse:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("limit must be an integer between 1 and 20")
        result = find_candidates(
            self._records,
            origin,
            at=at,
            config=replace(self._search_config, limit=limit),
            excluded_ids=excluded_ids,
        )
        candidates = []
        for candidate in result.candidates:
            if self._route_provider is None:
                estimate = straight_line_estimate(
                    origin,
                    candidate.record.point,
                    now=at,
                    config=self._route_config,
                    failure_reason="route_provider_not_configured",
                )
            else:
                estimate = estimate_walking_route(
                    self._route_provider,
                    origin,
                    candidate.record.point,
                    now=at,
                    config=self._route_config,
                )
            availability = {
                AvailabilityStatus.OPEN: "available",
                AvailabilityStatus.CLOSED: "unavailable",
                AvailabilityStatus.UNKNOWN: "unknown",
            }[candidate.availability.status]
            route_based = estimate.is_route_based
            candidates.append(
                AedCandidateResponse(
                    aedId=candidate.stable_id,
                    name=candidate.record.name,
                    latitude=candidate.record.latitude,
                    longitude=candidate.record.longitude,
                    address=candidate.record.address,
                    accessNotes=candidate.record.access_notes,
                    availability=availability,
                    straightLineMeters=round(candidate.straight_line_meters, 1),
                    walkingMeters=round(estimate.distance_meters, 1) if route_based else None,
                    etaSeconds=round(estimate.duration_seconds) if route_based else None,
                    routeUpdatedAt=estimate.computed_at if route_based else None,
                    estimateSource="route" if route_based else "straight_line",
                )
            )
        updated = max(
            (
                record.source_updated_at or record.ingested_at
                for record in self._records
            ),
            default=None,
        )
        return AedListResponse(candidates=candidates, dataUpdatedAt=updated)
