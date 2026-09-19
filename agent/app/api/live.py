from __future__ import annotations

import base64
import binascii
import json
from typing import Callable
from uuid import UUID

from flask import Flask, request
from flask_sock import Sock
from pydantic import ValidationError
from simple_websocket.errors import ConnectionClosed

from app.agent.live_provider import ObservationProvider, default_provider
from app.api.auth import TokenVerifier
from app.api.errors import ApiError, unavailable
from app.schemas.contracts import InteractionMode, LiveEnvelope, MediaFrame
from app.services.ports import IncidentService


class LiveSession:
    def __init__(self, service: IncidentService, verifier: TokenVerifier, provider_factory: Callable[[str, UUID], ObservationProvider] = default_provider):
        self.service = service
        self.verifier = verifier
        self.provider_factory = provider_factory
        self.provider: ObservationProvider | None = None
        self.voice_allowed = False
        self.uid: str | None = None
        self.incident_id: UUID | None = None
        self.client_id: UUID | None = None
        self.client_instance_id: UUID | None = None
        self.last_sequence = -1
        self.last_media_sequence = -1
        self.session_id: UUID | None = None
        self.mode_revision = 0

    def authenticate(self, message: dict, incident_id: UUID) -> dict:
        if message.get("type") != "auth" or not isinstance(message.get("token"), str):
            raise ApiError("unauthorized", 401, "Authentication required")
        uid = self.verifier.verify(message["token"])
        envelope = LiveEnvelope.model_validate(message.get("envelope"))
        if envelope.incidentId != incident_id or envelope.payload.get("type") != "session.hello":
            raise ApiError("invalid_input", 400, "Invalid Live hello")
        view = self.service.authorize(uid, incident_id, {"primary"})
        if envelope.clientId != view.primaryClientId:
            raise ApiError("unauthorized", 403, "Client does not own incident")
        if envelope.authorityEpoch != view.authorityEpoch:
            raise ApiError("stale_revision", 409, "Authority epoch changed")
        self.uid = uid
        self.incident_id = incident_id
        self.client_id = envelope.clientId
        self.client_instance_id = envelope.clientInstanceId
        self.last_sequence = envelope.clientSequence
        self.mode_revision = view.modeRevision
        return {
            "type": "session.ready", "voiceAllowed": False,
            "interactionMode": view.interactionMode.value,
            "stateRevision": view.stateRevision,
            "modeRevision": view.modeRevision,
            "authorityEpoch": view.authorityEpoch,
            "resumeRequired": True,
        }

    def receive(self, raw: dict) -> dict:
        if self.uid is None or self.incident_id is None:
            raise ApiError("unauthorized", 401, "Authentication required")
        envelope = LiveEnvelope.model_validate(raw)
        if envelope.incidentId != self.incident_id or envelope.clientId != self.client_id or envelope.clientInstanceId != self.client_instance_id:
            raise ApiError("unauthorized", 403, "Live identity mismatch")
        if envelope.clientSequence <= self.last_sequence:
            raise ApiError("stale_revision", 409, "Client sequence is stale")
        self.last_sequence = envelope.clientSequence
        kind = envelope.payload.get("type")
        if kind == "mode.silence":
            self.silence()
            return {"type": "mode.silenced", "messageId": str(envelope.messageId), "modeRevision": envelope.modeRevision}
        view = self.service.authorize(self.uid, self.incident_id, {"primary"})
        if envelope.authorityEpoch != view.authorityEpoch or envelope.modeRevision != view.modeRevision or envelope.stateRevision != view.stateRevision:
            self.silence()
            raise ApiError("stale_revision", 409, "Live state changed", {"stateRevision": view.stateRevision, "modeRevision": view.modeRevision, "authorityEpoch": view.authorityEpoch})
        self.mode_revision = view.modeRevision
        if kind == "resume.request":
            if view.interactionMode != InteractionMode.VOICE_GUIDANCE:
                self.silence()
                raise ApiError("unauthorized", 403, "Voice guidance is not active")
            if self.provider is None:
                provider = self.provider_factory(self.uid, self.incident_id)
                try:
                    provider.start()
                except Exception:
                    provider.close()
                    raise
                self.provider = provider
            self.voice_allowed = True
            return {"type": "resume.accepted", "messageId": str(envelope.messageId), "modeRevision": view.modeRevision}
        if kind == "media.frame":
            if not self.voice_allowed or view.interactionMode != InteractionMode.VOICE_GUIDANCE or not self.provider:
                raise ApiError("unauthorized", 403, "Media is muted")
            frame = MediaFrame.model_validate(envelope.payload.get("frame"))
            if frame.modeRevision != view.modeRevision or frame.sequence <= self.last_media_sequence:
                raise ApiError("stale_revision", 409, "Media frame is stale")
            if self.session_id is None:
                self.session_id = frame.sessionId
            elif frame.sessionId != self.session_id:
                raise ApiError("invalid_input", 400, "Media session changed")
            try:
                data = base64.b64decode(frame.data, validate=True)
            except binascii.Error:
                raise ApiError("invalid_input", 400, "Invalid media encoding") from None
            if len(data) > 65_536:
                raise ApiError("invalid_input", 413, "Media frame too large")
            if frame.contentType != "audio/pcm;rate=16000":
                raise unavailable()  # Camera analysis requires a separate reviewed adapter.
            self.provider.send_audio(data)
            self.last_media_sequence = frame.sequence
            return {"type": "media.ack", "messageId": str(envelope.messageId), "sequence": frame.sequence, "modeRevision": view.modeRevision}
        raise ApiError("invalid_input", 400, "Unknown Live payload")

    def poll(self) -> list[dict]:
        if not self.voice_allowed or not self.provider or not self.uid or not self.incident_id:
            return []
        view = self.service.authorize(self.uid, self.incident_id, {"primary"})
        if view.modeRevision != self.mode_revision or view.interactionMode != InteractionMode.VOICE_GUIDANCE:
            self.silence()
            return []
        return [{
            "type": "observation.proposed",
            "messageId": item["observationId"],
            "stateRevision": view.stateRevision,
            "modeRevision": view.modeRevision,
            "observation": item,
        } for item in self.provider.poll()]

    def silence(self) -> None:
        self.voice_allowed = False
        if self.provider:
            self.provider.close()
            self.provider = None
        self.session_id = None
        self.last_media_sequence = -1

    def close(self) -> None:
        self.silence()


def register_live(app: Flask, service: IncidentService | None, verifier: TokenVerifier, origins: set[str]) -> None:
    sock = Sock(app)

    @sock.route("/v1/incidents/<incident_id>/live")
    def live(ws, incident_id):
        origin = request.headers.get("Origin")
        if not origin or origin not in origins:
            ws.close(reason="Origin not permitted")
            return
        if service is None:
            ws.send(json.dumps({"type": "error", "code": "unavailable"}))
            ws.close()
            return
        try:
            incident_uuid = UUID(incident_id)
        except ValueError:
            ws.close(reason="Invalid incident ID")
            return
        session = LiveSession(service, verifier)
        try:
            first = ws.receive(timeout=5)
            if first is None or len(first) > 8192:
                ws.close(reason="Authentication required")
                return
            ws.send(json.dumps(session.authenticate(json.loads(first), incident_uuid)))
            while True:
                try:
                    message = ws.receive(timeout=0.25)
                except ConnectionClosed:
                    break
                if message is not None:
                    try:
                        if len(message) > 350_000:
                            raise ApiError("invalid_input", 413, "Live message too large")
                        ws.send(json.dumps(session.receive(json.loads(message))))
                    except (ApiError, ValidationError, ValueError, TypeError) as exc:
                        code = exc.code if isinstance(exc, ApiError) else "invalid_input"
                        ws.send(json.dumps({"type": "error", "code": code}))
                for event in session.poll():
                    ws.send(json.dumps(event))
        except (ApiError, ValidationError, ValueError, TypeError) as exc:
            code = exc.code if isinstance(exc, ApiError) else "invalid_input"
            ws.send(json.dumps({"type": "error", "code": code}))
        except ConnectionClosed:
            pass
        finally:
            session.close()
            ws.close()
