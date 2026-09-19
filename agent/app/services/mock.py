"""Synthetic in-memory development mock. Never use for real incident data."""
from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import RLock
from uuid import UUID, uuid4

from app.api.errors import ApiError, stale, unauthorized, unavailable
from app.schemas.contracts import (
    AedListResponse, CreateIncidentRequest, CreateShareRequest, CreateShareResponse,
    EventAck, EventBatchRequest, EventBatchResponse, HandoffEvent,
    HandoffEventsResponse, HelperUpdateRequest, HelperUpdateResponse, IncidentStatus,
    IncidentView, InteractionMode, LocationDescriptionRequest,
    LocationDescriptionResponse, PatchIncidentRequest, SceneObservationRequest,
    SceneObservationResponse, SceneSnapshotResponse, Scope, ShareSessionRequest, ShareSessionResponse,
    RevokeAccessRequest, RevokeAccessResponse,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


_KEY_ALIASES = {
    "responsive": "patient.responsive",
    "breathing_normal": "patient.breathing",
    "breathing_reported": "patient.breathing",
}


@dataclass
class Record:
    owner: str
    view: IncidentView
    events: dict[UUID, HandoffEvent] = field(default_factory=dict)
    event_fingerprints: dict[UUID, str] = field(default_factory=dict)
    sequences: dict[tuple[UUID, UUID], int] = field(default_factory=dict)
    observations: dict[UUID, dict] = field(default_factory=dict)
    observation_keys: dict[UUID, tuple[str, SceneObservationResponse]] = field(default_factory=dict)
    shares: dict[UUID, tuple[str, CreateShareResponse]] = field(default_factory=dict)
    helpers: dict[UUID, HelperUpdateResponse] = field(default_factory=dict)
    update_ids: dict[UUID, tuple[str, UUID, HelperUpdateResponse]] = field(default_factory=dict)
    revocation_keys: dict[UUID, tuple[str, RevokeAccessResponse]] = field(default_factory=dict)


class SyntheticIncidentService:
    """Synthetic contract state machine; volatile unless wrapped by PostgreSQL."""

    def __init__(self):
        self._lock = RLock()
        self._incidents: dict[UUID, Record] = {}
        self._invites: dict[str, tuple[UUID, CreateShareResponse, UUID | None]] = {}
        self._invite_failures: dict[str, str] = {}
        self._grants: dict[tuple[str, UUID], tuple[Scope, UUID | None, datetime]] = {}

    def create_incident(self, uid: str, body: CreateIncidentRequest) -> IncidentView:
        with self._lock:
            existing = self._incidents.get(body.incidentId)
            if existing:
                if existing.owner != uid or existing.view.primaryClientId != body.primaryClientId or existing.view.ruleVersion != body.ruleVersion:
                    raise ApiError("invalid_input", 409, "Incident ID already registered")
                return existing.view
            view = IncidentView(
                incidentId=body.incidentId, primaryClientId=body.primaryClientId,
                ruleVersion=body.ruleVersion, status=IncidentStatus.ACTIVE,
                interactionMode=InteractionMode.CALL_119, stateRevision=0,
                modeRevision=0, snapshotRevision=0, authorityEpoch=1, createdAt=now(),
            )
            self._incidents[body.incidentId] = Record(uid, view)
            return view

    def authorize(self, uid: str, incident_id: UUID, scopes: set[str], helper_id: UUID | None = None) -> IncidentView:
        record = self._incidents.get(incident_id)
        if not record:
            raise unauthorized()
        if record.view.createdAt <= now() - timedelta(hours=72):
            raise ApiError("expired", 403, "Incident expired")
        if record.owner == uid and "primary" in scopes:
            return record.view
        grant = self._grants.get((uid, incident_id))
        if grant:
            scope, granted_helper, expires_at = grant
            if expires_at <= now():
                raise ApiError("expired", 403, "Grant expired")
            if scope.value in scopes and (helper_id is None or granted_helper == helper_id):
                return record.view
        raise unauthorized()

    def _primary_record(self, uid: str, incident_id: UUID) -> Record:
        self.authorize(uid, incident_id, {"primary"})
        record = self._incidents[incident_id]
        if record.view.status == IncidentStatus.CLOSED:
            raise ApiError("expired", 403, "Incident closed")
        return record

    def upload_events(self, uid: str, incident_id: UUID, body: EventBatchRequest) -> EventBatchResponse:
        with self._lock:
            record = self._primary_record(uid, incident_id)
            view = record.view
            acknowledgements = []
            for event in body.events:
                if event.eventId in record.events:
                    fingerprint = sha256(event.model_dump_json().encode()).hexdigest()
                    if record.event_fingerprints[event.eventId] == fingerprint:
                        acknowledgements.append(EventAck(eventId=event.eventId, status="duplicate"))
                    else:
                        acknowledgements.append(EventAck(eventId=event.eventId, status="conflict", code="invalid_input"))
                    continue
                code = None
                if event.clientId != view.primaryClientId:
                    code = "unauthorized"
                elif event.ruleVersion != view.ruleVersion:
                    code = "rule_mismatch"
                elif event.authorityEpoch != view.authorityEpoch or event.stateRevision != view.stateRevision or event.modeRevision != (view.modeRevision + 1 if event.type == "mode.changed" else view.modeRevision):
                    code = "stale_revision"
                elif event.clientSequence <= record.sequences.get((event.clientId, event.clientInstanceId), -1):
                    code = "stale_revision"
                if code:
                    acknowledgements.append(EventAck(eventId=event.eventId, status="conflict", code=code))
                    continue
                if event.type == "mode.changed":
                    requested = InteractionMode(event.detail["interactionMode"])
                    reason = event.detail["reason"]
                    transitions = {
                        (InteractionMode.CALL_119, "dial_started"): InteractionMode.ON_CALL,
                        (InteractionMode.CALL_119, "dispatcher_reported_active"): InteractionMode.ON_CALL,
                        (InteractionMode.CALL_119, "user_reports_call_failed"): InteractionMode.VOICE_GUIDANCE,
                        (InteractionMode.ON_CALL, "user_reports_call_ended_or_failed"): InteractionMode.VOICE_GUIDANCE,
                        (InteractionMode.VOICE_GUIDANCE, "dial_started"): InteractionMode.ON_CALL,
                        (InteractionMode.VOICE_GUIDANCE, "dispatcher_reported_active"): InteractionMode.ON_CALL,
                        (InteractionMode.CALL_119, "user_reports_ems_arrived"): InteractionMode.HANDOVER,
                        (InteractionMode.ON_CALL, "user_reports_ems_arrived"): InteractionMode.HANDOVER,
                        (InteractionMode.VOICE_GUIDANCE, "user_reports_ems_arrived"): InteractionMode.HANDOVER,
                    }
                    if transitions.get((view.interactionMode, reason)) != requested:
                        acknowledgements.append(EventAck(eventId=event.eventId, status="conflict", code="invalid_input"))
                        continue
                    view.interactionMode = requested
                    view.modeRevision = event.modeRevision
                view.stateRevision += 1
                record.sequences[(event.clientId, event.clientInstanceId)] = event.clientSequence
                record.events[event.eventId] = HandoffEvent(
                    eventId=event.eventId, type=event.type, clientTime=event.clientTime,
                    serverTime=now(), detail=event.detail,
                )
                record.event_fingerprints[event.eventId] = sha256(event.model_dump_json().encode()).hexdigest()
                acknowledgements.append(EventAck(eventId=event.eventId, status="accepted"))
            return EventBatchResponse(
                acknowledgements=acknowledgements, stateRevision=view.stateRevision,
                modeRevision=view.modeRevision, snapshotRevision=view.snapshotRevision,
                authorityEpoch=view.authorityEpoch,
                lastAcknowledgedClientSequence=max(record.sequences.values(), default=None),
            )

    def add_observations(self, uid: str, incident_id: UUID, body: SceneObservationRequest) -> SceneObservationResponse:
        with self._lock:
            record = self._primary_record(uid, incident_id)
            previous = record.observation_keys.get(body.idempotencyKey)
            fingerprint = sha256(body.model_dump_json().encode()).hexdigest()
            if previous:
                if previous[0] != fingerprint:
                    raise ApiError("invalid_input", 409, "Idempotency key reused with different request")
                return previous[1]
            if body.expectedSnapshotRevision != record.view.snapshotRevision:
                raise stale("snapshotRevision", record.view.snapshotRevision)
            normalized = []
            for observation in body.observations:
                value = observation.model_dump(mode="json")
                value["key"] = _KEY_ALIASES.get(observation.key, observation.key)
                normalized.append((observation.observationId, value))
                existing = record.observations.get(observation.observationId)
                if existing is not None and existing != value:
                    raise ApiError("invalid_input", 409, "Observation ID reused with different content")
            for observation_id, value in normalized:
                record.observations[observation_id] = value
            record.view.snapshotRevision += 1
            response = SceneObservationResponse(
                snapshotRevision=record.view.snapshotRevision,
                acceptedObservationIds=[item.observationId for item in body.observations],
                generatedThroughRevision=record.view.stateRevision,
            )
            record.observation_keys[body.idempotencyKey] = (fingerprint, response)
            return response

    def describe_location(self, uid: str, incident_id: UUID, body: LocationDescriptionRequest) -> LocationDescriptionResponse:
        self._primary_record(uid, incident_id)
        raise unavailable()  # No geocoding results are invented by the mock.

    def create_share(self, uid: str, incident_id: UUID, body: CreateShareRequest) -> CreateShareResponse:
        with self._lock:
            record = self._primary_record(uid, incident_id)
            previous = record.shares.get(body.idempotencyKey)
            fingerprint = sha256(body.model_dump_json().encode()).hexdigest()
            if previous:
                if previous[0] != fingerprint:
                    raise ApiError("invalid_input", 409, "Idempotency key reused with different request")
                return previous[1]
            secret = secrets.token_urlsafe(32)
            response = CreateShareResponse(inviteId=uuid4(), secret=secret, scope=body.scope, expiresAt=now() + timedelta(seconds=body.expiresInSeconds))
            record.shares[body.idempotencyKey] = (fingerprint, response)
            self._invites[sha256(secret.encode()).hexdigest()] = (incident_id, response, body.helperId)
            return response

    def revoke_access(self, uid: str, incident_id: UUID, body: RevokeAccessRequest) -> RevokeAccessResponse:
        with self._lock:
            record = self._primary_record(uid, incident_id)
            fingerprint = sha256(body.model_dump_json().encode()).hexdigest()
            previous = record.revocation_keys.get(body.idempotencyKey)
            if previous:
                if previous[0] != fingerprint:
                    raise ApiError("invalid_input", 409, "Idempotency key reused with different request")
                return previous[1]
            if body.expectedStateRevision != record.view.stateRevision:
                raise stale("stateRevision", record.view.stateRevision)
            invites = [key for key, value in self._invites.items() if value[0] == incident_id]
            grants = [key for key in self._grants if key[1] == incident_id]
            for key in invites:
                del self._invites[key]
                self._invite_failures[key] = "invitation_revoked"
            for key in grants:
                del self._grants[key]
            record.view.stateRevision += 1
            response = RevokeAccessResponse(stateRevision=record.view.stateRevision, revokedInvitations=len(invites), revokedGrants=len(grants))
            record.revocation_keys[body.idempotencyKey] = (fingerprint, response)
            return response

    def exchange_share(self, uid: str, body: ShareSessionRequest) -> ShareSessionResponse:
        with self._lock:
            secret_hash = sha256(body.secret.encode()).hexdigest()
            invite = self._invites.get(secret_hash)
            if not invite:
                reason = self._invite_failures.get(secret_hash, "invitation_expired")
                raise ApiError("expired", 403, "Invitation is unavailable", {"reason": reason})
            incident_id, share, helper_id = invite
            if self._incidents[incident_id].owner == uid:
                raise ApiError("unauthorized", 403, "Owner cannot redeem invitation", {"reason": "permission_denied"})
            if share.expiresAt <= now():
                del self._invites[secret_hash]
                self._invite_failures[secret_hash] = "invitation_expired"
                raise ApiError("expired", 403, "Invitation expired", {"reason": "invitation_expired"})
            del self._invites[secret_hash]
            self._invite_failures[secret_hash] = "invitation_redeemed"
            self._grants[(uid, incident_id)] = (share.scope, helper_id, share.expiresAt)
            return ShareSessionResponse(incidentId=incident_id, scope=share.scope, helperId=helper_id, expiresAt=share.expiresAt)

    def update_helper(self, uid: str, incident_id: UUID, helper_id: UUID, body: HelperUpdateRequest) -> HelperUpdateResponse:
        with self._lock:
            self.authorize(uid, incident_id, {Scope.RUNNER.value, Scope.GREETER.value}, helper_id)
            record = self._incidents[incident_id]
            fingerprint = sha256(body.model_dump_json().encode()).hexdigest()
            if body.updateId in record.update_ids:
                prior_fingerprint, prior_helper, prior_response = record.update_ids[body.updateId]
                if prior_fingerprint != fingerprint or prior_helper != helper_id:
                    raise ApiError("invalid_input", 409, "Update ID reused with different request")
                return prior_response
            previous = record.helpers.get(helper_id)
            revision = previous.assignmentRevision if previous else 0
            if body.expectedAssignmentRevision != revision:
                raise stale("assignmentRevision", revision)
            response = HelperUpdateResponse(
                helperId=helper_id, assignmentRevision=revision + 1,
                status=body.status or (previous.status if previous else "accepted"),
                locationUpdatedAt=body.reportedAt if body.lat is not None else (previous.locationUpdatedAt if previous else None),
            )
            record.helpers[helper_id] = response
            record.update_ids[body.updateId] = (fingerprint, helper_id, response)
            return response

    def list_aeds(self, uid: str, incident_id: UUID, limit: int, *, lat: float | None = None, lng: float | None = None) -> AedListResponse:
        self.authorize(uid, incident_id, {"primary", Scope.RUNNER.value})
        if self._incidents[incident_id].view.status == IncidentStatus.CLOSED:
            raise ApiError("expired", 403, "Incident closed")
        return AedListResponse(candidates=[], dataUpdatedAt=None)  # Clearly empty synthetic data.

    def get_snapshot(self, uid: str, incident_id: UUID) -> SceneSnapshotResponse:
        with self._lock:
            view = self.authorize(uid, incident_id, {"primary", Scope.GREETER.value, Scope.EMS.value})
            record = self._incidents[incident_id]
            from app.schemas.contracts import ObservationInput, ObservationRecord
            observations = []
            for raw in record.observations.values():
                item = ObservationInput.model_validate(raw)
                output = item.model_dump(mode="python")
                output["source"] = {
                    "voice_report": "user_report", "manual_report": "user_report",
                    "button": "button", "camera_proposal": "camera_proposal",
                }[item.source]
                output["confirmation"] = {
                    "user_confirmed": "confirmed", "uncertain": "proposed",
                    "proposed": "proposed",
                }[item.confirmation]
                observations.append(ObservationRecord.model_validate(output))
            return SceneSnapshotResponse(
                incidentId=incident_id, snapshotRevision=view.snapshotRevision,
                generatedThroughRevision=view.stateRevision, observations=observations,
            )

    def handoff_events(self, uid: str, incident_id: UUID, cursor: str | None, limit: int) -> HandoffEventsResponse:
        with self._lock:
            view = self.authorize(uid, incident_id, {"primary", Scope.EMS.value})
            record = self._incidents[incident_id]
            events = list(record.events.values())
            start = 0
            if cursor:
                try:
                    start = int(base64.urlsafe_b64decode(cursor + "==").decode())
                except (ValueError, UnicodeDecodeError):
                    raise ApiError("invalid_input", 400, "Invalid cursor") from None
            page = events[start:start + limit]
            if record.owner != uid:
                visible = {
                    "mode.changed": {"interactionMode", "reason"},
                    "call.reported": {"reportedState"},
                    "action.reported": {"action"},
                    "event.corrected": {"correctsEventId"},
                    "observation.proposed": {"observationId"},
                    "observation.confirmed": {"observationId"},
                }
                page = [item.model_copy(update={"detail": {key: value for key, value in item.detail.items() if key in visible.get(item.type, set())}}) for item in page]
            next_cursor = base64.urlsafe_b64encode(str(start + limit).encode()).decode().rstrip("=") if start + limit < len(events) else None
            return HandoffEventsResponse(snapshotRevision=view.snapshotRevision, generatedThroughRevision=view.stateRevision, events=page, nextCursor=next_cursor)

    def patch_incident(self, uid: str, incident_id: UUID, body: PatchIncidentRequest) -> IncidentView:
        with self._lock:
            record = self._primary_record(uid, incident_id)
            if body.expectedStateRevision != record.view.stateRevision:
                raise stale("stateRevision", record.view.stateRevision)
            record.view.status = IncidentStatus(body.status)
            record.view.stateRevision += 1
            if record.view.interactionMode != InteractionMode.HANDOVER:
                record.view.interactionMode = InteractionMode.HANDOVER
                record.view.modeRevision += 1
            if body.status == "closed":
                self._grants = {key: grant for key, grant in self._grants.items() if key[1] != incident_id}
            return record.view
