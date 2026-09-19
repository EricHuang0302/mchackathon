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
    clientSequence: int = Field(ge=1)
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


class LocationPointInput(StrictModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ObservationInput(StrictModel):
    observationId: UUID
    key: str = Field(pattern=r"^[a-z][a-zA-Z0-9_.]{0,63}$")
    value: bool | float | str | LocationPointInput
    source: Literal["voice_report", "button", "camera_proposal", "manual_report"]
    observedAt: datetime
    confirmation: Literal["proposed", "user_confirmed", "uncertain"]
    evidenceEventIds: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def proposal_is_not_confirmed(self) -> ObservationInput:
        if self.key == "location.coordinates" and not isinstance(self.value, LocationPointInput):
            raise ValueError("location.coordinates requires latitude and longitude")
        if self.key != "location.coordinates" and isinstance(self.value, LocationPointInput):
            raise ValueError("coordinates require location.coordinates key")
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


class SceneImageAnalysisRequest(StrictModel):
    imageBase64: str = Field(min_length=4, max_length=950_000)
    mimeType: Literal["image/jpeg", "image/webp"]
    capturedAt: datetime
    expectedModeRevision: int = Field(ge=0)


class CameraObservationProposal(StrictModel):
    observationId: UUID
    key: Literal[
        "hazards.traffic", "hazards.fire", "hazards.standingWater",
        "hazards.crowd", "patient.bleeding",
    ]
    value: bool | Literal["none", "minor", "severe", "life_threatening", "unknown"]
    source: Literal["camera_proposal"] = "camera_proposal"
    observedAt: datetime
    confirmation: Literal["proposed"] = "proposed"
    evidenceEventIds: list[UUID] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high", "unknown"] = "unknown"

    @model_validator(mode="after")
    def value_matches_key(self) -> CameraObservationProposal:
        if self.key == "patient.bleeding":
            if isinstance(self.value, bool) or self.value not in {
                "none", "minor", "severe", "life_threatening", "unknown",
            }:
                raise ValueError("patient.bleeding requires a bleeding severity")
        elif not isinstance(self.value, bool) and self.value != "unknown":
            raise ValueError("hazard proposals require boolean or unknown")
        return self


class SceneImageAnalysisResponse(StrictModel):
    analysisId: UUID
    model: str
    proposals: list[CameraObservationProposal] = Field(min_length=5, max_length=5)
    warnings: list[str] = Field(default_factory=list, max_length=5)


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
    status: Literal["accepted", "en_route", "arrived", "obtained", "delivered", "unavailable"] | None = None
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
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str
    accessNotes: str | None = None
    availability: Literal["available", "unavailable", "unknown"]
    straightLineMeters: float = Field(ge=0)
    walkingMeters: float | None = Field(default=None, ge=0)
    etaSeconds: int | None = Field(default=None, ge=0)
    routeUpdatedAt: datetime | None = None
    estimateSource: Literal["route", "straight_line", "none"]


class AedListResponse(StrictModel):
    candidates: list[AedCandidate]
    dataUpdatedAt: datetime | None


class ObservationRecord(StrictModel):
    observationId: UUID
    key: str
    value: bool | float | str | LocationPointInput
    source: Literal[
        "user_report", "button", "camera_proposal", "model_proposal",
        "geocoder", "device", "helper_report", "rule_engine",
    ]
    observedAt: datetime
    confirmation: Literal["unknown", "proposed", "reported", "confirmed"]
    evidenceEventIds: list[UUID] = Field(default_factory=list)


class SceneSnapshotResponse(StrictModel):
    incidentId: UUID
    snapshotRevision: int
    generatedThroughRevision: int
    observations: list[ObservationRecord]
    generatedThroughSequence: int = 0
    updatedAt: datetime | None = None
    sections: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    actionsPerformed: list[dict[str, Any]] = Field(default_factory=list)


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


class RuleEvaluationRequest(StrictModel):
    expectedStateRevision: int = Field(ge=0)
    expectedModeRevision: int = Field(ge=0)
    trigger: dict[str, Any]
    observations: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    timers: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class RuleEvaluationResponse(StrictModel):
    ruleVersion: str
    contentHash: str
    reviewStatus: Literal["unreviewed_demo", "in_review", "reviewed"]
    clinicalReviewRequired: bool
    decision: dict[str, Any]


class HandoffReadResponse(StrictModel):
    snapshot: dict[str, Any]
    mist: dict[str, Any]
    timeline: dict[str, Any]


class AedDispatchRequest(StrictModel):
    helperId: UUID
    expectedStateRevision: int = Field(ge=0)
    helperLocation: LocationPointInput | None = None


class AedUnavailabilityRequest(StrictModel):
    reportId: UUID
    aedId: str = Field(min_length=1, max_length=200)
    reasonCode: str = Field(min_length=1, max_length=100)
    expectedAssignmentRevision: int = Field(ge=1)
    reportedAt: datetime
    helperLocation: LocationPointInput | None = None


class AedAssignmentResponse(StrictModel):
    outcome: Literal[
        "assigned", "reassigned", "duplicate_report", "stale_revision",
        "not_assigned", "aed_mismatch", "no_candidate", "conflict",
    ]
    incidentId: UUID
    reportId: UUID | None = None
    helperId: UUID | None = None
    aedId: str | None = None
    assignmentRevision: int | None = None
    previousAedId: str | None = None
    excludedAedIds: list[str]
    deduplicated: bool
    estimate: dict[str, Any] | None = None


class AedAssignmentReadResponse(StrictModel):
    incidentId: UUID
    helperId: UUID
    aedId: str | None
    assignmentRevision: int = Field(ge=1)
    status: Literal["assigned", "no_candidate"]
    assignedAt: datetime
    previousAedId: str | None = None
    helperStatus: Literal["accepted", "en_route", "arrived", "obtained", "delivered", "unavailable"] | None = None
    helperStatusUpdatedAt: datetime | None = None
    destination: AedCandidate | None = None
    estimate: dict[str, Any] | None = None


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
