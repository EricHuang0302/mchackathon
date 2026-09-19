from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InteractionMode(StrEnum):
    CALL_119 = "call_119"
    ON_CALL = "on_call"
    VOICE_GUIDANCE = "voice_guidance"
    HANDOVER = "handover"


class IncidentStatus(StrEnum):
    ACTIVE = "active"
    HANDED_OVER = "handed_over"
    CLOSED = "closed"


class Scope(StrEnum):
    RUNNER = "aed_runner"
    GREETER = "ambulance_greeter"
    EMS = "ems_viewer"


class ErrorBody(StrictModel):
    code: Literal["unauthorized", "expired", "stale_revision", "rule_mismatch", "unavailable", "invalid_input"]
    message: str
    requestId: str
    details: dict[str, Any] | None = None


class ErrorResponse(StrictModel):
    error: ErrorBody


class SessionResponse(StrictModel):
    actorId: UUID
    sessionToken: str
    expiresAt: datetime


class CreateIncidentRequest(StrictModel):
    incidentId: UUID
    primaryClientId: UUID
    ruleVersion: str = Field(min_length=1, max_length=100)


class IncidentView(StrictModel):
    incidentId: UUID
    primaryClientId: UUID
    ruleVersion: str
    status: IncidentStatus
    interactionMode: InteractionMode
    stateRevision: int = Field(ge=0)
    modeRevision: int = Field(ge=0)
    snapshotRevision: int = Field(ge=0)
    authorityEpoch: int = Field(ge=1)
    createdAt: datetime


class EventInput(StrictModel):
    eventId: UUID
    type: Literal[
        "mode.changed", "call.reported", "action.reported", "event.corrected",
        "observation.proposed", "observation.confirmed", "command.acknowledged",
        "timer.elapsed", "helper.updated",
    ]
    detail: dict[str, Any]
    clientId: UUID
    clientInstanceId: UUID
    clientSequence: int = Field(ge=0)
    clientTime: datetime
    authorityEpoch: int = Field(ge=1)
    stateRevision: int = Field(ge=0)
    modeRevision: int = Field(ge=0)
    ruleVersion: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_detail(self) -> EventInput:
        allowed = {
            "mode.changed": {"interactionMode", "reason"},
            "call.reported": {"reportedState", "source", "delegatedCallActive"},
            "action.reported": {"action"},
            "event.corrected": {"correctsEventId", "replacement"},
            "observation.proposed": {"observationId"},
            "observation.confirmed": {"observationId"},
            "command.acknowledged": {"commandId", "status"},
            "timer.elapsed": {"timerId"},
            "helper.updated": {"helperId", "status"},
        }
        if not self.detail or set(self.detail) - allowed[self.type]:
            raise ValueError("unsupported event detail")
        if self.type == "mode.changed":
            if set(self.detail) != {"interactionMode", "reason"}:
                raise ValueError("mode.changed requires interactionMode and reason")
            InteractionMode(self.detail["interactionMode"])
            if self.detail["reason"] not in {
                "dial_started", "dispatcher_reported_active", "user_reports_call_failed",
                "user_reports_call_ended_or_failed", "user_reports_ems_arrived",
            }:
                raise ValueError("invalid mode transition reason")
        if self.type == "action.reported" and not isinstance(self.detail.get("action"), str):
            raise ValueError("action.reported requires action")
        if self.type == "call.reported" and (self.detail.get("source") != "user" or self.detail.get("reportedState") not in {"attempted", "active", "ended", "failed", "uncertain"}):
            raise ValueError("call.reported requires user reportedState")
        for kind, key in {"event.corrected": "correctsEventId", "observation.proposed": "observationId", "observation.confirmed": "observationId", "command.acknowledged": "commandId", "timer.elapsed": "timerId", "helper.updated": "helperId"}.items():
            if self.type == kind:
                try:
                    UUID(str(self.detail[key]))
                except (KeyError, ValueError):
                    raise ValueError(f"{kind} requires valid {key}") from None
        if self.type == "command.acknowledged" and self.detail.get("status") not in {"received", "started", "completed", "failed", "interrupted"}:
            raise ValueError("invalid command status")
        return self


class EventBatchRequest(StrictModel):
    events: list[EventInput] = Field(min_length=1, max_length=50)


class EventAck(StrictModel):
    eventId: UUID
    status: Literal["accepted", "duplicate", "conflict"]
    code: str | None = None


class EventBatchResponse(StrictModel):
    acknowledgements: list[EventAck]
    stateRevision: int
    modeRevision: int
    snapshotRevision: int
    authorityEpoch: int
    lastAcknowledgedClientSequence: int | None = None


class ObservationInput(StrictModel):
    observationId: UUID
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value: bool | float | str | Literal["unknown"]
    source: Literal["voice_report", "button", "camera_proposal", "manual_report"]
    observedAt: datetime
    confirmation: Literal["proposed", "user_confirmed", "uncertain"]
    evidenceEventIds: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def proposal_is_not_confirmed(self) -> ObservationInput:
        if self.source == "camera_proposal" and self.confirmation == "user_confirmed":
            raise ValueError("camera proposal cannot confirm itself")
        return self


class SceneObservationRequest(StrictModel):
    observations: list[ObservationInput] = Field(min_length=1, max_length=20)
    expectedSnapshotRevision: int = Field(ge=0)
    idempotencyKey: UUID


class SceneObservationResponse(StrictModel):
    snapshotRevision: int
    acceptedObservationIds: list[UUID]
    generatedThroughRevision: int


class LocationDescriptionRequest(StrictModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracyMeters: float | None = Field(default=None, ge=0)


class LocationCandidate(StrictModel):
    formattedAddress: str
    source: str
    confidence: Literal["low", "medium", "high", "unknown"]


class LocationDescriptionResponse(StrictModel):
    candidates: list[LocationCandidate]
    entranceKnown: bool = False
    floorKnown: bool = False


class CreateShareRequest(StrictModel):
    scope: Scope
    helperId: UUID | None = None
    expiresInSeconds: int = Field(ge=60, le=3600)
    idempotencyKey: UUID

    @model_validator(mode="after")
    def helper_scope(self) -> CreateShareRequest:
        if (self.scope in {Scope.RUNNER, Scope.GREETER}) != (self.helperId is not None):
            raise ValueError("helperId is required only for helper scopes")
        return self


class CreateShareResponse(StrictModel):
    inviteId: UUID
    secret: str
    scope: Scope
    expiresAt: datetime


class ShareSessionRequest(StrictModel):
    secret: str = Field(min_length=32, max_length=256)


class ShareSessionResponse(StrictModel):
    incidentId: UUID
    scope: Scope
    helperId: UUID | None
    expiresAt: datetime


class RevokeAccessRequest(StrictModel):
    expectedStateRevision: int = Field(ge=0)
    idempotencyKey: UUID


class RevokeAccessResponse(StrictModel):
    stateRevision: int
    revokedInvitations: int
    revokedGrants: int


class HelperUpdateRequest(StrictModel):
    updateId: UUID
    expectedAssignmentRevision: int = Field(ge=0)
    status: Literal["accepted", "en_route", "arrived", "obtained", "unavailable"] | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    locationAccuracyMeters: float | None = Field(default=None, ge=0)
    reportedAt: datetime

    @model_validator(mode="after")
    def valid_location(self) -> HelperUpdateRequest:
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must be supplied together")
        if self.status is None and self.lat is None:
            raise ValueError("status or location required")
        return self


class HelperUpdateResponse(StrictModel):
    helperId: UUID
    assignmentRevision: int
    status: str
    locationUpdatedAt: datetime | None = None


class AedCandidate(StrictModel):
    aedId: str
    name: str
    availability: Literal["available", "unavailable", "unknown"]
    straightLineMeters: float = Field(ge=0)
    walkingMeters: float | None = Field(default=None, ge=0)
    etaSeconds: int | None = Field(default=None, ge=0)
    routeUpdatedAt: datetime | None = None
    estimateSource: Literal["route", "straight_line", "none"]


class AedListResponse(StrictModel):
    candidates: list[AedCandidate]
    dataUpdatedAt: datetime | None


class SceneSnapshotResponse(StrictModel):
    incidentId: UUID
    snapshotRevision: int
    generatedThroughRevision: int
    observations: list[ObservationInput]


class HandoffEvent(StrictModel):
    eventId: UUID
    type: str
    clientTime: datetime
    serverTime: datetime
    detail: dict[str, Any]


class HandoffEventsResponse(StrictModel):
    snapshotRevision: int
    generatedThroughRevision: int
    events: list[HandoffEvent]
    nextCursor: str | None = None


class PatchIncidentRequest(StrictModel):
    status: Literal["handed_over", "closed"]
    expectedStateRevision: int = Field(ge=0)


class LiveEnvelope(StrictModel):
    protocolVersion: Literal[1]
    messageId: UUID
    incidentId: UUID
    clientId: UUID
    clientInstanceId: UUID
    clientSequence: int = Field(ge=0)
    clientTime: datetime
    authorityEpoch: int = Field(ge=1)
    stateRevision: int = Field(ge=0)
    modeRevision: int = Field(ge=0)
    payload: dict[str, Any]


class MediaFrame(StrictModel):
    sessionId: UUID
    sequence: int = Field(ge=0)
    modeRevision: int = Field(ge=0)
    contentType: Literal["audio/pcm;rate=16000", "image/jpeg"]
    data: str = Field(max_length=262144)
