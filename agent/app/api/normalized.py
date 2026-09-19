"""Flask-facing adapter over the normalized workstream 5 services.

The adapter owns transport compatibility and authentication context. Clinical
rules, scene projection, access decisions, and AED ranking stay in their
respective domain services.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from uuid import UUID, uuid4

import psycopg
from cryptography.fernet import Fernet

from app.api.errors import ApiError, stale, unavailable
from app.schemas.contracts import (
    AedAssignmentReadResponse, AedAssignmentResponse, AedCandidate,
    AedDispatchRequest, AedListResponse,
    AedUnavailabilityRequest, CreateIncidentRequest, CreateShareRequest,
    CreateShareResponse, EventAck, EventBatchRequest, EventBatchResponse,
    HandoffEventsResponse, HelperUpdateRequest, HelperUpdateResponse,
    IncidentView, LocationDescriptionRequest, LocationDescriptionResponse,
    PatchIncidentRequest, RevokeAccessRequest, RevokeAccessResponse,
    RuleEvaluationRequest, RuleEvaluationResponse, SceneObservationRequest,
    SceneObservationResponse, SceneSnapshotResponse,
    ShareSessionRequest, ShareSessionResponse,
)
from app.services.aed.assignment import (
    AedAssignmentService, ReassignmentOutcome, ReassignmentResult,
    UnavailabilityReport,
)
from app.services.aed.catalog import AedCatalogService
from app.services.aed.helpers import HelperPosition, evaluate_helper_location
from app.services.aed.routing import RouteProviderError
from app.services.incident import event_types as et
from app.services.incident.access import (
    MANAGE_SHARES,
    ROLE_AED_RUNNER, ROLE_AMBULANCE_GREETER, ROLE_EMS_VIEWER, ROLE_PRIMARY,
    WRITE_OWN_HELPER_UPDATES, AccessGrant, Principal, resolve_principal,
)
from app.services.incident.clock import iso
from app.services.incident.errors import EXPIRED, INVALID_INPUT, STALE_REVISION, UNAUTHORIZED, RetentionPolicy, ServiceError
from app.services.incident.ingestion import IncidentEventService
from app.services.incident.models import IncidentRecord, with_updated
from app.services.incident.read_models import IncidentReadModelService
from app.services.incident.scene_snapshot import project_scene_snapshot
from app.services.postgres_data.access import AccessInvitation
from app.services.postgres_data.aed import PostgresAedCatalogRepository, PostgresAssignmentStore
from app.services.postgres_data.uow import PostgresUnitOfWork
from app.services.rules.service import ClinicalRuleService
from data.aed.models import GeoPoint


_RETENTION = RetentionPolicy(
    incident_seconds=72 * 3600,
    event_seconds=72 * 3600,
    projection_seconds=72 * 3600,
)
_KEY_ALIASES = {
    "responsive": "patient.responsive",
    "breathing_normal": "patient.breathing",
    "breathing_reported": "patient.breathing",
}
_SOURCE_TO_DOMAIN = {
    "voice_report": "user_report",
    "manual_report": "user_report",
    "button": "button",
    "camera_proposal": "camera_proposal",
}
_CONFIRMATION_TO_DOMAIN = {
    "user_confirmed": "confirmed",
    "uncertain": "proposed",
    "proposed": "proposed",
}
_CALL_STATES = {
    "attempted": "dial_started",
    "active": "dispatcher_active",
    "ended": "call_ended",
    "failed": "could_not_connect",
    "uncertain": "uncertain",
}


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _UnavailableRoutes:
    name = "unconfigured"

    def walking_route(self, origin: GeoPoint, destination: GeoPoint, *, computed_at: datetime):
        raise RouteProviderError("route_provider_not_configured")


def _fingerprint(body) -> str:
    raw = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode()).hexdigest()


class NormalizedIncidentService:
    """Implement the existing HTTP port with normalized PostgreSQL services."""

    def __init__(self, dsn: str, invite_key: str) -> None:
        self.dsn = dsn
        self.cipher = Fernet(invite_key.encode())
        self.clock = _SystemClock()
        self.rules = ClinicalRuleService()
        self.catalog = PostgresAedCatalogRepository(dsn)
        self.assignments = PostgresAssignmentStore(dsn)

    def _events(self, uow: PostgresUnitOfWork) -> IncidentEventService:
        return IncidentEventService(uow.events, uow.incidents, self.clock, retention=_RETENTION)

    def _reads(self, uow: PostgresUnitOfWork) -> IncidentReadModelService:
        return IncidentReadModelService(
            uow.incidents, uow.events, uow.grants, self.clock, retention=_RETENTION,
        )

    def _principal(
        self, uow: PostgresUnitOfWork, uid: str, incident_id: UUID,
        scopes: set[str], *, helper_id: UUID | None = None, write: bool = False,
    ) -> tuple[IncidentRecord, Principal]:
        record = uow.incidents.get(str(incident_id))
        if record is None:
            raise ServiceError(UNAUTHORIZED, "incident_scope_denied")
        if self.clock.now() >= record.expires_at or record.status == "closed":
            raise ServiceError(EXPIRED, "incident_expired_or_closed")
        principal = resolve_principal(
            incident_id=str(incident_id), owner_uid=record.owner_uid,
            uid=uid, now=self.clock.now(), grants=uow.grants,
        )
        if principal.role not in scopes:
            raise ServiceError(UNAUTHORIZED, "incident_scope_denied")
        if helper_id is not None and principal.helper_id != str(helper_id):
            raise ServiceError(UNAUTHORIZED, "helper_scope_denied")
        if write and record.status != "active":
            raise ServiceError(EXPIRED, "incident_is_not_active")
        return record, principal

    def _view(self, uow: PostgresUnitOfWork, record: IncidentRecord) -> IncidentView:
        snapshot = uow.snapshots.get(record.incident_id)
        return IncidentView(
            incidentId=record.incident_id, primaryClientId=record.primary_client_id,
            ruleVersion=record.rule_version, status=record.status,
            interactionMode=record.interaction_mode, stateRevision=record.state_revision,
            modeRevision=record.mode_revision,
            snapshotRevision=snapshot.snapshot_revision if snapshot else 0,
            authorityEpoch=max(record.authority_epoch, 1), createdAt=record.created_at,
        )

    def _project(self, uow: PostgresUnitOfWork, record: IncidentRecord):
        snapshot = project_scene_snapshot(
            record, uow.events.list_events(record.incident_id),
            now=self.clock.now(), retention=_RETENTION,
        )
        return uow.snapshots.put(snapshot)

    def _operation_get(self, uow, incident_id: UUID, operation: str, key: UUID, fingerprint: str):
        row = uow.connection.execute(
            "SELECT fingerprint, response FROM api_operation_keys WHERE incident_id = %s AND operation = %s AND idempotency_key = %s",
            (str(incident_id), operation, str(key)),
        ).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            raise ApiError("invalid_input", 409, "Idempotency key reused with different content")
        return row[1]

    def _operation_put(self, uow, record: IncidentRecord, operation: str, key: UUID, fingerprint: str, response):
        uow.connection.execute(
            "INSERT INTO api_operation_keys (incident_id, operation, idempotency_key, fingerprint, response, expires_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (record.incident_id, operation, str(key), fingerprint,
             psycopg.types.json.Jsonb(response.model_dump(mode="json")), record.expires_at),
        )

    def create_incident(self, uid: str, body: CreateIncidentRequest) -> IncidentView:
        now = self.clock.now()
        record = IncidentRecord(
            incident_id=str(body.incidentId), owner_uid=uid,
            primary_client_id=str(body.primaryClientId), rule_version=body.ruleVersion,
            created_at=now, updated_at=now, expires_at=now + timedelta(seconds=_RETENTION.incident_seconds),
            authority_epoch=1,
        )
        with PostgresUnitOfWork(self.dsn) as uow:
            stored = uow.incidents.create(record)
            if uow.snapshots.get(stored.incident_id) is None:
                self._project(uow, stored)
            return self._view(uow, stored)

    def authorize(self, uid: str, incident_id: UUID, scopes: set[str], helper_id: UUID | None = None) -> IncidentView:
        with PostgresUnitOfWork(self.dsn) as uow:
            record, _ = self._principal(uow, uid, incident_id, scopes, helper_id=helper_id)
            return self._view(uow, record)

    @staticmethod
    def _normalized_event(event) -> dict:
        payload = event.model_dump(mode="json")
        detail = dict(payload["detail"])
        if event.type == "mode.changed":
            detail["mode"] = detail.pop("interactionMode")
            detail["modeRevision"] = event.modeRevision
        elif event.type == "call.reported":
            detail["reportedState"] = _CALL_STATES[detail["reportedState"]]
        payload["detail"] = detail
        payload["source"] = "user_report"
        return payload

    def upload_events(self, uid: str, incident_id: UUID, body: EventBatchRequest) -> EventBatchResponse:
        with PostgresUnitOfWork(self.dsn) as uow:
            uow.lock_incident(str(incident_id))
            record, principal = self._principal(uow, uid, incident_id, {ROLE_PRIMARY}, write=True)
            result = self._events(uow).ingest_batch(
                str(incident_id), [self._normalized_event(event) for event in body.events],
                principal=principal,
            )
            snapshot = self._project(uow, result.incident)
            statuses = {
                item.event_id: EventAck(eventId=item.event_id, status=item.status)
                for item in result.acknowledgements
            }
            statuses.update({
                item.event_id: EventAck(eventId=item.event_id, status="conflict", code=item.code)
                for item in result.conflicts if item.event_id is not None
            })
            return EventBatchResponse(
                acknowledgements=[statuses[str(event.eventId)] for event in body.events],
                stateRevision=result.incident.state_revision,
                modeRevision=result.incident.mode_revision,
                snapshotRevision=snapshot.snapshot_revision,
                authorityEpoch=result.incident.authority_epoch,
                lastAcknowledgedClientSequence=result.incident.last_acknowledged_client_sequence(
                    result.incident.primary_client_id
                ),
            )

    def add_observations(self, uid: str, incident_id: UUID, body: SceneObservationRequest) -> SceneObservationResponse:
        fingerprint = _fingerprint(body)
        with PostgresUnitOfWork(self.dsn) as uow:
            uow.lock_incident(str(incident_id))
            record, principal = self._principal(uow, uid, incident_id, {ROLE_PRIMARY}, write=True)
            previous = self._operation_get(uow, incident_id, "scene_observations", body.idempotencyKey, fingerprint)
            if previous is not None:
                return SceneObservationResponse.model_validate(previous)
            current = uow.snapshots.get(str(incident_id))
            current_revision = current.snapshot_revision if current else 0
            if body.expectedSnapshotRevision != current_revision:
                raise stale("snapshotRevision", current_revision)
            payloads = []
            for sequence, observation in enumerate(body.observations, start=1):
                key = _KEY_ALIASES.get(observation.key, observation.key)
                if key not in et.OBSERVATION_KEYS:
                    raise ApiError("invalid_input", 400, "Unknown scene observation key")
                source = _SOURCE_TO_DOMAIN[observation.source]
                confirmation = _CONFIRMATION_TO_DOMAIN[observation.confirmation]
                payloads.append({
                    "eventId": str(observation.observationId),
                    "type": "observation.confirmed" if confirmation == "confirmed" else "observation.proposed",
                    "detail": {
                        "observationId": str(observation.observationId), "key": key,
                        "value": observation.value.model_dump(mode="json") if hasattr(observation.value, "model_dump") else observation.value,
                        "confirmation": confirmation,
                        "observedAt": iso(observation.observedAt),
                        "evidenceEventIds": [str(item) for item in observation.evidenceEventIds],
                    },
                    "clientId": record.primary_client_id,
                    "clientInstanceId": str(body.idempotencyKey),
                    "clientSequence": sequence,
                    "clientTime": iso(observation.observedAt),
                    "authorityEpoch": record.authority_epoch,
                    "stateRevision": record.state_revision,
                    "modeRevision": record.mode_revision,
                    "ruleVersion": record.rule_version,
                    "source": source,
                })
            result = self._events(uow).ingest_batch(str(incident_id), payloads, principal=principal)
            if result.conflicts:
                conflict = result.conflicts[0]
                status = 409 if conflict.code in {STALE_REVISION, INVALID_INPUT} else 403
                raise ApiError(conflict.code, status, "Scene observation conflict")
            snapshot = self._project(uow, result.incident)
            response = SceneObservationResponse(
                snapshotRevision=snapshot.snapshot_revision,
                acceptedObservationIds=[item.observationId for item in body.observations],
                generatedThroughRevision=snapshot.generated_through_revision,
            )
            self._operation_put(uow, record, "scene_observations", body.idempotencyKey, fingerprint, response)
            return response

    def describe_location(self, uid: str, incident_id: UUID, body: LocationDescriptionRequest) -> LocationDescriptionResponse:
        self.authorize(uid, incident_id, {ROLE_PRIMARY})
        raise unavailable()

    def create_share(self, uid: str, incident_id: UUID, body: CreateShareRequest) -> CreateShareResponse:
        with PostgresUnitOfWork(self.dsn) as uow:
            uow.lock_incident(str(incident_id))
            self._principal(uow, uid, incident_id, {ROLE_PRIMARY}, write=True)[1].require(MANAGE_SHARES)
            existing = uow.invitations.get_by_idempotency_key(str(incident_id), str(body.idempotencyKey))
            if existing is not None:
                if existing.scope != body.scope.value or existing.helper_id != (str(body.helperId) if body.helperId else None) or int((existing.expires_at - existing.created_at).total_seconds()) != body.expiresInSeconds:
                    raise ApiError("invalid_input", 409, "Idempotency key reused with different content")
                return CreateShareResponse(
                    inviteId=existing.invitation_id,
                    secret=self.cipher.decrypt(existing.encrypted_secret).decode(),
                    scope=existing.scope, expiresAt=existing.expires_at,
                )
            now = self.clock.now()
            secret = secrets.token_urlsafe(32)
            invitation = AccessInvitation(
                invitation_id=str(uuid4()), incident_id=str(incident_id),
                secret_hash=sha256(secret.encode()).hexdigest(),
                encrypted_secret=self.cipher.encrypt(secret.encode()),
                scope=body.scope.value, helper_id=str(body.helperId) if body.helperId else None,
                idempotency_key=str(body.idempotencyKey), created_at=now,
                expires_at=now + timedelta(seconds=body.expiresInSeconds),
            )
            saved = uow.invitations.put(invitation)
            return CreateShareResponse(inviteId=saved.invitation_id, secret=secret, scope=saved.scope, expiresAt=saved.expires_at)

    def revoke_access(self, uid: str, incident_id: UUID, body: RevokeAccessRequest) -> RevokeAccessResponse:
        fingerprint = _fingerprint(body)
        with PostgresUnitOfWork(self.dsn) as uow:
            uow.lock_incident(str(incident_id))
            record, principal = self._principal(uow, uid, incident_id, {ROLE_PRIMARY}, write=True)
            principal.require(MANAGE_SHARES)
            previous = self._operation_get(uow, incident_id, "access_revocation", body.idempotencyKey, fingerprint)
            if previous is not None:
                return RevokeAccessResponse.model_validate(previous)
            if body.expectedStateRevision != record.state_revision:
                raise stale("stateRevision", record.state_revision)
            now = self.clock.now()
            invitations = uow.invitations.revoke_incident(str(incident_id), now)
            grants = uow.grants.revoke_incident(str(incident_id), now)
            updated = uow.incidents.put(with_updated(record, state_revision=record.state_revision + 1, updated_at=now))
            response = RevokeAccessResponse(
                stateRevision=updated.state_revision,
                revokedInvitations=invitations, revokedGrants=grants,
            )
            self._operation_put(uow, updated, "access_revocation", body.idempotencyKey, fingerprint, response)
            return response

    def exchange_share(self, uid: str, body: ShareSessionRequest) -> ShareSessionResponse:
        secret_hash = sha256(body.secret.encode()).hexdigest()
        with PostgresUnitOfWork(self.dsn) as uow:
            invitation = uow.invitations.get_by_secret_hash(secret_hash)
            current_time = self.clock.now()
            if invitation is None:
                raise ServiceError(EXPIRED, "invitation_expired", detail={"reason": "invitation_expired"})
            if invitation.redeemed_at is not None:
                raise ServiceError(EXPIRED, "invitation_redeemed", detail={"reason": "invitation_redeemed"})
            if invitation.revoked_at is not None:
                raise ServiceError(EXPIRED, "invitation_revoked", detail={"reason": "invitation_revoked"})
            if invitation.expires_at <= current_time:
                raise ServiceError(EXPIRED, "invitation_expired", detail={"reason": "invitation_expired"})
            uow.lock_incident(invitation.incident_id)
            record = uow.incidents.require(invitation.incident_id)
            if record.status == "closed" or record.expires_at <= current_time:
                raise ServiceError(EXPIRED, "incident_expired_or_closed")
            if record.owner_uid == uid:
                raise ServiceError(UNAUTHORIZED, "owner_cannot_redeem_share", detail={"reason": "permission_denied"})
            redeemed = uow.invitations.redeem(secret_hash, uid, current_time)
            if redeemed is None:
                latest = uow.invitations.get_by_secret_hash(secret_hash)
                reason = "invitation_redeemed"
                if latest and latest.revoked_at is not None:
                    reason = "invitation_revoked"
                elif latest and latest.expires_at <= current_time:
                    reason = "invitation_expired"
                raise ServiceError(EXPIRED, reason, detail={"reason": reason})
            grant = AccessGrant(
                grant_id=str(uuid4()), incident_id=invitation.incident_id, uid=uid,
                scope=invitation.scope, helper_id=invitation.helper_id,
                expires_at=min(invitation.expires_at, record.expires_at),
            )
            uow.grants.put(grant)
            return ShareSessionResponse(
                incidentId=invitation.incident_id, scope=invitation.scope,
                helperId=invitation.helper_id, expiresAt=grant.expires_at,
            )

    def update_helper(self, uid: str, incident_id: UUID, helper_id: UUID, body: HelperUpdateRequest) -> HelperUpdateResponse:
        fingerprint = _fingerprint(body)
        with PostgresUnitOfWork(self.dsn) as uow:
            uow.lock_incident(str(incident_id))
            record, principal = self._principal(
                uow, uid, incident_id, {ROLE_AED_RUNNER, ROLE_AMBULANCE_GREETER},
                helper_id=helper_id, write=True,
            )
            principal.require(WRITE_OWN_HELPER_UPDATES)
            previous = self._operation_get(uow, incident_id, f"helper:{helper_id}", body.updateId, fingerprint)
            if previous is not None:
                return HelperUpdateResponse.model_validate(previous)
            row = uow.connection.execute(
                "SELECT COUNT(*), MAX(server_time) FROM incident_events WHERE incident_id = %s AND event_type = 'helper.updated' AND detail->>'helperId' = %s",
                (str(incident_id), str(helper_id)),
            ).fetchone()
            revision = int(row[0])
            if body.expectedAssignmentRevision != revision:
                raise stale("assignmentRevision", revision)
            detail = {"helperId": str(helper_id), "role": principal.role}
            if body.status:
                detail["status"] = body.status
            if body.lat is not None:
                detail["location"] = {"lat": body.lat, "lng": body.lng, "accuracyMeters": body.locationAccuracyMeters}
            payload = {
                "eventId": str(body.updateId), "type": "helper.updated", "detail": detail,
                "clientId": str(helper_id), "clientInstanceId": principal.grant_id,
                "clientSequence": revision + 1, "clientTime": iso(body.reportedAt),
                "authorityEpoch": record.authority_epoch, "stateRevision": record.state_revision,
                "modeRevision": record.mode_revision, "ruleVersion": record.rule_version,
                "source": "helper_report",
            }
            result = self._events(uow).ingest_batch(str(incident_id), [payload], principal=principal)
            if result.conflicts:
                raise ApiError(result.conflicts[0].code, 409, "Helper update conflict")
            self._project(uow, result.incident)
            response = HelperUpdateResponse(
                helperId=helper_id, assignmentRevision=revision + 1,
                status=body.status or "location_only",
                locationUpdatedAt=body.reportedAt if body.lat is not None else None,
            )
            self._operation_put(uow, record, f"helper:{helper_id}", body.updateId, fingerprint, response)
            return response

    def _patient_point(self, uow: PostgresUnitOfWork, record: IncidentRecord) -> GeoPoint | None:
        snapshot = uow.snapshots.get(record.incident_id)
        if snapshot is None:
            return None
        value = snapshot.field_for("location.coordinates").value
        if not isinstance(value, dict):
            return None
        try:
            return GeoPoint(float(value["latitude"]), float(value["longitude"]))
        except (KeyError, TypeError, ValueError):
            return None

    def list_aeds(self, uid: str, incident_id: UUID, limit: int, *, lat: float | None = None, lng: float | None = None) -> AedListResponse:
        with PostgresUnitOfWork(self.dsn) as uow:
            record, _ = self._principal(uow, uid, incident_id, {ROLE_PRIMARY, ROLE_AED_RUNNER})
            origin = GeoPoint(lat, lng) if lat is not None and lng is not None else self._patient_point(uow, record)
            records = self.catalog.list_active()
            if origin is None:
                updated = max((item.source_updated_at or item.ingested_at for item in records), default=None)
                return AedListResponse(candidates=[], dataUpdatedAt=updated)
            return AedCatalogService(records).list_candidates(origin=origin, at=self.clock.now(), limit=limit)

    def get_snapshot(self, uid: str, incident_id: UUID) -> SceneSnapshotResponse:
        with PostgresUnitOfWork(self.dsn) as uow:
            self._principal(uow, uid, incident_id, {ROLE_PRIMARY, ROLE_AMBULANCE_GREETER, ROLE_EMS_VIEWER})
            snapshot = self._reads(uow).scene_snapshot(incident_id=str(incident_id), uid=uid)
            observations = []
            for event in uow.events.list_events(str(incident_id)):
                if event.type not in {et.OBSERVATION_PROPOSED, et.OBSERVATION_CONFIRMED}:
                    continue
                detail = event.detail
                if detail.get("key") not in et.OBSERVATION_KEYS:
                    continue
                observations.append({
                    "observationId": detail.get("observationId", event.event_id),
                    "key": detail["key"], "value": detail.get("value", "unknown"),
                    "source": event.envelope.source,
                    "observedAt": detail.get("observedAt", iso(event.envelope.client_time)),
                    "confirmation": detail.get("confirmation", "proposed"),
                    "evidenceEventIds": detail.get("evidenceEventIds", []),
                })
            return SceneSnapshotResponse(
                incidentId=incident_id, snapshotRevision=snapshot.snapshot_revision,
                generatedThroughRevision=snapshot.generated_through_revision,
                generatedThroughSequence=snapshot.generated_through_sequence,
                updatedAt=snapshot.updated_at,
                sections={name: [field.to_dict() for field in values] for name, values in snapshot.sections.items()},
                actionsPerformed=[item.to_dict() for item in snapshot.actions_performed],
                observations=observations,
            )

    def handoff_events(self, uid: str, incident_id: UUID, cursor: str | None, limit: int) -> HandoffEventsResponse:
        with PostgresUnitOfWork(self.dsn) as uow:
            self._principal(uow, uid, incident_id, {ROLE_PRIMARY, ROLE_EMS_VIEWER})
            model = self._reads(uow).handoff(incident_id=str(incident_id), uid=uid, cursor=cursor, page_size=limit)
            return HandoffEventsResponse(
                snapshotRevision=model.snapshot.snapshot_revision,
                generatedThroughRevision=model.snapshot.generated_through_revision,
                events=[{
                    "eventId": entry.event_id, "type": entry.type,
                    "clientTime": entry.client_time, "serverTime": entry.server_time,
                    "detail": entry.detail,
                } for entry in model.timeline.entries],
                nextCursor=model.timeline.next_cursor,
            )

    def handoff(self, uid: str, incident_id: UUID, cursor: str | None, limit: int):
        from app.schemas.contracts import HandoffReadResponse
        with PostgresUnitOfWork(self.dsn) as uow:
            self._principal(uow, uid, incident_id, {ROLE_PRIMARY, ROLE_EMS_VIEWER})
            model = self._reads(uow).handoff(incident_id=str(incident_id), uid=uid, cursor=cursor, page_size=limit)
            return HandoffReadResponse.model_validate(model.to_dict())

    def evaluate_rules(self, uid: str, incident_id: UUID, body: RuleEvaluationRequest) -> RuleEvaluationResponse:
        with PostgresUnitOfWork(self.dsn) as uow:
            record, _ = self._principal(uow, uid, incident_id, {ROLE_PRIMARY}, write=True)
            if body.expectedStateRevision != record.state_revision:
                raise stale("stateRevision", record.state_revision)
            if body.expectedModeRevision != record.mode_revision:
                raise stale("modeRevision", record.mode_revision)
            request = {
                "schemaVersion": "1.0.0", "ruleVersion": record.rule_version,
                "incidentId": record.incident_id, "clinicalState": record.clinical_state or "scene_safety",
                "stateRevision": record.state_revision, "interactionMode": record.interaction_mode,
                "modeRevision": record.mode_revision, "trigger": body.trigger,
                "observations": body.observations, "timers": body.timers,
            }
            outcome = self.rules.evaluate(pinned_rule_version=record.rule_version, request=request)
            if not outcome.ok:
                raise ApiError(outcome.error.code, outcome.error.http_status, outcome.error.message)
            if outcome.pin.clinical_review_required and os.getenv("ENABLE_UNREVIEWED_DEMO_RULES") != "1":
                raise unavailable()
            return RuleEvaluationResponse(
                ruleVersion=outcome.pin.rule_version, contentHash=outcome.pin.content_hash,
                reviewStatus=outcome.pin.review_status,
                clinicalReviewRequired=outcome.pin.clinical_review_required,
                decision=dict(outcome.decision),
            )

    def _assignment_service(self) -> AedAssignmentService:
        return AedAssignmentService(
            records=self.catalog.list_active(), route_provider=_UnavailableRoutes(),
            store=self.assignments,
        )

    def _assignment_response(self, result: ReassignmentResult) -> AedAssignmentResponse:
        assignment = result.assignment
        return AedAssignmentResponse(
            outcome=result.outcome.value, incidentId=result.incident_id,
            reportId=result.report_id, helperId=assignment.helper_id if assignment else None,
            aedId=assignment.aed_id if assignment else None,
            assignmentRevision=assignment.assignment_revision if assignment else None,
            previousAedId=assignment.previous_aed_id if assignment else None,
            excludedAedIds=list(result.excluded_aed_ids), deduplicated=result.deduplicated,
            estimate={
                "outbound": assignment.estimate.outbound.describe(self.clock.now()),
                "return": assignment.estimate.return_leg.describe(self.clock.now()),
                "uncertainty": list(assignment.estimate.uncertainty),
            } if assignment and assignment.estimate else None,
        )

    def get_aed_assignment(
        self, uid: str, incident_id: UUID, helper_id: UUID,
    ) -> AedAssignmentReadResponse:
        with PostgresUnitOfWork(self.dsn) as uow:
            _, principal = self._principal(uow, uid, incident_id, {ROLE_PRIMARY, ROLE_AED_RUNNER})
            if principal.role == ROLE_AED_RUNNER and principal.helper_id != str(helper_id):
                raise ServiceError(UNAUTHORIZED, "helper_scope_denied")
            helper_row = uow.connection.execute(
                "SELECT detail->>'status', server_time FROM incident_events "
                "WHERE incident_id = %s AND event_type = 'helper.updated' "
                "AND detail->>'helperId' = %s AND detail->>'status' IS NOT NULL "
                "ORDER BY server_sequence DESC LIMIT 1",
                (str(incident_id), str(helper_id)),
            ).fetchone()
        assignment = self.assignments.get_assignment(str(incident_id))
        if assignment is None:
            raise ApiError("unavailable", 404, "AED assignment is not available")
        if assignment.helper_id != str(helper_id):
            raise ServiceError(UNAUTHORIZED, "aed_assignment_scope_denied")

        destination = None
        candidate = assignment.candidate
        outbound = assignment.estimate.outbound if assignment.estimate else None
        if candidate is not None:
            availability = {
                "open": "available", "closed": "unavailable", "unknown": "unknown",
            }[candidate.availability.status.value]
            route_based = bool(outbound and outbound.is_route_based)
            destination = AedCandidate(
                aedId=candidate.stable_id,
                name=candidate.record.name,
                latitude=candidate.record.latitude,
                longitude=candidate.record.longitude,
                address=candidate.record.address,
                accessNotes=candidate.record.access_notes,
                availability=availability,
                straightLineMeters=round(candidate.straight_line_meters, 1),
                walkingMeters=round(outbound.distance_meters, 1) if route_based and outbound else None,
                etaSeconds=round(outbound.duration_seconds) if route_based and outbound else None,
                routeUpdatedAt=outbound.computed_at if route_based and outbound else None,
                estimateSource="route" if route_based else "straight_line",
            )
        return AedAssignmentReadResponse(
            incidentId=incident_id,
            helperId=helper_id,
            aedId=assignment.aed_id,
            assignmentRevision=assignment.assignment_revision,
            status=assignment.status.value,
            assignedAt=assignment.assigned_at,
            previousAedId=assignment.previous_aed_id,
            helperStatus=helper_row[0] if helper_row else None,
            helperStatusUpdatedAt=helper_row[1] if helper_row else None,
            destination=destination,
            estimate=assignment.estimate.describe(self.clock.now()) if assignment.estimate else None,
        )

    def dispatch_aed(self, uid: str, incident_id: UUID, body: AedDispatchRequest) -> AedAssignmentResponse:
        with PostgresUnitOfWork(self.dsn) as uow:
            record, _ = self._principal(uow, uid, incident_id, {ROLE_PRIMARY}, write=True)
            if body.expectedStateRevision != record.state_revision:
                raise stale("stateRevision", record.state_revision)
            runner = uow.connection.execute(
                "SELECT 1 FROM access_grants WHERE incident_id = %s AND helper_id = %s "
                "AND scope = 'aed_runner' AND revoked_at IS NULL AND expires_at > %s",
                (str(incident_id), str(body.helperId), self.clock.now()),
            ).fetchone()
            if runner is None:
                raise ServiceError(UNAUTHORIZED, "aed_runner_grant_required")
            patient = self._patient_point(uow, record)
            if patient is None:
                raise ApiError("invalid_input", 409, "Patient location must be reported before AED dispatch")
        helper = (
            HelperPosition(str(body.helperId), GeoPoint(body.helperLocation.latitude, body.helperLocation.longitude), self.clock.now())
            if body.helperLocation else None
        )
        result = self._assignment_service().assign(
            incident_id=str(incident_id), helper_location=evaluate_helper_location(helper, now=self.clock.now(), helper_id=str(body.helperId)),
            patient_point=patient, now=self.clock.now(),
        )
        if result.assignment is not None and result.assignment.helper_id != str(body.helperId):
            raise ApiError("stale_revision", 409, "Incident already has an AED assignment for another helper")
        if result.outcome is ReassignmentOutcome.CONFLICT:
            raise ApiError("stale_revision", 409, "AED assignment changed during dispatch")
        return self._assignment_response(result)

    def report_aed_unavailable(self, uid: str, incident_id: UUID, helper_id: UUID, body: AedUnavailabilityRequest) -> AedAssignmentResponse:
        with PostgresUnitOfWork(self.dsn) as uow:
            record, _ = self._principal(uow, uid, incident_id, {ROLE_AED_RUNNER}, helper_id=helper_id, write=True)
            patient = self._patient_point(uow, record)
            if patient is None:
                raise ApiError("invalid_input", 409, "Patient location is unavailable")
        helper = (
            HelperPosition(str(helper_id), GeoPoint(body.helperLocation.latitude, body.helperLocation.longitude), body.reportedAt)
            if body.helperLocation else None
        )
        report = UnavailabilityReport(
            report_id=str(body.reportId), incident_id=str(incident_id), helper_id=str(helper_id),
            aed_id=body.aedId, reason_code=body.reasonCode,
            reported_at=body.reportedAt, expected_assignment_revision=body.expectedAssignmentRevision,
        )
        result = self._assignment_service().report_unavailable(
            report, helper_location=evaluate_helper_location(helper, now=self.clock.now(), helper_id=str(helper_id)),
            patient_point=patient, now=self.clock.now(),
        )
        if result.outcome is ReassignmentOutcome.STALE_REVISION:
            raise stale("assignmentRevision", result.assignment.assignment_revision if result.assignment else 0)
        if result.outcome is ReassignmentOutcome.AED_MISMATCH:
            raise ServiceError(UNAUTHORIZED, "aed_assignment_scope_denied")
        if result.outcome is ReassignmentOutcome.CONFLICT:
            raise ApiError("stale_revision", 409, "AED assignment changed during report")
        return self._assignment_response(result)

    def patch_incident(self, uid: str, incident_id: UUID, body: PatchIncidentRequest) -> IncidentView:
        with PostgresUnitOfWork(self.dsn) as uow:
            uow.lock_incident(str(incident_id))
            record, _ = self._principal(uow, uid, incident_id, {ROLE_PRIMARY})
            if body.expectedStateRevision != record.state_revision:
                raise stale("stateRevision", record.state_revision)
            now = self.clock.now()
            updated = uow.incidents.put(with_updated(
                record, status=body.status, state_revision=record.state_revision + 1,
                interaction_mode="handover", updated_at=now,
            ))
            if body.status == "closed":
                uow.invitations.revoke_incident(str(incident_id), now)
                uow.grants.revoke_incident(str(incident_id), now)
            return self._view(uow, updated)
