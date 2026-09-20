from __future__ import annotations

from typing import Any
from uuid import UUID

from app.api.errors import ApiError
from app.services.ports import IncidentService
from app.tools.adapters import ToolAdapters, ToolContext


class LiveAgentToolExecutor:
    """Execute only the bounded application tools exposed to Gemini Live."""

    def __init__(self, service: IncidentService, actor_uid: str, incident_id: UUID):
        self.service = service
        self.actor_uid = actor_uid
        self.incident_id = incident_id
        self.adapters = ToolAdapters(service)

    def _context(self) -> ToolContext:
        view = self.service.authorize(self.actor_uid, self.incident_id, {"primary"})
        return ToolContext(
            actor_uid=self.actor_uid,
            incident_id=self.incident_id,
            expected_state_revision=view.stateRevision,
            expected_mode_revision=view.modeRevision,
            authority_epoch=view.authorityEpoch,
        )

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        context = self._context()
        if name == "find_nearest_aeds":
            raw_limit = arguments.get("limit", 3)
            if not isinstance(raw_limit, int) or isinstance(raw_limit, bool):
                raise ApiError("invalid_input", 400, "AED limit must be an integer")
            return self.adapters.find_nearest_aeds(context, raw_limit).model_dump(mode="json")
        if name == "dispatch_helper":
            role = arguments.get("role")
            if not isinstance(role, str):
                raise ApiError("invalid_input", 400, "Helper role is required")
            return self.adapters.dispatch_helper(context, role)
        raise ApiError("invalid_input", 400, "Unknown Agent tool")
