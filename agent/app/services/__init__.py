"""AED data and routing services.

This package holds the workstream 5 services that the Flask API and the Agent
tools call into: bounded candidate search, availability evaluation, walking
route estimates behind a provider adapter, helper-location freshness, and
unavailable-AED reassignment.

Boundaries kept deliberately: no Flask routes, no request/response schemas, no
Gemini or ADK integration, no Firestore persistence, and no clinical rules.
"""

from agent.app.services.assignment import (
    AedAssignment,
    AedAssignmentService,
    AssignmentStatus,
    AssignmentStore,
    InMemoryAssignmentStore,
    ReassignmentOutcome,
    ReassignmentResult,
    UnavailabilityReport,
)
from agent.app.services.availability import AvailabilityAssessment, evaluate_availability
from agent.app.services.candidates import (
    AedCandidate,
    CandidateSearchConfig,
    CandidateSearchResult,
    find_candidates,
    rank_candidates,
)
from agent.app.services.geo import BoundingBox, bounding_box, haversine_meters
from agent.app.services.helpers import (
    HelperLocationConfig,
    HelperLocationStatus,
    HelperPosition,
    LocationFreshness,
    ProximityAssessment,
    assess_proximity,
    evaluate_helper_location,
)
from agent.app.services.retrieval import (
    RetrievalAssumption,
    RetrievalEstimate,
    estimate_remaining_after_collection,
    estimate_retrieval,
)
from agent.app.services.routing import (
    DeterministicFakeRouteProvider,
    GoogleRoutesProvider,
    HttpRequest,
    HttpResponse,
    RouteEstimate,
    RouteEstimateConfig,
    RouteEstimateSource,
    RouteFreshness,
    RouteLeg,
    RouteProvider,
    RouteProviderError,
    estimate_walking_route,
    straight_line_estimate,
)

__all__ = [
    "AedAssignment",
    "AedAssignmentService",
    "AedCandidate",
    "AssignmentStatus",
    "AssignmentStore",
    "AvailabilityAssessment",
    "BoundingBox",
    "CandidateSearchConfig",
    "CandidateSearchResult",
    "DeterministicFakeRouteProvider",
    "GoogleRoutesProvider",
    "HelperLocationConfig",
    "HelperLocationStatus",
    "HelperPosition",
    "HttpRequest",
    "HttpResponse",
    "InMemoryAssignmentStore",
    "LocationFreshness",
    "ProximityAssessment",
    "ReassignmentOutcome",
    "ReassignmentResult",
    "RetrievalAssumption",
    "RetrievalEstimate",
    "RouteEstimate",
    "RouteEstimateConfig",
    "RouteEstimateSource",
    "RouteFreshness",
    "RouteLeg",
    "RouteProvider",
    "RouteProviderError",
    "UnavailabilityReport",
    "assess_proximity",
    "bounding_box",
    "estimate_remaining_after_collection",
    "estimate_retrieval",
    "estimate_walking_route",
    "evaluate_availability",
    "evaluate_helper_location",
    "find_candidates",
    "haversine_meters",
    "rank_candidates",
    "straight_line_estimate",
]
