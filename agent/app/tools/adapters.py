from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

from app.api.errors import ApiError, stale, unavailable
from app.schemas.contracts import (
    CreateShareRequest,
    EventBatchRequest,
    LocationDescriptionRequest,
    SceneObservationRequest,
    Scope,
)
from app.services.ports import IncidentService


@dataclass(frozen=True)
class ToolContext:
    actor_uid: str
    incident_id: UUID
    expected_state_revision: int
    expected_mode_revision: int
    authority_epoch: int


class ToolAdapters:
    """Only server-created contexts can invoke the Workstream 5 service port."""

    def __init__(self, service: IncidentService):
        self.service = service

    def _check(self, context: ToolContext):
        view = self.service.authorize(context.actor_uid, context.incident_id, {"primary"})
        if context.authority_epoch != view.authorityEpoch:
            raise stale("authorityEpoch", view.authorityEpoch)
        if context.expected_state_revision != view.stateRevision:
            raise stale("stateRevision", view.stateRevision)
        if context.expected_mode_revision != view.modeRevision:
            raise stale("modeRevision", view.modeRevision)
        return view

    def log_event(self, context: ToolContext, body: EventBatchRequest):
        self._check(context)
        return self.service.upload_events(context.actor_uid, context.incident_id, body)

    def find_nearest_aeds(self, context: ToolContext, limit: int):
        self._check(context)
        if not 1 <= limit <= 20:
            raise ApiError("invalid_input", 400, "Invalid AED limit")
        return self.service.list_aeds(context.actor_uid, context.incident_id, limit)

    def update_scene_snapshot(self, context: ToolContext, body: SceneObservationRequest):
        self._check(context)
        return self.service.add_observations(context.actor_uid, context.incident_id, body)

    def describe_location(self, context: ToolContext, body: LocationDescriptionRequest):
        self._check(context)
        return self.service.describe_location(context.actor_uid, context.incident_id, body)

    def get_next_step(self, context: ToolContext, observations: list[dict]):
        self._check(context)
        raise unavailable()  # Requires Workstream 5 pinned rules.

    def dispatch_helper(self, context: ToolContext, role: str):
        self._check(context)
        try:
            scope = Scope(role)
        except ValueError:
            raise ApiError("invalid_input", 400, "Unsupported helper role") from None
        if scope not in {Scope.RUNNER, Scope.GREETER}:
            raise ApiError("invalid_input", 400, "Unsupported helper role")
        helper_id = uuid5(context.incident_id, f"gemini-helper:{scope.value}")
        idempotency_key = uuid5(context.incident_id, f"gemini-invite:{scope.value}")
        invite = self.service.create_share(
            context.actor_uid,
            context.incident_id,
            CreateShareRequest(
                scope=scope,
                helperId=helper_id,
                expiresInSeconds=300,
                idempotencyKey=idempotency_key,
            ),
        )
        return {
            "helperId": str(helper_id),
            **invite.model_dump(mode="json"),
        }

    def get_helper_status(self, context: ToolContext):
        self._check(context)
        raise unavailable()

    def analyze_scene(self, context: ToolContext, image: bytes):
        self._check(context)
        raise unavailable()
