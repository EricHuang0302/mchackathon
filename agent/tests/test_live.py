from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.errors import ApiError
from app.api.live import LiveSession
from app.schemas.contracts import CreateIncidentRequest, EventBatchRequest, EventInput
from app.services.mock import SyntheticIncidentService


class Verifier:
    def verify(self, token):
        if token != "alice":
            raise ApiError("unauthorized", 401, "Invalid authentication")
        return "alice"


class Provider:
    def __init__(self):
        self.closed = False
        self.audio = []

    def start(self):
        pass

    def send_audio(self, data):
        self.audio.append(data)

    def poll(self):
        return []

    def close(self):
        self.closed = True


def envelope(incident_id, client_id, instance_id, sequence, state=0, mode=0, payload=None):
    return {"protocolVersion": 1, "messageId": str(uuid4()), "incidentId": str(incident_id), "clientId": str(client_id), "clientInstanceId": str(instance_id), "clientSequence": sequence, "clientTime": datetime.now(timezone.utc).isoformat(), "authorityEpoch": 1, "stateRevision": state, "modeRevision": mode, "payload": payload or {"type": "session.hello"}}


def test_reconnect_starts_muted_and_on_call_refuses_resume():
    service = SyntheticIncidentService()
    incident_id, client_id, instance_id = uuid4(), uuid4(), uuid4()
    service.create_incident("alice", CreateIncidentRequest(incidentId=incident_id, primaryClientId=client_id, ruleVersion="demo-v1"))
    providers = []

    def factory(_uid, _incident_id):
        provider = Provider()
        providers.append(provider)
        return provider

    session = LiveSession(service, Verifier(), factory)
    ready = session.authenticate({"type": "auth", "token": "alice", "envelope": envelope(incident_id, client_id, instance_id, 0)}, incident_id)
    assert ready["voiceAllowed"] is False
    with pytest.raises(ApiError):
        session.receive(envelope(incident_id, client_id, instance_id, 1, payload={"type": "resume.request"}))
    assert providers == []
    mode_event = EventInput.model_validate({"eventId": str(uuid4()), "type": "mode.changed", "detail": {"interactionMode": "on_call", "reason": "dial_started"}, "clientId": str(client_id), "clientInstanceId": str(instance_id), "clientSequence": 1, "clientTime": datetime.now(timezone.utc).isoformat(), "authorityEpoch": 1, "stateRevision": 0, "modeRevision": 1, "ruleVersion": "demo-v1"})
    service.upload_events("alice", incident_id, EventBatchRequest(events=[mode_event]))
    session.silence()
    reconnect = LiveSession(service, Verifier(), factory)
    ready = reconnect.authenticate({"type": "auth", "token": "alice", "envelope": envelope(incident_id, client_id, uuid4(), 0)}, incident_id)
    assert ready["interactionMode"] == "on_call"
    assert ready["voiceAllowed"] is False
    with pytest.raises(ApiError):
        reconnect.receive(envelope(incident_id, client_id, reconnect.client_instance_id, 1, state=1, mode=1, payload={"type": "resume.request"}))


def test_silence_stops_provider_and_stale_media():
    service = SyntheticIncidentService()
    incident_id, client_id, instance_id = uuid4(), uuid4(), uuid4()
    service.create_incident("alice", CreateIncidentRequest(incidentId=incident_id, primaryClientId=client_id, ruleVersion="demo-v1"))
    service.upload_events("alice", incident_id, EventBatchRequest(events=[EventInput.model_validate({"eventId": str(uuid4()), "type": "mode.changed", "detail": {"interactionMode": "voice_guidance", "reason": "user_reports_call_failed"}, "clientId": str(client_id), "clientInstanceId": str(instance_id), "clientSequence": 1, "clientTime": datetime.now(timezone.utc).isoformat(), "authorityEpoch": 1, "stateRevision": 0, "modeRevision": 1, "ruleVersion": "demo-v1"})]))
    provider = Provider()
    session = LiveSession(service, Verifier(), lambda *_: provider)
    session.authenticate({"type": "auth", "token": "alice", "envelope": envelope(incident_id, client_id, instance_id, 2, state=1, mode=1)}, incident_id)
    session.receive(envelope(incident_id, client_id, instance_id, 3, state=1, mode=1, payload={"type": "resume.request"}))
    assert session.voice_allowed
    session.receive(envelope(incident_id, client_id, instance_id, 4, state=1, mode=2, payload={"type": "mode.silence"}))
    assert not session.voice_allowed and provider.closed
    with pytest.raises(ApiError):
        session.receive(envelope(incident_id, client_id, instance_id, 5, state=1, mode=1, payload={"type": "media.frame", "frame": {"sessionId": str(uuid4()), "sequence": 1, "modeRevision": 1, "contentType": "audio/pcm;rate=16000", "data": "AA=="}}))


def test_redial_revision_discards_pending_output():
    service = SyntheticIncidentService()
    incident_id, client_id, instance_id = uuid4(), uuid4(), uuid4()
    service.create_incident("alice", CreateIncidentRequest(incidentId=incident_id, primaryClientId=client_id, ruleVersion="demo-v1"))
    def mode_event(sequence, state, mode, target, reason):
        return EventInput.model_validate({"eventId": str(uuid4()), "type": "mode.changed", "detail": {"interactionMode": target, "reason": reason}, "clientId": str(client_id), "clientInstanceId": str(instance_id), "clientSequence": sequence, "clientTime": datetime.now(timezone.utc).isoformat(), "authorityEpoch": 1, "stateRevision": state, "modeRevision": mode, "ruleVersion": "demo-v1"})
    service.upload_events("alice", incident_id, EventBatchRequest(events=[mode_event(1, 0, 1, "voice_guidance", "user_reports_call_failed")]))
    provider = Provider()
    session = LiveSession(service, Verifier(), lambda *_: provider)
    session.authenticate({"type": "auth", "token": "alice", "envelope": envelope(incident_id, client_id, instance_id, 2)}, incident_id)
    session.receive(envelope(incident_id, client_id, instance_id, 3, state=1, mode=1, payload={"type": "resume.request"}))
    service.upload_events("alice", incident_id, EventBatchRequest(events=[mode_event(4, 1, 2, "on_call", "dial_started")]))
    assert session.poll() == []
    assert provider.closed and not session.voice_allowed
    with pytest.raises(ApiError):
        session.receive(envelope(incident_id, client_id, instance_id, 4, state=1, mode=1, payload={"type": "resume.request"}))


def test_model_output_only_proposes_allowlisted_observations():
    from app.agent.live_provider import AdkObservationProvider

    provider = AdkObservationProvider("alice", uuid4())
    provider._accept_text('{"observations":[{"key":"treatment","value":"start CPR"},{"key":"breathing_normal","value":"start CPR"},{"key":"breathing_normal","value":"unknown"}]}')
    proposals = provider.poll()
    assert len(proposals) == 1
    assert proposals[0]["key"] == "breathing_normal"
    assert proposals[0]["source"] == "model_proposal"
    assert proposals[0]["confirmation"] == "proposed"


def test_live_poll_pushes_proposal_with_deduplication_id():
    service = SyntheticIncidentService()
    incident_id, client_id, instance_id = uuid4(), uuid4(), uuid4()
    service.create_incident("alice", CreateIncidentRequest(incidentId=incident_id, primaryClientId=client_id, ruleVersion="demo-v1"))
    service.upload_events("alice", incident_id, EventBatchRequest(events=[EventInput.model_validate({"eventId": str(uuid4()), "type": "mode.changed", "detail": {"interactionMode": "voice_guidance", "reason": "user_reports_call_failed"}, "clientId": str(client_id), "clientInstanceId": str(instance_id), "clientSequence": 1, "clientTime": datetime.now(timezone.utc).isoformat(), "authorityEpoch": 1, "stateRevision": 0, "modeRevision": 1, "ruleVersion": "demo-v1"})]))
    observation_id = str(uuid4())
    provider = Provider()
    provider.poll = lambda: [{
        "observationId": observation_id, "key": "responsive", "value": False,
        "source": "model_proposal", "observedAt": datetime.now(timezone.utc).isoformat(),
        "confirmation": "proposed", "evidenceEventIds": [],
    }]
    session = LiveSession(service, Verifier(), lambda *_: provider)
    session.authenticate({"type": "auth", "token": "alice", "envelope": envelope(incident_id, client_id, instance_id, 2, state=1, mode=1)}, incident_id)
    session.receive(envelope(incident_id, client_id, instance_id, 3, state=1, mode=1, payload={"type": "resume.request"}))

    event = session.poll()[0]
    assert event["type"] == "observation.proposed"
    assert event["messageId"] == observation_id
    assert event["stateRevision"] == 1
    assert event["modeRevision"] == 1
