"""Transactional PostgreSQL persistence for the prototype incident state machine.

A single JSONB state row serializes mutations across API workers. This keeps the
existing validated domain transitions and idempotency rules consistent while the
workstream 5 normalized data services are still being built.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import psycopg
from cryptography.fernet import Fernet
from psycopg.types.json import Jsonb

from app.api.errors import unavailable
from app.schemas.contracts import (
    AedListResponse, CreateIncidentRequest, CreateShareRequest, CreateShareResponse,
    EventBatchRequest, EventBatchResponse, HandoffEvent, HandoffEventsResponse,
    HelperUpdateRequest, HelperUpdateResponse, IncidentView, LocationDescriptionRequest,
    LocationDescriptionResponse, PatchIncidentRequest, RevokeAccessRequest,
    RevokeAccessResponse, SceneObservationRequest, SceneObservationResponse,
    SceneSnapshotResponse, Scope, ShareSessionRequest, ShareSessionResponse,
)
from app.services.mock import Record, SyntheticIncidentService


def _seal_share(value: CreateShareResponse, cipher: Fernet) -> dict:
    data = value.model_dump(mode="json")
    data["secret"] = cipher.encrypt(value.secret.encode()).decode()
    return data


def _open_share(value: dict, cipher: Fernet) -> CreateShareResponse:
    data = dict(value)
    data["secret"] = cipher.decrypt(data["secret"].encode()).decode()
    return CreateShareResponse.model_validate(data)


def _dump(service: SyntheticIncidentService, cipher: Fernet) -> dict:
    incidents = {}
    for incident_id, record in service._incidents.items():
        incidents[str(incident_id)] = {
            "owner": record.owner,
            "view": record.view.model_dump(mode="json"),
            "events": {str(key): value.model_dump(mode="json") for key, value in record.events.items()},
            "event_fingerprints": {str(key): value for key, value in record.event_fingerprints.items()},
            "sequences": {f"{key[0]}:{key[1]}": value for key, value in record.sequences.items()},
            "observations": {str(key): value for key, value in record.observations.items()},
            "observation_keys": {str(key): [value[0], value[1].model_dump(mode="json")] for key, value in record.observation_keys.items()},
            "shares": {str(key): [value[0], _seal_share(value[1], cipher)] for key, value in record.shares.items()},
            "helpers": {str(key): value.model_dump(mode="json") for key, value in record.helpers.items()},
            "update_ids": {str(key): [value[0], str(value[1]), value[2].model_dump(mode="json")] for key, value in record.update_ids.items()},
            "revocation_keys": {str(key): [value[0], value[1].model_dump(mode="json")] for key, value in record.revocation_keys.items()},
        }
    return {
        "incidents": incidents,
        "invites": {key: [str(value[0]), _seal_share(value[1], cipher), str(value[2]) if value[2] else None] for key, value in service._invites.items()},
        "invite_failures": dict(service._invite_failures),
        "grants": {f"{key[0]}:{key[1]}": [value[0].value, str(value[1]) if value[1] else None, value[2].isoformat()] for key, value in service._grants.items()},
    }


def _load(data: dict, cipher: Fernet) -> SyntheticIncidentService:
    service = SyntheticIncidentService()
    for key, value in data.get("incidents", {}).items():
        service._incidents[UUID(key)] = Record(
            owner=value["owner"],
            view=IncidentView.model_validate(value["view"]),
            events={UUID(k): HandoffEvent.model_validate(v) for k, v in value["events"].items()},
            event_fingerprints={UUID(k): v for k, v in value["event_fingerprints"].items()},
            sequences={tuple(UUID(part) for part in k.split(":")): v for k, v in value["sequences"].items()},
            observations={UUID(k): v for k, v in value["observations"].items()},
            observation_keys={UUID(k): (v[0], SceneObservationResponse.model_validate(v[1])) for k, v in value["observation_keys"].items()},
            shares={UUID(k): (v[0], _open_share(v[1], cipher)) for k, v in value["shares"].items()},
            helpers={UUID(k): HelperUpdateResponse.model_validate(v) for k, v in value["helpers"].items()},
            update_ids={UUID(k): (v[0], UUID(v[1]), HelperUpdateResponse.model_validate(v[2]) if len(v) > 2 else HelperUpdateResponse.model_validate(value["helpers"][v[1]])) for k, v in value["update_ids"].items()},
            revocation_keys={UUID(k): (v[0], RevokeAccessResponse.model_validate(v[1])) for k, v in value.get("revocation_keys", {}).items()},
        )
    service._invites = {key: (UUID(value[0]), _open_share(value[1], cipher), UUID(value[2]) if value[2] else None) for key, value in data.get("invites", {}).items()}
    service._invite_failures = dict(data.get("invite_failures", {}))
    service._grants = {(parts[0], UUID(parts[1])): (Scope(value[0]), UUID(value[1]) if value[1] else None, datetime.fromisoformat(value[2])) for key, value in data.get("grants", {}).items() for parts in [key.rsplit(":", 1)]}
    return service


class PostgresIncidentService:
    """PostgreSQL backed adapter; external AED, maps, and rules stay unavailable."""

    _writes = frozenset({
        "create_incident", "upload_events", "add_observations", "create_share",
        "exchange_share", "update_helper", "patch_incident", "revoke_access",
    })

    def __init__(self, dsn: str):
        self.dsn = dsn
        key = os.getenv("LOCAL_INVITE_KEY")
        if not key:
            raise RuntimeError("LOCAL_INVITE_KEY is required for encrypted invitations")
        self.cipher = Fernet(key.encode())
        with psycopg.connect(dsn) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS app_state (id integer PRIMARY KEY CHECK (id = 1), data jsonb NOT NULL)")
            connection.execute("INSERT INTO app_state (id, data) VALUES (1, '{}'::jsonb) ON CONFLICT (id) DO NOTHING")

    @staticmethod
    def _purge(service: SyntheticIncidentService) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
        expired_ids = {incident_id for incident_id, record in service._incidents.items() if record.view.createdAt < cutoff}
        for incident_id in expired_ids:
            del service._incidents[incident_id]
        now = datetime.now(timezone.utc)
        old_invites = [key for key, value in service._invites.items() if value[0] in expired_ids or value[1].expiresAt <= now]
        old_grants = [key for key, value in service._grants.items() if key[1] in expired_ids or value[2] <= now]
        for key in old_invites:
            del service._invites[key]
            service._invite_failures[key] = "invitation_expired"
        for key in old_grants:
            del service._grants[key]
        return bool(expired_ids or old_invites or old_grants)

    def _invoke(self, name: str, *args, **kwargs):
        try:
            with psycopg.connect(self.dsn) as connection:
                row = connection.execute("SELECT data FROM app_state WHERE id = 1 FOR UPDATE").fetchone()
                if not row:
                    raise unavailable()
                service = _load(row[0], self.cipher)
                purged = self._purge(service)
                result = getattr(service, name)(*args, **kwargs)
                if name in self._writes or purged:
                    connection.execute("UPDATE app_state SET data = %s WHERE id = 1", (Jsonb(_dump(service, self.cipher)),))
                return result
        except psycopg.Error:
            raise unavailable() from None

    def create_incident(self, uid: str, body: CreateIncidentRequest) -> IncidentView:
        return self._invoke("create_incident", uid, body)

    def authorize(self, uid: str, incident_id: UUID, scopes: set[str], helper_id: UUID | None = None) -> IncidentView:
        return self._invoke("authorize", uid, incident_id, scopes, helper_id)

    def upload_events(self, uid: str, incident_id: UUID, body: EventBatchRequest) -> EventBatchResponse:
        return self._invoke("upload_events", uid, incident_id, body)

    def add_observations(self, uid: str, incident_id: UUID, body: SceneObservationRequest) -> SceneObservationResponse:
        return self._invoke("add_observations", uid, incident_id, body)

    def get_snapshot(self, uid: str, incident_id: UUID) -> SceneSnapshotResponse:
        return self._invoke("get_snapshot", uid, incident_id)

    def describe_location(self, uid: str, incident_id: UUID, body: LocationDescriptionRequest) -> LocationDescriptionResponse:
        return self._invoke("describe_location", uid, incident_id, body)

    def create_share(self, uid: str, incident_id: UUID, body: CreateShareRequest) -> CreateShareResponse:
        return self._invoke("create_share", uid, incident_id, body)

    def revoke_access(self, uid: str, incident_id: UUID, body: RevokeAccessRequest) -> RevokeAccessResponse:
        return self._invoke("revoke_access", uid, incident_id, body)

    def exchange_share(self, uid: str, body: ShareSessionRequest) -> ShareSessionResponse:
        return self._invoke("exchange_share", uid, body)

    def update_helper(self, uid: str, incident_id: UUID, helper_id: UUID, body: HelperUpdateRequest) -> HelperUpdateResponse:
        return self._invoke("update_helper", uid, incident_id, helper_id, body)

    def list_aeds(self, uid: str, incident_id: UUID, limit: int, *, lat: float | None = None, lng: float | None = None) -> AedListResponse:
        return self._invoke("list_aeds", uid, incident_id, limit, lat=lat, lng=lng)

    def handoff_events(self, uid: str, incident_id: UUID, cursor: str | None, limit: int) -> HandoffEventsResponse:
        return self._invoke("handoff_events", uid, incident_id, cursor, limit)

    def patch_incident(self, uid: str, incident_id: UUID, body: PatchIncidentRequest) -> IncidentView:
        return self._invoke("patch_incident", uid, incident_id, body)
