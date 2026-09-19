"""Idempotent, append-only incident event ingestion.

One bounded ordered batch is the unit of work (``docs/sdd.md`` section 9). A
single bad event produces a conflict entry and the rest of the batch is still
processed, because discarding a whole offline batch over one stale revision
would lose scene history that cannot be recreated.

Checks applied per event, in order:

1. envelope validation and event-type allowlist (``invalid_input``);
2. idempotency by client-supplied ``eventId`` (``duplicate``);
3. role authorization for the submitted type (``unauthorized``);
4. pinned rule version (``rule_mismatch``);
5. authority epoch (``stale_revision`` / ``unauthorized``);
6. monotonic revision checks for authority-asserting types
   (``stale_revision``);
7. correction target resolution (``invalid_input``).

Nothing in this module rewrites an accepted event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from . import event_types as et
from .access import (
    HELPER_ROLES,
    ROLE_PRIMARY,
    WRITE_INCIDENT_EVENTS,
    WRITE_OWN_HELPER_UPDATES,
    Principal,
)
from .clock import Clock, iso, utc
from .errors import (
    INVALID_INPUT,
    RULE_MISMATCH,
    STALE_REVISION,
    UNAUTHORIZED,
    RetentionPolicy,
    ServiceError,
)
from .event_store import EventStore, IncidentStore
from .ids import require_event_id
from .models import (
    Acknowledgement,
    EventBatchResult,
    EventConflict,
    EventEnvelope,
    IncidentRecord,
    JsonDict,
    StoredEvent,
    with_updated,
)

#: Upper bound on one uploaded batch. A reconnecting client uploads several
#: bounded batches rather than one unbounded replay.
DEFAULT_MAX_BATCH_SIZE = 200

_CALL_REPORT_STATES = frozenset(
    {
        "dial_started",
        "dispatcher_active",
        "delegated_call_active",
        "call_ended",
        "could_not_connect",
        "uncertain",
    }
)


def _require(condition: bool, reason: str, **detail: Any) -> None:
    if not condition:
        raise ServiceError(INVALID_INPUT, reason, detail=detail)


def _as_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceError(INVALID_INPUT, "expected_integer", detail={"field": field})
    if value < minimum:
        raise ServiceError(
            INVALID_INPUT, "integer_below_minimum",
            detail={"field": field, "minimum": minimum},
        )
    return value


def _as_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ServiceError(
            INVALID_INPUT, "expected_non_empty_string", detail={"field": field}
        )
    return value


def parse_envelope(payload: Mapping[str, Any]) -> EventEnvelope:
    """Validate one client event payload into an :class:`EventEnvelope`.

    ``source`` defaults to ``user_report`` because the wire example in section
    9 omits it for plain user reports; any other source must be stated.
    """
    if not isinstance(payload, Mapping):
        raise ServiceError(INVALID_INPUT, "expected_object")

    event_id = require_event_id(payload.get("eventId"))
    event_type = payload.get("type")
    if event_type not in et.EVENT_TYPE_SET:
        raise ServiceError(
            INVALID_INPUT, "unknown_event_type", detail={"type": event_type}
        )
    if event_type not in et.CLIENT_SUBMITTABLE_EVENT_TYPES:
        raise ServiceError(
            INVALID_INPUT,
            "server_projected_event_type",
            detail={"type": event_type},
        )

    detail = payload.get("detail", {})
    _require(isinstance(detail, Mapping), "detail_must_be_object", field="detail")

    source = payload.get("source", "user_report")
    if source not in et.SOURCE_SET:
        raise ServiceError(INVALID_INPUT, "unknown_source", detail={"source": source})

    client_time_raw = payload.get("clientTime")
    _require(isinstance(client_time_raw, str), "expected_timestamp", field="clientTime")
    try:
        client_time = utc(client_time_raw)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ServiceError(
            INVALID_INPUT, "malformed_timestamp", detail={"field": "clientTime"}
        ) from exc

    uncertain = payload.get("clientTimeUncertain", False)
    _require(isinstance(uncertain, bool), "expected_boolean", field="clientTimeUncertain")

    return EventEnvelope(
        event_id=event_id,
        type=event_type,
        detail=dict(detail),
        client_id=_as_text(payload.get("clientId"), "clientId"),
        client_instance_id=_as_text(
            payload.get("clientInstanceId"), "clientInstanceId"
        ),
        client_sequence=_as_int(
            payload.get("clientSequence"), "clientSequence", minimum=1
        ),
        client_time=client_time,
        authority_epoch=_as_int(payload.get("authorityEpoch"), "authorityEpoch"),
        state_revision=_as_int(payload.get("stateRevision"), "stateRevision"),
        mode_revision=_as_int(payload.get("modeRevision"), "modeRevision"),
        rule_version=_as_text(payload.get("ruleVersion"), "ruleVersion"),
        source=source,
        client_time_uncertain=uncertain,
    )


def envelope_fingerprint(envelope: EventEnvelope) -> str:
    """Stable fingerprint of the meaningful content of an event.

    Used to detect an event ID reused for different content, which is a client
    bug that must not be silently accepted as a duplicate.
    """
    return json.dumps(
        {
            "eventId": envelope.event_id,
            "type": envelope.type,
            "detail": envelope.detail,
            "clientId": envelope.client_id,
            "clientInstanceId": envelope.client_instance_id,
            "clientSequence": envelope.client_sequence,
            "clientTime": iso(envelope.client_time),
            "clientTimeUncertain": envelope.client_time_uncertain,
            "authorityEpoch": envelope.authority_epoch,
            "stateRevision": envelope.state_revision,
            "modeRevision": envelope.mode_revision,
            "ruleVersion": envelope.rule_version,
            "source": envelope.source,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


@dataclass(frozen=True, slots=True)
class _Outcome:
    """Internal per-event decision before anything is written."""

    conflict: EventConflict | None = None
    incident: IncidentRecord | None = None


class IncidentEventService:
    """Append-only ingestion plus canonical incident-state maintenance."""

    def __init__(
        self,
        events: EventStore,
        incidents: IncidentStore,
        clock: Clock,
        *,
        retention: RetentionPolicy | None = None,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
    ) -> None:
        self._events = events
        self._incidents = incidents
        self._clock = clock
        self._retention = retention or RetentionPolicy()
        self._max_batch_size = max_batch_size

    # -- incident lifecycle -------------------------------------------------

    def register_incident(
        self,
        *,
        incident_id: str,
        owner_uid: str,
        primary_client_id: str,
        rule_version: str,
    ) -> IncidentRecord:
        """Idempotently register a client-generated incident ID."""
        require_event_id(incident_id, field="incidentId")
        now = self._clock.now()
        record = IncidentRecord(
            incident_id=incident_id,
            owner_uid=_as_text(owner_uid, "ownerUid"),
            primary_client_id=_as_text(primary_client_id, "primaryClientId"),
            rule_version=_as_text(rule_version, "ruleVersion"),
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=self._retention.incident_seconds),
        )
        return self._incidents.create(record)

    def get_incident(self, incident_id: str) -> IncidentRecord:
        return self._incidents.require(incident_id)

    def save_incident(self, record: IncidentRecord) -> IncidentRecord:
        """Persist a canonical incident record produced by another service."""
        return self._incidents.put(record)

    def events_for(self, incident_id: str) -> tuple[StoredEvent, ...]:
        """Return every retained event for an incident in server receipt order."""
        return self._events.list_events(incident_id)

    # -- ingestion ----------------------------------------------------------

    def ingest_batch(
        self,
        incident_id: str,
        payloads: Sequence[Mapping[str, Any] | EventEnvelope],
        *,
        principal: Principal,
    ) -> EventBatchResult:
        """Ingest one bounded ordered batch and return per-event results."""
        incident = self._incidents.require(incident_id)
        self._authorize_batch(incident, principal)

        if len(payloads) > self._max_batch_size:
            raise ServiceError(
                INVALID_INPUT,
                "batch_too_large",
                detail={"maxBatchSize": self._max_batch_size, "received": len(payloads)},
            )

        acknowledgements: list[Acknowledgement] = []
        conflicts: list[EventConflict] = []
        accepted_ids: set[str] = set()
        settled: dict[str, list[int]] = {}

        for payload in payloads:
            try:
                envelope = (
                    payload
                    if isinstance(payload, EventEnvelope)
                    else parse_envelope(payload)
                )
            except ServiceError as exc:
                raw_id = (
                    payload.get("eventId") if isinstance(payload, Mapping) else None
                )
                conflicts.append(
                    EventConflict(
                        event_id=raw_id if isinstance(raw_id, str) else None,
                        code=exc.code,
                        reason=exc.reason,
                        detail=exc.detail,
                    )
                )
                continue

            existing = self._events.get(incident_id, envelope.event_id)
            if existing is not None:
                if envelope_fingerprint(existing.envelope) != envelope_fingerprint(
                    envelope
                ):
                    conflicts.append(
                        EventConflict(
                            event_id=envelope.event_id,
                            code=INVALID_INPUT,
                            reason="event_id_reused_for_different_content",
                        )
                    )
                    continue
                acknowledgements.append(_acknowledge(existing, "duplicate"))
                settled.setdefault(envelope.client_id, []).append(
                    envelope.client_sequence
                )
                continue

            outcome = self._evaluate(incident, envelope, principal, accepted_ids)
            if outcome.conflict is not None:
                conflicts.append(outcome.conflict)
                continue

            sequence_owner = self._events._get_by_client_sequence(
                incident_id, envelope.client_id, envelope.client_instance_id,
                envelope.client_sequence,
            )
            if sequence_owner is not None:
                conflicts.append(EventConflict(
                    event_id=envelope.event_id, code=INVALID_INPUT,
                    reason="client_sequence_reused_for_different_event",
                    detail={"existingEventId": sequence_owner.event_id},
                ))
                continue

            stored = self._append(incident_id, envelope, principal)
            incident = outcome.incident or incident
            accepted_ids.add(envelope.event_id)
            acknowledgements.append(_acknowledge(stored, "accepted"))
            settled.setdefault(envelope.client_id, []).append(envelope.client_sequence)

        incident = self._advance_acknowledged(incident, settled)
        incident = with_updated(incident, updated_at=self._clock.now())
        self._incidents.put(incident)
        return EventBatchResult(
            incident=incident,
            acknowledgements=tuple(acknowledgements),
            conflicts=tuple(conflicts),
        )

    # -- internals ----------------------------------------------------------

    def _authorize_batch(
        self, incident: IncidentRecord, principal: Principal
    ) -> None:
        if principal.incident_id != incident.incident_id:
            raise ServiceError(
                UNAUTHORIZED,
                "principal_incident_mismatch",
                detail={"incidentId": incident.incident_id},
            )
        if principal.role == ROLE_PRIMARY:
            principal.require(WRITE_INCIDENT_EVENTS)
            if principal.uid != incident.owner_uid:
                raise ServiceError(UNAUTHORIZED, "not_incident_owner")
            return
        if principal.role in HELPER_ROLES:
            principal.require(WRITE_OWN_HELPER_UPDATES)
            return
        raise ServiceError(
            UNAUTHORIZED, "role_cannot_write_events", detail={"role": principal.role}
        )

    def _evaluate(
        self,
        incident: IncidentRecord,
        envelope: EventEnvelope,
        principal: Principal,
        accepted_ids: set[str],
    ) -> _Outcome:
        conflict = self._check_role_scope(incident, envelope, principal)
        if conflict is not None:
            return _Outcome(conflict=conflict)

        if envelope.rule_version != incident.rule_version:
            return _Outcome(
                conflict=EventConflict(
                    envelope.event_id,
                    RULE_MISMATCH,
                    "pinned_rule_version_mismatch",
                    {"expected": incident.rule_version, "received": envelope.rule_version},
                )
            )

        updated = incident
        if envelope.authority_epoch < incident.authority_epoch:
            return _Outcome(
                conflict=EventConflict(
                    envelope.event_id,
                    STALE_REVISION,
                    "authority_epoch_stale",
                    {
                        "expected": incident.authority_epoch,
                        "received": envelope.authority_epoch,
                    },
                )
            )
        if envelope.authority_epoch > incident.authority_epoch:
            # Only the registered primary client may advance the epoch; a
            # second writer claiming a higher epoch is the ownership conflict
            # described in section 7.4, not a valid takeover.
            if (
                principal.role != ROLE_PRIMARY
                or envelope.client_id != incident.primary_client_id
            ):
                return _Outcome(
                    conflict=EventConflict(
                        envelope.event_id,
                        UNAUTHORIZED,
                        "non_primary_authority_epoch_advance",
                        {"primaryClientId": incident.primary_client_id},
                    )
                )
            updated = with_updated(updated, authority_epoch=envelope.authority_epoch)

        try:
            updated = self._apply_type_rules(updated, envelope, accepted_ids)
        except ServiceError as exc:
            return _Outcome(
                conflict=EventConflict(
                    envelope.event_id, exc.code, exc.reason, exc.detail
                )
            )
        return _Outcome(incident=updated)

    def _check_role_scope(
        self,
        incident: IncidentRecord,
        envelope: EventEnvelope,
        principal: Principal,
    ) -> EventConflict | None:
        if principal.role == ROLE_PRIMARY:
            return None
        if envelope.type != et.HELPER_UPDATED:
            return EventConflict(
                envelope.event_id,
                UNAUTHORIZED,
                "helper_may_only_submit_helper_updates",
                {"role": principal.role, "type": envelope.type},
            )
        helper_id = envelope.detail.get("helperId")
        if not helper_id or helper_id != principal.helper_id:
            return EventConflict(
                envelope.event_id,
                UNAUTHORIZED,
                "helper_id_not_owned_by_principal",
                {"role": principal.role},
            )
        return None

    def _apply_type_rules(
        self,
        incident: IncidentRecord,
        envelope: EventEnvelope,
        accepted_ids: set[str],
    ) -> IncidentRecord:
        detail = envelope.detail
        kind = envelope.type

        if kind == et.MODE_CHANGED:
            mode = detail.get("mode")
            if mode not in et.INTERACTION_MODE_SET:
                raise ServiceError(
                    INVALID_INPUT, "unknown_interaction_mode", detail={"mode": mode}
                )
            revision = _as_int(detail.get("modeRevision"), "detail.modeRevision")
            reason = detail.get("reason")
            if reason is not None:
                transitions = {
                    ("call_119", "dial_started"): "on_call",
                    ("call_119", "dispatcher_reported_active"): "on_call",
                    ("call_119", "user_reports_call_failed"): "voice_guidance",
                    ("on_call", "user_reports_call_ended_or_failed"): "voice_guidance",
                    ("voice_guidance", "dial_started"): "on_call",
                    ("voice_guidance", "dispatcher_reported_active"): "on_call",
                    ("call_119", "user_reports_ems_arrived"): "handover",
                    ("on_call", "user_reports_ems_arrived"): "handover",
                    ("voice_guidance", "user_reports_ems_arrived"): "handover",
                }
                if transitions.get((incident.interaction_mode, reason)) != mode:
                    raise ServiceError(INVALID_INPUT, "invalid_mode_transition")
                if revision != incident.mode_revision + 1:
                    raise ServiceError(
                        STALE_REVISION, "mode_revision_not_next",
                        detail={"currentModeRevision": incident.mode_revision},
                    )
            if revision <= incident.mode_revision:
                # The local mode wins: a late or replayed mode event never
                # overwrites a newer mode the client already applied.
                raise ServiceError(
                    STALE_REVISION,
                    "mode_revision_not_advancing",
                    detail={
                        "currentModeRevision": incident.mode_revision,
                        "receivedModeRevision": revision,
                        "currentInteractionMode": incident.interaction_mode,
                    },
                )
            return with_updated(
                incident, interaction_mode=mode, mode_revision=revision
            )

        if kind == et.INCIDENT_STATE_UPDATED:
            revision = _as_int(detail.get("stateRevision"), "detail.stateRevision")
            if revision <= incident.state_revision:
                raise ServiceError(
                    STALE_REVISION,
                    "state_revision_not_advancing",
                    detail={
                        "currentStateRevision": incident.state_revision,
                        "receivedStateRevision": revision,
                    },
                )
            changes: dict[str, Any] = {"state_revision": revision}
            if "clinicalState" in detail:
                changes["clinical_state"] = detail["clinicalState"]
            if "status" in detail:
                status = detail["status"]
                if status not in et.INCIDENT_STATUS_SET:
                    raise ServiceError(
                        INVALID_INPUT, "unknown_incident_status",
                        detail={"status": status},
                    )
                changes["status"] = status
            if "guidancePaused" in detail:
                paused = detail["guidancePaused"]
                if not isinstance(paused, bool):
                    raise ServiceError(
                        INVALID_INPUT, "expected_boolean",
                        detail={"field": "detail.guidancePaused"},
                    )
                changes["guidance_paused"] = paused
            return with_updated(incident, **changes)

        if kind == et.DECISION_COMMITTED:
            decision_rule_version = detail.get("ruleVersion", envelope.rule_version)
            if decision_rule_version != incident.rule_version:
                raise ServiceError(
                    RULE_MISMATCH,
                    "decision_rule_version_mismatch",
                    detail={"expected": incident.rule_version},
                )
            expected = detail.get("expectedStateRevision")
            if expected is not None:
                expected_revision = _as_int(expected, "detail.expectedStateRevision")
                if expected_revision != incident.state_revision:
                    raise ServiceError(
                        STALE_REVISION,
                        "decision_expected_state_revision_mismatch",
                        detail={
                            "currentStateRevision": incident.state_revision,
                            "expectedStateRevision": expected_revision,
                        },
                    )
            revision = _as_int(detail.get("stateRevision"), "detail.stateRevision")
            if revision <= incident.state_revision:
                raise ServiceError(
                    STALE_REVISION,
                    "state_revision_not_advancing",
                    detail={"currentStateRevision": incident.state_revision},
                )
            changes = {"state_revision": revision}
            if "toState" in detail:
                changes["clinical_state"] = detail["toState"]
            return with_updated(incident, **changes)

        if kind == et.CALL_REPORTED:
            reported_state = detail.get("reportedState")
            if reported_state not in _CALL_REPORT_STATES:
                raise ServiceError(
                    INVALID_INPUT,
                    "unknown_call_report_state",
                    detail={"reportedState": reported_state},
                )
            # A call report is a user statement, never verified telephony. It
            # records call status and deliberately does not move the
            # interaction mode; only an explicit mode.changed does that.
            delegated_call_active = detail.get("delegatedCallActive", False)
            if not isinstance(delegated_call_active, bool):
                raise ServiceError(
                    INVALID_INPUT,
                    "expected_boolean",
                    detail={"field": "detail.delegatedCallActive"},
                )
            call_status: JsonDict = {
                "reportedState": reported_state,
                "source": envelope.source,
                "reportedAt": iso(envelope.client_time),
                "delegatedCallActive": delegated_call_active,
                "eventId": envelope.event_id,
            }
            return with_updated(incident, call_status=call_status)

        if kind == et.EVENT_CORRECTED:
            target = detail.get("correctsEventId")
            if not isinstance(target, str) or not target:
                raise ServiceError(
                    INVALID_INPUT, "correction_requires_target",
                    detail={"field": "detail.correctsEventId"},
                )
            if target == envelope.event_id:
                raise ServiceError(INVALID_INPUT, "correction_targets_itself")
            known = target in accepted_ids or self._events.contains(
                incident.incident_id, target
            )
            if not known:
                raise ServiceError(
                    INVALID_INPUT,
                    "unknown_correction_target",
                    detail={"correctsEventId": target},
                )
            return incident

        if kind in (et.OBSERVATION_PROPOSED, et.OBSERVATION_CONFIRMED):
            key = detail.get("key")
            if key not in et.OBSERVATION_KEYS:
                raise ServiceError(
                    INVALID_INPUT, "unknown_observation_key", detail={"key": key}
                )
            if kind == et.OBSERVATION_CONFIRMED and (
                envelope.source not in et.CONFIRMING_SOURCES
            ):
                # A model or camera proposal cannot confirm itself.
                raise ServiceError(
                    INVALID_INPUT,
                    "source_cannot_confirm",
                    detail={"source": envelope.source},
                )
            return incident

        if kind == et.ACTION_REPORTED:
            _as_text(detail.get("action"), "detail.action")
            return incident

        if kind == et.HELPER_UPDATED:
            _as_text(detail.get("helperId"), "detail.helperId")
            return incident

        return incident

    def _append(
        self, incident_id: str, envelope: EventEnvelope, principal: Principal
    ) -> StoredEvent:
        now = self._clock.now()
        stored = StoredEvent(
            incident_id=incident_id,
            envelope=envelope,
            actor_id=principal.actor_id,
            actor_role=principal.role,
            server_time=now,
            server_sequence=self._events.next_sequence(incident_id),
            expires_at=now + timedelta(seconds=self._retention.event_seconds),
        )
        return self._events.append(stored)

    def _advance_acknowledged(
        self, incident: IncidentRecord, settled: Mapping[str, list[int]]
    ) -> IncidentRecord:
        """Advance each client's acknowledged sequence contiguously.

        A gap left by a conflicted event stops the advance, so the client
        re-uploads from the first unacknowledged sequence on its next attempt
        instead of assuming the rejected event was stored.
        """
        if not settled:
            return incident
        acknowledged = dict(incident.acknowledged_client_sequences)
        for client_id, sequences in settled.items():
            cursor = int(acknowledged.get(client_id, 0))
            for sequence in sorted(sequences):
                if sequence == cursor + 1:
                    cursor = sequence
                elif sequence <= cursor:
                    continue
                else:
                    break
            acknowledged[client_id] = cursor
        return with_updated(incident, acknowledged_client_sequences=acknowledged)


def _acknowledge(event: StoredEvent, status: str) -> Acknowledgement:
    return Acknowledgement(
        event_id=event.event_id,
        status=status,
        server_time=event.server_time,
        server_sequence=event.server_sequence,
        client_sequence=event.envelope.client_sequence,
        client_id=event.envelope.client_id,
    )


def ordered_events(events: Iterable[StoredEvent]) -> tuple[StoredEvent, ...]:
    """Sort events into the deterministic projection order.

    See :attr:`StoredEvent.order_key`: client occurrence time first, then
    ``clientId``, ``clientSequence`` and ``eventId``. Server receipt time is
    never part of this order.
    """
    return tuple(sorted(events, key=lambda event: event.order_key))


__all__ = [
    "DEFAULT_MAX_BATCH_SIZE",
    "IncidentEventService",
    "envelope_fingerprint",
    "ordered_events",
    "parse_envelope",
]
