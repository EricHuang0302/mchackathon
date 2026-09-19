"""Outbound and return-time estimates for an AED retrieval run.

The total is presented as three visible components, never as a single opaque
number:

1. outbound   helper to AED
2. retrieval  a labeled assumption for locating and collecting the device
3. return     AED to patient

After collection only the remaining helper-to-patient leg is estimated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from data.aed.models import GeoPoint

from .helpers import (
    DEFAULT_HELPER_LOCATION_CONFIG,
    HelperLocationConfig,
    HelperLocationStatus,
    assess_proximity,
)
from .routing import (
    DEFAULT_ROUTE_ESTIMATE_CONFIG,
    RouteEstimate,
    RouteEstimateConfig,
    RouteProvider,
    at_destination_estimate,
    estimate_walking_route,
)


@dataclass(frozen=True)
class RetrievalAssumption:
    """A labeled, non-measured allowance for collecting the device."""

    seconds: float
    label: str

    def describe(self) -> dict[str, Any]:
        return {"seconds": self.seconds, "label": self.label, "measured": False}


DEFAULT_RETRIEVAL_ASSUMPTION = RetrievalAssumption(
    seconds=60.0,
    label="assumed_time_to_locate_and_collect_the_aed",
)


@dataclass(frozen=True)
class RetrievalEstimate:
    """A full runner round trip with every component and caveat visible."""

    helper_id: str
    aed_id: str
    outbound: RouteEstimate
    retrieval_assumption: RetrievalAssumption
    return_leg: RouteEstimate
    computed_at: datetime
    helper_location: HelperLocationStatus | None = None
    uncertainty: tuple[str, ...] = ()

    @property
    def total_seconds(self) -> float:
        return (
            self.outbound.duration_seconds
            + self.retrieval_assumption.seconds
            + self.return_leg.duration_seconds
        )

    @property
    def fully_route_based(self) -> bool:
        """False whenever any leg fell back to a straight line."""

        return self.outbound.is_route_based and self.return_leg.is_route_based

    def describe(self, now: datetime) -> dict[str, Any]:
        return {
            "helperId": self.helper_id,
            "aedId": self.aed_id,
            "components": {
                "outbound": self.outbound.describe(now),
                "retrievalAssumption": self.retrieval_assumption.describe(),
                "return": self.return_leg.describe(now),
            },
            "totalSeconds": round(self.total_seconds, 1),
            "fullyRouteBased": self.fully_route_based,
            "uncertainty": list(self.uncertainty),
        }


def estimate_retrieval(
    provider: RouteProvider,
    *,
    helper_location: HelperLocationStatus,
    aed_id: str,
    aed_point: GeoPoint,
    patient_point: GeoPoint,
    now: datetime,
    route_config: RouteEstimateConfig = DEFAULT_ROUTE_ESTIMATE_CONFIG,
    location_config: HelperLocationConfig = DEFAULT_HELPER_LOCATION_CONFIG,
    retrieval_assumption: RetrievalAssumption = DEFAULT_RETRIEVAL_ASSUMPTION,
) -> RetrievalEstimate:
    """Estimate the outbound and return legs for one retrieval assignment.

    When the helper's own device reports being inside the arrival radius, the
    outbound leg collapses to zero and is labeled as a proximity report rather
    than a measured arrival.
    """

    helper_uncertainty = helper_location.uncertainty_codes()
    proximity = assess_proximity(helper_location, aed_point, config=location_config)

    if helper_location.position is None:
        # With no helper position, anchor the outbound leg on the patient.
        outbound = estimate_walking_route(
            provider,
            patient_point,
            aed_point,
            now=now,
            config=route_config,
            extra_uncertainty=(
                "outbound_anchored_on_patient_location",
                *helper_uncertainty,
            ),
        )
    elif proximity is not None and proximity.at_destination:
        outbound = at_destination_estimate(
            helper_location.position.point,
            now=now,
            distance_meters=proximity.distance_meters,
            config=route_config,
        )
    else:
        outbound = estimate_walking_route(
            provider,
            helper_location.position.point,
            aed_point,
            now=now,
            config=route_config,
            extra_uncertainty=helper_uncertainty,
        )

    return_leg = estimate_walking_route(
        provider,
        aed_point,
        patient_point,
        now=now,
        config=route_config,
    )

    uncertainty: list[str] = [f"retrieval_time_assumed:{retrieval_assumption.label}"]
    uncertainty.extend(helper_uncertainty)
    if not outbound.is_route_based:
        uncertainty.append(f"outbound_{outbound.source.value}")
    if not return_leg.is_route_based:
        uncertainty.append(f"return_{return_leg.source.value}")

    return RetrievalEstimate(
        helper_id=helper_location.helper_id,
        aed_id=aed_id,
        outbound=outbound,
        retrieval_assumption=retrieval_assumption,
        return_leg=return_leg,
        computed_at=now,
        helper_location=helper_location,
        uncertainty=tuple(dict.fromkeys(uncertainty)),
    )


def estimate_remaining_after_collection(
    provider: RouteProvider,
    *,
    helper_location: HelperLocationStatus,
    patient_point: GeoPoint,
    now: datetime,
    route_config: RouteEstimateConfig = DEFAULT_ROUTE_ESTIMATE_CONFIG,
) -> RouteEstimate:
    """Estimate only the remaining helper-to-patient leg after collection.

    A collection report is a helper report. This function estimates travel from
    the last known helper position and inherits that position's caveats.
    """

    uncertainty = ("post_collection_remaining_leg", *helper_location.uncertainty_codes())
    if helper_location.position is None:
        raise ValueError("cannot estimate the remaining leg without a helper position")

    return estimate_walking_route(
        provider,
        helper_location.position.point,
        patient_point,
        now=now,
        config=route_config,
        extra_uncertainty=uncertainty,
    )
